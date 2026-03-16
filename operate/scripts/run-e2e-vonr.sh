#!/bin/bash

# End-to-end VoNR test runner using UERANSIM + pjsua.
#
# This script orchestrates the full e2e VoNR test:
#   1. Verifies the 5G core + IMS stack is running
#   2. Copies modified Kamailio configs (digest auth, no IPsec)
#   3. Restarts P-CSCF and S-CSCF with the modified configs
#   4. Provisions test subscribers
#   5. Deploys the gNB (if not running)
#   6. Deploys two UERANSIM UEs with pjsua
#
# Usage: ./operate/scripts/run-e2e-vonr.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

set -a
source "$REPO_ROOT/.env"
source "$SCRIPT_DIR/../e2e.env"
set +a

[ ${#MNC} == 3 ] && IMS_DOMAIN="ims.mnc${MNC}.mcc${MCC}.3gppnetwork.org" || IMS_DOMAIN="ims.mnc0${MNC}.mcc${MCC}.3gppnetwork.org"

echo "============================================"
echo "  E2E VoNR Test Runner (UERANSIM + pjsua)"
echo "============================================"

# --- Step 1: Verify core stack ---
echo ""
echo "--- Step 1: Verifying 5G core + IMS stack ---"

REQUIRED_CONTAINERS="mongo nrf scp ausf udr udm amf smf upf pcf dns mysql pyhss icscf scscf pcscf rtpengine"
MISSING=""
for c in $REQUIRED_CONTAINERS; do
    if ! docker ps --format '{{.Names}}' | grep -q "^${c}$"; then
        MISSING="${MISSING} ${c}"
    fi
done

if [ -n "$MISSING" ]; then
    echo "ERROR: The following required containers are not running:${MISSING}"
    echo ""
    echo "Start the core stack first:"
    echo "  docker compose -f sa-vonr-deploy.yaml up -d"
    exit 1
fi
echo "  All required containers are running."

# --- Step 2: Apply modified Kamailio configs ---
echo ""
echo "--- Step 2: Applying digest auth Kamailio configs ---"

echo "  Copying modified P-CSCF config (IPsec disabled)..."
docker cp "$REPO_ROOT/operate/kamailio/pcscf/pcscf.cfg" pcscf:/mnt/pcscf/pcscf.cfg

echo "  Copying modified S-CSCF config (MD5 auth)..."
docker cp "$REPO_ROOT/operate/kamailio/scscf/scscf.cfg" scscf:/mnt/scscf/scscf.cfg

echo "  Restarting P-CSCF and S-CSCF..."
docker restart pcscf scscf

echo "  Waiting for Kamailio to initialize..."
sleep 15

for c in pcscf scscf; do
    if ! docker ps --format '{{.Names}}' | grep -q "^${c}$"; then
        echo "ERROR: ${c} failed to restart. Check logs: docker logs ${c}"
        exit 1
    fi
done
echo "  P-CSCF and S-CSCF restarted with digest auth."

# --- Step 3: Provision subscribers ---
echo ""
echo "--- Step 3: Provisioning test subscribers ---"
bash "$SCRIPT_DIR/provision.sh"

# --- Step 4: Verify gNB ---
echo ""
echo "--- Step 4: Verifying gNB ---"
if ! docker ps --format '{{.Names}}' | grep -q "nr_gnb"; then
    echo "  gNB not running. Starting..."
    cd "$REPO_ROOT"
    docker compose -f nr-gnb.yaml up -d
    echo "  Waiting for gNB to connect to AMF..."
    sleep 10
fi
echo "  gNB is running."

# --- Step 5: Deploy UEs ---
echo ""
echo "--- Step 5: Deploying test UEs ---"

if ! docker image inspect docker_ueransim_pjsua >/dev/null 2>&1; then
    echo "ERROR: Image 'docker_ueransim_pjsua' not found."
    echo "Build it first: ./operate/scripts/build.sh"
    exit 1
fi

cd "$REPO_ROOT"
docker compose -f operate/e2e-vonr.yaml up -d

echo ""
echo "============================================"
echo "  E2E VoNR test deployment complete!"
echo ""
echo "  Monitor UE1: docker logs -f e2e_ue1"
echo "  Monitor UE2: docker logs -f e2e_ue2"
echo ""
echo "  Once both UEs show 'IMS bearer established'"
echo "  and pjsua shows 'Registration complete',"
echo "  you can make a call."
echo ""
echo "  To make a call from UE1 to UE2:"
echo "    docker attach e2e_ue1"
echo "    Then type: m"
echo "    Then type: sip:${UE2_MSISDN}@${IMS_DOMAIN}"
echo ""
echo "  To tear down:"
echo "    ./operate/scripts/teardown.sh"
echo "============================================"

#!/bin/bash

# Deploy two test UEs onto an already-running core + IMS stack.
# Applies Kamailio configs, provisions subscribers, starts UEs,
# and waits for IMS registration.
#
# Prerequisites: core + IMS stack and gNB must be running.
#
# Usage: ./operate/scripts/deploy-ues.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

set -a
source "$REPO_ROOT/.env"
source "$SCRIPT_DIR/../e2e.env"
set +a

[ ${#MNC} == 3 ] && IMS_DOMAIN="ims.mnc${MNC}.mcc${MCC}.3gppnetwork.org" || IMS_DOMAIN="ims.mnc0${MNC}.mcc${MCC}.3gppnetwork.org"

REG_TIMEOUT=180

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_step()  { echo -e "\n${CYAN}==== $1 ====${NC}"; }
log_ok()    { echo -e "  ${GREEN}[OK]${NC} $1"; }
log_fail()  { echo -e "  ${RED}[FAIL]${NC} $1"; }
log_info()  { echo -e "  $1"; }

cd "$REPO_ROOT"

echo -e "${CYAN}"
echo "============================================"
echo "  Deploy UEs"
echo "============================================"
echo -e "${NC}"

# =========================================================================
# Step 1: Verify core stack is running
# =========================================================================
log_step "Step 1/5: Verifying core stack"

REQUIRED="amf smf pcscf scscf icscf pyhss"
for c in $REQUIRED; do
    if docker ps --format '{{.Names}}' | grep -q "^${c}$"; then
        log_ok "$c is running"
    else
        log_fail "$c is NOT running — start the core stack first"
        exit 1
    fi
done

# =========================================================================
# Step 2: Apply digest-auth Kamailio configs
# =========================================================================
log_step "Step 2/5: Applying digest auth Kamailio configs"

docker cp "$REPO_ROOT/operate/kamailio/pcscf/kamailio_pcscf.cfg" pcscf:/etc/kamailio_pcscf/kamailio_pcscf.cfg
log_ok "P-CSCF kamailio config updated (UDP for oversized SIP messages)"

docker cp "$REPO_ROOT/operate/kamailio/pcscf/pcscf.cfg" pcscf:/mnt/pcscf/pcscf.cfg
log_ok "P-CSCF config updated (IPsec disabled)"

docker cp "$REPO_ROOT/operate/kamailio/scscf/scscf.cfg" scscf:/mnt/scscf/scscf.cfg
log_ok "S-CSCF config updated (MD5 digest auth)"

docker restart pcscf scscf
log_info "Waiting for Kamailio to reinitialize..."
sleep 15

for c in pcscf scscf; do
    if docker ps --format '{{.Names}}' | grep -q "^${c}$"; then
        log_ok "$c restarted successfully"
    else
        log_fail "$c failed to restart"
        exit 1
    fi
done

# =========================================================================
# Step 3: Provision test subscribers
# =========================================================================
log_step "Step 3/5: Provisioning test subscribers"

bash "$SCRIPT_DIR/provision.sh"
log_ok "Subscribers provisioned in Open5GS and PyHSS"

# =========================================================================
# Step 4: Start UEs
# =========================================================================
log_step "Step 4/5: Starting UEs"

docker compose -f operate/e2e-vonr.yaml up -d
log_ok "UE containers started"

# =========================================================================
# Step 5: Wait for IMS registration
# =========================================================================
log_step "Step 5/5: Waiting for IMS registration"

wait_for_registration() {
    local container=$1
    local timeout=$2
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        if docker logs "$container" 2>&1 | grep -qi "registration.*success\|status=200.*reg"; then
            return 0
        fi
        if [ $elapsed -eq 0 ]; then
            log_info "Waiting for $container to attach and register..."
        fi
        sleep 3
        elapsed=$((elapsed + 3))
    done
    return 1
}

if wait_for_registration "e2e_ue1" $REG_TIMEOUT; then
    log_ok "UE1 (${UE1_MSISDN}) registered with IMS"
else
    log_fail "UE1 registration timed out after ${REG_TIMEOUT}s"
    log_info "Check logs: docker logs e2e_ue1"
    exit 1
fi

if wait_for_registration "e2e_ue2" $REG_TIMEOUT; then
    log_ok "UE2 (${UE2_MSISDN}) registered with IMS"
else
    log_fail "UE2 registration timed out after ${REG_TIMEOUT}s"
    log_info "Check logs: docker logs e2e_ue2"
    exit 1
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  UEs deployed and registered with IMS${NC}"
echo -e "${GREEN}============================================${NC}"

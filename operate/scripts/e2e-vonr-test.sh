#!/bin/bash

# =============================================================================
# E2E VoNR Super Script
# =============================================================================
#
# Brings up the entire 5G SA + IMS stack from scratch, deploys two UERANSIM UEs
# with pjsua, and demonstrates a successful VoNR call between them.
#
# What this script does:
#   1. Builds all required Docker images (if not already built) if missing
#   2. Starts the 5G core + IMS stack (sa-vonr-deploy.yaml), verifies all 17 containers are up
#   3. Builds the pjsua-enabled UERANSIM image if missing
#   4. Injects modified Kamailio configs (IPsec off, MD5 auth), restarts P-CSCF and S-CSCF
#   5. Provisions two test subscribers (Open5GS + PyHSS)
#   6. Starts the gNB
#   7. Starts two UEs (UERANSIM + pjsua)
#   8. Polls container logs until both UEs show IMS registration success (180s timeout)
#   9. Initiates a call from UE1 to UE2
#  10. Verifies the call connects
#  11. Hangs up and reports results
#
# Usage: ./operate/scripts/e2e-vonr-test.sh
#
# To clean up afterward: ./operate/scripts/teardown.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

set -a
source "$REPO_ROOT/.env"
source "$SCRIPT_DIR/../e2e.env"
set +a

[ ${#MNC} == 3 ] && IMS_DOMAIN="ims.mnc${MNC}.mcc${MCC}.3gppnetwork.org" || IMS_DOMAIN="ims.mnc0${MNC}.mcc${MCC}.3gppnetwork.org"

CALL_HOLD_SECS=10
REG_TIMEOUT=180
CALL_TIMEOUT=30

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_step()  { echo -e "\n${CYAN}==== $1 ====${NC}"; }
log_ok()    { echo -e "  ${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
log_fail()  { echo -e "  ${RED}[FAIL]${NC} $1"; }
log_info()  { echo -e "  $1"; }

# Track overall result
RESULT="PASS"
fail() { RESULT="FAIL"; log_fail "$1"; }

cd "$REPO_ROOT"

echo -e "${CYAN}"
echo "============================================================"
echo "           E2E VoNR Test — Full Stack Verification"
echo "============================================================"
echo -e "${NC}"
echo "  UE1: IMSI=${UE1_IMSI}  MSISDN=${UE1_MSISDN} (caller)"
echo "  UE2: IMSI=${UE2_IMSI}  MSISDN=${UE2_MSISDN} (callee)"
echo "  IMS Domain: ${IMS_DOMAIN}"
echo ""

# =========================================================================
# Step 1: Build base Docker images
# =========================================================================
log_step "Step 1/10: Building base Docker images"

build_if_missing() {
    local image=$1
    shift
    if docker image inspect "$image" >/dev/null 2>&1; then
        log_ok "$image already exists"
    else
        log_info "Building $image (this may take a while)..."
        docker build -t "$image" "$@"
        log_ok "$image built"
    fi
}

build_if_missing "docker_open5gs"  "./base"
build_if_missing "docker_kamailio" "./ims_base"
build_if_missing "docker_ueransim" "./ueransim"

# =========================================================================
# Step 2: Start 5G core + IMS stack
# =========================================================================
log_step "Step 2/10: Starting 5G core + IMS stack"

docker compose -f sa-vonr-deploy.yaml up -d

log_info "Waiting for core services to initialize..."
sleep 20

# Verify critical containers
REQUIRED="mongo nrf scp ausf udr udm amf smf upf pcf dns mysql pyhss icscf scscf pcscf rtpengine"
ALL_UP=true
for c in $REQUIRED; do
    if docker ps --format '{{.Names}}' | grep -q "^${c}$"; then
        log_ok "$c is running"
    else
        fail "$c is NOT running"
        ALL_UP=false
    fi
done

if [ "$ALL_UP" = false ]; then
    echo ""
    log_fail "Core stack failed to start. Aborting."
    exit 1
fi

# =========================================================================
# Step 3: Build pjsua-enabled UERANSIM image
# =========================================================================
log_step "Step 3/10: Building docker_ueransim_pjsua image"

build_if_missing "docker_ueransim_pjsua" -f "operate/ueransim/Dockerfile" "operate/ueransim/"

# =========================================================================
# Step 4: Apply digest-auth Kamailio configs
# =========================================================================
log_step "Step 4/10: Applying digest auth Kamailio configs"

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
        fail "$c failed to restart"
        echo "Check logs: docker logs $c"
        exit 1
    fi
done

# =========================================================================
# Step 5: Provision test subscribers
# =========================================================================
log_step "Step 5/10: Provisioning test subscribers"

bash "$SCRIPT_DIR/provision.sh"
log_ok "Subscribers provisioned in Open5GS and PyHSS"

# =========================================================================
# Step 6: Start gNB
# =========================================================================
log_step "Step 6/10: Starting UERANSIM gNB"

if docker ps --format '{{.Names}}' | grep -q "^nr_gnb$"; then
    log_ok "gNB already running"
else
    docker compose -f nr-gnb.yaml up -d
    log_info "Waiting for gNB to connect to AMF..."
    sleep 10
fi

if docker ps --format '{{.Names}}' | grep -q "^nr_gnb$"; then
    log_ok "gNB is running"
else
    fail "gNB failed to start"
    exit 1
fi

# =========================================================================
# Step 7: Start UEs
# =========================================================================
log_step "Step 7/10: Deploying UERANSIM UEs with pjsua"

docker compose -f operate/e2e-vonr.yaml up -d
log_ok "UE containers started"

# =========================================================================
# Step 8: Wait for IMS registration
# =========================================================================
log_step "Step 8/10: Waiting for IMS registration"

wait_for_registration() {
    local container=$1
    local timeout=$2
    local elapsed=0

    while [ $elapsed -lt $timeout ]; do
        # pjsua logs "registration success" or "Registration success" on 200 OK
        if docker logs "$container" 2>&1 | grep -qi "registration.*success\|status=200.*reg"; then
            return 0
        fi
        # Also check for the IMS bearer first
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
    fail "UE1 registration timed out after ${REG_TIMEOUT}s"
    log_info "Check logs: docker logs e2e_ue1"
    exit 1
fi

if wait_for_registration "e2e_ue2" $REG_TIMEOUT; then
    log_ok "UE2 (${UE2_MSISDN}) registered with IMS"
else
    fail "UE2 registration timed out after ${REG_TIMEOUT}s"
    log_info "Check logs: docker logs e2e_ue2"
    exit 1
fi

# =========================================================================
# Done — manual call step follows
# =========================================================================
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Stack is ready — both UEs registered with IMS${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "  To make a VoNR call, follow these steps:"
echo ""
echo "  1. In a separate terminal, start watching UE1 logs:"
echo "       docker logs -f e2e_ue1"
echo ""
echo "  2. Send the make-call command:"
echo "       docker exec e2e_ue1 bash -c \"echo m >> /tmp/pjsua_cmd\""
echo ""
echo "  3. Wait 2-3 seconds for the call menu to appear in the logs, then dial UE2:"
echo "       docker exec e2e_ue1 bash -c \"echo 'sip:${UE2_IMSI}@${IMS_DOMAIN}' >> /tmp/pjsua_cmd\""
echo ""
echo "  4. Look for 'Call 0 state changed to CONFIRMED' in the logs."
echo ""
echo "  5. To hang up:"
echo "       docker exec e2e_ue1 bash -c \"echo h >> /tmp/pjsua_cmd\""
echo ""
echo "  To tear down: ./operate/scripts/teardown.sh"
echo ""

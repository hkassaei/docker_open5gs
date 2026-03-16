#!/bin/bash

# Tear down E2E test environment and restore original Kamailio configs.
#
# Usage: ./operate/scripts/teardown.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "============================================"
echo "  E2E Test Teardown"
echo "============================================"

cd "$REPO_ROOT"

# Stop UE containers
echo "Stopping test UEs..."
docker compose -f operate/e2e-vonr.yaml down 2>/dev/null || true

# Restore original Kamailio configs
echo ""
echo "Restoring original Kamailio configs..."

if docker ps --format '{{.Names}}' | grep -q "^pcscf$"; then
    echo "  Restoring P-CSCF config (WITH_IPSEC enabled)..."
    docker cp "$REPO_ROOT/pcscf/pcscf.cfg" pcscf:/mnt/pcscf/pcscf.cfg
    docker restart pcscf
fi

if docker ps --format '{{.Names}}' | grep -q "^scscf$"; then
    echo "  Restoring S-CSCF config (HSS-Selected auth)..."
    docker cp "$REPO_ROOT/scscf/scscf.cfg" scscf:/mnt/scscf/scscf.cfg
    docker restart scscf
fi

# Cleanup subscribers
echo ""
echo "Cleaning up test subscribers..."
bash "$SCRIPT_DIR/provision.sh" --cleanup

echo ""
echo "Teardown complete. Original Kamailio configs restored."

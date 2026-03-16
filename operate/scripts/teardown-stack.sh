#!/bin/bash

# Tear down the core + IMS stack and gNB.
# Does NOT tear down UEs — use teardown-ues.sh for that,
# or teardown.sh for everything.
#
# Usage: ./operate/scripts/teardown-stack.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "============================================"
echo "  Core + IMS Stack Teardown"
echo "============================================"

cd "$REPO_ROOT"

# Stop gNB
echo ""
echo "--- Stopping gNB ---"
if docker ps --format '{{.Names}}' | grep -q "^nr_gnb$"; then
    docker compose -f nr-gnb.yaml down
    echo "  gNB stopped."
else
    echo "  gNB not running, skipping."
fi

# Stop core + IMS stack
echo ""
echo "--- Stopping core + IMS stack ---"
docker compose -f sa-vonr-deploy.yaml down
echo "  Core stack stopped."

echo ""
echo "============================================"
echo "  Core + IMS stack teardown complete."
echo "============================================"

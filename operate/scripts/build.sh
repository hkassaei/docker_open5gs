#!/bin/bash

# Build the pjsua-enabled UERANSIM image for e2e testing.
#
# Prerequisites:
#   - The base docker_ueransim image must already be built.
#     Build it with: docker build -t docker_ueransim ./ueransim
#
# Usage: ./operate/scripts/build.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "============================================"
echo "  Building docker_ueransim_pjsua image"
echo "============================================"

# Check that the base image exists
if ! docker image inspect docker_ueransim >/dev/null 2>&1; then
    echo "ERROR: Base image 'docker_ueransim' not found."
    echo "Build it first with: docker build -t docker_ueransim ./ueransim"
    exit 1
fi

docker build \
    -t docker_ueransim_pjsua \
    -f "$REPO_ROOT/operate/ueransim/Dockerfile" \
    "$REPO_ROOT/operate/ueransim/"

echo ""
echo "Build complete: docker_ueransim_pjsua"

#!/bin/bash

# Tear down everything: UEs, gNB, and core + IMS stack.
#
# Usage: ./operate/scripts/teardown.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

bash "$SCRIPT_DIR/teardown-ues.sh"
bash "$SCRIPT_DIR/teardown-stack.sh"

#!/bin/bash

# Image init dispatcher for e2e UERANSIM + pjsua containers.
# Routes to the correct init script based on COMPONENT_NAME.

if [[ -z "$COMPONENT_NAME" ]]; then
    echo "Error: COMPONENT_NAME environment variable not set"; exit 1;
elif [[ "$COMPONENT_NAME" =~ ^(ueransim-gnb[[:digit:]]*$) ]]; then
    echo "Deploying component: '$COMPONENT_NAME'"
    /mnt/ueransim/${COMPONENT_NAME}_init.sh
elif [[ "$COMPONENT_NAME" =~ ^(ueransim-ue[[:digit:]]*$) ]]; then
    echo "Deploying component: '$COMPONENT_NAME'"
    /mnt/ueransim/${COMPONENT_NAME}_init.sh
else
    echo "Error: Invalid component name: '$COMPONENT_NAME'"
fi

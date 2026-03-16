#!/bin/bash

# Init script for UERANSIM UE2 with pjsua for e2e VoNR testing.
# Starts nr-ue, waits for IMS bearer, then starts pjsua.

export IP_ADDR=$(awk 'END{print $1}' /etc/hosts)

# Copy and configure UE2 template
cp /mnt/ueransim/${COMPONENT_NAME}.yaml /UERANSIM/config/${COMPONENT_NAME}.yaml
sed -i 's|MNC|'$MNC'|g' /UERANSIM/config/${COMPONENT_NAME}.yaml
sed -i 's|MCC|'$MCC'|g' /UERANSIM/config/${COMPONENT_NAME}.yaml
sed -i 's|UE2_KI|'$UE2_KI'|g' /UERANSIM/config/${COMPONENT_NAME}.yaml
sed -i 's|UE2_OPC|'$UE2_OPC'|g' /UERANSIM/config/${COMPONENT_NAME}.yaml
sed -i 's|UE2_AMF|'$UE2_AMF'|g' /UERANSIM/config/${COMPONENT_NAME}.yaml
sed -i 's|UE2_IMEISV|'$UE2_IMEISV'|g' /UERANSIM/config/${COMPONENT_NAME}.yaml
sed -i 's|UE2_IMEI|'$UE2_IMEI'|g' /UERANSIM/config/${COMPONENT_NAME}.yaml
sed -i 's|UE2_IMSI|'$UE2_IMSI'|g' /UERANSIM/config/${COMPONENT_NAME}.yaml
sed -i 's|NR_GNB_IP|'$NR_GNB_IP'|g' /UERANSIM/config/${COMPONENT_NAME}.yaml

# Compute IMS domain
[ ${#MNC} == 3 ] && IMS_DOMAIN="ims.mnc${MNC}.mcc${MCC}.3gppnetwork.org" || IMS_DOMAIN="ims.mnc0${MNC}.mcc${MCC}.3gppnetwork.org"

echo "============================================"
echo "  UERANSIM UE2 + pjsua E2E VoNR Test"
echo "  IMSI:       ${UE2_IMSI}"
echo "  MSISDN:     ${MSISDN}"
echo "  IMS Domain: ${IMS_DOMAIN}"
echo "  P-CSCF:     ${PCSCF_IP}"
echo "============================================"

# Start UERANSIM nr-ue in background
echo "Starting UERANSIM nr-ue..."
./nr-ue -c ../config/${COMPONENT_NAME}.yaml &
NRUE_PID=$!

# Wait for IMS APN TUN interface
echo "Waiting for IMS APN bearer (192.168.101.x)..."
MAX_WAIT=120
elapsed=0
IMS_IP=""

while [ $elapsed -lt $MAX_WAIT ]; do
    IMS_IP=$(ip -4 addr show 2>/dev/null | grep -oP '192\.168\.101\.\d+' | head -1)
    if [ -n "${IMS_IP}" ]; then
        echo "IMS bearer established with IP: ${IMS_IP}"
        break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done

if [ -z "${IMS_IP}" ]; then
    echo "ERROR: IMS APN bearer did not come up within ${MAX_WAIT}s"
    echo "nr-ue is still running (PID: ${NRUE_PID}). Check for attach errors."
    echo "Available interfaces:"
    ip -4 addr show
    wait $NRUE_PID
    exit 1
fi

# Small delay to let routes stabilize
sleep 2

# Start pjsua
echo "Starting pjsua on IMS bearer (${IMS_IP})..."
export SIP_DOMAIN="${IMS_DOMAIN}"
/usr/local/bin/pjsua_entrypoint.sh &
PJSUA_PID=$!

echo "nr-ue PID: ${NRUE_PID}, pjsua PID: ${PJSUA_PID}"

# Wait for either process to exit
wait -n $NRUE_PID $PJSUA_PID
EXIT_CODE=$?
kill $NRUE_PID $PJSUA_PID 2>/dev/null || true
wait $NRUE_PID $PJSUA_PID 2>/dev/null || true
exit $EXIT_CODE

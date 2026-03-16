#!/bin/bash

# pjsua entrypoint for e2e voice testing inside a UERANSIM UE container.
# Waits for the IMS APN TUN interface, then starts pjsua bound to it.

set -e

: "${SIP_DOMAIN:?SIP_DOMAIN is required}"
: "${IMSI:?IMSI is required}"
: "${MSISDN:?MSISDN is required}"
: "${PCSCF_IP:?PCSCF_IP is required}"
: "${SIP_PASSWORD:=${MSISDN}}"
: "${AUTO_ANSWER:=yes}"
: "${NULL_AUDIO:=yes}"
: "${CALL_DURATION:=0}"
: "${MAX_WAIT_SECS:=120}"

SIP_USER="sip:${IMSI}@${SIP_DOMAIN}"
SIP_REGISTRAR="sip:${SIP_DOMAIN}"
OUTBOUND_PROXY="sip:${PCSCF_IP}:5060;transport=udp;lr"

echo "============================================"
echo "  pjsua SIP Client for E2E Voice Testing"
echo "============================================"
echo "  SIP User:     ${SIP_USER}"
echo "  Registrar:    ${SIP_REGISTRAR}"
echo "  Outbound:     ${OUTBOUND_PROXY}"
echo "  Auto-answer:  ${AUTO_ANSWER}"
echo "  Null audio:   ${NULL_AUDIO}"
echo "============================================"

# Wait for the IMS APN TUN interface to come up
echo "Waiting for IMS APN TUN interface (192.168.101.x)..."
elapsed=0
IMS_IP=""

while [ $elapsed -lt $MAX_WAIT_SECS ]; do
    # UERANSIM creates uesimtunX interfaces — look for IMS APN IP
    IMS_IP=$(ip -4 addr show 2>/dev/null | grep -oP '192\.168\.101\.\d+' | head -1)
    if [ -n "${IMS_IP}" ]; then
        echo "IMS TUN interface is up with IP: ${IMS_IP}"
        break
    fi
    sleep 2
    elapsed=$((elapsed + 2))
done

if [ -z "${IMS_IP}" ]; then
    echo "ERROR: IMS APN TUN interface did not come up within ${MAX_WAIT_SECS}s"
    echo "Available interfaces:"
    ip -4 addr show
    exit 1
fi

# Build pjsua command
PJSUA_ARGS=(
    --id "${SIP_USER}"
    --registrar "${SIP_REGISTRAR}"
    --outbound "${OUTBOUND_PROXY}"
    --realm "${SIP_DOMAIN}"
    --username "${IMSI}"
    --password "${SIP_PASSWORD}"
    --bound-addr "${IMS_IP}"
    --nameserver "${DNS_IP:-172.22.0.15}"
    --reg-timeout 3600
    --rereg-delay 5
    --log-level 4
    --app-log-level 4
)

if [ "${NULL_AUDIO}" = "yes" ]; then
    PJSUA_ARGS+=(--null-audio)
fi

# Disable TCP to ensure all SIP messages use UDP, matching the UDP registration.
# Without this, pjsua may send large SIP messages (>1300 bytes) via TCP,
# causing P-CSCF's pcscf_is_registered() to fail on transport mismatch.
PJSUA_ARGS+=(--no-tcp)

if [ "${AUTO_ANSWER}" = "yes" ]; then
    PJSUA_ARGS+=(--auto-answer 200)
fi

if [ "${CALL_DURATION}" -gt 0 ] 2>/dev/null; then
    PJSUA_ARGS+=(--duration "${CALL_DURATION}")
fi

if [ -n "${PLAY_FILE}" ] && [ -f "${PLAY_FILE}" ]; then
    PJSUA_ARGS+=(--play-file "${PLAY_FILE}")
fi

# Create a command file so external scripts can send commands to pjsua.
# Use 'echo cmd >> /tmp/pjsua_cmd' to send commands.
PJSUA_CMD_PIPE="/tmp/pjsua_cmd"
rm -f "${PJSUA_CMD_PIPE}"
touch "${PJSUA_CMD_PIPE}"

echo "Starting pjsua with bound address: ${IMS_IP}"
echo "Command pipe: ${PJSUA_CMD_PIPE}"

# Use tail -f on the command file as pjsua's stdin.
# This allows external processes to append commands at any time.
tail -f "${PJSUA_CMD_PIPE}" | /usr/local/bin/pjsua "${PJSUA_ARGS[@]}" "$@"

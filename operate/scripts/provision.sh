#!/bin/bash

# Provision two test subscribers for E2E voice testing.
# This script creates subscribers in both Open5GS (core attach) and PyHSS (IMS).
#
# Usage: ./operate/scripts/provision.sh [--cleanup]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Load environment
source "$REPO_ROOT/.env"
source "$SCRIPT_DIR/../e2e.env"

# Compute IMS domain
[ ${#MNC} == 3 ] && IMS_DOMAIN="ims.mnc${MNC}.mcc${MCC}.3gppnetwork.org" || IMS_DOMAIN="ims.mnc0${MNC}.mcc${MCC}.3gppnetwork.org"

PYHSS_API="${PYHSS_API:-http://localhost:8080}"
OPEN5GS_DB="open5gs"

echo "============================================"
echo "  E2E Voice Test - Subscriber Provisioning"
echo "============================================"
echo "  PyHSS API:  ${PYHSS_API}"
echo "  IMS Domain: ${IMS_DOMAIN}"
echo "  UE1 IMSI:   ${UE1_IMSI} / MSISDN: ${UE1_MSISDN}"
echo "  UE2 IMSI:   ${UE2_IMSI} / MSISDN: ${UE2_MSISDN}"
echo "============================================"

pyhss_lookup_id() {
    local endpoint=$1
    local imsi=$2
    curl -s "${PYHSS_API}${endpoint}" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('ims_subscriber_id') or json.load(sys.stdin).get('subscriber_id') or json.load(sys.stdin).get('auc_id',''))" 2>/dev/null || echo ""
}

if [ "$1" = "--cleanup" ]; then
    echo ""
    echo "--- Cleaning up test subscribers ---"

    echo "Removing UE1 from Open5GS..."
    docker exec -i mongo mongosh --quiet "$OPEN5GS_DB" --eval "db.subscribers.deleteOne({imsi: '${UE1_IMSI}'})" 2>/dev/null || true
    echo "Removing UE2 from Open5GS..."
    docker exec -i mongo mongosh --quiet "$OPEN5GS_DB" --eval "db.subscribers.deleteOne({imsi: '${UE2_IMSI}'})" 2>/dev/null || true

    echo "Removing PyHSS data..."
    # Delete by looking up IDs from IMSI, then deleting by ID
    for IMSI in "$UE1_IMSI" "$UE2_IMSI"; do
        echo "  Cleaning up IMSI ${IMSI}..."
        # IMS subscriber
        IMS_SUB=$(curl -s "${PYHSS_API}/ims_subscriber/ims_subscriber_imsi/${IMSI}" 2>/dev/null)
        IMS_ID=$(echo "$IMS_SUB" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ims_subscriber_id',''))" 2>/dev/null || echo "")
        [ -n "$IMS_ID" ] && curl -s -X DELETE "${PYHSS_API}/ims_subscriber/${IMS_ID}" >/dev/null 2>&1 && echo "    Deleted IMS subscriber ${IMS_ID}" || true

        # Subscriber
        SUB=$(curl -s "${PYHSS_API}/subscriber/imsi/${IMSI}" 2>/dev/null)
        SUB_ID=$(echo "$SUB" | python3 -c "import sys,json; print(json.load(sys.stdin).get('subscriber_id',''))" 2>/dev/null || echo "")
        [ -n "$SUB_ID" ] && curl -s -X DELETE "${PYHSS_API}/subscriber/${SUB_ID}" >/dev/null 2>&1 && echo "    Deleted subscriber ${SUB_ID}" || true

        # AUC
        AUC=$(curl -s "${PYHSS_API}/auc/imsi/${IMSI}" 2>/dev/null)
        AUC_ID=$(echo "$AUC" | python3 -c "import sys,json; print(json.load(sys.stdin).get('auc_id',''))" 2>/dev/null || echo "")
        [ -n "$AUC_ID" ] && curl -s -X DELETE "${PYHSS_API}/auc/${AUC_ID}" >/dev/null 2>&1 && echo "    Deleted AUC ${AUC_ID}" || true
    done

    echo "Cleanup complete."
    exit 0
fi

# =====================================================
# Step 1: Provision in Open5GS (MongoDB)
# =====================================================
echo ""
echo "--- Step 1: Provisioning subscribers in Open5GS ---"

provision_open5gs_subscriber() {
    local IMSI=$1
    local KI=$2
    local OPC=$3
    local MSISDN=$4

    echo "Adding subscriber IMSI=${IMSI}, MSISDN=${MSISDN}..."

    docker exec -i mongo mongosh --quiet "$OPEN5GS_DB" <<MONGOEOF
db.subscribers.updateOne(
  { imsi: "${IMSI}" },
  {
    \$set: {
      imsi: "${IMSI}",
      msisdn: ["${MSISDN}"],
      security: {
        k: "${KI}",
        amf: "8000",
        op: null,
        opc: "${OPC}"
      },
      schema_version: 1,
      ambr: { downlink: { value: 1, unit: 3 }, uplink: { value: 1, unit: 3 } },
      slice: [{
        sst: 1,
        default_indicator: true,
        session: [
          {
            name: "internet",
            type: 3,
            qos: { index: 9, arp: { priority_level: 8, pre_emption_capability: 1, pre_emption_vulnerability: 1 } },
            ambr: { downlink: { value: 1, unit: 3 }, uplink: { value: 1, unit: 3 } }
          },
          {
            name: "ims",
            type: 3,
            qos: { index: 5, arp: { priority_level: 1, pre_emption_capability: 1, pre_emption_vulnerability: 1 } },
            ambr: { downlink: { value: 1, unit: 3 }, uplink: { value: 1, unit: 3 } }
          }
        ]
      }]
    }
  },
  { upsert: true }
);
MONGOEOF
    echo "  Done."
}

provision_open5gs_subscriber "$UE1_IMSI" "$UE1_KI" "$UE1_OPC" "$UE1_MSISDN"
provision_open5gs_subscriber "$UE2_IMSI" "$UE2_KI" "$UE2_OPC" "$UE2_MSISDN"

# Add PCC rules for VoNR QoS (5QI=1) to the IMS session
echo "Adding PCC rules for voice QoS..."
for IMSI in "$UE1_IMSI" "$UE2_IMSI"; do
    docker exec -i mongo mongosh --quiet "$OPEN5GS_DB" <<PCCEOF
db.subscribers.updateOne(
  { imsi: "${IMSI}" },
  {
    \$set: {
      "slice.0.session.1.pcc_rule": [{
        qos: {
          index: 1,
          arp: {
            priority_level: 1,
            pre_emption_capability: 1,
            pre_emption_vulnerability: 1
          },
          mbr: { downlink: { value: 128, unit: 1 }, uplink: { value: 128, unit: 1 } },
          gbr: { downlink: { value: 128, unit: 1 }, uplink: { value: 128, unit: 1 } }
        }
      }]
    }
  }
);
PCCEOF
done
echo "  Done."

# =====================================================
# Step 2: Provision in PyHSS (IMS)
# =====================================================
echo ""
echo "--- Step 2: Provisioning subscribers in PyHSS ---"

LAST_PYHSS_BODY=""

pyhss_put() {
    local endpoint=$1
    local data=$2
    local description=$3

    echo "  ${description}..."
    RESPONSE=$(curl -s -w "\n%{http_code}" -X PUT "${PYHSS_API}${endpoint}" \
        -H "Content-Type: application/json" \
        -d "${data}")
    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    LAST_PYHSS_BODY=$(echo "$RESPONSE" | head -n -1)

    if [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 300 ]; then
        echo "    OK (${HTTP_CODE})"
    elif [ "$HTTP_CODE" -eq 409 ]; then
        echo "    Already exists (${HTTP_CODE}), skipping."
    else
        echo "    WARNING: ${HTTP_CODE} - ${LAST_PYHSS_BODY}"
    fi
}

# Create APNs if they don't already exist
echo "Creating APNs..."
EXISTING_APNS=$(curl -s "${PYHSS_API}/apn/list" 2>/dev/null)
if echo "$EXISTING_APNS" | python3 -c "import sys,json; apns=[a['apn'] for a in json.load(sys.stdin)]; sys.exit(0 if 'internet' in apns else 1)" 2>/dev/null; then
    echo "  internet APN already exists, skipping."
else
    pyhss_put "/apn/" '{"apn":"internet","apn_ambr_dl":0,"apn_ambr_ul":0}' "Creating internet APN"
fi
if echo "$EXISTING_APNS" | python3 -c "import sys,json; apns=[a['apn'] for a in json.load(sys.stdin)]; sys.exit(0 if 'ims' in apns else 1)" 2>/dev/null; then
    echo "  ims APN already exists, skipping."
else
    pyhss_put "/apn/" '{"apn":"ims","apn_ambr_dl":0,"apn_ambr_ul":0}' "Creating ims APN"
fi

# Get APN IDs for subscriber references
INTERNET_APN_ID=$(curl -s "${PYHSS_API}/apn/list" 2>/dev/null | python3 -c "import sys,json; apns=json.load(sys.stdin); print(next(a['apn_id'] for a in apns if a['apn']=='internet'))" 2>/dev/null)
IMS_APN_ID=$(curl -s "${PYHSS_API}/apn/list" 2>/dev/null | python3 -c "import sys,json; apns=json.load(sys.stdin); print(next(a['apn_id'] for a in apns if a['apn']=='ims'))" 2>/dev/null)
echo "  internet APN ID: ${INTERNET_APN_ID}, ims APN ID: ${IMS_APN_ID}"

provision_pyhss_subscriber() {
    local IMSI=$1
    local KI=$2
    local OP=$3
    local MSISDN=$4

    echo ""
    echo "Provisioning IMS subscriber: IMSI=${IMSI}, MSISDN=${MSISDN}"

    # Check if AUC already exists for this IMSI
    EXISTING_AUC=$(curl -s "${PYHSS_API}/auc/imsi/${IMSI}" 2>/dev/null)
    AUC_ID=$(echo "$EXISTING_AUC" | python3 -c "import sys,json; print(json.load(sys.stdin).get('auc_id',''))" 2>/dev/null || echo "")

    if [ -n "$AUC_ID" ]; then
        echo "  AUC already exists (auc_id=${AUC_ID}), skipping."
    else
        pyhss_put "/auc/" "{
            \"ki\": \"${KI}\",
            \"opc\": \"${OP}\",
            \"amf\": \"8000\",
            \"sqn\": 0,
            \"imsi\": \"${IMSI}\"
        }" "Creating AUC"
        AUC_ID=$(echo "$LAST_PYHSS_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin)['auc_id'])" 2>/dev/null || echo "")
    fi

    if [ -z "$AUC_ID" ]; then
        echo "    ERROR: Failed to get AUC ID for IMSI ${IMSI}"
        return 1
    fi
    echo "  Using auc_id=${AUC_ID}"

    # Check if subscriber already exists
    EXISTING_SUB=$(curl -s "${PYHSS_API}/subscriber/imsi/${IMSI}" 2>/dev/null)
    SUB_ID=$(echo "$EXISTING_SUB" | python3 -c "import sys,json; print(json.load(sys.stdin).get('subscriber_id',''))" 2>/dev/null || echo "")

    if [ -n "$SUB_ID" ]; then
        echo "  Subscriber already exists (subscriber_id=${SUB_ID}), skipping."
    else
        pyhss_put "/subscriber/" "{
            \"imsi\": \"${IMSI}\",
            \"enabled\": true,
            \"auc_id\": ${AUC_ID},
            \"default_apn\": ${INTERNET_APN_ID},
            \"apn_list\": \"${INTERNET_APN_ID},${IMS_APN_ID}\",
            \"msisdn\": \"${MSISDN}\",
            \"ue_ambr_dl\": 0,
            \"ue_ambr_ul\": 0
        }" "Creating subscriber"
    fi

    # Check if IMS subscriber already exists
    EXISTING_IMS=$(curl -s "${PYHSS_API}/ims_subscriber/ims_subscriber_imsi/${IMSI}" 2>/dev/null)
    IMS_ID=$(echo "$EXISTING_IMS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('ims_subscriber_id',''))" 2>/dev/null || echo "")

    if [ -n "$IMS_ID" ]; then
        echo "  IMS subscriber already exists (ims_subscriber_id=${IMS_ID}), skipping."
    else
        pyhss_put "/ims_subscriber/" "{
            \"imsi\": \"${IMSI}\",
            \"msisdn\": \"${MSISDN}\",
            \"sh_profile\": \"string\",
            \"scscf_peer\": \"scscf.${IMS_DOMAIN}\",
            \"msisdn_list\": \"[${MSISDN}]\",
            \"ifc_path\": \"default_ifc.xml\",
            \"scscf\": \"sip:scscf.${IMS_DOMAIN}:6060\",
            \"scscf_realm\": \"${IMS_DOMAIN}\"
        }" "Creating IMS subscriber"
    fi
}

provision_pyhss_subscriber "$UE1_IMSI" "$UE1_KI" "$UE1_OPC" "$UE1_MSISDN"
provision_pyhss_subscriber "$UE2_IMSI" "$UE2_KI" "$UE2_OPC" "$UE2_MSISDN"

echo ""
echo "============================================"
echo "  Provisioning complete!"
echo ""
echo "  Open5GS WebUI: http://${DOCKER_HOST_IP}:9999"
echo "  PyHSS API:     ${PYHSS_API}/docs/"
echo "============================================"

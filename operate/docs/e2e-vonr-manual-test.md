# E2E VoNR Test Guide

## Overview

This guide walks through running an end-to-end Voice over New Radio (VoNR) call between two simulated UEs. The setup script automates everything up to and including IMS registration. The call itself is performed manually.

## Step 1: Run the Setup Script

```bash
./operate/scripts/e2e-vonr-test.sh
```

This script handles steps 1-8 automatically:

1. Builds Docker images (if missing)
2. Starts the 5G core + IMS stack
3. Builds the pjsua-enabled UERANSIM image
4. Applies digest auth Kamailio configs (IPsec off, MD5 auth)
5. Provisions two test subscribers in Open5GS and PyHSS
6. Starts the gNB
7. Deploys two UEs (UERANSIM + pjsua)
8. Waits for both UEs to register with IMS

When the script completes, it prints instructions for the manual call step.

## Step 2: Make a VoNR Call (Manual)

Open a **second terminal** to watch UE1's logs:

```bash
docker logs -f e2e_ue1
```

Back in your **first terminal**, send the make-call command:

```bash
docker exec e2e_ue1 bash -c "echo m >> /tmp/pjsua_cmd"
```

In the logs terminal, wait until you see the call menu:

```
(You currently have 0 calls)
Buddy list:
 -none-

Choices:
   0         For current dialog.
  URL        An URL
  <Enter>    Empty input (or 'q') to cancel
```

Once you see this, dial UE2:

```bash
docker exec e2e_ue1 bash -c "echo 'sip:001011234567892@ims.mnc001.mcc001.3gppnetwork.org' >> /tmp/pjsua_cmd"
```

A successful call shows this in the logs:

```
Call 0 state changed to CONNECTING
Call 0 state changed to CONFIRMED
```

UE2 auto-answers (configured with `--auto-answer 200`).

## Step 3: Hang Up

```bash
docker exec e2e_ue1 bash -c "echo h >> /tmp/pjsua_cmd"
```

You should see a `BYE` sent and a `200 OK` response.

## Step 4: Tear Down

```bash
./operate/scripts/teardown.sh
```

This stops the test UEs, restores original Kamailio configs, and cleans up test subscribers.

## Troubleshooting

### UE doesn't register (script hangs at step 8)

Check that the IMS PDU session was established:

```bash
docker logs e2e_ue1 2>&1 | grep 'PDU Session'
```

You should see `PDU Session establishment is successful PSI[2]` with an IP in `192.168.101.x`. If not, check `docker logs amf` and `docker logs smf`.

### Registration fails with 403

- **"User Unknown"**: PyHSS can't find the subscriber. Re-run `bash operate/scripts/provision.sh`.
- **"Authentication Failed"**: SIP password doesn't match the subscriber's Ki. Check that `SIP_PASSWORD=${UE1_KI}` is set in `operate/e2e-vonr.yaml`.

### Call menu doesn't appear after `echo m`

The `echo >> /tmp/pjsua_cmd` approach relies on `tail -f` picking up appended data. Wait a few seconds and try again.

### Call fails with 412

PCF can't find PCC rules for voice QoS. Re-run `bash operate/scripts/provision.sh` — it adds the required PCC rules (5QI=1) to the MongoDB subscriber profiles.

### Call fails with 403 "Must register first"

Transport mismatch — pjsua sent via TCP but registered via UDP. Ensure `--no-tcp` is in the pjsua args (check `operate/ueransim/pjsua_entrypoint.sh`).

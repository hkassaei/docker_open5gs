# VoNR Learning Tool

A browser-based GUI for deploying, controlling, and observing the full 5G SA + IMS + VoNR stack.

## Quick Start

```bash
# From the repo root
python3 -m venv operate/gui/.venv
source operate/gui/.venv/bin/activate
pip install -r operate/gui/requirements.txt

python3 operate/gui/server.py
```

Open http://localhost:8073 in your browser.

## What it does

- **Deploy Stack** — full stack from scratch (core + IMS + gNB + UEs)
- **Deploy UEs** — provisions and starts UEs on an already-running stack
- **Tear Down UEs** — stops UEs, restores Kamailio configs, cleans up subscribers
- **Tear Down Stack** — stops gNB and core + IMS containers
- **UE Controls** — call, hang up, answer, hold/unhold via pjsua commands
- **Live Logs** — streams `docker logs -f` from both UE containers in real time, with noise filtering and color-coded SIP/NAS events
- **Event Timeline** — extracts key milestones (registration, PDU sessions, call state changes) into a sidebar
- **AI Explain** — sends logs to Claude Code CLI for a plain-English explanation of what happened

## Requirements

- Python 3.10+
- Docker and Docker Compose
- Claude Code CLI installed and authenticated (for the AI Explain feature)
- All prerequisites for the docker_open5gs stack (see main README)

## Port

Default: `8073`. Override with `GUI_PORT` environment variable.

# dar-light-copilot (MVP)

Internal multi-agent copilot for Dar Blockchain + Lightency.

## MVP goals
- Telegram-first interface (low friction)
- Specialist modes: PM, SRE, Dev, QA, HR, Security
- Optional on-device assistance via OpenClaw Windows Node host (with kill switches)
- Safe-by-default: least privilege, explicit attach, easy stop

## Contents
- `windows-node/` — Windows node host + global hotkeys + SSH tunnel scripts
- `vps/` — VPS hardening + monitoring scripts (OpenClaw gateway loopback-only)
- `agent/` — Telegram router + specialist prompt templates (MVP)
- `docs/` — architecture, security model, demo script

## Quickstart (high level)
1) VPS: harden + run OpenClaw gateway locally only.
2) Windows: install OpenClaw CLI + node host service; enable hotkeys.
3) Agent: run router (Telegram) and route to specialist modes.

## Secrets
Never commit secrets. Use `.env` files locally.


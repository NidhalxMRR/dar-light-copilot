# dar-light-copilot (MVP)

Internal multi-agent copilot for Dar Blockchain + Lightency.

## MVP goals
- Telegram-first interface (low friction)
- Specialist modes: PM, SRE, Dev, QA, HR, Security
- Optional on-device assistance via OpenClaw Windows Node host (with kill switches)
- HR MVP: repetitive desktop task automation (example: Excel → PDF dropbox)
- Safe-by-default: least privilege, explicit attach, easy stop

## Contents
- `windows-node/` — Windows node host + global hotkeys + SSH tunnel scripts
- `vps/` — VPS hardening + monitoring scripts (OpenClaw gateway loopback-only)
- `agent/` — Telegram router + specialist prompt templates (MVP)
- `rag/` — Postgres RAG knowledge base (code + schema only; VPS holds encrypted data)
- `docs/` — architecture, security model, demo script, RAG notes

## Quickstart (high level)
1) VPS: harden + run OpenClaw gateway locally only.
2) Windows: install OpenClaw CLI + node host service; enable hotkeys.
3) Agent: run router (Telegram) and route to specialist modes.
4) RAG: bring up Postgres (VPS localhost) + run sync timer (ingest/tag/summarize).

## Knowledge base (RAG)
We maintain a single searchable “brain” across Telegram + Control UI sessions.

- Code lives in this repo under `rag/`.
- Real data lives on the VPS in Postgres, encrypted via `pgcrypto`.
- Sub-agents should use **read-only** DB credentials (see `docs/SUBAGENTS-RAG.md`).
- Writer is the VPS `rag-sync` timer.

Docs:
- `docs/RAG-KNOWLEDGE.md`
- `docs/SUBAGENTS-RAG.md`
- `docs/UPDATES-2026-03-01.md`
- `docs/UPDATES-2026-03-02.md` (Windows node HR Excel→PDF MVP + watchdog/dashboard)

## Secrets
Never commit secrets. Use `.env` files locally.
- Never paste/commit dashboard `#token=...` URLs.
- Never commit `OPENCLAW_GATEWAY_TOKEN`.


Docs (security):
- `docs/CODE-AUDIT.md` (VPS-only redacted code audit dropbox)

Docs (EMS):
- `docs/EMS-PIPELINE.md` (real-time lossless EMS alerts pipeline)

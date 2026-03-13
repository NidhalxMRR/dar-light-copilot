# Security & Responsible Disclosure

This repository includes automation/orchestration for security research workflows.

## Never commit secrets
Do not commit:
- `.env`, `.env.*`, or any environment files
- API keys (RPC providers, Telegram bot tokens, etc.)
- VPS-only config under `/home/ubuntu/.openclaw/*`

## Never commit target-specific research artifacts
Do not commit:
- `targets/**` (cloned target repos, PoCs, local forks)
- `*.log` (debug logs)
- `IMMUNEFI_REPORT.md` (draft reports)
- `POC_CONFIRMED.txt` (internal markers)

All target-specific work should live in:
- Postgres RAG DB (`orchestration_*`, `rag_*`) and/or
- local VPS paths (private)

## Disclosure
If a vulnerability is found:
1) Verify scope + rules for the program
2) Prepare a minimal, reproducible PoC
3) Submit privately via the program (e.g., Immunefi)
4) Do not publish until disclosure is approved

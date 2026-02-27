# Architecture (MVP)

## Components
- **Gateway (VPS)**: OpenClaw gateway bound to loopback; authenticated.
- **Windows Node Host**: connects to gateway through SSH tunnel (localhost port-forward).
- **Telegram Router**: front door for employees; routes to specialist prompts.

## Modes
- PM: meeting transcript → actions/decisions + dbwork/todoist formats
- QA: user story → test cases + edge cases
- Dev: log triage + root cause
- SRE: incident triage + best practices
- HR: Excel → PDF/report pack
- Security: hardening scripts + weekly report template


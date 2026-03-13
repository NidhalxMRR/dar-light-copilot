# Agent-to-agent orchestration (via Postgres RAG)

Goal: make multi-agent work reliable without relying on Telegram mentions.
The **database is the bus**.

## Roles
- **Writer/sync job (VPS only):** ingests + tags + summarizes (writes encrypted fields)
- **Sub-agents (read-only):** can read summaries + tasks/decisions to coordinate
- **Human (monitor):** approves target + scope + submissions

## Tables used
Existing (encrypted content):
- `rag_session`, `rag_message`, `rag_topic`, `rag_summary`, `rag_keyword`

Orchestration (plaintext, safe to share with sub-agents):
- `rag_task` — task queue and status
- `rag_decision` — key decisions + rationale

Sub-agents should connect using `rag_readonly`.

## Minimal workflow
1) Human or main agent creates/updates `rag_task` rows.
2) Sub-agent reads tasks, proposes next actions, and (if it has write access) updates status.
   - If sub-agent is truly read-only, it posts an update to Telegram; main agent updates DB.
3) `rag-sync.timer` runs periodically to keep summaries fresh.

## Systemd setup (VPS)
Copy the units from `vps/systemd/`:

```bash
sudo cp vps/systemd/rag-sync.service /etc/systemd/system/
sudo cp vps/systemd/rag-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rag-sync.timer
sudo systemctl status rag-sync.timer
```

## Check-ins to Telegram
Recommended: schedule **OpenClaw cron** jobs to post a daily plan + EOD summary.
Systemd keeps the DB fresh; OpenClaw handles messaging.

Suggested cadence (UTC):
- 09:00 weekdays: post "today plan" based on `rag_task` + latest `rag_summary`
- 18:00 weekdays: post "EOD recap" and roll tasks forward

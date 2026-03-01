# Sub-agents + RAG (Postgres)

Goal: any sub-agent (PM/Dev/SRE/QA/HR/Security) can query the same knowledge base.

## Hard rules
- Do NOT commit any real data, logs, transcripts, or tokens to git.
- All real data stays on the VPS in Postgres on localhost.
- Encryption key lives only on VPS: `/home/ubuntu/.openclaw/rag/enc_key`.

## Runtime environment (VPS)

### Read-only access (recommended for sub-agents)
Use the read-only DB user **rag_ro** (no writes). Connect via localhost (VPS) or an SSH tunnel.

Example (VPS):
```bash
psql "postgresql://rag_ro:<PASSWORD>@127.0.0.1:5432/rag"
```

Example (from your PC via SSH tunnel):
```bash
ssh -N -L 55432:127.0.0.1:5432 ubuntu@149.202.63.227
psql "postgresql://rag_ro:<PASSWORD>@127.0.0.1:55432/rag"
```

### Writer/sync job (VPS only)
Only the VPS `rag-sync` timer should run write operations (ingest/tag/summarize).
To run RAG scripts as the writer, source the VPS-only env file:

```bash
set -a
source /home/ubuntu/.openclaw/rag/rag.env
set +a
```

## Useful commands
Initialize tree:
```bash
python -m rag.scripts.init_tree
```

Ingest OpenClaw session logs:
```bash
python -m rag.scripts.ingest_openclaw_sessions
```

Auto-tag:
```bash
python -m rag.scripts.auto_tag
```

Show branch:
```bash
python -m rag.scripts.show_branch openclaw/windows-node/debug 5
```

Summaries:
```bash
python -m rag.scripts.summarize_topics
```

## How sub-agents should behave
- Use `show_branch` for fast recall.
- Prefer topic summaries (`rag_summary`) when answering.
- When unsure, search by keyword in `rag_keyword` (script can be added).


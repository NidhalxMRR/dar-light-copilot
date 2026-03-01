# Sub-agents + RAG (Postgres)

Goal: any sub-agent (PM/Dev/SRE/QA/HR/Security) can query the same knowledge base.

## Hard rules
- Do NOT commit any real data, logs, transcripts, or tokens to git.
- All real data stays on the VPS in Postgres on localhost.
- Encryption key lives only on VPS: `/home/ubuntu/.openclaw/rag/enc_key`.

## Runtime environment (VPS)
Source the env file before running any RAG scripts:

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


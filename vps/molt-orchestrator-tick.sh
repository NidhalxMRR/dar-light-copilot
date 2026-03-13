#!/usr/bin/env bash
set -euo pipefail

# Writer tick: keep the RAG "brain" fresh and leave a heartbeat event.
# Requires VPS-only env: /home/ubuntu/.openclaw/rag/rag.env

cd /home/ubuntu/.openclaw/workspace/dar-light-copilot

# shellcheck disable=SC1091
set -a
source /home/ubuntu/.openclaw/rag/rag.env
set +a

# Run the full sync loop (idempotent)
/home/ubuntu/.openclaw/workspace/dar-light-copilot/.venv/bin/python -m rag.scripts.sync_all

# Optional: record tick event (plaintext)
psql "${RAG_DATABASE_URL}" -c "INSERT INTO orchestration_event(kind, actor, message, tags) VALUES ('note','writer','tick: sync_all ok', ARRAY['tick']);" >/dev/null

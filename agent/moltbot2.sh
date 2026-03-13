#!/bin/sh
set -eu

apk add --no-cache postgresql16-client curl jq >/dev/null 2>&1 || true

echo "[moltbot2] starting DB poll + Telegram report loop"

LAST_FP=""

send() {
  [ -z "${MOLTBOT2_TELEGRAM_TOKEN:-}" ] && return 0
  [ -z "${MOLTBOT2_CHAT_ID:-}" ] && return 0
  curl -sS -X POST "https://api.telegram.org/bot${MOLTBOT2_TELEGRAM_TOKEN}/sendMessage" \
    -d chat_id="${MOLTBOT2_CHAT_ID}" \
    --data-urlencode text="$1" \
    -d disable_web_page_preview=true >/dev/null 2>&1 || true
}

claim_one() {
  # Auto-claim exactly one task using the DB function (enforces strict workflow + deps).
  # Returns claimed task id or empty.
  psql "$RAG_RO_DATABASE_URL" -At -c "SELECT (orchestration_claim_task('aluma:worker', 600)).id;" 2>/dev/null \
    | head -n1 \
    | tr -d '[:space:]' \
    | grep -E '^[0-9]+$' || true
}

while true; do
  NOW=$(date -Is)

  # If we're already running something (unexpired lease), don't claim a second task.
  RUNNING_CNT=$(psql "$RAG_RO_DATABASE_URL" -At -c "SELECT count(*) FROM orchestration_task WHERE status='running' AND claimed_by='aluma:worker' AND lease_expires_at IS NOT NULL AND lease_expires_at >= now();" 2>/dev/null | tr -d '[:space:]' || echo "0")

  CLAIMED_ID=""
  if [ "${RUNNING_CNT:-0}" = "0" ]; then
    CLAIMED_ID=$(claim_one)
    if [ -n "${CLAIMED_ID:-}" ]; then
      send "[moltbot2] ${NOW}\nclaimed task_id=${CLAIMED_ID} (lease=10m)"
    fi
  fi

  ROWS=$(psql "$RAG_RO_DATABASE_URL" -At -F "\t" -c "SELECT id, status, priority, owner, claimed_by, lease_expires_at, workflow_id, seq, (CASE WHEN debug_notes<>'' THEN 'YES' ELSE '' END), left(title,70) FROM orchestration_task WHERE status IN ('queued','running','blocked') ORDER BY priority ASC, due_at NULLS LAST, updated_at DESC LIMIT 5;" 2>/dev/null || true)
  FP=$(printf '%s' "$ROWS" | sha256sum | awk '{print $1}')

  if [ "${MOLTBOT2_REPORT_EVERY_POLL:-0}" = "1" ] || [ "$FP" != "$LAST_FP" ]; then
    MSG="[moltbot2] ${NOW}\n"
    if [ -z "$ROWS" ]; then
      MSG="${MSG}(no tasks or DB error)"
    else
      MSG="${MSG}id\tstatus\tp\town\tclaimed_by\tlease\twf\tseq\tdebug\ttitle\n${ROWS}"
    fi
    send "$MSG"
    LAST_FP="$FP"
  fi

  sleep "${CHECKIN_INTERVAL_SECONDS:-1800}"
done

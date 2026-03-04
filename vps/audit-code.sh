#!/usr/bin/env bash
set -euo pipefail

# Secure-by-default code audit runner.
# - Input: .zip files dropped into AUDIT_IN
# - Output: report.md + findings.jsonl into AUDIT_OUT
# - No secret values are printed; only file paths + line numbers + rule ids.

AUDIT_ROOT="${AUDIT_ROOT:-/home/ubuntu/.openclaw/audit}"
AUDIT_IN="${AUDIT_IN:-$AUDIT_ROOT/in}"
AUDIT_OUT="${AUDIT_OUT:-$AUDIT_ROOT/out}"
AUDIT_DONE="${AUDIT_DONE:-$AUDIT_ROOT/done}"
AUDIT_WORK="${AUDIT_WORK:-$AUDIT_ROOT/work}"
AUDIT_LOGS="${AUDIT_LOGS:-$AUDIT_ROOT/logs}"

mkdir -p "$AUDIT_IN" "$AUDIT_OUT" "$AUDIT_DONE" "$AUDIT_WORK" "$AUDIT_LOGS"

now_iso() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }

log() {
  echo "[$(now_iso)] $*" | tee -a "$AUDIT_LOGS/audit.log" >&2
}

# redact any match: we never print the secret value
# We only keep: rule_id, file, line
scan_rules() {
  local root="$1"
  local findings="$2"

  # Files that should never be included in findings content.
  # We still flag their existence.
  while IFS= read -r f; do
    printf '{"rule":"SENSITIVE_FILE","file":%s,"line":0}\n' "$(printf '%s' "$f" | jq -Rs .)" >> "$findings"
  done < <(
    find "$root" -maxdepth 6 -type f \( -name ".env" -o -name ".env.*" -o -name "*.pem" -o -name "id_rsa" -o -name "id_ed25519" -o -name "*.p12" -o -name "*.pfx" \) 2>/dev/null || true
  )

  # ripgrep based scans (fast). We only record file + line number.
  # NOTE: patterns are intentionally broad; expect false positives.
  local rg_base=(rg --no-heading --line-number --hidden --glob '!.git/**' --glob '!node_modules/**' --glob '!dist/**' --glob '!build/**' --glob '!target/**' --glob '!vendor/**' --glob '!*.min.js' --glob '!*.map')

  rg_emit() {
    local rule="$1"
    local pattern="$2"
    # rg output format: file:line:match
    "${rg_base[@]}" -S "$pattern" "$root" 2>/dev/null \
      | while IFS=: read -r f ln _rest; do
          # Quote file path safely; never include match value.
          printf '{"rule":"%s","file":%s,"line":%s}\n' \
            "$rule" \
            "$(printf '%s' "$f" | jq -Rs .)" \
            "${ln:-0}";
        done \
      >> "$findings" || true
  }

  rg_emit "PRIVATE_KEY_PEM" "BEGIN (RSA|EC|OPENSSH) PRIVATE KEY"
  rg_emit "AWS_KEY_ID" "(AKIA|ASIA)[0-9A-Z]{16}"
  rg_emit "SLACK_TOKEN" "(xox[baprs]-[0-9A-Za-z-]{10,})"
  rg_emit "GITHUB_TOKEN" "(ghp_|github_pat_)[0-9A-Za-z_]{10,}"
  rg_emit "LLM_KEYWORD" "(OPENAI|ANTHROPIC|CLAUDE|GEMINI|DEEPSEEK).{0,40}(KEY|TOKEN)"
  rg_emit "MNEMONIC_KEYWORD" "(seed phrase|mnemonic)"
  rg_emit "GENERIC_SECRET_ASSIGN" "(private_key|secret_key|api[_-]?key|password)\\s*[:=]"
}

process_one() {
  local input="$1"
  local base
  base="$(basename "$input")"
  base="${base%.zip}"
  base="${base%.xlsx}"

  local run_id
  run_id="$(date -u +"%Y%m%d-%H%M%S")_${base}"

  local workdir="$AUDIT_WORK/$run_id"
  rm -rf "$workdir"
  mkdir -p "$workdir/src"

  log "audit: start input=$input run_id=$run_id"

  # unzip safely (works for .zip and .xlsx)
  unzip -q "$input" -d "$workdir/src"

  local findings="$workdir/findings.jsonl"
  : > "$findings"

  # Run scans (no secret values logged)
  scan_rules "$workdir/src" "$findings"

  # Produce report
  local report="$AUDIT_OUT/${run_id}.report.md"
  {
    echo "# Secure Code Audit Report"
    echo
    echo "- run_id: $run_id"
    echo "- input: $(basename "$input")"
    echo "- generated_at_utc: $(now_iso)"
    echo "- status: DONE"
    echo
    echo "## Findings summary"
    echo
    if [[ ! -s "$findings" ]]; then
      echo "No findings (based on current heuristic rules)."
    else
      echo "Findings were detected. Values are intentionally redacted; only file paths + line numbers are reported."
    fi
    echo
    echo "## Findings (redacted)"
    echo
    if [[ -s "$findings" ]]; then
      # Count by rule
      echo "### Counts by rule"
      awk -F'"rule":"' 'NF>1{split($2,a,"\""); c[a[1]]++} END{for(k in c) printf("- %s: %d\n", k, c[k])}' "$findings" | sort
      echo
      echo "### Raw (JSONL)"
      echo "(stored separately as .jsonl next to this report)"
    fi
  } > "$report"

  # Embed findings into the report (single-file output)
  {
    echo
    echo "## Findings details (JSONL, redacted)"
    echo
    printf '%s\n' '```jsonl'
    if [[ -s "$findings" ]]; then
      cat "$findings"
    fi
    printf '%s\n' '```'
  } >> "$report"

  # Mark completion (sync-friendly): create a small DONE marker next to the report
  local done_marker="$AUDIT_OUT/${run_id}.done.txt"
  {
    echo "DONE"
    echo "run_id=$run_id"
    echo "input=$(basename "$input")"
    echo "report=$(basename "$report")"
    echo "generated_at_utc=$(now_iso)"
  } > "$done_marker"

  mv "$input" "$AUDIT_DONE/$(basename "$input")"
  log "audit: done run_id=$run_id report=$report done_marker=$done_marker"
}

main() {
  shopt -s nullglob
  local inputs=("$AUDIT_IN"/*.zip "$AUDIT_IN"/*.xlsx)
  # remove unmatched globs
  local files=()
  for f in "${inputs[@]}"; do
    [[ -e "$f" ]] && files+=("$f")
  done

  if (( ${#files[@]} == 0 )); then
    log "audit: no input files (.zip/.xlsx)"
    return 0
  fi

  for f in "${files[@]}"; do
    process_one "$f"
  done
}

main "$@"

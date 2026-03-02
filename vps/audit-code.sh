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

  # Files that should never be included in findings content
  # We still flag their existence.
  {
    find "$root" -maxdepth 6 -type f \( -name ".env" -o -name ".env.*" -o -name "*.pem" -o -name "id_rsa" -o -name "id_ed25519" -o -name "*.p12" -o -name "*.pfx" \) \
      -printf '{"rule":"SENSITIVE_FILE","file":%q,"line":0}\n' || true
  } >> "$findings"

  # ripgrep based scans (fast). We only record file + line number.
  # NOTE: patterns are intentionally broad; expect false positives.
  local rg_base=(rg --no-heading --line-number --hidden --glob '!.git/**' --glob '!node_modules/**' --glob '!dist/**' --glob '!build/**' --glob '!target/**' --glob '!vendor/**' --glob '!*.min.js' --glob '!*.map')

  # Common secret-ish patterns
  "${rg_base[@]}" -S "BEGIN (RSA|EC|OPENSSH) PRIVATE KEY" "$root" 2>/dev/null \
    | awk -F: '{printf("{\"rule\":\"PRIVATE_KEY_PEM\",\"file\":%s,\"line\":%d}\n", json_escape($1), $2)}' \
    >> "$findings" || true

  "${rg_base[@]}" -S "(AKIA|ASIA)[0-9A-Z]{16}" "$root" 2>/dev/null \
    | awk -F: '{printf("{\"rule\":\"AWS_KEY_ID\",\"file\":%s,\"line\":%d}\n", json_escape($1), $2)}' \
    >> "$findings" || true

  "${rg_base[@]}" -S "(xox[baprs]-[0-9A-Za-z-]{10,})" "$root" 2>/dev/null \
    | awk -F: '{printf("{\"rule\":\"SLACK_TOKEN\",\"file\":%s,\"line\":%d}\n", json_escape($1), $2)}' \
    >> "$findings" || true

  "${rg_base[@]}" -S "(ghp_|github_pat_)[0-9A-Za-z_]{10,}" "$root" 2>/dev/null \
    | awk -F: '{printf("{\"rule\":\"GITHUB_TOKEN\",\"file\":%s,\"line\":%d}\n", json_escape($1), $2)}' \
    >> "$findings" || true

  "${rg_base[@]}" -S "(OPENAI|ANTHROPIC|CLAUDE|GEMINI|DEEPSEEK).{0,40}(KEY|TOKEN)" "$root" 2>/dev/null \
    | awk -F: '{printf("{\"rule\":\"LLM_KEYWORD\",\"file\":%s,\"line\":%d}\n", json_escape($1), $2)}' \
    >> "$findings" || true

  "${rg_base[@]}" -S "(seed phrase|mnemonic)" "$root" 2>/dev/null \
    | awk -F: '{printf("{\"rule\":\"MNEMONIC_KEYWORD\",\"file\":%s,\"line\":%d}\n", json_escape($1), $2)}' \
    >> "$findings" || true

  "${rg_base[@]}" -S "(private_key|secret_key|api[_-]?key|password)\s*[:=]" "$root" 2>/dev/null \
    | awk -F: '{printf("{\"rule\":\"GENERIC_SECRET_ASSIGN\",\"file\":%s,\"line\":%d}\n", json_escape($1), $2)}' \
    >> "$findings" || true
}

# Small awk helper: JSON-escape a string (best-effort)
# We inject this into awk via -v and a function definition.
awk_json='function json_escape(str,    out,i,c){out="\""; for(i=1;i<=length(str);i++){c=substr(str,i,1); if(c=="\\") out=out"\\\\"; else if(c=="\"") out=out"\\\""; else out=out c;} return out"\"" }'

process_one() {
  local zip="$1"
  local base
  base="$(basename "$zip" .zip)"

  local run_id
  run_id="$(date -u +"%Y%m%d-%H%M%S")_${base}"

  local workdir="$AUDIT_WORK/$run_id"
  rm -rf "$workdir"
  mkdir -p "$workdir/src"

  log "audit: start zip=$zip run_id=$run_id"

  # unzip safely
  unzip -q "$zip" -d "$workdir/src"

  local findings="$workdir/findings.jsonl"
  : > "$findings"

  # Run scans (no secret values logged)
  awk "$awk_json" </dev/null >/dev/null 2>&1 || true
  # shellcheck disable=SC2016
  export AWK_JSON="$awk_json"

  # Use awk with embedded function
  scan_rules "$workdir/src" "$findings"

  # Produce report
  local report="$AUDIT_OUT/${run_id}.report.md"
  {
    echo "# Secure Code Audit Report"
    echo
    echo "- run_id: $run_id"
    echo "- input: $(basename "$zip")"
    echo "- generated_at_utc: $(now_iso)"
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

  # Write findings to OUT as well
  if [[ -s "$findings" ]]; then
    cp "$findings" "$AUDIT_OUT/${run_id}.findings.jsonl"
  else
    : > "$AUDIT_OUT/${run_id}.findings.jsonl"
  fi

  mv "$zip" "$AUDIT_DONE/$(basename "$zip")"
  log "audit: done run_id=$run_id report=$report"
}

main() {
  shopt -s nullglob
  local zips=("$AUDIT_IN"/*.zip)
  if (( ${#zips[@]} == 0 )); then
    log "audit: no input zips"
    return 0
  fi

  for z in "${zips[@]}"; do
    process_one "$z"
  done
}

main "$@"

#!/usr/bin/env bash
set -euo pipefail

# Host-side task runner.
# - Claims 1 task (lease-based) as aluma:worker
# - Executes known task types (ENS workflow v1)
# - Writes report events to Postgres
# - Marks tasks done/blocked

: "${RAG_DB_URL:?set RAG_DB_URL}"
: "${TELEGRAM_TOKEN:?set TELEGRAM_TOKEN}"
: "${TELEGRAM_CHAT_ID:?set TELEGRAM_CHAT_ID}"

AGENT_ID="aluma:worker"
LEASE_SECONDS="600"

# Ensure Foundry is on PATH for non-interactive runs
export PATH="$HOME/.foundry/bin:$PATH"

send_tg() {
  local text="$1"
  curl -sS -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
    -d chat_id="${TELEGRAM_CHAT_ID}" \
    --data-urlencode text="$text" \
    -d disable_web_page_preview=true >/dev/null 2>&1 || true
}

psqlq() {
  psql "$RAG_DB_URL" -v ON_ERROR_STOP=1 -At -F $'\t' -c "$1"
}

claim_task_id() {
  # Returns claimed id or empty.
  # NOTE: we only execute tasks owned by "aluma" (executor lane). Coordinator tasks are skipped.
  local id
  id=$(psqlq "SELECT (orchestration_claim_task('${AGENT_ID}', ${LEASE_SECONDS})).id;" 2>/dev/null | head -n1 | tr -d '[:space:]' | grep -E '^[0-9]+$' || true)
  if [[ -z "${id:-}" ]]; then
    return 0
  fi

  local owner
  owner=$(psqlq "SELECT owner FROM orchestration_task WHERE id=${id};" | tr -d '[:space:]' || true)
  if [[ "${owner:-}" != "aluma" ]]; then
    # Release claim and skip.
    psqlq "UPDATE orchestration_task SET status='queued', claimed_by='', claimed_at=NULL, lease_expires_at=NULL, updated_at=now() WHERE id=${id} AND claimed_by='${AGENT_ID}';" >/dev/null 2>&1 || true
    echo ""
    return 0
  fi

  echo "$id"
}

post_report() {
  local task_id="$1"; shift
  local msg="$*"
  # Escape single quotes for SQL literal.
  local esc
  esc=${msg//"'"/"''"}
  psqlq "INSERT INTO orchestration_event(kind, task_id, actor, message, tags) VALUES ('report', ${task_id}, '${AGENT_ID}', '${esc}', ARRAY['runner']);" >/dev/null
  send_tg "[runner][report] task_id=${task_id}\n${msg}"
}

mark_done() {
  local task_id="$1"
  psqlq "UPDATE orchestration_task SET status='done', updated_at=now() WHERE id=${task_id} AND claimed_by='${AGENT_ID}';"
}

mark_blocked() {
  local task_id="$1"; shift
  local reason="$*"
  local esc
  esc=${reason//"'"/"''"}
  psqlq "UPDATE orchestration_task
        SET status='blocked',
            debug_notes=CASE WHEN debug_notes='' THEN '${esc}' ELSE debug_notes || E'\\n' || '${esc}' END,
            updated_at=now()
        WHERE id=${task_id} AND claimed_by='${AGENT_ID}';" >/dev/null
  post_report "$task_id" "BLOCKED: ${reason}"
}

handle_task() {
  local id="$1"
  local title="$2"
  local body="$3"
  local url="$4"

  if [[ "$title" == ENS:*deployments* ]]; then
    # Fetch deployments wiki and extract core addresses.
    local page
    # Prefer the raw wiki markdown (stable to parse)
    local raw_url="https://raw.githubusercontent.com/wiki/ensdomains/ens-contracts/ENS-Contract-Deployments.md"
    local page
    page=$(curl -fsSL "$raw_url" || true)
    if [[ -z "$page" ]]; then
      # fallback to the HTML page
      page=$(curl -fsSL "$url" || true)
    fi
    if [[ -z "$page" ]]; then
      mark_blocked "$id" "failed to fetch deployments page (raw+html): $url"
      return
    fi

    # Extract core addresses
    local out
    out=$(printf "%s" "$page" | grep -Eo '0x[a-fA-F0-9]{40}' | head -n 40 | tr '\n' ' ' || true)
    post_report "$id" "Fetched deployments list. First addresses: ${out}"
    mark_done "$id"
    return
  fi

  if [[ "$title" == ENS:*clone*ens-contracts* ]]; then
    local dest="/home/ubuntu/.openclaw/workspace/targets/ens-contracts"
    mkdir -p /home/ubuntu/.openclaw/workspace/targets
    if [[ -d "$dest/.git" ]]; then
      git -C "$dest" fetch --all -q && git -C "$dest" reset --hard origin/master -q || true
    else
      git clone -q https://github.com/ensdomains/ens-contracts "$dest"
    fi
    local files
    files=$(find "$dest" -maxdepth 6 -type f -name '*.sol' | wc -l | tr -d ' ')
    local top
    top=$(find "$dest/contracts" -maxdepth 2 -type f -name '*.sol' | head -n 12 | sed 's#^'$dest'/##' | tr '\n' '; ')
    post_report "$id" "Cloned ens-contracts to $dest. Solidity files: $files. Sample: ${top}. Next: identify Registry/Registrar/Controller/Resolver/Wrapper entrypoints."
    mark_done "$id"
    return
  fi

  if [[ "$title" == ENS:*Foundry*fork*harness* ]]; then
    if ! command -v forge >/dev/null 2>&1; then
      mark_blocked "$id" "Foundry (forge) not installed on host. Install Foundry or provide path."
      return
    fi
    local proj="/home/ubuntu/.openclaw/workspace/targets/ens-foundry"
    if [[ ! -d "$proj" ]]; then
      mkdir -p "$proj"
      (cd /home/ubuntu/.openclaw/workspace/targets && forge init -q ens-foundry)
    fi
    post_report "$id" "Foundry harness ready at $proj. Next: add fork RPC + smoke test ENSRegistry.owner(namehash)."
    mark_done "$id"
    return
  fi

  if [[ "$title" == ENS:*hypotheses* ]]; then
    post_report "$id" "Hypotheses (start): (1) RegistrarController register/renew duration/pricing edge cases; (2) NameWrapper fuse/state race variants; (3) Resolver auth bypass / unauthorized record change. Proceeding with (1) first."
    mark_done "$id"
    return
  fi

  if [[ "$title" == ENS\ PoC:*fork*smoke*test* ]]; then
    local proj="/home/ubuntu/.openclaw/workspace/targets/ens-foundry"
    if [[ ! -d "$proj" ]]; then
      mark_blocked "$id" "Foundry project missing at $proj (expected from previous workflow)."
      return
    fi
    if [[ -z "${ETH_RPC_URL:-}" ]]; then
      mark_blocked "$id" "ETH_RPC_URL not set in runner env. Add ETH_RPC_URL=<mainnet RPC> to /home/ubuntu/.openclaw/moltbot2.env, then requeue."
      return
    fi
    local testfile="$proj/test/SmokeENS.t.sol"
    cat > "$testfile" <<'EOF'
// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.20;

import "forge-std/Test.sol";

interface IENSRegistry {
    function owner(bytes32 node) external view returns (address);
}

contract SmokeENS is Test {
    // ENSRegistry mainnet
    address constant ENS = 0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e;

    function namehash(bytes32 label) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(bytes32(0), label));
    }

    function test_registry_owner_eth_nonzero() public {
        bytes32 ethNode = namehash(keccak256("eth"));
        address o = IENSRegistry(ENS).owner(ethNode);
        assertTrue(o != address(0), "owner(eth) should be nonzero on mainnet fork");
    }
}
EOF

    (cd "$proj" && forge test --fork-url "$ETH_RPC_URL" -q) || {
      mark_blocked "$id" "forge test failed; check RPC or fork settings."
      return
    }
    post_report "$id" "Smoke test passed on mainnet fork. Test file: $testfile"
    mark_done "$id"
    return
  fi

  if [[ "$title" == ENS\ PoC:*map*RegistrarController* ]]; then
    local repo="/home/ubuntu/.openclaw/workspace/targets/ens-contracts"
    if [[ ! -d "$repo" ]]; then
      mark_blocked "$id" "ens-contracts repo missing at $repo"
      return
    fi
    # Find likely controller contract and key functions
    local hits
    hits=$(rg -n "contract .*RegistrarController|function register\(|function renew\(" "$repo/contracts" | head -n 40 || true)
    post_report "$id" "RegistrarController mapping (first hits):\n${hits}"
    mark_done "$id"
    return
  fi

  if [[ "$title" == ENS\ PoC\ attempt*duration/pricing* ]]; then
    post_report "$id" "PoC attempt plan: (a) inspect register/renew duration bounds + overflow/underflow; (b) pricing oracle rounding + premium logic; (c) refund handling. Next: implement failing test cases in ens-foundry." 
    mark_done "$id"
    return
  fi

  if [[ "$title" == ENS\ writeup\ skeleton* ]]; then
    local out="/home/ubuntu/.openclaw/workspace/targets/ens-foundry/IMMUNEFI_REPORT.md"
    cat > "$out" <<'EOF'
# Immunefi Report Draft (ENS)

## Title

## Summary

## Impact

## Affected Components

## Steps to Reproduce

## Proof of Concept

## Mitigation

## Scope Proof
- Program: https://immunefi.com/bug-bounty/ens/
- Deployments: https://github.com/ensdomains/ens-contracts/wiki/ENS-Contract-Deployments

EOF
    post_report "$id" "Created report skeleton at $out"
    mark_done "$id"
    return
  fi

  if [[ "$title" == ENS\ web/app\ triage*high-EV* ]] || [[ "$title" == ENS\ web/app\ triage* ]] || [[ "$title" == ENS:*web/app*triage* ]]; then
    # Manual triage using local repos if present; otherwise pull the scope repos.
    local base="/home/ubuntu/.openclaw/workspace/targets"
    mkdir -p "$base"

    # Try to ensure repos exist
    local app_repo="$base/ens-app-v3"
    local meta_repo="$base/metadata-service"

    if [[ ! -d "$app_repo/.git" ]]; then
      git clone -q https://github.com/ensdomains/ens-app-v3 "$app_repo" || true
    fi
    if [[ ! -d "$meta_repo/.git" ]]; then
      git clone -q https://github.com/ensdomains/metadata-service "$meta_repo" || true
    fi

    # Heuristic: look for wallet tx building + record update flows
    local hits
    hits=$( (rg -n "sendTransaction|eth_sendTransaction|wallet|connector|wagmi|viem|ethers" "$app_repo" 2>/dev/null || true; \
            rg -n "setAddr|setText|setContenthash|setResolver|setOwner" "$app_repo" 2>/dev/null || true) | head -n 60 )

    local hits2
    hits2=$( (rg -n "metadata|image|animation_url|description|name" "$meta_repo" 2>/dev/null || true; \
              rg -n "sanitize|escape|html|script|xss" "$meta_repo" 2>/dev/null || true) | head -n 40 )

    post_report "$id" "Web/App triage quick hits:\n[ens-app-v3]\n${hits}\n\n[metadata-service]\n${hits2}\n\nHypotheses to pursue: (1) state-modifying authenticated action via request tampering; (2) wallet-tx parameter substitution in app flow; (3) metadata HTML injection → wallet interaction/XSS (per scope)."
    mark_done "$id"
    return
  fi

  if [[ "$title" == Install\ Foundry* ]] || [[ "$title" == *Foundry*forge* ]]; then
    # Install Foundry toolchain for PoC work.
    if command -v forge >/dev/null 2>&1; then
      post_report "$id" "Foundry already installed: $(forge --version 2>/dev/null | head -n1)"
      mark_done "$id"
      return
    fi

    # Install dependencies if missing
    command -v curl >/dev/null 2>&1 || sudo apt-get update -y && sudo apt-get install -y curl

    # Install foundryup
    curl -fsSL https://foundry.paradigm.xyz | bash

    # shellcheck disable=SC1090
    if [ -f "$HOME/.bashrc" ]; then
      # ensure PATH for this run
      export PATH="$HOME/.foundry/bin:$PATH"
    fi

    "$HOME/.foundry/bin/foundryup"

    if command -v forge >/dev/null 2>&1; then
      post_report "$id" "Installed Foundry OK: $(forge --version 2>/dev/null | head -n1)"
      mark_done "$id"
      return
    fi

    mark_blocked "$id" "Foundry install attempted but forge still missing"
    return
  fi

  mark_blocked "$id" "Unknown task title; runner has no handler: $title"
}

main() {
  # If we already have a running task with unexpired lease, execute that one.
  local running_id
  running_id=$(psqlq "SELECT id FROM orchestration_task WHERE status='running' AND claimed_by='${AGENT_ID}' AND lease_expires_at IS NOT NULL AND lease_expires_at >= now() ORDER BY updated_at DESC LIMIT 1;" | tr -d '[:space:]' || true)

  local task_id
  if [[ -n "${running_id:-}" ]]; then
    task_id="$running_id"
  else
    task_id=$(claim_task_id)
  fi

  if [[ -z "${task_id:-}" ]]; then
    exit 0
  fi

  # Renew lease early to avoid expiry mid-run
  psqlq "SELECT orchestration_heartbeat(${task_id}, '${AGENT_ID}', ${LEASE_SECONDS});" >/dev/null 2>&1 || true

  # Load task details
  IFS=$'\t' read -r title body url < <(psqlq "SELECT title, body, source_url FROM orchestration_task WHERE id=${task_id};")
  handle_task "$task_id" "$title" "$body" "$url"
}

main "$@"

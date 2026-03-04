# Secure code audit (VPS-only, redacted)

Goal: run sensitive code audits without leaking secrets (e.g., `.env` values) outside the VPS/node.

## Design
- Input arrives as **zip** files dropped into a VPS folder.
- Audit runs entirely on the VPS.
- Output is **redacted**:
  - we never print secret values
  - we only report **rule id + file path + line number**
- Output is written to `OUT/` as `*.report.md` + `*.findings.jsonl`.

## Folders (VPS)
Root: `/home/ubuntu/.openclaw/audit`

- `in/` — drop `*.zip` here
- `out/` — redacted reports + findings
- `done/` — processed zips
- `work/` — temporary extraction dir
- `logs/` — audit logs

## Runner
- Script: `/usr/local/bin/audit-code.sh`

## Schedule
- systemd:
  - `audit-code.service` (oneshot)
  - `audit-code.timer` (every 30 minutes)

Check:
```bash
systemctl status audit-code.timer --no-pager
journalctl -u audit-code.service -n 100 --no-pager
```

## Usage
1) Create a zip of the repo/code you want audited.
2) Upload it to the VPS:

```bash
scp repo.zip ubuntu@<vps>:/home/ubuntu/.openclaw/audit/in/
```

3) Wait for the timer (or run now):

```bash
sudo systemctl start audit-code.service
```

4) Download report from:

- `/home/ubuntu/.openclaw/audit/out/`

## Notes
- This is a heuristic scan (fast MVP). Add Semgrep/Gitleaks later if needed.
- Do not commit audit outputs to git.

## Completion marker
For sync workflows (WinSCP), each run also writes a small completion marker next to the report:
- `out/<run_id>.done.txt`

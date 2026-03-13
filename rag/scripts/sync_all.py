"""VPS writer job: run the full RAG sync loop.

Designed to be called from systemd timer (rag-sync.timer).
Keep it deterministic and quiet; logs go to journal.

Order:
- init_tree (idempotent)
- ingest_openclaw_sessions
- auto_tag
- summarize_topics
"""

import subprocess
import sys


STEPS = [
    [sys.executable, "-m", "rag.scripts.init_tree"],
    [sys.executable, "-m", "rag.scripts.ingest_openclaw_sessions"],
    [sys.executable, "-m", "rag.scripts.auto_tag"],
    [sys.executable, "-m", "rag.scripts.summarize_topics"],
]


def main() -> int:
    for cmd in STEPS:
        print(f"==> {' '.join(cmd)}")
        subprocess.check_call(cmd)
    print("ok: sync_all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

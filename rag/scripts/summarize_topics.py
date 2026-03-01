"""Generate "fruitful summaries" per topic into rag_summary.

MVP implementation (no external LLM):
- Pull linked messages for each topic via rag_keyword
- Decrypt bodies
- Extract:
  - key decisions
  - key commands
  - key errors
- Store encrypted summary in rag_summary + plaintext teaser (non-sensitive)

This gives clean recall without exposing raw logs.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict

import psycopg

DB = os.environ.get("RAG_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5432/rag")
KEY = os.environ.get("RAG_ENCRYPTION_KEY")
if not KEY:
    raise SystemExit("Missing RAG_ENCRYPTION_KEY")

CMD_PAT = re.compile(r"^(ssh |openclaw |ufw |fail2ban-client |systemctl |journalctl |curl |psql )", re.I)
ERR_PAT = re.compile(r"(device signature invalid|ECONNREFUSED|1008|exec denied|fail2ban|banned)", re.I)


def encrypt(cur, plain: str, key: str) -> bytes:
    cur.execute("SELECT pgp_sym_encrypt(%s, %s)", (plain, key))
    return cur.fetchone()[0]


def decrypt(cur, cipher: bytes, key: str) -> str:
    cur.execute("SELECT pgp_sym_decrypt(%s, %s)", (psycopg.Binary(cipher), key))
    return str(cur.fetchone()[0] or "")


def build_summary(texts: list[str], title: str) -> tuple[str, str]:
    # Extract commands/errors/decisions
    cmds = []
    errs = []
    decisions = []

    for t in texts:
        for line in t.splitlines():
            s = line.strip()
            if not s:
                continue
            if CMD_PAT.search(s):
                cmds.append(s)
            if ERR_PAT.search(s):
                errs.append(s)
            if s.lower().startswith(("decision", "key decision", "we decided", "we will", "approved")):
                decisions.append(s)

    # de-dupe while preserving order
    def uniq(xs):
        out=[]
        seen=set()
        for x in xs:
            if x in seen: continue
            seen.add(x)
            out.append(x)
        return out

    cmds = uniq(cmds)[:12]
    errs = uniq(errs)[:12]
    decisions = uniq(decisions)[:12]

    summary_lines = [
        f"# {title}",
        "",
        "## What happened",
        f"- Collected and indexed messages linked to this topic.",
    ]

    if decisions:
        summary_lines += ["", "## Decisions / approvals", *[f"- {d}" for d in decisions]]

    if errs:
        summary_lines += ["", "## Notable errors / symptoms", *[f"- {e}" for e in errs]]

    if cmds:
        summary_lines += ["", "## Key commands (most useful)", *[f"- `{c}`" for c in cmds]]

    summary_lines += [
        "",
        "## Next steps",
        "- Refine tagging rules + add semantic search later if needed.",
        "- Add manual curated notes for this topic as new info arrives.",
    ]

    full = "\n".join(summary_lines).strip() + "\n"

    teaser = f"{title}: {(' / '.join(cmds[:3]))[:140]}" if cmds else f"{title}: summary generated"
    return full, teaser


def main():
    with psycopg.connect(DB) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, slug, title FROM rag_topic ORDER BY id")
            topics = cur.fetchall()

            updated = 0
            for topic_id, slug, title in topics:
                # gather message ids linked to this topic
                cur.execute(
                    """
                    SELECT DISTINCT m.id, m.body_cipher
                    FROM rag_keyword k
                    JOIN rag_message m ON m.id = k.message_id
                    WHERE k.topic_id=%s
                    ORDER BY m.id DESC
                    LIMIT 200
                    """,
                    (topic_id,),
                )
                rows = cur.fetchall()
                if not rows:
                    continue

                texts = [decrypt(cur, cipher, KEY) for _, cipher in rows]
                summary, teaser = build_summary(texts, title)
                cipher = encrypt(cur, summary, KEY)

                cur.execute(
                    """
                    INSERT INTO rag_summary(topic_id, summary_cipher, teaser)
                    VALUES (%s,%s,%s)
                    ON CONFLICT (topic_id)
                    DO UPDATE SET updated_at=now(), summary_cipher=EXCLUDED.summary_cipher, teaser=EXCLUDED.teaser
                    """,
                    (topic_id, psycopg.Binary(cipher), teaser),
                )
                updated += 1

        conn.commit()

    print(f"ok: summaries_updated={updated}")


if __name__ == "__main__":
    main()

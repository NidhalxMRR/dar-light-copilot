"""Show a branch with keyword counts + sample message snippets."""

from __future__ import annotations

import os
import psycopg

DB = os.environ.get("RAG_DATABASE_URL", "postgresql://rag:rag@127.0.0.1:5432/rag")
KEY = os.environ.get("RAG_ENCRYPTION_KEY")


def get_topic_id(cur, path: str) -> int | None:
    parts = path.split("/")
    parent = None
    for slug in parts:
        if parent is None:
            cur.execute("SELECT id FROM rag_topic WHERE parent_id IS NULL AND slug=%s", (slug,))
        else:
            cur.execute("SELECT id FROM rag_topic WHERE parent_id=%s AND slug=%s", (parent, slug))
        r = cur.fetchone()
        if not r:
            return None
        parent = r[0]
    return parent


def main():
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "openclaw/windows-node/debug"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    with psycopg.connect(DB) as conn:
        with conn.cursor() as cur:
            tid = get_topic_id(cur, path)
            if tid is None:
                raise SystemExit(f"topic not found: {path}")

            cur.execute("SELECT count(*) FROM rag_keyword WHERE topic_id=%s", (tid,))
            kwc = cur.fetchone()[0]
            print(f"Topic: {path}  keywords={kwc}")

            cur.execute(
                """
                SELECT m.ts, m.role, m.body_cipher
                FROM rag_keyword k
                JOIN rag_message m ON m.id = k.message_id
                WHERE k.topic_id=%s
                GROUP BY m.id
                ORDER BY max(m.ts) DESC
                LIMIT %s
                """,
                (tid, limit),
            )
            rows = cur.fetchall()

            if not rows:
                print("(no linked messages yet)")
                return

            if not KEY:
                print("(no RAG_ENCRYPTION_KEY in env; cannot decrypt snippets)")
                return

            for ts, role, cipher in rows:
                cur.execute("SELECT pgp_sym_decrypt(%s, %s)", (psycopg.Binary(cipher), KEY))
                body = cur.fetchone()[0]
                s = str(body).replace("\n", " ")[:180]
                print(f"- [{ts}] {role}: {s}...")


if __name__ == "__main__":
    main()

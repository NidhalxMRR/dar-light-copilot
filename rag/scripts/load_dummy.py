"""Load dummy (non-sensitive) data to demonstrate indexing + topic tree."""

import os
from datetime import datetime, timezone
import psycopg
from rag.scripts.db import connect, sha256_hex


def main():
    # Dummy text only
    msgs = [
        ("telegram", "agent:main:telegram:direct:6072002251", "user", "We implemented secwatch + Telegram alerts."),
        ("telegram", "agent:main:telegram:direct:6072002251", "assistant", "UFW allow 22/tcp only; fail2ban sshd enabled."),
        ("openclaw-ui", "control-ui", "user", "Node pairing was failing: device signature invalid."),
    ]

    with connect() as conn:
        with conn.cursor() as cur:
            for source, sk, role, body in msgs:
                cur.execute(
                    "INSERT INTO rag_session(source, session_key) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (source, sk),
                )
                cur.execute(
                    "SELECT id FROM rag_session WHERE source=%s AND session_key=%s",
                    (source, sk),
                )
                session_id = cur.fetchone()[0]

                # Encrypt body using pgcrypto
                key = os.getenv("RAG_ENCRYPTION_KEY")
                if not key or key.startswith("CHANGE_ME"):
                    raise RuntimeError("Set a real RAG_ENCRYPTION_KEY in your env/.env before loading data")
                sha = sha256_hex(body)
                cur.execute("SELECT pgp_sym_encrypt(%s, %s)", (body, key))
                cipher = cur.fetchone()[0]
                cur.execute(
                    "INSERT INTO rag_message(session_id, ts, role, body_cipher, body_sha256) VALUES (%s,%s,%s,%s,%s)",
                    (session_id, datetime.now(timezone.utc), role, psycopg.Binary(cipher), sha),
                )
                msg_id = cur.fetchone()[0] if cur.description else None

            # Create a simple topic tree
            cur.execute("INSERT INTO rag_topic(parent_id, slug, title) VALUES (NULL,'business','Business') ON CONFLICT DO NOTHING")
            cur.execute("SELECT id FROM rag_topic WHERE parent_id IS NULL AND slug='business'")
            business_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO rag_topic(parent_id, slug, title) VALUES (%s,'mr-r','MR R') ON CONFLICT DO NOTHING",
                (business_id,),
            )
            cur.execute("SELECT id FROM rag_topic WHERE parent_id=%s AND slug='mr-r'", (business_id,))
            mrr_id = cur.fetchone()[0]
            for slug, title in [
                ("security-startup", "Security startup"),
                ("devops", "DevOps"),
                ("trading", "Trading"),
            ]:
                cur.execute(
                    "INSERT INTO rag_topic(parent_id, slug, title) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (mrr_id, slug, title),
                )

            # Add some keywords
            cur.execute("SELECT id FROM rag_topic WHERE slug='security-startup'")
            sec_id = cur.fetchone()[0]
            for kw in ["secwatch", "ufw", "fail2ban", "telegram", "hardening"]:
                cur.execute(
                    "INSERT INTO rag_keyword(topic_id, message_id, keyword, weight) VALUES (%s, NULL, %s, 1)",
                    (sec_id, kw),
                )

        conn.commit()

    print("ok: loaded dummy")


if __name__ == "__main__":
    main()

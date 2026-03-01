"""Auto-tagging MVP.

- Decrypts message bodies on the VPS using the local encryption key.
- Assigns messages to topic nodes via keyword rules.
- Stores ONLY derived keywords + weights + (optional) topic/message links.

No plaintext is written to disk.
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

# Simple rule-based mapping (hackathon MVP)
RULES: list[tuple[str, list[str]]] = [
    ("openclaw/windows-node/debug", [
        "device signature invalid", "1008", "websocket", "gateway", "node run", "openclaw node", "paired", "pending",
        "approval", "exec denied", "tunnel", "ssh -n", "-l", "port forward", "econnrefused"
    ]),
    ("security/vps-hardening/ufw", ["ufw", "deny incoming", "allow 22", "22/tcp"]),
    ("security/vps-hardening/fail2ban", ["fail2ban", "sshd jail", "ban", "unban", "banned"]),
    ("security/vps-hardening/secwatch", ["secwatch", "mrsec-hourly", "hourly report", "timer", "systemd"]),
    ("business/mr-r/security-startup", ["mr security", "fiverr", "upwork", "client report", "pricing", "offer"]),
    ("business/mr-r/devops", ["sre", "devops", "monitoring", "uptime", "incident", "runbook"]),
    ("business/mr-r/trading", ["trading", "crypto", "redotpay"]),
]

# Keywords to extract (derived index)
KW_RE = re.compile(r"[a-z0-9][a-z0-9\-]{2,}")
STOP = {
    "the","and","for","with","this","that","you","your","are","was","were","have","has","from",
    "into","then","when","what","how","we","our","can","will","just","like","also","only","not",
    "but","its","it's","dont","does","did","been","them","they","his","her","she","him","who",
    "http","https","www","com","org","net","localhost","ubuntu","windows","system32","users","xfive"
}


def get_topic_id(cur, path: str) -> int | None:
    # path like openclaw/windows-node/debug
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


def extract_keywords(text: str) -> dict[str, int]:
    words = [w.lower() for w in KW_RE.findall(text.lower())]
    freq: dict[str, int] = {}
    for w in words:
        if w in STOP:
            continue
        if w.startswith("<redacted"):
            continue
        freq[w] = freq.get(w, 0) + 1
    # keep top-ish
    return dict(sorted(freq.items(), key=lambda kv: kv[1], reverse=True)[:25])


def main():
    with psycopg.connect(DB) as conn:
        with conn.cursor() as cur:
            # Pre-resolve rule topic IDs
            rule_topic_ids = []
            for path, needles in RULES:
                tid = get_topic_id(cur, path)
                if tid is None:
                    print(f"warn: topic path not found: {path}")
                    continue
                rule_topic_ids.append((tid, path, [n.lower() for n in needles]))

            # iterate messages
            cur.execute("SELECT id, body_cipher FROM rag_message")
            rows = cur.fetchall()

            inserted_kw = 0
            linked = 0

            for msg_id, cipher in rows:
                # decrypt
                cur.execute("SELECT pgp_sym_decrypt(%s, %s)", (psycopg.Binary(cipher), KEY))
                plain = cur.fetchone()[0]
                if not plain:
                    continue
                text = str(plain)
                low = text.lower()

                # determine topic hits
                hit_topics = []
                for tid, path, needles in rule_topic_ids:
                    if any(n in low for n in needles):
                        hit_topics.append(tid)

                if not hit_topics:
                    continue

                # derived keywords
                kws = extract_keywords(low)

                for tid in hit_topics:
                    # store keyword weights
                    for kw, w in kws.items():
                        cur.execute(
                            "INSERT INTO rag_keyword(topic_id, message_id, keyword, weight) VALUES (%s,%s,%s,%s)",
                            (tid, msg_id, kw, int(w)),
                        )
                        inserted_kw += 1
                    linked += 1

            conn.commit()

    print(f"ok: linked_messages={linked} inserted_keywords={inserted_kw}")


if __name__ == "__main__":
    main()

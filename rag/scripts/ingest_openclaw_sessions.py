"""Ingest OpenClaw agent session JSONL files into Postgres.

- Encrypt message bodies (pgcrypto)
- Redact obvious secrets before storing
- Store keywords separately (non-sensitive)

This is MVP-quality ingestion for hackathon.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

import psycopg

from rag.scripts.db import connect, sha256_hex

TOKEN_HEX64 = re.compile(r"\b[0-9a-f]{64}\b", re.I)
URL_TOKEN = re.compile(r"(#token=)[0-9a-f]{16,}", re.I)
ENV_TOKEN = re.compile(r"(OPENCLAW_GATEWAY_TOKEN=)[0-9a-f]{16,}", re.I)


def redact(text: str) -> str:
    t = URL_TOKEN.sub(r"\1<REDACTED>", text)
    t = ENV_TOKEN.sub(r"\1<REDACTED>", t)
    # if any 64-hex token occurs, redact it
    t = TOKEN_HEX64.sub("<REDACTED_TOKEN>", t)
    return t


def extract_text(content) -> str:
    if not isinstance(content, list):
        return ""
    parts = []
    for blk in content:
        if blk.get("type") == "text":
            parts.append(blk.get("text", ""))
    return "\n".join([p for p in parts if p]).strip()


def upsert_session(cur, source: str, session_key: str) -> int:
    cur.execute(
        "INSERT INTO rag_session(source, session_key) VALUES (%s,%s) ON CONFLICT(source, session_key) DO UPDATE SET session_key=EXCLUDED.session_key RETURNING id",
        (source, session_key),
    )
    return cur.fetchone()[0]


def encrypt(cur, plain: str, key: str) -> bytes:
    cur.execute("SELECT pgp_sym_encrypt(%s, %s)", (plain, key))
    return cur.fetchone()[0]


def ingest_file(path: Path, source: str = "openclaw-session") -> dict:
    key = os.environ.get("RAG_ENCRYPTION_KEY", "")
    if not key or key.startswith("CHANGE_ME"):
        raise RuntimeError("Missing/weak RAG_ENCRYPTION_KEY in env")

    inserted = 0
    skipped = 0

    with connect() as conn:
        with conn.cursor() as cur:
            session_id = upsert_session(cur, source, str(path))

            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    skipped += 1
                    continue

                if obj.get("type") != "message":
                    continue

                ts = obj.get("timestamp")
                msg = obj.get("message", {})
                role = msg.get("role")
                content = msg.get("content")
                body = extract_text(content)
                if not body:
                    continue

                body = redact(body)
                sha = sha256_hex(body)

                # de-dupe by sha within DB
                cur.execute("SELECT 1 FROM rag_message WHERE body_sha256=%s LIMIT 1", (sha,))
                if cur.fetchone():
                    continue

                cipher = encrypt(cur, body, key)

                cur.execute(
                    "INSERT INTO rag_message(session_id, ts, role, body_cipher, body_sha256, meta_json) VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        session_id,
                        datetime.fromisoformat(ts.replace("Z", "+00:00")),
                        role,
                        psycopg.Binary(cipher),
                        sha,
                        json.dumps({"source": source, "sessionFile": str(path)}),
                    ),
                )
                inserted += 1

        conn.commit()

    return {"file": str(path), "inserted": inserted, "skipped": skipped}


def main():
    base = Path("/home/ubuntu/.openclaw/agents")
    files = list(base.glob("**/*.jsonl"))
    files = [f for f in files if not f.name.endswith(".lock")]

    results = []
    for f in sorted(files, key=lambda p: p.stat().st_mtime):
        results.append(ingest_file(f))

    print(json.dumps({"files": len(files), "results": results}, indent=2))


if __name__ == "__main__":
    main()

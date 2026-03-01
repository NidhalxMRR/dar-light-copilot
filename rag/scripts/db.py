import os
import hashlib
import psycopg


def get_env(name: str, default: str | None = None) -> str:
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing env var: {name}")
    return v


def database_url() -> str:
    return get_env("RAG_DATABASE_URL")


def enc_key() -> str:
    key = get_env("RAG_ENCRYPTION_KEY")
    if os.getenv("RAG_REQUIRE_STRONG_KEY", "1") == "1" and key.startswith("CHANGE_ME"):
        raise RuntimeError("Refusing to run: RAG_ENCRYPTION_KEY is default")
    return key


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def connect():
    return psycopg.connect(database_url())


def pg_encrypt(conn: psycopg.Connection, plain: str) -> tuple[bytes, str]:
    """Encrypt using pgcrypto (pgp_sym_encrypt).

    Returns (cipher_bytes, sha256_hex).
    """
    key = enc_key()
    sha = sha256_hex(plain)
    with conn.cursor() as cur:
        cur.execute("SELECT pgp_sym_encrypt(%s, %s)", (plain, key))
        cipher = cur.fetchone()[0]
    return cipher, sha


def pg_decrypt(conn: psycopg.Connection, cipher: bytes) -> str:
    key = enc_key()
    with conn.cursor() as cur:
        cur.execute("SELECT pgp_sym_decrypt(%s, %s)", (psycopg.Binary(cipher), key))
        plain = cur.fetchone()[0]
    return plain

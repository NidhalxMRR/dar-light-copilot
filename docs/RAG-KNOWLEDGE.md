# Knowledge Base (Postgres RAG)

Goal: One logical knowledge system across multiple chat surfaces (Telegram + Control UI + future sub-bots), without committing sensitive data to Git.

## Rules
- Repo contains **code + schema only**.
- VPS contains **data**.
- Tokens/credentials never enter Git.

## Security model
- Postgres listens on **localhost** only.
- Field-level encryption for raw text using pgcrypto is supported.
- Retrieval uses derived artifacts (keywords, topics, summaries). If you want full semantic search later, we can add embeddings with strict key handling.

## Topic tree
Business → MR R → {Security startup, DevOps, Trading}
Security → VPS hardening → {UFW, fail2ban, secwatch}
OpenClaw → Windows node pairing → {tunnel, token, approvals}

## Backups
Implement a systemd timer to run `pg_dump` to a local path on the VPS. (Backups are **not** committed.)


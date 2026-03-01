# Postgres RAG (Telegram-first) — dar-light-copilot

This folder contains the **code + schema** for our internal “one brain” knowledge system.

## Non-goals / security
- **Do not commit real chat logs**.
- **Do not commit tokens**.
- Repo contains only: schema, migrations, scripts, and **dummy data**.

## Architecture
- Data lives on the VPS in **PostgreSQL** bound to **localhost**.
- Optional pooler: pgbouncer.
- Messages can be stored **encrypted at rest at field-level** (pgcrypto) while keeping **derived indexes** (keywords/tags) for retrieval.

## Quick start (dev/demo)
1) Copy env:
```bash
cp .env.example .env
```
2) Start DB (docker):
```bash
docker compose -f docker-compose.yml up -d
```
3) Apply schema:
```bash
python3 -m rag.scripts.migrate
```
4) Load dummy data:
```bash
python3 -m rag.scripts.load_dummy
```
5) Search:
```bash
python3 -m rag.scripts.search "secwatch"
```


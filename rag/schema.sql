-- Postgres RAG schema (code-only; no sensitive data)

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Sources: telegram, control-ui, etc.
CREATE TABLE IF NOT EXISTS rag_session (
  id              bigserial PRIMARY KEY,
  source          text NOT NULL,
  session_key     text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE(source, session_key)
);

-- Raw message bodies are stored encrypted.
-- Derived searchable artifacts should be stored separately.
CREATE TABLE IF NOT EXISTS rag_message (
  id              bigserial PRIMARY KEY,
  session_id      bigint NOT NULL REFERENCES rag_session(id) ON DELETE CASCADE,
  ts             timestamptz NOT NULL,
  role            text NOT NULL,
  body_cipher     bytea NOT NULL,
  body_sha256     text NOT NULL,
  meta_json       jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS rag_message_session_ts_idx ON rag_message(session_id, ts);
CREATE INDEX IF NOT EXISTS rag_message_sha_idx ON rag_message(body_sha256);

-- Topic tree (your requested structure)
CREATE TABLE IF NOT EXISTS rag_topic (
  id          bigserial PRIMARY KEY,
  parent_id   bigint REFERENCES rag_topic(id) ON DELETE CASCADE,
  slug        text NOT NULL,
  title       text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE(parent_id, slug)
);

-- Curated summaries per topic node (encrypted + plaintext redacted teaser)
CREATE TABLE IF NOT EXISTS rag_summary (
  id            bigserial PRIMARY KEY,
  topic_id      bigint NOT NULL REFERENCES rag_topic(id) ON DELETE CASCADE,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  summary_cipher bytea NOT NULL,
  teaser        text NOT NULL DEFAULT ''
);

-- Search index table: store only non-sensitive derived terms.
-- (If you decide later to allow plaintext chunks, we can add an FTS tsvector.)
CREATE TABLE IF NOT EXISTS rag_keyword (
  id          bigserial PRIMARY KEY,
  topic_id    bigint REFERENCES rag_topic(id) ON DELETE CASCADE,
  message_id  bigint REFERENCES rag_message(id) ON DELETE CASCADE,
  keyword     text NOT NULL,
  weight      int NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS rag_keyword_kw_idx ON rag_keyword(keyword);


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

-- Orchestration layer (non-sensitive): tasks + events/decisions.
-- These tables are intentionally plaintext so both the main agent and sub-agents
-- can coordinate without needing decrypt keys.
--
-- NOTE: Naming follows the "orchestration_*" convention used in ops chat.
-- We also provide a compatibility view "rag_task" for older scripts.

CREATE TABLE IF NOT EXISTS orchestration_task (
  id              bigserial PRIMARY KEY,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now(),
  status          text NOT NULL DEFAULT 'queued', -- queued|running|blocked|done|failed
  priority        int NOT NULL DEFAULT 3,         -- 1 (high) .. 5 (low)
  owner           text NOT NULL DEFAULT '',       -- molt|aluma|human

  -- Lease/claim fields (conflict prevention)
  claimed_by      text NOT NULL DEFAULT '',
  claimed_at      timestamptz,
  lease_expires_at timestamptz,
  attempt         int NOT NULL DEFAULT 0,

  title           text NOT NULL,
  body            text NOT NULL DEFAULT '',
  debug_notes     text NOT NULL DEFAULT '',
  tags            text[] NOT NULL DEFAULT '{}'::text[],
  due_at          timestamptz,
  source_url      text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS orchestration_task_status_idx ON orchestration_task(status);
CREATE INDEX IF NOT EXISTS orchestration_task_due_idx ON orchestration_task(due_at);

-- Workflows: allow strict sequences of dependent tasks ("while cycle").
CREATE TABLE IF NOT EXISTS orchestration_workflow (
  id          bigserial PRIMARY KEY,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  status      text NOT NULL DEFAULT 'active', -- active|paused|done
  name        text NOT NULL,
  strict      boolean NOT NULL DEFAULT false,
  notes       text NOT NULL DEFAULT ''
);

-- Attach tasks to a workflow + sequence/deps
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS workflow_id bigint REFERENCES orchestration_workflow(id) ON DELETE SET NULL;
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS seq int NOT NULL DEFAULT 0;
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS depends_on_task_id bigint REFERENCES orchestration_task(id) ON DELETE SET NULL;
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS debug_notes text NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS orchestration_task_workflow_idx ON orchestration_task(workflow_id, seq);

CREATE TABLE IF NOT EXISTS orchestration_event (
  id            bigserial PRIMARY KEY,
  created_at    timestamptz NOT NULL DEFAULT now(),
  kind          text NOT NULL,                -- assign|report|decision|note|debug|heartbeat
  task_id       bigint REFERENCES orchestration_task(id) ON DELETE SET NULL,
  actor         text NOT NULL DEFAULT '',
  message       text NOT NULL,
  tags          text[] NOT NULL DEFAULT '{}'::text[]
);
CREATE INDEX IF NOT EXISTS orchestration_event_task_idx ON orchestration_event(task_id);

-- Backfill/upgrade existing DBs (idempotent)
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS claimed_by text NOT NULL DEFAULT '';
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS claimed_at timestamptz;
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS lease_expires_at timestamptz;
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS attempt int NOT NULL DEFAULT 0;
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS debug_notes text NOT NULL DEFAULT '';
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS workflow_id bigint REFERENCES orchestration_workflow(id) ON DELETE SET NULL;
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS seq int NOT NULL DEFAULT 0;
ALTER TABLE orchestration_task ADD COLUMN IF NOT EXISTS depends_on_task_id bigint REFERENCES orchestration_task(id) ON DELETE SET NULL;

-- Normalize status semantics across upgrades
ALTER TABLE orchestration_task ALTER COLUMN status SET DEFAULT 'queued';
UPDATE orchestration_task SET status='queued' WHERE status='todo';
UPDATE orchestration_task SET status='running' WHERE status='doing';

CREATE INDEX IF NOT EXISTS orchestration_task_lease_idx ON orchestration_task(lease_expires_at);

-- Claim helper: atomic lease-based task claiming.
CREATE OR REPLACE FUNCTION orchestration_claim_task(p_agent text, p_lease_seconds int DEFAULT 600)
RETURNS orchestration_task
LANGUAGE plpgsql
AS $$
DECLARE
  t orchestration_task;
BEGIN
  WITH candidate AS (
    SELECT t.id
    FROM orchestration_task t
    LEFT JOIN orchestration_workflow wf ON wf.id = t.workflow_id
    WHERE t.status IN ('queued','running')
      AND (t.status = 'queued' OR t.lease_expires_at IS NULL OR t.lease_expires_at < now())

      -- dependency gate (raw dependency)
      AND (
        t.depends_on_task_id IS NULL
        OR EXISTS (
          SELECT 1 FROM orchestration_task d
          WHERE d.id = t.depends_on_task_id AND d.status = 'done'
        )
      )

      -- strict workflow gate ("while cycle" / do-not-interrupt sequence)
      AND (
        wf.strict IS DISTINCT FROM true
        OR (
          -- no other currently-running (non-expired) task in same workflow
          NOT EXISTS (
            SELECT 1 FROM orchestration_task r
            WHERE r.workflow_id = t.workflow_id
              AND r.status = 'running'
              AND r.lease_expires_at IS NOT NULL
              AND r.lease_expires_at >= now()
              AND r.id <> t.id
          )
          AND
          -- all earlier seq tasks are done
          NOT EXISTS (
            SELECT 1 FROM orchestration_task p
            WHERE p.workflow_id = t.workflow_id
              AND p.seq < t.seq
              AND p.status <> 'done'
          )
        )
      )

    ORDER BY t.priority ASC, t.due_at NULLS LAST, t.updated_at ASC
    FOR UPDATE SKIP LOCKED
    LIMIT 1
  )
  UPDATE orchestration_task ot
  SET status = 'running',
      claimed_by = p_agent,
      claimed_at = now(),
      lease_expires_at = now() + make_interval(secs => p_lease_seconds),
      attempt = attempt + 1,
      updated_at = now()
  FROM candidate
  WHERE ot.id = candidate.id
  RETURNING ot.* INTO t;

  IF t.id IS NULL THEN
    RAISE EXCEPTION 'no_task_available';
  END IF;

  INSERT INTO orchestration_event(kind, task_id, actor, message, tags)
  VALUES ('assign', t.id, p_agent, 'claimed task (lease)', ARRAY['lease']);

  RETURN t;
END;
$$;

CREATE OR REPLACE FUNCTION orchestration_heartbeat(p_task_id bigint, p_agent text, p_lease_seconds int DEFAULT 600)
RETURNS void
LANGUAGE sql
AS $$
  UPDATE orchestration_task
  SET lease_expires_at = now() + make_interval(secs => p_lease_seconds),
      updated_at = now()
  WHERE id = p_task_id AND claimed_by = p_agent AND status = 'running';

  INSERT INTO orchestration_event(kind, task_id, actor, message, tags)
  VALUES ('heartbeat', p_task_id, p_agent, 'lease renewed', ARRAY['lease']);
$$;

-- Compatibility (optional): allow older code to SELECT tasks via rag_task
CREATE OR REPLACE VIEW rag_task AS
  SELECT * FROM orchestration_task;

-- Read-only role access (sub-agents)
GRANT SELECT ON orchestration_task TO rag_readonly;
GRANT SELECT ON orchestration_event TO rag_readonly;
GRANT SELECT ON rag_task TO rag_readonly;

-- Global orchestration state (plaintext): feature flags like "r3ad mode".
CREATE TABLE IF NOT EXISTS orchestration_state (
  key         text PRIMARY KEY,
  value       text NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO orchestration_state(key, value)
VALUES ('r3ad_mode', 'off')
ON CONFLICT (key) DO NOTHING;

GRANT SELECT ON orchestration_state TO rag_readonly;


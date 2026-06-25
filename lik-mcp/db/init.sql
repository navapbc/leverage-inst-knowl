-- Discovery Layer service-fronted store (v0.4): the Catalog and Confirmation signals.
-- Idempotent: safe to run on an empty DB via the Docker entrypoint or by hand
--   (`psql "$CONNINFO" -f db/init.sql`).

-- Trigram matching powers partial + fuzzy Catalog search on `subject`
-- (see catalog_subject_trgm below). Requires CREATE privilege on first run.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- The Catalog: a directory mapping (entry_type, subject) -> where an output lives.
-- Columns follow v0.4/05-architecture.md section 3.
CREATE TABLE IF NOT EXISTS catalog (
    entry_type        text        NOT NULL,
    subject           text        NOT NULL,
    location          text        NOT NULL,
    store_kind        text        NOT NULL,
    locator           text,
    provenance        text        NOT NULL DEFAULT 'ai-generated',
    verification      text        NOT NULL DEFAULT 'unverified',
    verified_by       text,
    verified_at       timestamptz,
    freshness         text        NOT NULL DEFAULT 'current',
    source_refs       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    last_computed_at  timestamptz,
    last_validated_at timestamptz,
    access_groups     text[]      NOT NULL DEFAULT '{}',
    sensitivity       text        NOT NULL DEFAULT 'restricted',
    category          text,
    computed_by       text        NOT NULL,
    row_provenance    text        NOT NULL DEFAULT 'skill',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    updated_by        text,
    -- Discovery key + upsert target.
    CONSTRAINT catalog_pkey PRIMARY KEY (entry_type, subject)
);

-- Index the ACL hint for later query-time filtering.
CREATE INDEX IF NOT EXISTS catalog_access_groups_gin ON catalog USING GIN (access_groups);

-- Trigram index on `subject` to accelerate partial (ILIKE) and fuzzy (similarity)
-- matching in search_catalog_entries.
CREATE INDEX IF NOT EXISTS catalog_subject_trgm ON catalog USING GIN (subject gin_trgm_ops);

-- Confirmation signals: durable, non-recomputable human trust. `locator` and `version`
-- are NOT NULL DEFAULT '' so the dedup key is reliable (a NULL never equals a NULL in UNIQUE).
-- `version` defaults to '' when the store cannot supply one (e.g. Confluence via MCP);
-- use `created_at` for recency-based trust weighing in that case.
CREATE TABLE IF NOT EXISTS confirmations (
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_kind   text        NOT NULL,
    location     text        NOT NULL,
    locator      text        NOT NULL DEFAULT '',
    version      text        NOT NULL DEFAULT '',
    confirmed_by text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    archived_at  timestamptz,  -- reserved for the deferred age-out/archive lifecycle
    -- At most one confirmation per user per cited source-version.
    CONSTRAINT confirmations_unique UNIQUE (confirmed_by, store_kind, location, locator, version)
);

-- Idempotent migration: add DEFAULT '' to version on existing instances.
-- CREATE TABLE IF NOT EXISTS above won't alter an already-existing table.
ALTER TABLE confirmations ALTER COLUMN version SET DEFAULT '';

-- Least-privilege roles per output type (R11). The deployed app role is granted
-- membership as needed; per-action role switching is wired in a later slice.
DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'catalog_writer') THEN
        CREATE ROLE catalog_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'confirmations_writer') THEN
        CREATE ROLE confirmations_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'dl_reader') THEN
        CREATE ROLE dl_reader NOLOGIN;
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE ON catalog TO catalog_writer;
GRANT SELECT, INSERT, UPDATE ON confirmations TO confirmations_writer;
GRANT SELECT ON catalog, confirmations TO dl_reader;

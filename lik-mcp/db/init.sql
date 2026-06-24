-- Discovery Layer service-fronted store (v0.4): the Catalog and Confirmation signals.
-- Idempotent: safe to run on an empty DB via the Docker entrypoint or by hand
--   (`psql "$CONNINFO" -f db/init.sql`).

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

-- Confirmation signals: durable, non-recomputable human trust. `locator` is NOT NULL
-- DEFAULT '' so the dedup key is reliable (a NULL never equals a NULL in UNIQUE).
CREATE TABLE IF NOT EXISTS confirmations (
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_kind   text        NOT NULL,
    location     text        NOT NULL,
    locator      text        NOT NULL DEFAULT '',
    version      text        NOT NULL,
    confirmed_by text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    archived_at  timestamptz,  -- reserved for the deferred age-out/archive lifecycle
    -- At most one confirmation per user per cited source-version.
    CONSTRAINT confirmations_unique UNIQUE (confirmed_by, store_kind, location, locator, version)
);

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

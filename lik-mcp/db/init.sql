-- Discovery Layer service-fronted store (v0.4): the Catalog and Confirmation signals.
-- Idempotent: safe to run on an empty DB via the Docker entrypoint or by hand
--   (`psql "$CONNINFO" -f db/init.sql`).

-- Trigram matching powers partial + fuzzy Catalog search on `subject`
-- (see catalog_subject_trgm below). Requires CREATE privilege on first run.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- The Catalog: a directory mapping (entry_type, subject) -> where an output lives.
-- Columns follow v0.4/05-architecture.md section 3.
--
-- A key may resolve to several rows: a lookup returns all matching pointers, ranked
-- (section 3, "Keys"). A skill keeps exactly one row per (entry_type, subject, computed_by)
-- — re-derived in place via the partial unique index below — so duplicates arise only from
-- independent human saves, never skill churn. The surrogate id is the stable row handle.
CREATE TABLE IF NOT EXISTS catalog (
    id                bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
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
    updated_by        text
);

-- A skill owns at most one row per (entry_type, subject) and re-derives it in place; this
-- partial unique index is the upsert arbiter for skill rows. Human-saved rows (row_provenance
-- = 'human') are exempt, so independent saves on the same key coexist as ranked duplicates.
CREATE UNIQUE INDEX IF NOT EXISTS catalog_skill_key
    ON catalog (entry_type, subject, computed_by) WHERE row_provenance = 'skill';

-- Accelerate the (entry_type, subject) discovery lookup now that it is no longer the PK.
CREATE INDEX IF NOT EXISTS catalog_discovery_key ON catalog (entry_type, subject);

-- Index the ACL hint for later query-time filtering.
CREATE INDEX IF NOT EXISTS catalog_access_groups_gin ON catalog USING GIN (access_groups);

-- Trigram index on `subject` to accelerate partial (ILIKE) and fuzzy (similarity)
-- matching in search_catalog_entries.
CREATE INDEX IF NOT EXISTS catalog_subject_trgm ON catalog USING GIN (subject gin_trgm_ops);

-- Confirmation signals: durable, non-recomputable human trust. `locator` is NOT NULL
-- DEFAULT '' so the dedup key is reliable (a NULL never equals a NULL in UNIQUE).
-- `source_state` is an opaque content-state marker (a native change signal or a content
-- hash, per source) recorded so "edited since" works; it is NOT part of the dedup key, so
-- one user has at most one confirmation per source and re-confirming updates the marker.
-- It defaults to '' when the store cannot supply one (e.g. Confluence via MCP).
--
-- The signal is *signed*: `vote` is 'up' (right) or 'down' (wrong). A down vote carries a
-- `reason` — 'bad-retrieval' (poor/irrelevant result) or 'wrong-content' (factually wrong) —
-- stored distinctly; an up vote has no reason. `comment` is a reason-agnostic free-text note
-- (solicited only on wrong-content, but the column is open to any vote). Vote/reason/comment
-- are non-key state, so re-voting (flip up<->down or change reason) replaces the one row.
CREATE TABLE IF NOT EXISTS confirmations (
    id           bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    store_kind   text        NOT NULL,
    location     text        NOT NULL,
    locator      text        NOT NULL DEFAULT '',
    source_state text        NOT NULL DEFAULT '',
    confirmed_by text        NOT NULL,
    vote         text        NOT NULL DEFAULT 'up',
    reason       text,
    comment      text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    archived_at  timestamptz,  -- reserved for the deferred age-out/archive lifecycle
    -- At most one confirmation per user per cited source (marker is non-key state).
    CONSTRAINT confirmations_unique UNIQUE (confirmed_by, store_kind, location, locator),
    -- Signed-vote integrity: a down vote names a reason; an up vote names none.
    CONSTRAINT confirmations_vote_kind CHECK (vote IN ('up', 'down')),
    CONSTRAINT confirmations_reason_matches_vote CHECK (
        (vote = 'down' AND reason IN ('bad-retrieval', 'wrong-content'))
        OR (vote = 'up' AND reason IS NULL)
    )
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

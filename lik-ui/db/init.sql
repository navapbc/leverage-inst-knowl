-- lik-ui's own store. Idempotent: safe to run on an empty DB via the Docker entrypoint
-- or by hand (`psql "$CONNINFO" -f db/init.sql`). NOTE: the CREATE TABLE IF NOT EXISTS
-- statements below only create missing tables — they do NOT add new columns to a table
-- that already exists. The prod DB (Lightsail) holds real data, so schema changes must be
-- applied there as explicit, non-destructive ALTERs; never drop-and-recreate prod.

-- App users, keyed by their verified Google email (the app-login identity claim).
CREATE TABLE IF NOT EXISTS users (
    id          bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email       text        NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- One credential vault per user (the user -> VAULT_ID mapping). The vault holds the
-- per-source MCP credentials this user has connected.
CREATE TABLE IF NOT EXISTS user_vaults (
    user_id     bigint      NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    vault_id    text        NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- One managed session per row, keyed by the Managed Agents session id; a user resumes
-- by reopening a stored session_id.
CREATE TABLE IF NOT EXISTS sessions (
    session_id  text        PRIMARY KEY,
    user_id     bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agent_id    text        NOT NULL,
    title       text,
    -- When true, any authenticated user who knows the session_id gets read-only access
    -- (view transcript, attach to an in-flight turn). Writes stay owner-only.
    shared      boolean     NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    -- When this session (row + platform transcript) is auto-deleted. Defaults to 7 days
    -- after creation; the owner can push it out but cannot disable it.
    auto_delete_at timestamptz NOT NULL DEFAULT (now() + interval '7 days')
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id, created_at DESC);

-- Non-destructive migration for an existing sessions table (CREATE TABLE IF NOT EXISTS above
-- won't add this column to a table that already exists — e.g. prod). A single ADD COLUMN with
-- NOT NULL DEFAULT is atomic (one ACCESS EXCLUSIVE lock, no partial-migration race and no
-- concurrent-INSERT NULL window) and fills existing rows with now() + 7 days — a fresh window
-- measured from migration time.
--
-- It deliberately does NOT backfill created_at + 7 days: that would put every session older
-- than 7 days in the past, so the first cleanup run would delete all of them immediately with
-- no warning window. Idempotent (IF NOT EXISTS), so this is a no-op on a freshly-created table.
--
-- NOTE: because now() is volatile this rewrites the table under that ACCESS EXCLUSIVE lock —
-- momentary on lik-ui's small sessions table; size the row count before running on a large one.
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS auto_delete_at timestamptz NOT NULL DEFAULT (now() + interval '7 days');
CREATE INDEX IF NOT EXISTS sessions_auto_delete_idx ON sessions (auto_delete_at);

-- Short-lived OAuth client credentials for an in-flight connect, keyed by the connect's
-- state token. A dynamically-registered client must be reused between the authorize step
-- and the token exchange (the authorization code is bound to the client that requested it),
-- but its secret can't live in the signed-not-encrypted session cookie. Rows are deleted
-- on use in the callback; stale rows (abandoned connects) are purged opportunistically.
CREATE TABLE IF NOT EXISTS pending_connections (
    state          text        PRIMARY KEY,
    client_id      text        NOT NULL,
    client_secret  text,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- Recurring, unattended agent runs a user has scheduled for themselves. This table is the
-- cron-like state of record: what to run (agent_name + prompt), how often (run_interval),
-- when it is next due, whether a run is in flight (started_at set, completed_at null), and
-- the last run's outcome. A scheduled GitHub Action scans it for due rows, claims each
-- atomically, drives the agent session to completion as the owning user, and updates timing.
-- Each run executes with the owner's own vault; ownership is scoped by user_id everywhere
-- except the scanner's cross-user claim (see Store.claim_due_runs).
CREATE TABLE IF NOT EXISTS scheduled_runs (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id       bigint      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Agent referenced by roster name (never a platform id), resolved to an id at run time,
    -- consistent with the "no platform ids pinned in the repo/DB config" convention.
    agent_name    text        NOT NULL,
    prompt        text        NOT NULL,
    -- Preset cadence stored as a Postgres interval; next_run_at advances by this on completion.
    run_interval  interval    NOT NULL,
    -- Per-schedule hard runtime bound in seconds (materialized from the agent's roster max_runtime
    -- at creation). Single source of truth for BOTH the runner's watchdog and the scanner's stuck-row
    -- reclaim cutoff, so the invariant "reclaim only after max_runtime + margin" holds by construction.
    max_runtime_s integer     NOT NULL DEFAULT 1800,
    next_run_at   timestamptz NOT NULL DEFAULT now(),
    -- In-flight marker: set when a scan claims the row, cleared on completion. A row with
    -- started_at set and completed_at null is running (or was abandoned — see reclaim).
    started_at    timestamptz,
    completed_at  timestamptz,
    -- Last run's outcome, so the Settings UI and the scanner can see health without opening
    -- the session (and it survives deletion of an empty failed session).
    last_status   text,
    last_error    text,
    last_skipped  jsonb,
    -- Paused schedules are never claimed. pause_reason distinguishes a user pause from an
    -- auto-pause (e.g. 'needs_reauth' after a lapsed-credential run).
    paused        boolean     NOT NULL DEFAULT false,
    pause_reason  text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS scheduled_runs_user_idx ON scheduled_runs (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS scheduled_runs_due_idx ON scheduled_runs (next_run_at);

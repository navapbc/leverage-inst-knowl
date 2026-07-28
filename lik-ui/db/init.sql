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

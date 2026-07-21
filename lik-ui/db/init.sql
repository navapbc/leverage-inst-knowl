-- lik-ui's own store. Idempotent: safe to run on an empty DB via the Docker entrypoint
-- or by hand (`psql "$CONNINFO" -f db/init.sql`). Drop-and-recreate for schema changes
-- (drafting mode, no migrations).

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
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id, created_at DESC);

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

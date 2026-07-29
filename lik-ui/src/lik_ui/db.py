"""Postgres access for lik-ui's own store: users, the user->vault mapping, and sessions
(one managed session each).

``Database`` owns the connection pool (mirrors lik-mcp); ``Store`` holds the domain
queries. Nothing here logs credential material — vault ids and client ids are opaque
handles.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool


class Database:
    """Owns the Postgres connection pool. The app holds one; call sites borrow
    connections through ``connection()`` and never open their own."""

    def __init__(self, conninfo: str, *, min_size: int = 1, max_size: int = 4):
        # check on checkout: the scheduled-runs scanner borrows a connection for claim_due_runs,
        # then holds the pool idle for a whole multi-minute agent run (no DB traffic) before the
        # terminal complete_run. The public Postgres/network silently drops that idle connection,
        # so an unchecked pool would hand back a dead socket and the final write would fail with
        # "SSL error: unexpected eof while reading" — losing the run's recorded outcome.
        # check_connection validates (and the pool reconnects) on checkout, so a stale connection
        # is replaced before use instead of erroring mid-write.
        self.pool = ConnectionPool(
            conninfo,
            min_size=min_size,
            max_size=max_size,
            open=True,
            timeout=5,
            check=ConnectionPool.check_connection,
        )

    @contextmanager
    def connection(self):
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            yield conn

    def close(self) -> None:
        self.pool.close()


class Store:
    """Domain queries over the Database. Methods commit their own writes."""

    def __init__(self, db: Database):
        self.db = db

    # --- users -----------------------------------------------------------------
    def upsert_user(self, email: str) -> dict:
        """Idempotent on email: returns the existing row or creates one."""
        with self.db.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO users (email) VALUES (%s)
                ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
                RETURNING id, email, created_at
                """,
                (email,),
            ).fetchone()
            conn.commit()
            return row

    def get_user_by_email(self, email: str) -> dict | None:
        with self.db.connection() as conn:
            return conn.execute(
                "SELECT id, email, created_at FROM users WHERE email = %s", (email,)
            ).fetchone()

    def get_user_by_id(self, user_id: int) -> dict | None:
        """Resolve a user by id. Used by the scheduled runner, which starts from a
        ``scheduled_runs.user_id`` (not an email) and needs the ``{id, email}`` shape
        ``ensure_user_vault`` expects."""
        with self.db.connection() as conn:
            return conn.execute(
                "SELECT id, email, created_at FROM users WHERE id = %s", (user_id,)
            ).fetchone()

    # --- user -> vault mapping -------------------------------------------------
    def set_user_vault(self, user_id: int, vault_id: str) -> None:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO user_vaults (user_id, vault_id) VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET vault_id = EXCLUDED.vault_id
                """,
                (user_id, vault_id),
            )
            conn.commit()

    def get_user_vault(self, user_id: int) -> str | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT vault_id FROM user_vaults WHERE user_id = %s", (user_id,)
            ).fetchone()
            return row["vault_id"] if row else None

    def delete_user_vault(self, user_id: int) -> None:
        """Forget the user->vault mapping. A new vault is provisioned on next use."""
        with self.db.connection() as conn:
            conn.execute("DELETE FROM user_vaults WHERE user_id = %s", (user_id,))
            conn.commit()

    # --- pending OAuth connects ------------------------------------------------
    def stash_pending_client(self, state: str, client_id: str, client_secret: str | None) -> None:
        """Persist the client credentials for an in-flight connect, keyed by its state
        token, so the callback can redeem the code with the same client that requested it.
        Opportunistically purge abandoned connects so the table can't grow unbounded."""
        with self.db.connection() as conn:
            conn.execute("DELETE FROM pending_connections WHERE created_at < now() - interval '15 minutes'")
            conn.execute(
                "INSERT INTO pending_connections (state, client_id, client_secret) VALUES (%s, %s, %s)",
                (state, client_id, client_secret),
            )
            conn.commit()

    def take_pending_client(self, state: str) -> dict | None:
        """Return and delete the stashed client for this state (single-use). None if the
        state is unknown or already consumed."""
        with self.db.connection() as conn:
            row = conn.execute(
                "DELETE FROM pending_connections WHERE state = %s RETURNING client_id, client_secret",
                (state,),
            ).fetchone()
            conn.commit()
            return row

    # --- sessions --------------------------------------------------------------
    def create_session(self, user_id: int, agent_id: str, session_id: str, title: str | None = None) -> dict:
        """Persist a session record keyed by the Managed Agents ``session_id``."""
        with self.db.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO sessions (session_id, user_id, agent_id, title)
                VALUES (%s, %s, %s, %s)
                RETURNING session_id, user_id, agent_id, title, shared, created_at, auto_delete_at
                """,
                (session_id, user_id, agent_id, title),
            ).fetchone()
            conn.commit()
            return row

    def list_sessions(self, user_id: int) -> list[dict]:
        with self.db.connection() as conn:
            return conn.execute(
                """
                SELECT session_id, user_id, agent_id, title, shared, created_at, auto_delete_at
                FROM sessions WHERE user_id = %s ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()

    def get_session(self, session_id: str, user_id: int) -> dict | None:
        """Scoped to the owning user so one user can't open another's session. Use this to
        gate writes and management (send, confirm, delete, share toggle)."""
        with self.db.connection() as conn:
            return conn.execute(
                """
                SELECT session_id, user_id, agent_id, title, shared, created_at, auto_delete_at
                FROM sessions WHERE session_id = %s AND user_id = %s
                """,
                (session_id, user_id),
            ).fetchone()

    def get_accessible_session(self, session_id: str, user_id: int) -> dict | None:
        """Read access: the row if this user owns it OR the owner marked it shared. Use this
        to gate read-only views (open, history, resume); never to gate a write."""
        with self.db.connection() as conn:
            return conn.execute(
                """
                SELECT session_id, user_id, agent_id, title, shared, created_at, auto_delete_at
                FROM sessions WHERE session_id = %s AND (user_id = %s OR shared = true)
                """,
                (session_id, user_id),
            ).fetchone()

    def set_session_shared(self, session_id: str, user_id: int, shared: bool) -> bool:
        """Flip a session's shared flag. Owner-scoped so one user can't share another's
        session. Returns whether a row was updated."""
        with self.db.connection() as conn:
            row = conn.execute(
                "UPDATE sessions SET shared = %s WHERE session_id = %s AND user_id = %s RETURNING session_id",
                (shared, session_id, user_id),
            ).fetchone()
            conn.commit()
            return row is not None

    def set_session_auto_delete_at(self, session_id: str, user_id: int, when: datetime) -> bool:
        """Reschedule a session's auto-delete time. Owner-scoped so one user can't reschedule
        another's session. There is no way to clear it (sessions always have a date). Returns
        whether a row was updated."""
        with self.db.connection() as conn:
            row = conn.execute(
                "UPDATE sessions SET auto_delete_at = %s WHERE session_id = %s AND user_id = %s RETURNING session_id",
                (when, session_id, user_id),
            ).fetchone()
            conn.commit()
            return row is not None

    def list_sessions_due(self, cutoff: datetime) -> list[dict]:
        """Every session whose auto-delete time is at or before ``cutoff``, across all users
        (not owner-scoped — the scheduled cleanup acts as no single user). Returns each
        session_id with its owning user_id so the caller can reuse the owner-scoped delete.
        Also carries agent_id + created_at so the pre-delete analytics capture can populate a
        record (including the local-only fallback) without a second per-session read."""
        with self.db.connection() as conn:
            return conn.execute(
                "SELECT session_id, user_id, agent_id, created_at FROM sessions "
                "WHERE auto_delete_at <= %s ORDER BY auto_delete_at",
                (cutoff,),
            ).fetchall()

    def delete_session(self, session_id: str, user_id: int) -> bool:
        """Forget a session record. Scoped to the owning user so one user can't delete
        another's. Returns whether a row was removed."""
        with self.db.connection() as conn:
            row = conn.execute(
                "DELETE FROM sessions WHERE session_id = %s AND user_id = %s RETURNING session_id",
                (session_id, user_id),
            ).fetchone()
            conn.commit()
            return row is not None

    # --- session analytics -----------------------------------------------------
    # Durable per-session usage record, written just before physical deletion. Keyed by
    # session_id and upserted, so a re-attempted deletion overwrites rather than duplicating
    # (exactly one record per session). Not owner-scoped: the record outlives the user/session.
    _ANALYTICS_COLS = (
        "session_id", "user_id", "user_email", "agent_id", "deletion_path",
        "created_at", "deleted_at", "capture_incomplete", "capture_reason",
        "input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens",
        "active_seconds", "wall_clock_seconds",
        "user_message_count", "ai_message_count", "tool_use_count", "error_count",
        "tool_breakdown", "error_types",
    )
    _ANALYTICS_JSON_COLS = frozenset({"tool_breakdown", "error_types"})

    def write_session_analytics(self, record: dict) -> None:
        """Upsert one analytics record keyed on ``session_id``. ``record`` supplies any subset of
        the analytics columns; ``session_id``, ``user_id`` and ``deletion_path`` are required, the
        rest default (``deleted_at`` to now(), ``capture_incomplete`` to false, metrics to NULL).

        A second write for the same session upserts in place (exactly one record), but a *flagged*
        (incomplete) write never overwrites an existing *complete* record — see the WHERE guard
        below. That handles the re-attempted-deletion case: a first attempt captures a full record,
        the platform delete fails so the row survives, and a later retry can only re-read after the
        platform session is gone. Without the guard that degraded retry would flip a complete row to
        capture_incomplete=true while leaving its real metrics in place — a self-contradictory row
        that also over-counts the incomplete tally. A complete capture still always wins."""
        cols = [c for c in self._ANALYTICS_COLS if c in record]
        values = [Json(record[c]) if c in self._ANALYTICS_JSON_COLS else record[c] for c in cols]
        placeholders = ", ".join(["%s"] * len(cols))
        # Overwrite every supplied column except the PK on conflict.
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "session_id")
        with self.db.connection() as conn:
            conn.execute(
                f"INSERT INTO session_analytics ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT (session_id) DO UPDATE SET {updates} "
                # Update only when the stored row is itself incomplete, or the incoming row is
                # complete — so an incomplete retry can't clobber a good, complete capture.
                "WHERE session_analytics.capture_incomplete OR NOT EXCLUDED.capture_incomplete",
                values,
            )
            conn.commit()

    def get_session_analytics(self, session_id: str) -> dict | None:
        """The analytics record for one session, or None. Used by tests and single-session views."""
        with self.db.connection() as conn:
            return conn.execute(
                f"SELECT {', '.join(self._ANALYTICS_COLS)} FROM session_analytics WHERE session_id = %s",
                (session_id,),
            ).fetchone()

    def list_all_sessions(self) -> list[dict]:
        """Every live session across all users, with the owner's email — the cross-user live list
        behind /all-stats. Not owner-scoped (the operator view acts as no single user)."""
        with self.db.connection() as conn:
            return conn.execute(
                """
                SELECT s.session_id, s.user_id, u.email AS user_email, s.agent_id,
                       s.title, s.shared, s.created_at, s.auto_delete_at
                FROM sessions s JOIN users u ON u.id = s.user_id
                ORDER BY s.created_at DESC
                """
            ).fetchall()

    # Total tokens = the four usage columns summed, treating unread (NULL) metrics as 0.
    _ANALYTICS_TOKENS = (
        "COALESCE(input_tokens,0) + COALESCE(output_tokens,0) "
        "+ COALESCE(cache_read_tokens,0) + COALESCE(cache_creation_tokens,0)"
    )

    def session_analytics_totals(self, user_id: int | None = None) -> dict:
        """Aggregate totals over deleted-session records. Scoped to one user when ``user_id`` is
        given (the /stats page), else across all users (/all-stats). Sums are 0 on an empty set."""
        where, params = ("WHERE user_id = %s", (user_id,)) if user_id is not None else ("", ())
        with self.db.connection() as conn:
            return conn.execute(
                f"""
                SELECT
                    count(*)                                   AS sessions,
                    COALESCE(sum(input_tokens),0)              AS input_tokens,
                    COALESCE(sum(output_tokens),0)             AS output_tokens,
                    COALESCE(sum(cache_read_tokens),0)         AS cache_read_tokens,
                    COALESCE(sum(cache_creation_tokens),0)     AS cache_creation_tokens,
                    COALESCE(sum({self._ANALYTICS_TOKENS}),0)  AS total_tokens,
                    COALESCE(sum(tool_use_count),0)            AS tool_use_count,
                    COALESCE(sum(error_count),0)               AS error_count,
                    COALESCE(sum(CASE WHEN capture_incomplete THEN 1 ELSE 0 END),0) AS incomplete
                FROM session_analytics {where}
                """,
                params,
            ).fetchone()

    def session_analytics_daily(self, user_id: int | None = None) -> list[dict]:
        """Per-day buckets of deleted-session count and total tokens, oldest first — the over-time
        view (R12). Scoped to one user when ``user_id`` is given, else across all users."""
        where, params = ("WHERE user_id = %s", (user_id,)) if user_id is not None else ("", ())
        with self.db.connection() as conn:
            return conn.execute(
                f"""
                SELECT date_trunc('day', deleted_at) AS day,
                       count(*)                       AS sessions,
                       COALESCE(sum({self._ANALYTICS_TOKENS}),0) AS tokens
                FROM session_analytics {where}
                GROUP BY day ORDER BY day
                """,
                params,
            ).fetchall()

    def session_analytics_by_user(self) -> list[dict]:
        """Per-user totals over deleted-session records (the 'sessions per user' dimension of the
        /all-stats view), busiest first. Cross-user; keyed by the denormalized email."""
        with self.db.connection() as conn:
            return conn.execute(
                f"""
                SELECT COALESCE(user_email, '(unknown)') AS user_email,
                       count(*)                          AS sessions,
                       COALESCE(sum({self._ANALYTICS_TOKENS}),0) AS tokens
                FROM session_analytics
                GROUP BY user_email ORDER BY tokens DESC, sessions DESC
                """
            ).fetchall()

    # --- scheduled runs --------------------------------------------------------
    # CRUD here is owner-scoped (the Settings UI). The scanner's cross-user claim/complete
    # live below in the "scheduled runs (scanner)" section.
    _SCHEDULED_RUN_COLS = (
        "id, user_id, agent_name, prompt, run_interval, max_runtime_s, next_run_at, started_at, "
        "completed_at, last_status, last_error, last_skipped, last_duration_s, paused, pause_reason, created_at"
    )

    def create_scheduled_run(
        self,
        user_id: int,
        agent_name: str,
        prompt: str,
        run_interval: timedelta,
        max_runtime_s: int = 1800,
    ) -> dict:
        """Create a schedule owned by ``user_id``. It becomes due immediately (next_run_at
        defaults to now()) and recurs every ``run_interval``. ``max_runtime_s`` is materialized
        from the agent's roster ``max_runtime`` and feeds both the runner watchdog and the reclaim
        cutoff."""
        with self.db.connection() as conn:
            row = conn.execute(
                f"""
                INSERT INTO scheduled_runs (user_id, agent_name, prompt, run_interval, max_runtime_s)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {self._SCHEDULED_RUN_COLS}
                """,
                (user_id, agent_name, prompt, run_interval, max_runtime_s),
            ).fetchone()
            conn.commit()
            return row

    def list_scheduled_runs(self, user_id: int) -> list[dict]:
        """This user's schedules, newest first. Owner-scoped for the Settings list."""
        with self.db.connection() as conn:
            return conn.execute(
                f"SELECT {self._SCHEDULED_RUN_COLS} FROM scheduled_runs "
                "WHERE user_id = %s ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()

    def delete_scheduled_run(self, run_id: int, user_id: int) -> bool:
        """Delete a schedule. Owner-scoped so one user can't delete another's. Returns
        whether a row was removed."""
        with self.db.connection() as conn:
            row = conn.execute(
                "DELETE FROM scheduled_runs WHERE id = %s AND user_id = %s RETURNING id",
                (run_id, user_id),
            ).fetchone()
            conn.commit()
            return row is not None

    def set_scheduled_run_paused(self, run_id: int, user_id: int, paused: bool) -> bool:
        """Pause or resume a schedule (owner-scoped). Resuming clears any pause_reason (e.g.
        after the owner re-authenticates a lapsed connection). Returns whether a row updated."""
        with self.db.connection() as conn:
            row = conn.execute(
                """
                UPDATE scheduled_runs
                SET paused = %s, pause_reason = CASE WHEN %s THEN pause_reason ELSE NULL END
                WHERE id = %s AND user_id = %s
                RETURNING id
                """,
                (paused, paused, run_id, user_id),
            ).fetchone()
            conn.commit()
            return row is not None

    def delete_scheduled_runs_for_user(self, user_id: int) -> int:
        """Remove all of a user's schedules — used when their vault is deleted so a schedule
        cannot keep running with revoked credentials (R19). Returns the count removed."""
        with self.db.connection() as conn:
            rows = conn.execute(
                "DELETE FROM scheduled_runs WHERE user_id = %s RETURNING id", (user_id,)
            ).fetchall()
            conn.commit()
            return len(rows)

    # --- scheduled runs (scanner: cross-user, not owner-scoped) ----------------
    # These run inside the scheduled GitHub Action, which acts as no single user (like
    # ``list_sessions_due``). The claim is atomic so overlapping scans can't double-run a row.
    def claim_due_runs(self, margin_s: int = 300) -> list[dict]:
        """Atomically claim and return every runnable row: due-and-idle schedules, plus stuck
        rows whose runner died. A row is *due* when ``next_run_at <= now`` and not in flight
        (``started_at IS NULL``); a row is *stuck* when it has been in flight past its own
        ``max_runtime_s + margin_s`` (the runner crashed without completing). Claiming sets
        ``started_at = now`` so a concurrent scan can't take the same row (``FOR UPDATE SKIP
        LOCKED`` plus the row-level guard). Reclaimed rows are stamped ``abandoned`` so the dead
        run's failure is surfaced. Never claims a paused row.

        "Now" is the database clock (``now()`` in SQL), not a caller-supplied timestamp — rows are
        stamped with the DB clock, so comparing against a client clock would be subject to skew.
        The reclaim cutoff is computed per row from ``max_runtime_s`` — the same value the runner
        uses as its watchdog budget — so a scan can never reclaim a runner still within its own
        runtime bound (the double-run invariant)."""
        with self.db.connection() as conn:
            rows = conn.execute(
                f"""
                UPDATE scheduled_runs AS s
                SET started_at   = now(),
                    completed_at = NULL,
                    last_status  = CASE WHEN s.started_at IS NOT NULL THEN 'abandoned' ELSE s.last_status END,
                    last_error   = CASE WHEN s.started_at IS NOT NULL
                                        THEN 'reclaimed after exceeding max runtime' ELSE s.last_error END
                WHERE s.id IN (
                    SELECT id FROM scheduled_runs
                    WHERE NOT paused AND (
                        (started_at IS NULL AND next_run_at <= now())
                        OR (started_at IS NOT NULL AND completed_at IS NULL
                            AND started_at + make_interval(secs => max_runtime_s + %(margin)s) < now())
                    )
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING {self._SCHEDULED_RUN_COLS}
                """,
                {"margin": margin_s},
            ).fetchall()
            conn.commit()
            return rows

    def complete_run(
        self,
        run_id: int,
        status: str,
        error: str | None,
        skipped: list | None,
        duration_s: int | None = None,
    ) -> None:
        """Record a finished run and advance the schedule: clear the in-flight marker, stamp the
        outcome (R4), and set the next due time to ``now() + run_interval`` (computed in SQL from
        the row's own cadence, so it is skew-free and uses the stored interval). ``duration_s`` is
        the run's measured wall-clock, persisted so ``max_runtime`` can be tuned per agent from
        real run times. Used for every terminal outcome except a lapsed credential, which pauses
        instead (see ``pause_and_flag``)."""
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE scheduled_runs
                SET started_at = NULL, completed_at = now(), last_status = %s, last_error = %s,
                    last_skipped = %s, last_duration_s = %s, next_run_at = now() + run_interval
                WHERE id = %s
                """,
                (status, error, Json(skipped) if skipped is not None else None, duration_s, run_id),
            )
            conn.commit()

    def pause_and_flag(
        self, run_id: int, reason: str, error: str | None = None, duration_s: int | None = None
    ) -> None:
        """Pause a schedule and flag why, instead of advancing it — used when a run fails on a
        lapsed credential (only interactive re-auth fixes it, so re-running every cadence would
        just re-fail). Clears the in-flight marker and records the outcome; ``next_run_at`` is left
        unchanged (a paused row is never claimed). The owner resuming (or re-authing) unpauses it."""
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE scheduled_runs
                SET started_at = NULL, completed_at = now(), paused = true, pause_reason = %s,
                    last_status = 'auth_lapsed', last_error = %s, last_duration_s = %s
                WHERE id = %s
                """,
                (reason, error, duration_s, run_id),
            )
            conn.commit()

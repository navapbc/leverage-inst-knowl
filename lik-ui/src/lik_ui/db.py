"""Postgres access for lik-ui's own store: users, the user->vault mapping, sessions
(one managed session each), and app-level DCR client registrations.

``Database`` owns the connection pool (mirrors lik-mcp); ``Store`` holds the domain
queries. Nothing here logs credential material — vault ids and client ids are opaque
handles, but client secrets stored in ``dcr_registrations`` are never emitted in logs.
"""

from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg.types.json import Json
from psycopg_pool import ConnectionPool


class Database:
    """Owns the Postgres connection pool. The app holds one; call sites borrow
    connections through ``connection()`` and never open their own."""

    def __init__(self, conninfo: str, *, min_size: int = 1, max_size: int = 4):
        self.pool = ConnectionPool(conninfo, min_size=min_size, max_size=max_size, open=True, timeout=5)

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

    # --- sessions --------------------------------------------------------------
    def create_session(self, user_id: int, agent_id: str, session_id: str, title: str | None = None) -> dict:
        """Persist a session record keyed by the Managed Agents ``session_id``."""
        with self.db.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO sessions (session_id, user_id, agent_id, title)
                VALUES (%s, %s, %s, %s)
                RETURNING session_id, user_id, agent_id, title, created_at
                """,
                (session_id, user_id, agent_id, title),
            ).fetchone()
            conn.commit()
            return row

    def list_sessions(self, user_id: int) -> list[dict]:
        with self.db.connection() as conn:
            return conn.execute(
                """
                SELECT session_id, user_id, agent_id, title, created_at
                FROM sessions WHERE user_id = %s ORDER BY created_at DESC
                """,
                (user_id,),
            ).fetchall()

    def get_session(self, session_id: str, user_id: int) -> dict | None:
        """Scoped to the owning user so one user can't open another's session."""
        with self.db.connection() as conn:
            return conn.execute(
                """
                SELECT session_id, user_id, agent_id, title, created_at
                FROM sessions WHERE session_id = %s AND user_id = %s
                """,
                (session_id, user_id),
            ).fetchone()

    # --- DCR registrations -----------------------------------------------------
    def get_dcr_registration(self, issuer: str) -> dict | None:
        with self.db.connection() as conn:
            return conn.execute(
                "SELECT issuer, client_id, client_secret, metadata FROM dcr_registrations WHERE issuer = %s",
                (issuer,),
            ).fetchone()

    def put_dcr_registration(
        self, issuer: str, client_id: str, client_secret: str | None, metadata: dict | None = None
    ) -> dict:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO dcr_registrations (issuer, client_id, client_secret, metadata)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (issuer) DO UPDATE
                    SET client_id = EXCLUDED.client_id,
                        client_secret = EXCLUDED.client_secret,
                        metadata = EXCLUDED.metadata
                RETURNING issuer, client_id, client_secret, metadata
                """,
                (issuer, client_id, client_secret, Json(metadata or {})),
            ).fetchone()
            conn.commit()
            return row

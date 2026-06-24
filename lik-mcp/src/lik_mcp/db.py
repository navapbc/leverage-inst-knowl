from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Database:
    """Owns the Postgres connection pool. The MCP service is the only thing that
    holds one of these; tools never open their own connections."""

    def __init__(self, conninfo: str, *, min_size: int = 1, max_size: int = 4):
        self.pool = ConnectionPool(
            conninfo, min_size=min_size, max_size=max_size, open=True, timeout=5
        )

    @contextmanager
    def connection(self):
        with self.pool.connection() as conn:
            conn.row_factory = dict_row
            yield conn

    def close(self) -> None:
        self.pool.close()

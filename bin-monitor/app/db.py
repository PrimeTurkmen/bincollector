"""Tiny PostgreSQL helper built on psycopg3."""
from contextlib import contextmanager
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

from . import config

SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"


@contextmanager
def connect(autocommit: bool = True):
    """Yield a psycopg connection with dict rows."""
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=autocommit)
    try:
        yield conn
    finally:
        conn.close()


def query(sql: str, params=None) -> list[dict]:
    with connect() as conn:
        cur = conn.execute(sql, params or ())
        return cur.fetchall()


def execute(sql: str, params=None):
    with connect() as conn:
        conn.execute(sql, params or ())


def init_schema():
    """Create all tables/indexes (idempotent)."""
    ddl = SCHEMA_SQL.read_text()
    with connect() as conn:
        conn.execute(ddl)

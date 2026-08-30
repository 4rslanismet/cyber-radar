"""Postgres bağlantı yardımcıları. psycopg3 kullanır, connection pool yok -
tek sunucuda günde 2 koşu için gereksiz karmaşıklık; her koşu kendi bağlantısını
açıp kapatır."""
from __future__ import annotations

import contextlib
import json
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from . import config


@contextlib.contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(config.DATABASE_URL, row_factory=dict_row, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


def get_state(conn: psycopg.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM pipeline_state WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn: psycopg.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO pipeline_state (key, value, updated_at)
        VALUES (%s, %s, now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        (key, value),
    )


def log_collector_run(
    conn: psycopg.Connection,
    source: str,
    kind: str,
    query: str | None,
    result_count: int | None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO collector_runs (source, kind, finished_at, query, result_count, error)
        VALUES (%s, %s, now(), %s, %s, %s)
        """,
        (source, kind, query, result_count, error),
    )


def to_jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)

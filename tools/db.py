# ==============================================
# DuckDB 连接管理
# 线程级连接复用 + 超时中断 + 定期重建
# ==============================================

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "finance.db"
MAX_QUERIES_PER_CONN = 200
QUERY_TIMEOUT_SECONDS = 10

_local = threading.local()


class QueryTimeoutError(Exception):
    pass


def _attr_names(read_only: bool) -> tuple[str, str]:
    return ("_conn_ro", "_count_ro") if read_only else ("_conn_rw", "_count_rw")


def _new_conn(read_only: bool) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(str(DB_PATH), read_only=read_only)
    conn.execute("PRAGMA threads=4")
    conn.execute("PRAGMA memory_limit='4GB'")
    conn.execute("PRAGMA enable_progress_bar=false")
    conn.execute("PRAGMA enable_object_cache=false")
    return conn


def close_conn(read_only: bool = True) -> None:
    conn_attr, count_attr = _attr_names(read_only)
    conn = getattr(_local, conn_attr, None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    if hasattr(_local, conn_attr):
        delattr(_local, conn_attr)
    if hasattr(_local, count_attr):
        delattr(_local, count_attr)


def reset_conn(read_only: bool = True) -> None:
    close_conn(read_only=read_only)


def get_conn(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    conn_attr, count_attr = _attr_names(read_only)
    conn = getattr(_local, conn_attr, None)
    count = getattr(_local, count_attr, 0)

    if conn is None or count >= MAX_QUERIES_PER_CONN:
        close_conn(read_only=read_only)
        conn = _new_conn(read_only=read_only)
        setattr(_local, conn_attr, conn)
        setattr(_local, count_attr, 0)

    return conn


def _increment_count(read_only: bool) -> None:
    _, count_attr = _attr_names(read_only)
    count = getattr(_local, count_attr, 0)
    setattr(_local, count_attr, count + 1)


def execute_query(
    sql: str,
    params: list[Any] | tuple[Any, ...] | None = None,
    timeout: int = QUERY_TIMEOUT_SECONDS,
    read_only: bool = True,
):
    conn = get_conn(read_only=read_only)
    timed_out = False

    def interrupt_query() -> None:
        nonlocal timed_out
        timed_out = True
        try:
            conn.interrupt()
        except Exception:
            pass

    timer = threading.Timer(timeout, interrupt_query)
    timer.daemon = True
    timer.start()
    try:
        result = conn.execute(sql, params or [])
        _increment_count(read_only=read_only)
        return result
    except Exception:
        reset_conn(read_only=read_only)
        if timed_out:
            raise QueryTimeoutError("query timeout")
        raise
    finally:
        timer.cancel()

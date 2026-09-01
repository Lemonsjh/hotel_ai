from __future__ import annotations

import os
import sqlite3
import time
from functools import wraps
from typing import Any, Callable

from runtime.storage import ensure_dirs, init_schema


_DEFAULT_MYSQL_CONNECT_TIMEOUT_SECONDS = 2
_DEFAULT_MYSQL_IO_TIMEOUT_SECONDS = 3
_DEFAULT_SQLITE_BUSY_TIMEOUT_MS = 1000
_SQLITE_SCHEMA_TABLES = {
    "meituan_ota_goods_price_mapping",
    "ctrip_ota_goods_price_mapping",
}


def _bounded_env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


def _sqlite_task_tables() -> set[str]:
    return {
        os.environ.get("HOTEL_OTA_PRICE_TASK_TABLE_MEITUAN", "meituan_zhiting_price_task"),
        os.environ.get("HOTEL_OTA_PRICE_TASK_TABLE_CTRIP", "ctrip_zhiting_price_task"),
    }


def _sqlite_schema_ready(conn: Any) -> bool:
    required = _SQLITE_SCHEMA_TABLES | _sqlite_task_tables()
    placeholders = ", ".join("?" for _ in required)
    rows = conn.execute(
        f"SELECT name FROM sqlite_master WHERE type='table' AND name IN ({placeholders})",
        tuple(sorted(required)),
    ).fetchall()
    names = {
        str(row["name"] if hasattr(row, "keys") and "name" in row.keys() else row[0])
        for row in rows
    }
    return required.issubset(names)


def _open_fast_sqlite(db_path: str, *, busy_timeout_ms: int) -> sqlite3.Connection:
    ensure_dirs(db_path)
    conn = sqlite3.connect(
        db_path,
        timeout=max(busy_timeout_ms / 1000.0, 0.1),
    )
    try:
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}").close()
        conn.execute("PRAGMA journal_mode=WAL").close()
        return conn
    except Exception:
        conn.close()
        raise


def _connection_failure(kind: str, exc: BaseException) -> tuple[None, str, dict[str, Any]]:
    return None, kind, {
        "status": "blocked",
        "blocked_reason": "price_task_db_connection_failed",
        "db_kind": kind,
        "error_type": exc.__class__.__name__,
        "write_performed": False,
        "live_api_called": False,
        "plugin_waited": False,
    }


def _fast_connect_task_db(
    db_path: str,
    *,
    db_kind: str | None = None,
    dsn: str | None = None,
) -> tuple[Any | None, str, dict[str, Any] | None]:
    """Open the S6 outbox database with short waits and lazy schema setup."""

    kind = (
        db_kind
        or os.environ.get("HOTEL_OTA_PRICE_TASK_DB_KIND")
        or os.environ.get("HOTEL_OTA_DB_KIND")
        or "sqlite"
    ).lower()

    if kind == "mysql":
        try:
            import pymysql
            from runtime.adapters.database import _parse_mysql_dsn
        except Exception:
            return None, "mysql", {
                "status": "blocked",
                "blocked_reason": "missing_mysql_driver",
                "message": "Install PyMySQL before writing zhiting price task outbox to MySQL.",
                "write_performed": False,
                "live_api_called": False,
                "plugin_waited": False,
            }

        if not dsn:
            return None, "mysql", {
                "status": "blocked",
                "blocked_reason": "price_task_dsn_not_configured",
                "write_performed": False,
                "live_api_called": False,
                "plugin_waited": False,
            }
        try:
            params = _parse_mysql_dsn(dsn)
            connect_timeout = _bounded_env_int(
                "HOTEL_OTA_PRICE_TASK_MYSQL_CONNECT_TIMEOUT_SECONDS",
                _DEFAULT_MYSQL_CONNECT_TIMEOUT_SECONDS,
                minimum=1,
                maximum=10,
            )
            io_timeout = _bounded_env_int(
                "HOTEL_OTA_PRICE_TASK_MYSQL_IO_TIMEOUT_SECONDS",
                _DEFAULT_MYSQL_IO_TIMEOUT_SECONDS,
                minimum=1,
                maximum=15,
            )
            conn = pymysql.connect(
                host=params["host"],
                port=params["port"],
                user=params["user"],
                password=params["password"],
                database=params["database"],
                charset=params["charset"],
                autocommit=False,
                cursorclass=pymysql.cursors.DictCursor,
                connect_timeout=connect_timeout,
                read_timeout=io_timeout,
                write_timeout=io_timeout,
            )
            return conn, "mysql", None
        except Exception as exc:
            return _connection_failure("mysql", exc)

    if kind != "sqlite":
        return None, kind, {
            "status": "blocked",
            "blocked_reason": "unsupported_price_task_db_kind",
            "db_kind": kind,
            "write_performed": False,
            "live_api_called": False,
            "plugin_waited": False,
        }

    conn: sqlite3.Connection | None = None
    try:
        busy_timeout_ms = _bounded_env_int(
            "HOTEL_OTA_PRICE_TASK_SQLITE_BUSY_TIMEOUT_MS",
            _DEFAULT_SQLITE_BUSY_TIMEOUT_MS,
            minimum=100,
            maximum=5000,
        )
        conn = _open_fast_sqlite(db_path, busy_timeout_ms=busy_timeout_ms)
        # Production databases are already migrated. Avoid running the full
        # schema initializer on every S6 enqueue; retain first-run compatibility.
        if not _sqlite_schema_ready(conn):
            init_schema(conn)
        return conn, "sqlite", None
    except Exception as exc:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        return _connection_failure("sqlite", exc)


def guard_write_zhiting_price_tasks(
    original: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    if getattr(original, "_s6_fast_enqueue_guard", False):
        return original

    @wraps(original)
    def guarded(*args: Any, **kwargs: Any) -> dict[str, Any]:
        started = time.perf_counter()
        result = original(*args, **kwargs)
        if not isinstance(result, dict):
            return result
        guarded_result = dict(result)
        guarded_result.setdefault("completion_scope", "outbox_write_only")
        guarded_result.setdefault("plugin_waited", False)
        guarded_result.setdefault("platform_readback_waited", False)
        guarded_result.setdefault("live_api_called", False)
        guarded_result["enqueue_elapsed_ms"] = round(
            (time.perf_counter() - started) * 1000,
            2,
        )
        guarded_result["execution_dispatch"] = "asynchronous_plugin"
        guarded_result["request_completed_after_commit"] = (
            guarded_result.get("status") == "queued"
            and bool(guarded_result.get("write_performed"))
        )
        return guarded_result

    guarded._s6_fast_enqueue_guard = True  # type: ignore[attr-defined]
    return guarded


def install_s6_fast_outbox_guard() -> None:
    from runtime.adapters import zhiting_price_task_outbox

    zhiting_price_task_outbox._connect_task_db = _fast_connect_task_db
    zhiting_price_task_outbox.write_zhiting_price_tasks = guard_write_zhiting_price_tasks(
        zhiting_price_task_outbox.write_zhiting_price_tasks
    )

from __future__ import annotations

import sqlite3
import sys
import types
from unittest import mock

from runtime.adapters.s6_fast_outbox_guard import (
    _fast_connect_task_db,
    _open_fast_sqlite,
    _sqlite_schema_ready,
    guard_write_zhiting_price_tasks,
)


_REQUIRED_TABLES = (
    "meituan_ota_goods_price_mapping",
    "ctrip_ota_goods_price_mapping",
    "meituan_zhiting_price_task",
    "ctrip_zhiting_price_task",
)


def _ready_sqlite_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    for table in _REQUIRED_TABLES:
        conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
    return conn


def test_open_fast_sqlite_applies_short_busy_timeout() -> None:
    conn = _open_fast_sqlite(":memory:", busy_timeout_ms=1000)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1000
    finally:
        conn.close()


def test_fast_sqlite_connection_skips_full_schema_init_when_migrated() -> None:
    conn = _ready_sqlite_connection()
    assert _sqlite_schema_ready(conn)

    with mock.patch(
        "runtime.adapters.s6_fast_outbox_guard._open_fast_sqlite",
        return_value=conn,
    ) as open_sqlite, mock.patch(
        "runtime.adapters.s6_fast_outbox_guard.init_schema",
    ) as init:
        opened, dialect, blocked = _fast_connect_task_db(":memory:", db_kind="sqlite")

    assert opened is conn
    assert dialect == "sqlite"
    assert blocked is None
    open_sqlite.assert_called_once_with(":memory:", busy_timeout_ms=1000)
    init.assert_not_called()
    conn.close()


def test_fast_sqlite_connection_initializes_missing_outbox_schema() -> None:
    conn = sqlite3.connect(":memory:")
    assert not _sqlite_schema_ready(conn)

    with mock.patch(
        "runtime.adapters.s6_fast_outbox_guard._open_fast_sqlite",
        return_value=conn,
    ), mock.patch(
        "runtime.adapters.s6_fast_outbox_guard.init_schema",
    ) as init:
        opened, dialect, blocked = _fast_connect_task_db(":memory:", db_kind="sqlite")

    assert opened is conn
    assert dialect == "sqlite"
    assert blocked is None
    init.assert_called_once_with(conn)
    conn.close()


def test_fast_mysql_connection_uses_short_timeouts() -> None:
    fake_connect = mock.Mock(return_value=object())
    fake_pymysql = types.SimpleNamespace(
        connect=fake_connect,
        cursors=types.SimpleNamespace(DictCursor=object()),
    )
    parsed = {
        "host": "db",
        "port": 3306,
        "user": "user",
        "password": "secret",
        "database": "hotel",
        "charset": "utf8mb4",
    }

    with mock.patch.dict(sys.modules, {"pymysql": fake_pymysql}), mock.patch(
        "runtime.adapters.database._parse_mysql_dsn",
        return_value=parsed,
    ):
        conn, dialect, blocked = _fast_connect_task_db(
            "",
            db_kind="mysql",
            dsn="mysql://ignored",
        )

    assert conn is fake_connect.return_value
    assert dialect == "mysql"
    assert blocked is None
    kwargs = fake_connect.call_args.kwargs
    assert kwargs["connect_timeout"] == 2
    assert kwargs["read_timeout"] == 3
    assert kwargs["write_timeout"] == 3
    assert kwargs["autocommit"] is False


def test_enqueue_result_explicitly_returns_without_plugin_wait() -> None:
    def writer(*_args: object, **_kwargs: object) -> dict:
        return {
            "status": "queued",
            "execute_status": "PENDING",
            "write_performed": True,
        }

    result = guard_write_zhiting_price_tasks(writer)(":memory:")

    assert result["status"] == "queued"
    assert result["execute_status"] == "PENDING"
    assert result["completion_scope"] == "outbox_write_only"
    assert result["plugin_waited"] is False
    assert result["platform_readback_waited"] is False
    assert result["live_api_called"] is False
    assert result["execution_dispatch"] == "asynchronous_plugin"
    assert result["request_completed_after_commit"] is True
    assert result["enqueue_elapsed_ms"] >= 0

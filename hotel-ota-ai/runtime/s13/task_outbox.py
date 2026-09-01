from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, unquote, urlparse

from runtime.s13.contracts import TaskRecord, WriteResult, task_channel_source


TASK_TABLE = "ota_review_reply_task"
TASK_COLUMNS = (
    "hotel_id",
    "platform",
    "channel_source",
    "review_id",
    "review_content",
    "reply_content",
    "status",
    "error_message",
    "created_at",
    "replied_at",
)


class TaskDataGap(RuntimeError):
    pass


class ReviewTaskOutbox(Protocol):
    def read_by_unique(self, *, hotel_id: str, platform: str, review_id: str) -> TaskRecord | None: ...

    def read_by_id(self, *, task_id: int, hotel_id: str, platform: str, review_id: str) -> TaskRecord | None: ...

    def insert_pending(
        self,
        *,
        hotel_id: str,
        platform: str,
        review_id: str,
        review_content: str | None,
        reply_content: str,
        created_at: str,
    ) -> WriteResult: ...

    def cas_retry(
        self,
        *,
        task: TaskRecord,
        new_review_content: str | None,
        new_reply_content: str,
        new_created_at: str,
    ) -> WriteResult: ...


class UnavailableReviewTaskOutbox:
    def __init__(self, reason: str = "review_task_writer_not_configured") -> None:
        self.reason = reason

    def read_by_unique(self, *, hotel_id: str, platform: str, review_id: str) -> TaskRecord | None:
        return None

    def read_by_id(self, *, task_id: int, hotel_id: str, platform: str, review_id: str) -> TaskRecord | None:
        return None

    def insert_pending(self, **kwargs: Any) -> WriteResult:
        return WriteResult(False, 0, None, False, None, error=self.reason)

    def cas_retry(self, **kwargs: Any) -> WriteResult:
        return WriteResult(False, 0, None, False, None, error=self.reason)


def _task_from_mapping(row: Any) -> TaskRecord | None:
    if not row:
        return None
    item = dict(row)
    return TaskRecord(
        id=int(item["id"]),
        hotel_id=str(item["hotel_id"]),
        platform=str(item["platform"]),
        channel_source=str(item["channel_source"]),
        review_id=str(item["review_id"]),
        review_content=None if item.get("review_content") is None else str(item.get("review_content")),
        reply_content=str(item.get("reply_content") or ""),
        status=str(item.get("status") or ""),
        error_message=None if item.get("error_message") is None else str(item.get("error_message")),
        created_at=str(item.get("created_at") or ""),
        replied_at=None if item.get("replied_at") is None else str(item.get("replied_at")),
    )


def _verified_pending(
    task: TaskRecord | None,
    *,
    hotel_id: str,
    platform: str,
    review_id: str,
    reply_content: str,
) -> bool:
    return bool(
        task
        and task.hotel_id == hotel_id
        and task.platform == platform
        and task.channel_source == task_channel_source(platform)
        and task.review_id == review_id
        and task.reply_content == reply_content
        and task.status == "pending"
    )


class SQLiteReviewTaskOutbox:
    """Test/dev implementation with the same fixed table contract as MySQL."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            self.ensure_schema_conn(conn)
            conn.commit()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def ensure_schema_conn(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ota_review_reply_task (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              hotel_id TEXT NOT NULL,
              platform TEXT NOT NULL,
              channel_source TEXT NOT NULL,
              review_id TEXT NOT NULL,
              review_content TEXT NULL,
              reply_content TEXT NOT NULL,
              status TEXT NOT NULL,
              error_message TEXT NULL,
              created_at TEXT NOT NULL,
              replied_at TEXT NULL,
              UNIQUE(hotel_id, channel_source, review_id)
            );
            CREATE INDEX IF NOT EXISTS idx_review_reply_task_status
              ON ota_review_reply_task(hotel_id, channel_source, status, created_at);
            """
        )

    def read_by_unique(self, *, hotel_id: str, platform: str, review_id: str) -> TaskRecord | None:
        channel_source = task_channel_source(platform)
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT id, hotel_id, platform, channel_source, review_id,
                       review_content, reply_content, status, error_message,
                       created_at, replied_at
                FROM ota_review_reply_task
                WHERE hotel_id=? AND platform=?
                  AND channel_source=? AND review_id=?
                LIMIT 1
                """,
                (hotel_id, platform, channel_source, review_id),
            ).fetchone()
            return _task_from_mapping(row)

    def read_by_id(self, *, task_id: int, hotel_id: str, platform: str, review_id: str) -> TaskRecord | None:
        channel_source = task_channel_source(platform)
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT id, hotel_id, platform, channel_source, review_id,
                       review_content, reply_content, status, error_message,
                       created_at, replied_at
                FROM ota_review_reply_task
                WHERE id=? AND hotel_id=? AND platform=?
                  AND channel_source=? AND review_id=?
                """,
                (task_id, hotel_id, platform, channel_source, review_id),
            ).fetchone()
            return _task_from_mapping(row)

    def insert_pending(
        self,
        *,
        hotel_id: str,
        platform: str,
        review_id: str,
        review_content: str | None,
        reply_content: str,
        created_at: str,
    ) -> WriteResult:
        channel_source = task_channel_source(platform)
        try:
            with closing(self.connect()) as conn, conn:
                cursor = conn.execute(
                    """
                    INSERT INTO ota_review_reply_task (
                      hotel_id, platform, channel_source, review_id,
                      review_content, reply_content, status, error_message,
                      created_at, replied_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'pending', NULL, ?, NULL)
                    """,
                    (hotel_id, platform, channel_source, review_id, review_content, reply_content, created_at),
                )
                task_id = int(cursor.lastrowid)
                affected_rows = int(cursor.rowcount)
        except sqlite3.IntegrityError:
            existing = self.read_by_unique(hotel_id=hotel_id, platform=platform, review_id=review_id)
            return WriteResult(
                False,
                0,
                existing.id if existing else None,
                False,
                existing,
                conflict_status=existing.status if existing else "unique_conflict",
            )
        task = self.read_by_id(task_id=task_id, hotel_id=hotel_id, platform=platform, review_id=review_id)
        verified = affected_rows == 1 and _verified_pending(
            task,
            hotel_id=hotel_id,
            platform=platform,
            review_id=review_id,
            reply_content=reply_content,
        )
        return WriteResult(True, affected_rows, task_id, verified, task)

    def cas_retry(
        self,
        *,
        task: TaskRecord,
        new_review_content: str | None,
        new_reply_content: str,
        new_created_at: str,
    ) -> WriteResult:
        if task.status not in {"failed", "cancelled"}:
            return WriteResult(False, 0, task.id, False, task, conflict_status=task.status)
        with closing(self.connect()) as conn, conn:
            cursor = conn.execute(
                """
                UPDATE ota_review_reply_task
                SET review_content=?, reply_content=?, status='pending',
                    error_message=NULL, created_at=?, replied_at=NULL
                WHERE id=? AND hotel_id=? AND platform=?
                  AND channel_source=? AND review_id=?
                  AND status=?
                  AND ((reply_content IS NULL AND ? IS NULL) OR reply_content=?)
                  AND created_at=?
                """,
                (
                    new_review_content,
                    new_reply_content,
                    new_created_at,
                    task.id,
                    task.hotel_id,
                    task.platform,
                    task.channel_source,
                    task.review_id,
                    task.status,
                    task.reply_content,
                    task.reply_content,
                    task.created_at,
                ),
            )
            affected_rows = int(cursor.rowcount)
        updated = self.read_by_id(task_id=task.id, hotel_id=task.hotel_id, platform=task.platform, review_id=task.review_id)
        verified = affected_rows == 1 and _verified_pending(
            updated,
            hotel_id=task.hotel_id,
            platform=task.platform,
            review_id=task.review_id,
            reply_content=new_reply_content,
        )
        return WriteResult(affected_rows == 1, affected_rows, task.id, verified, updated)


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise TaskDataGap("review_task_dsn_must_be_mysql")
    database = parsed.path.lstrip("/")
    if not database:
        raise TaskDataGap("review_task_database_required")
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "charset": query.get("charset", ["utf8mb4"])[0],
        "connect_timeout": int(query.get("connect_timeout", ["5"])[0]),
        "read_timeout": int(query.get("read_timeout", ["10"])[0]),
        "write_timeout": int(query.get("write_timeout", ["10"])[0]),
        "autocommit": False,
    }


def _mysql_timestamp(value: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone(timedelta(hours=8))).replace(tzinfo=None)
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


class MySQLReviewTaskOutbox:
    """Fixed DML adapter for the only approved S13 task sink."""

    def __init__(self, dsn: str) -> None:
        try:
            import pymysql  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional production dependency
            raise TaskDataGap("pymysql_not_installed") from exc
        self._pymysql = pymysql
        self._connection_kwargs = _parse_mysql_dsn(dsn)

    @classmethod
    def from_env(cls, explicit_dsn: str | None = None, hotel_id: str | None = None) -> "MySQLReviewTaskOutbox":
        from runtime.adapters.database import resolve_hotel_dsn

        enabled = str(os.environ.get("HOTEL_OTA_REVIEW_TASK_WRITE_ENABLED", "false")).strip().lower()
        if enabled not in {"1", "true", "yes", "y"}:
            raise TaskDataGap("review_task_write_gate_disabled")
        try:
            dsn = explicit_dsn or resolve_hotel_dsn(hotel_id, "HOTEL_OTA_REVIEW_TASK_DSN")
        except RuntimeError as exc:
            raise TaskDataGap("review_task_dsn_not_configured") from exc
        if not dsn:
            raise TaskDataGap("review_task_dsn_not_configured")
        return cls(dsn)

    def _connect(self):  # type: ignore[no-untyped-def]
        return self._pymysql.connect(
            cursorclass=self._pymysql.cursors.DictCursor,
            **self._connection_kwargs,
        )

    def read_by_unique(self, *, hotel_id: str, platform: str, review_id: str) -> TaskRecord | None:
        channel_source = task_channel_source(platform)
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, hotel_id, platform, channel_source, review_id,
                       review_content, reply_content, status, error_message,
                       created_at, replied_at
                FROM ota_review_reply_task
                WHERE hotel_id=%s AND platform=%s
                  AND channel_source=%s AND review_id=%s
                LIMIT 1
                """,
                (hotel_id, platform, channel_source, review_id),
            )
            return _task_from_mapping(cursor.fetchone())

    def read_by_id(self, *, task_id: int, hotel_id: str, platform: str, review_id: str) -> TaskRecord | None:
        channel_source = task_channel_source(platform)
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, hotel_id, platform, channel_source, review_id,
                       review_content, reply_content, status, error_message,
                       created_at, replied_at
                FROM ota_review_reply_task
                WHERE id=%s AND hotel_id=%s AND platform=%s
                  AND channel_source=%s AND review_id=%s
                """,
                (task_id, hotel_id, platform, channel_source, review_id),
            )
            return _task_from_mapping(cursor.fetchone())

    def insert_pending(
        self,
        *,
        hotel_id: str,
        platform: str,
        review_id: str,
        review_content: str | None,
        reply_content: str,
        created_at: str,
    ) -> WriteResult:
        channel_source = task_channel_source(platform)
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    affected_rows = cursor.execute(
                        """
                        INSERT INTO ota_review_reply_task (
                          hotel_id, platform, channel_source, review_id,
                          review_content, reply_content, status, error_message,
                          created_at, replied_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, 'pending', NULL, %s, NULL)
                        """,
                        (hotel_id, platform, channel_source, review_id, review_content, reply_content, _mysql_timestamp(created_at)),
                    )
                    task_id = int(cursor.lastrowid)
                conn.commit()
        except self._pymysql.err.IntegrityError:
            existing = self.read_by_unique(hotel_id=hotel_id, platform=platform, review_id=review_id)
            return WriteResult(
                False,
                0,
                existing.id if existing else None,
                False,
                existing,
                conflict_status=existing.status if existing else "unique_conflict",
            )
        except Exception as exc:  # pragma: no cover - production connectivity
            return WriteResult(False, 0, None, False, None, error=f"review_task_insert_failed:{type(exc).__name__}")
        task = self.read_by_id(task_id=task_id, hotel_id=hotel_id, platform=platform, review_id=review_id)
        verified = affected_rows == 1 and _verified_pending(
            task,
            hotel_id=hotel_id,
            platform=platform,
            review_id=review_id,
            reply_content=reply_content,
        )
        return WriteResult(True, int(affected_rows), task_id, verified, task)

    def cas_retry(
        self,
        *,
        task: TaskRecord,
        new_review_content: str | None,
        new_reply_content: str,
        new_created_at: str,
    ) -> WriteResult:
        if task.status not in {"failed", "cancelled"}:
            return WriteResult(False, 0, task.id, False, task, conflict_status=task.status)
        try:
            with self._connect() as conn:
                with conn.cursor() as cursor:
                    affected_rows = cursor.execute(
                        """
                        UPDATE ota_review_reply_task
                        SET review_content=%s, reply_content=%s, status='pending',
                            error_message=NULL, created_at=%s, replied_at=NULL
                        WHERE id=%s AND hotel_id=%s AND platform=%s
                          AND channel_source=%s AND review_id=%s
                          AND status=%s AND reply_content <=> %s
                          AND created_at=%s
                        """,
                        (
                            new_review_content,
                            new_reply_content,
                            _mysql_timestamp(new_created_at),
                            task.id,
                            task.hotel_id,
                            task.platform,
                            task.channel_source,
                            task.review_id,
                            task.status,
                            task.reply_content,
                            task.created_at,
                        ),
                    )
                conn.commit()
        except Exception as exc:  # pragma: no cover - production connectivity
            return WriteResult(False, 0, task.id, False, task, error=f"review_task_cas_failed:{type(exc).__name__}")
        updated = self.read_by_id(task_id=task.id, hotel_id=task.hotel_id, platform=task.platform, review_id=task.review_id)
        verified = affected_rows == 1 and _verified_pending(
            updated,
            hotel_id=task.hotel_id,
            platform=task.platform,
            review_id=task.review_id,
            reply_content=new_reply_content,
        )
        return WriteResult(affected_rows == 1, int(affected_rows), task.id, verified, updated)

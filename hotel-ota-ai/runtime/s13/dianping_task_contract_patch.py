from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import Any

from runtime.s13.contracts import (
    WriteResult,
    logical_task_platform,
    task_channel_source,
    task_storage_platform,
)


_INSTALLED = False


def _patch_task_decoder(task_outbox: Any) -> None:
    original = task_outbox._task_from_mapping
    if getattr(original, "_s13_dianping_storage_contract", False):
        return

    def task_from_mapping(row: Any):  # type: ignore[no-untyped-def]
        task = original(row)
        if task is None:
            return None
        logical_platform = logical_task_platform(task.platform, task.channel_source)
        return task if logical_platform == task.platform else replace(task, platform=logical_platform)

    task_from_mapping._s13_dianping_storage_contract = True  # type: ignore[attr-defined]
    task_outbox._task_from_mapping = task_from_mapping


def _patch_sqlite(task_outbox: Any) -> None:
    cls = task_outbox.SQLiteReviewTaskOutbox
    if getattr(cls, "_S13_DIANPING_STORAGE_PATCHED", False):
        return

    original_read_by_unique = cls.read_by_unique
    original_read_by_id = cls.read_by_id
    original_insert_pending = cls.insert_pending
    original_cas_retry = cls.cas_retry

    def read_by_unique(self, *, hotel_id: str, platform: str, review_id: str):  # type: ignore[no-untyped-def]
        if platform != "dianping":
            return original_read_by_unique(self, hotel_id=hotel_id, platform=platform, review_id=review_id)
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
                (
                    hotel_id,
                    task_storage_platform(platform),
                    task_channel_source(platform),
                    review_id,
                ),
            ).fetchone()
        return task_outbox._task_from_mapping(row)

    def read_by_id(self, *, task_id: int, hotel_id: str, platform: str, review_id: str):  # type: ignore[no-untyped-def]
        if platform != "dianping":
            return original_read_by_id(
                self,
                task_id=task_id,
                hotel_id=hotel_id,
                platform=platform,
                review_id=review_id,
            )
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
                (
                    task_id,
                    hotel_id,
                    task_storage_platform(platform),
                    task_channel_source(platform),
                    review_id,
                ),
            ).fetchone()
        return task_outbox._task_from_mapping(row)

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
        if platform != "dianping":
            return original_insert_pending(
                self,
                hotel_id=hotel_id,
                platform=platform,
                review_id=review_id,
                review_content=review_content,
                reply_content=reply_content,
                created_at=created_at,
            )
        storage_platform = task_storage_platform(platform)
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
                    (
                        hotel_id,
                        storage_platform,
                        channel_source,
                        review_id,
                        review_content,
                        reply_content,
                        created_at,
                    ),
                )
                task_id = int(cursor.lastrowid)
                affected_rows = int(cursor.rowcount)
        except sqlite3.IntegrityError:
            existing = self.read_by_unique(
                hotel_id=hotel_id,
                platform=platform,
                review_id=review_id,
            )
            return WriteResult(
                False,
                0,
                existing.id if existing else None,
                False,
                existing,
                conflict_status=existing.status if existing else "unique_conflict",
            )
        task = self.read_by_id(
            task_id=task_id,
            hotel_id=hotel_id,
            platform=platform,
            review_id=review_id,
        )
        verified = affected_rows == 1 and task_outbox._verified_pending(
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
        task,
        new_review_content: str | None,
        new_reply_content: str,
        new_created_at: str,
    ) -> WriteResult:
        if task.platform != "dianping":
            return original_cas_retry(
                self,
                task=task,
                new_review_content=new_review_content,
                new_reply_content=new_reply_content,
                new_created_at=new_created_at,
            )
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
                    task_storage_platform(task.platform),
                    task_channel_source(task.platform),
                    task.review_id,
                    task.status,
                    task.reply_content,
                    task.reply_content,
                    task.created_at,
                ),
            )
            affected_rows = int(cursor.rowcount)
        updated = self.read_by_id(
            task_id=task.id,
            hotel_id=task.hotel_id,
            platform=task.platform,
            review_id=task.review_id,
        )
        verified = affected_rows == 1 and task_outbox._verified_pending(
            updated,
            hotel_id=task.hotel_id,
            platform=task.platform,
            review_id=task.review_id,
            reply_content=new_reply_content,
        )
        return WriteResult(affected_rows == 1, affected_rows, task.id, verified, updated)

    cls.read_by_unique = read_by_unique
    cls.read_by_id = read_by_id
    cls.insert_pending = insert_pending
    cls.cas_retry = cas_retry
    cls._S13_DIANPING_STORAGE_PATCHED = True


def _patch_mysql(task_outbox: Any) -> None:
    cls = task_outbox.MySQLReviewTaskOutbox
    if getattr(cls, "_S13_DIANPING_STORAGE_PATCHED", False):
        return

    original_read_by_unique = cls.read_by_unique
    original_read_by_id = cls.read_by_id
    original_insert_pending = cls.insert_pending
    original_cas_retry = cls.cas_retry

    def read_by_unique(self, *, hotel_id: str, platform: str, review_id: str):  # type: ignore[no-untyped-def]
        if platform != "dianping":
            return original_read_by_unique(self, hotel_id=hotel_id, platform=platform, review_id=review_id)
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
                (
                    hotel_id,
                    task_storage_platform(platform),
                    task_channel_source(platform),
                    review_id,
                ),
            )
            row = cursor.fetchone()
        return task_outbox._task_from_mapping(row)

    def read_by_id(self, *, task_id: int, hotel_id: str, platform: str, review_id: str):  # type: ignore[no-untyped-def]
        if platform != "dianping":
            return original_read_by_id(
                self,
                task_id=task_id,
                hotel_id=hotel_id,
                platform=platform,
                review_id=review_id,
            )
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
                (
                    task_id,
                    hotel_id,
                    task_storage_platform(platform),
                    task_channel_source(platform),
                    review_id,
                ),
            )
            row = cursor.fetchone()
        return task_outbox._task_from_mapping(row)

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
        if platform != "dianping":
            return original_insert_pending(
                self,
                hotel_id=hotel_id,
                platform=platform,
                review_id=review_id,
                review_content=review_content,
                reply_content=reply_content,
                created_at=created_at,
            )
        storage_platform = task_storage_platform(platform)
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
                        (
                            hotel_id,
                            storage_platform,
                            channel_source,
                            review_id,
                            review_content,
                            reply_content,
                            task_outbox._mysql_timestamp(created_at),
                        ),
                    )
                    task_id = int(cursor.lastrowid)
                conn.commit()
        except self._pymysql.err.IntegrityError:
            existing = self.read_by_unique(
                hotel_id=hotel_id,
                platform=platform,
                review_id=review_id,
            )
            return WriteResult(
                False,
                0,
                existing.id if existing else None,
                False,
                existing,
                conflict_status=existing.status if existing else "unique_conflict",
            )
        except Exception as exc:  # pragma: no cover - production connectivity
            return WriteResult(
                False,
                0,
                None,
                False,
                None,
                error=f"review_task_insert_failed:{type(exc).__name__}",
            )
        task = self.read_by_id(
            task_id=task_id,
            hotel_id=hotel_id,
            platform=platform,
            review_id=review_id,
        )
        verified = affected_rows == 1 and task_outbox._verified_pending(
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
        task,
        new_review_content: str | None,
        new_reply_content: str,
        new_created_at: str,
    ) -> WriteResult:
        if task.platform != "dianping":
            return original_cas_retry(
                self,
                task=task,
                new_review_content=new_review_content,
                new_reply_content=new_reply_content,
                new_created_at=new_created_at,
            )
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
                            task_outbox._mysql_timestamp(new_created_at),
                            task.id,
                            task.hotel_id,
                            task_storage_platform(task.platform),
                            task_channel_source(task.platform),
                            task.review_id,
                            task.status,
                            task.reply_content,
                            task.created_at,
                        ),
                    )
                conn.commit()
        except Exception as exc:  # pragma: no cover - production connectivity
            return WriteResult(
                False,
                0,
                task.id,
                False,
                task,
                error=f"review_task_cas_failed:{type(exc).__name__}",
            )
        updated = self.read_by_id(
            task_id=task.id,
            hotel_id=task.hotel_id,
            platform=task.platform,
            review_id=task.review_id,
        )
        verified = affected_rows == 1 and task_outbox._verified_pending(
            updated,
            hotel_id=task.hotel_id,
            platform=task.platform,
            review_id=task.review_id,
            reply_content=new_reply_content,
        )
        return WriteResult(affected_rows == 1, int(affected_rows), task.id, verified, updated)

    cls.read_by_unique = read_by_unique
    cls.read_by_id = read_by_id
    cls.insert_pending = insert_pending
    cls.cas_retry = cas_retry
    cls._S13_DIANPING_STORAGE_PATCHED = True


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import runtime.s13.task_outbox as task_outbox

    task_outbox.task_channel_source = task_channel_source
    _patch_task_decoder(task_outbox)
    _patch_sqlite(task_outbox)
    _patch_mysql(task_outbox)

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from runtime.s13.contracts import RequestContext, ReviewRecord
from runtime.s13.repository import S13ControlRepository
from runtime.s13.service import S13Service
from runtime.s13.source import MemoryReviewSourceRepository
from runtime.s13.task_outbox import SQLiteReviewTaskOutbox


NOW = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)


class TaskOutboxCASTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.task_path = str(root / "task.sqlite")
        self.outbox = SQLiteReviewTaskOutbox(self.task_path)
        self.source = MemoryReviewSourceRepository(
            [ReviewRecord("hotel-a", "meituan", "m-1", None, 1, False, "2026-08-03T07:30:00+00:00")]
        )
        self.service = S13Service(
            control_repository=S13ControlRepository(str(root / "control.sqlite")),
            source_repository=self.source,
            task_outbox=self.outbox,
        )
        self.context = RequestContext("hotel-a", "owner", "owner-1", NOW)
        self.ref = self.service.list_pending(self.context)["items"][0]["review_ref"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _insert_failed_task(self) -> None:
        with closing(sqlite3.connect(self.task_path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO ota_review_reply_task (
                  hotel_id, platform, channel_source, review_id,
                  review_content, reply_content, status, error_message,
                  created_at, replied_at
                ) VALUES ('hotel-a','meituan','meituan','m-1',NULL,'old','failed','provider error','2026-08-03T07:00:00+00:00',NULL)
                """
            )

    def test_failed_task_requires_retry_and_cas(self) -> None:
        self._insert_failed_task()
        draft = self.service.generate_draft(self.context, review_ref=self.ref)
        confirm = self.service.confirm(self.context, request_id=draft["confirmation"]["request_id"])
        self.assertEqual(confirm["status"], "blocked")
        self.assertEqual(confirm["blocked_reason"], "failed_or_cancelled_task_requires_retry_command")
        retry = self.service.retry(self.context, request_id=draft["confirmation"]["request_id"])
        self.assertEqual(retry["status"], "ok")
        self.assertEqual(retry["task"]["retry_mode"], "cas_update")
        self.assertTrue(retry["task"]["pending_readback_verified"])

    def test_active_and_success_are_not_overwritten(self) -> None:
        for status, expected in (("pending", "active_conflict"), ("success", "already_handled")):
            with closing(sqlite3.connect(self.task_path)) as conn, conn:
                conn.execute("DELETE FROM ota_review_reply_task")
                conn.execute(
                    """
                    INSERT INTO ota_review_reply_task (
                      hotel_id, platform, channel_source, review_id,
                      review_content, reply_content, status, error_message,
                      created_at, replied_at
                    ) VALUES ('hotel-a','meituan','meituan','m-1',NULL,'old',?,NULL,'2026-08-03T07:00:00+00:00',NULL)
                    """,
                    (status,),
                )
            result = self.service.generate_draft(self.context, review_ref=self.ref)
            self.assertEqual(result["status"], expected)


if __name__ == "__main__":
    unittest.main()

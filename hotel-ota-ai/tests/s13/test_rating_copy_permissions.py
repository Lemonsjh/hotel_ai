from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.s13.contracts import RequestContext, ReviewRecord
from runtime.s13.repository import S13ControlRepository
from runtime.s13.service import S13Service
from runtime.s13.source import MemoryReviewSourceRepository
from runtime.s13.task_outbox import SQLiteReviewTaskOutbox


NOW = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)


class RatingCopyPermissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.task_db = str(root / "task.sqlite")
        self.service = S13Service(
            control_repository=S13ControlRepository(str(root / "control.sqlite")),
            source_repository=MemoryReviewSourceRepository(
                [
                    ReviewRecord("hotel-a", "meituan", "m-1", None, 5, False, "2026-08-03T07:30:00+00:00"),
                    ReviewRecord("hotel-a", "dianping", "m-1", "环境不错", 5, False, "2026-08-03T07:32:00+00:00"),
                    ReviewRecord("hotel-a", "ctrip", "c-1", "服务一般", 3, False, "2026-08-03T07:31:00+00:00"),
                ]
            ),
            task_outbox=SQLiteReviewTaskOutbox(self.task_db),
        )
        self.owner = RequestContext("hotel-a", "owner", "owner-1", NOW)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_rating_only_generates_deterministic_candidate(self) -> None:
        items = self.service.list_pending(self.owner)["items"]
        ref = next(item["review_ref"] for item in items if item["platform"] == "meituan")
        result = self.service.generate_draft(self.owner, review_ref=ref)
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["review_content_present"])
        self.assertEqual(result["draft_candidate"]["candidate_origin"], "deterministic_candidate")
        self.assertNotIn("None", result["draft_candidate"]["draft"])

    def test_non_meituan_is_copy_only(self) -> None:
        items = self.service.list_pending(self.owner)["items"]
        ref = next(item["review_ref"] for item in items if item["platform"] == "ctrip")
        result = self.service.generate_draft(self.owner, review_ref=ref)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["copy_only"])
        self.assertIsNone(result["task"])
        self.assertIsNone(result["confirmation"])

    def test_dianping_confirm_uses_meituan_family_plugin_contract(self) -> None:
        items = self.service.list_pending(self.owner)["items"]
        mt_ref = next(item["review_ref"] for item in items if item["platform"] == "meituan")
        dp_ref = next(item["review_ref"] for item in items if item["platform"] == "dianping")

        mt_draft = self.service.generate_draft(self.owner, review_ref=mt_ref)
        mt_result = self.service.confirm(
            self.owner,
            request_id=mt_draft["confirmation"]["request_id"],
        )
        self.assertEqual(mt_result["status"], "ok")
        self.assertEqual(mt_result["task"]["platform"], "meituan")
        self.assertEqual(mt_result["task"]["channel_source"], "meituan")

        dp_draft = self.service.generate_draft(self.owner, review_ref=dp_ref)
        self.assertFalse(dp_draft["copy_only"])
        result = self.service.confirm(
            self.owner,
            request_id=dp_draft["confirmation"]["request_id"],
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["platform"], "dianping")
        self.assertEqual(result["task"]["platform"], "dianping")
        self.assertEqual(result["task"]["channel_source"], "dainping")
        self.assertTrue(result["task"]["pending_readback_verified"])

        with sqlite3.connect(self.task_db) as conn:
            row = conn.execute(
                """
                SELECT platform, channel_source, status
                FROM ota_review_reply_task
                WHERE hotel_id=? AND review_id=? AND channel_source=?
                """,
                ("hotel-a", "m-1", "dainping"),
            ).fetchone()
        self.assertEqual(row, ("meituan", "dainping", "pending"))

    def test_frontdesk_and_viewer_are_blocked(self) -> None:
        for role in ("frontdesk", "viewer"):
            result = self.service.list_pending(RequestContext("hotel-a", role, role, NOW))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blocked_reason"], "review_reply_permission_denied")

    def test_admin_can_use_s13(self) -> None:
        result = self.service.list_pending(RequestContext("hotel-a", "admin", "admin-1", NOW))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 3)


if __name__ == "__main__":
    unittest.main()

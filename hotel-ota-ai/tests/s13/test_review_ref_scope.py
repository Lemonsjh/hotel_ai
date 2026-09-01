from __future__ import annotations

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


class ReviewRefScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.source = MemoryReviewSourceRepository(
            [
                ReviewRecord(
                    hotel_id="hotel-a",
                    platform="meituan",
                    review_id="physical-1",
                    review_content="房间卫生一般，手机号13800138000",
                    star_rating=2,
                    is_replied=False,
                    source_snapshot="2026-08-03T07:30:00+00:00",
                )
            ]
        )
        self.service = S13Service(
            control_repository=S13ControlRepository(str(root / "control.sqlite")),
            source_repository=self.source,
            task_outbox=SQLiteReviewTaskOutbox(str(root / "task.sqlite")),
        )
        self.owner = RequestContext("hotel-a", "owner", "principal-owner", NOW)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_list_issues_opaque_ref_without_physical_id(self) -> None:
        result = self.service.list_pending(self.owner)
        self.assertEqual(result["status"], "ok")
        review_ref = result["items"][0]["review_ref"]
        self.assertTrue(review_ref.startswith("REV-"))
        self.assertNotIn("physical-1", review_ref)
        self.assertNotIn("hotel-a", review_ref)
        self.assertNotIn("13800138000", result["items"][0]["redacted_excerpt"])

    def test_cross_hotel_ref_is_blocked(self) -> None:
        review_ref = self.service.list_pending(self.owner)["items"][0]["review_ref"]
        other = RequestContext("hotel-b", "owner", "principal-owner", NOW)
        result = self.service.generate_draft(other, review_ref=review_ref)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "hotel_scope_mismatch")

    def test_source_change_invalidates_ref(self) -> None:
        review_ref = self.service.list_pending(self.owner)["items"][0]["review_ref"]
        self.source.records[0] = ReviewRecord(
            hotel_id="hotel-a",
            platform="meituan",
            review_id="physical-1",
            review_content="内容已经变化",
            star_rating=2,
            is_replied=False,
            source_snapshot="2026-08-03T07:45:00+00:00",
        )
        result = self.service.generate_draft(self.owner, review_ref=review_ref)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "review_source_snapshot_changed")


if __name__ == "__main__":
    unittest.main()

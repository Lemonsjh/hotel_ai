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
from runtime.s13_runtime_patch import _patch_service
import runtime.s13.service as service_module


NOW = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)


class VersionConfirmationTests(unittest.TestCase):
    def setUp(self) -> None:
        _patch_service(service_module)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.service = S13Service(
            control_repository=S13ControlRepository(str(root / "control.sqlite")),
            source_repository=MemoryReviewSourceRepository(
                [ReviewRecord("hotel-a", "meituan", "m-1", "卫生不好", 2, False, "2026-08-03T07:30:00+00:00")]
            ),
            task_outbox=SQLiteReviewTaskOutbox(str(root / "task.sqlite")),
        )
        self.context = RequestContext("hotel-a", "operator", "operator-1", NOW)
        self.ref = self.service.list_pending(self.context)["items"][0]["review_ref"]

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_new_draft_invalidates_old_request(self) -> None:
        first = self.service.generate_draft(self.context, review_ref=self.ref)
        second = self.service.generate_draft(
            self.context,
            review_ref=self.ref,
            human_reply_content="感谢您的反馈。很抱歉本次体验未达到预期，我们会继续加强卫生检查。",
        )
        self.assertEqual(second["draft_candidate"]["draft_version"], 2)
        old_request = first["confirmation"]["request_id"]
        result = self.service.confirm(self.context, request_id=old_request)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "request_invalidated_by_new_version")

    def test_confirm_uses_request_id_only_and_exact_pending_readback(self) -> None:
        draft = self.service.generate_draft(self.context, review_ref=self.ref)
        result = self.service.confirm(self.context, request_id=draft["confirmation"]["request_id"])
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["task"]["pending_readback_verified"])
        self.assertEqual(result["task"]["status"], "pending")
        self.assertFalse(result["task"]["public_reply_verified"])

    def test_duplicate_confirm_is_idempotent_replay(self) -> None:
        draft = self.service.generate_draft(self.context, review_ref=self.ref)
        request_id = draft["confirmation"]["request_id"]
        first = self.service.confirm(self.context, request_id=request_id)
        second = self.service.confirm(self.context, request_id=request_id)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertTrue(second["idempotent_replay"])
        self.assertFalse(second["task"]["write_performed"])
        self.assertEqual(second["task"]["affected_rows"], 0)
        self.assertTrue(second["task"]["idempotency_verified"])


if __name__ == "__main__":
    unittest.main()

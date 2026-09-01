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


class HighRiskAndHumanReplyTests(unittest.TestCase):
    def _service(self, content: str) -> tuple[S13Service, RequestContext, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        service = S13Service(
            control_repository=S13ControlRepository(str(root / "control.sqlite")),
            source_repository=MemoryReviewSourceRepository(
                [ReviewRecord("hotel-a", "meituan", "m-1", content, 1, False, "2026-08-03T07:30:00+00:00")]
            ),
            task_outbox=SQLiteReviewTaskOutbox(str(root / "task.sqlite")),
        )
        context = RequestContext("hotel-a", "owner", "owner-1", NOW)
        ref = service.list_pending(context)["items"][0]["review_ref"]
        return service, context, ref

    def test_legal_claim_blocks_submittable_draft(self) -> None:
        service, context, ref = self._service("我要找律师起诉并索赔")
        result = service.generate_draft(context, review_ref=ref)
        self.assertEqual(result["eligibility_status"], "blocked_escalation")
        self.assertIsNone(result["draft_candidate"])
        self.assertIn("legal_dispute", result["risk_flags"])
        self.assertIn("claim", result["risk_flags"])

    def test_human_reply_cannot_include_unapproved_compensation(self) -> None:
        service, context, ref = self._service("卫生不好")
        result = service.generate_draft(context, review_ref=ref, human_reply_content="我们已经赔偿并免费升级房型")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "reply_content_contains_unapproved_commitment")


if __name__ == "__main__":
    unittest.main()

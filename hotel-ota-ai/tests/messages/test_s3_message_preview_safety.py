from __future__ import annotations

import unittest

from runtime.demo_mode import build_demo_node_result


class TestS3MessagePreviewSafety(unittest.TestCase):
    def test_s3_demo_preview_never_sends_or_creates_formal_approval(self) -> None:
        result = build_demo_node_result("N018")
        self.assertTrue(result["message_preview_allowed"])
        self.assertFalse(result["message_send_attempted"])
        self.assertFalse(result["formal_approval_created"])
        self.assertEqual(result["live_execution_count"], 0)
        self.assertTrue(result["approval_card_preview_allowed"])

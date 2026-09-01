from __future__ import annotations

import unittest

from runtime.s13.feishu import _parse_action, _render, is_s13_message


class FeishuTextConfirmationTests(unittest.TestCase):
    def test_confirm_reject_cancel_query_retry_use_request_id_only(self) -> None:
        cases = {
            "确认 REQ-review-001": ("confirm", "REQ-review-001"),
            "拒绝 REQ-review-001": ("reject", "REQ-review-001"),
            "取消 REQ-review-001": ("cancel", "REQ-review-001"),
            "查询 REQ-review-001": ("query_status", "REQ-review-001"),
            "重试 REQ-review-001": ("retry", "REQ-review-001"),
        }
        for message, expected in cases.items():
            with self.subTest(message=message):
                action, fields = _parse_action(message)
                self.assertEqual(action, expected[0])
                self.assertEqual(fields, {"request_id": expected[1]})
                self.assertNotIn("draft_version", fields)
                self.assertNotIn("content_hash", fields)

    def test_review_ref_routes_to_draft_or_status(self) -> None:
        ref = "REV-abcdefghijklmnopqrstuvwxyz012345"
        self.assertTrue(is_s13_message(f"帮我写这条评论的回复 {ref}"))
        action, fields = _parse_action(f"生成回复 {ref}")
        self.assertEqual(action, "generate_draft")
        self.assertEqual(fields["review_ref"], ref)
        action, fields = _parse_action(f"查询 {ref}")
        self.assertEqual(action, "query_status")
        self.assertEqual(fields["review_ref"], ref)

    def test_generic_review_reply_terms_open_real_pending_queue(self) -> None:
        for message in (
            "评论回复",
            "差评回复",
            "回复评论",
            "点评回复",
            "生成评论回复",
            "帮我写评论回复",
        ):
            with self.subTest(message=message):
                self.assertTrue(is_s13_message(message))
                self.assertEqual(_parse_action(message), ("list_pending", {}))

    def test_explicit_demo_is_not_intercepted_by_real_s13_route(self) -> None:
        self.assertFalse(is_s13_message("评论回复演示"))

    def test_latest_unreplied_review_routes_to_exact_s13_query(self) -> None:
        message = "\u6700\u65b0\u7684\u4e00\u6761\u672a\u56de\u590d\u8bc4\u8bba"
        self.assertTrue(is_s13_message(message))
        self.assertEqual(_parse_action(message), ("latest_pending", {}))

    def test_s13_code_lists_pending_reviews(self) -> None:
        self.assertTrue(is_s13_message("S13"))
        self.assertEqual(_parse_action("S13"), ("list_pending", {}))

    def test_draft_reply_keeps_redacted_review_context(self) -> None:
        text = _render(
            {
                "action": "generate_draft",
                "platform": "meituan",
                "star_rating": 4,
                "review_time": "2026-08-04 10:20:00",
                "redacted_excerpt": "服务很好",
                "draft_candidate": {"draft": "感谢您的评价。"},
                "confirmation": {"request_id": "REQ-test"},
            }
        )
        self.assertIn("原评论（脱敏）", text)
        self.assertIn("服务很好", text)
        self.assertIn("评论时间：2026-08-04 10:20:00", text)

    def test_human_reply_uses_ref_and_complete_text(self) -> None:
        ref = "REV-abcdefghijklmnopqrstuvwxyz012345"
        action, fields = _parse_action(
            f"人工回复 {ref}：感谢您的反馈。很抱歉本次体验未达到预期。"
        )
        self.assertEqual(action, "submit_human_draft")
        self.assertEqual(fields["review_ref"], ref)
        self.assertEqual(
            fields["human_reply_content"],
            "感谢您的反馈。很抱歉本次体验未达到预期。",
        )

    def test_confirm_returns_after_pending_readback_without_waiting_for_plugin(self) -> None:
        text = _render(
            {
                "action": "confirm", "status": "ok", "platform": "dianping",
                "task": {"platform": "dianping", "status": "pending", "pending_readback_verified": True},
            }
        )
        self.assertIn("pending", text)
        self.assertIn("不等待或查询渠道执行", text)
        self.assertIn("公开回复状态尚未验证", text)


if __name__ == "__main__":
    unittest.main()

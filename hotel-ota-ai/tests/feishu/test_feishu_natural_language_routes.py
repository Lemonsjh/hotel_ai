from __future__ import annotations

import unittest

from runtime.feishu_command_router import route_feishu_command


class TestFeishuNaturalLanguageRoutes(unittest.TestCase):
    def test_review_promotion_and_role_view_intents_do_not_fall_back_to_menu(self) -> None:
        cases = {
            "\u751f\u6210\u8bc4\u8bba\u56de\u590d\u8349\u7a3f": "review_reply_draft",
            "\u76f4\u63a5\u53d1\u5e03\u8bc4\u8bba\u56de\u590d": "review_publish_request",
            "\u751f\u6210\u63a8\u5e7f\u5efa\u8bae": "promotion_suggestion",
            "\u63a8\u5e7f\u6267\u884c": "promotion_suggestion",
            "\u8c03\u6574\u51fa\u4ef7": "promotion_suggestion",
            "\u67e5\u770b\u7ade\u5bf9\u76d1\u63a7": "competition_alert",
            "\u8001\u677f\u89c6\u89d2\u770b\u4eca\u65e5\u6f14\u793a": "owner_today_demo",
            "\u8fd0\u8425\u89c6\u89d2\u8dd1\u5168\u94fe\u8def": "operator_full_demo",
            "\u524d\u53f0\u89c6\u89d2\u4eca\u65e5\u4efb\u52a1": "frontdesk_today_tasks",
            "\u81ea\u67e5\u5b9a\u65f6\u4efb\u52a1\u548c\u7f51\u5173": "self_check",
        }
        for message, expected_intent in cases.items():
            with self.subTest(message=message):
                result = route_feishu_command(message, role="operator")
                self.assertEqual(result["intent"], expected_intent)
                self.assertNotEqual(result["intent"], "menu")
                self.assertFalse(result["live_allowed"])
                self.assertFalse(result["approval_data_allowed"])

    def test_review_publish_and_self_check_are_truthful_and_blocked(self) -> None:
        publish = route_feishu_command("\u76f4\u63a5\u53d1\u5e03\u8bc4\u8bba\u5230 OTA", role="admin")
        self.assertEqual(publish["intent"], "review_publish_request")
        self.assertEqual(publish["status"], "blocked")
        self.assertFalse(publish["publish_attempted"])
        self.assertFalse(publish["formal_approval_created"])
        self.assertFalse(publish["live_allowed"])

        self_check = route_feishu_command("\u81ea\u67e5 cron gateway openclaw", role="operator")
        self.assertEqual(self_check["intent"], "self_check")
        self.assertIn("cron_diagnostics", self_check)
        self.assertEqual(self_check["cron_diagnostics"]["cron_status"], "unknown")
        self.assertFalse(self_check["cron_diagnostics"]["success_claimed"])


if __name__ == "__main__":
    unittest.main()

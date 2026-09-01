from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.feishu_command_router import safe_route_feishu_command


class TestFeishuMultiIntent(unittest.TestCase):
    def test_multiple_numeric_menu_items_are_not_routed_to_plain_menu(self) -> None:
        result = safe_route_feishu_command("12 13 14", role="operator", trusted_runtime_role=True, render=True)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intent"], "multi_intent_summary")
        self.assertEqual(result["requested_intents"], ["12", "13", "14"])
        self.assertEqual(len(result["sub_results"]), 3)
        self.assertNotEqual(result["runtime_command"], "menu")
        self.assertIn("send_payload", result)

    def test_multi_intent_keeps_partial_results_when_one_sub_intent_fails(self) -> None:
        original = safe_route_feishu_command

        def fake_safe(message: str, **kwargs):
            if message == "13":
                raise RuntimeError("simulated route failure")
            return original(message, **kwargs)

        with patch("runtime.feishu_command_router.safe_route_feishu_command", side_effect=fake_safe):
            result = original("12 13 14", role="operator", trusted_runtime_role=True, render=True)

        self.assertEqual(result["intent"], "multi_intent_summary")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["sub_results"]), 3)
        self.assertIn("error", {item["status"] for item in result["sub_results"]})

    def test_multi_intent_parent_is_blocked_when_all_children_blocked(self) -> None:
        result = safe_route_feishu_command("12 13 14", role="guest", render=True)

        self.assertEqual(result["intent"], "multi_intent_summary")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "all_sub_intents_blocked")
        self.assertEqual({item["status"] for item in result["sub_results"]}, {"blocked"})
        self.assertIn("send_payload", result)

    def test_too_many_numeric_menu_items_are_rejected_safely(self) -> None:
        result = safe_route_feishu_command("1 2 3 4", role="operator", render=True)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["intent"], "multi_intent_too_many")
        self.assertIn("send_payload", result)

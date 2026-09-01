from __future__ import annotations

import unittest

import runtime  # noqa: F401 - installs runtime patches
from runtime import feishu_command_router as router
from runtime.decisions import command_menu
from runtime.decisions.customer import render_s17_summary


class TestS17FeishuRuntimePatch(unittest.TestCase):
    def test_short_and_natural_language_routes_are_formal(self) -> None:
        self.assertEqual(router._detect_intent("S17"), "customer_analysis")
        self.assertEqual(router._detect_intent("客户订单分析"), "customer_analysis")
        self.assertEqual(router._detect_intent("客户与订单结构分析"), "customer_analysis")
        self.assertEqual(router._detect_intent("客户/订单聚合分析"), "customer_analysis")

    def test_explicit_demo_remains_separate(self) -> None:
        self.assertEqual(router._detect_intent("S17 演示"), "customer_analysis_demo")

    def test_numeric_and_stateful_menus_use_14(self) -> None:
        self.assertEqual(router.NUMERIC_MENU_INTENTS["14"], "customer_analysis")
        self.assertIn("14", command_menu.COMMAND_BY_ID)
        self.assertNotIn("9", command_menu.COMMAND_BY_ID)
        self.assertEqual(command_menu._parse_reply("9"), ("14", []))

    def test_masked_contact_is_failure_closed(self) -> None:
        summary = render_s17_summary(
            {
                "populations": {
                    "pms_booking_created": {
                        "created_order_count": 1,
                        "booked_rooms": 1,
                        "current_cancelled_orders": 0,
                        "current_non_cancelled_orders": 1,
                        "contact_proxy": {
                            "status": "unavailable",
                            "reason": "contact_semantic_unavailable_or_masked",
                        },
                    }
                },
                "data_gaps": ["contact_semantic_unavailable_or_masked"],
            }
        )
        self.assertIn("脱敏值或字段语义不适用", summary)
        self.assertIn("不是普通的小样本隐私抑制", summary)
        self.assertNotIn("数据缺口：contact_semantic_unavailable_or_masked", summary)


if __name__ == "__main__":
    unittest.main()

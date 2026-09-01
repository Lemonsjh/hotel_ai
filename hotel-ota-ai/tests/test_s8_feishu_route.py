from __future__ import annotations

import unittest

from runtime import feishu_command_router as router
from runtime.p0_route_ownership_patch import _render_s8_display_text


class S8FeishuRouteTests(unittest.TestCase):
    def test_display_phrases_route_to_s8_without_hijacking_s10_or_s11(self) -> None:
        for message in (
            "推广通",
            "查看推广通数据",
            "推广通近30天表现",
            "推广近30天表现",
            "当前推广通快照",
        ):
            with self.subTest(message=message):
                self.assertEqual(router._detect_intent(message), "s8_promotion_display")

        self.assertEqual(router._detect_intent("推广建议"), "promotion_suggestion")
        self.assertEqual(router._detect_intent("推广值不值"), "roi_decision")
        self.assertNotEqual(router._detect_intent("打开推广通"), "s8_promotion_display")
        self.assertIn("s8_promotion_display", router.PROTECTED_BUSINESS_INTENTS)

    def test_s8_route_dispatches_display_only_runtime(self) -> None:
        original_capture = router._capture_runtime_emit

        def fake_capture(callback, args):
            return {
                "status": "ok",
                "skill_id": "S8",
                "summary": "已读取并展示推广通近30天数据，共 1 个投放单元。",
                "evidence": {
                    "promotion_display": {
                        "status": "ok",
                        "source_status": "ok",
                        "source_table": "meituan_ota_promotion_performance_30d",
                        "data_business_date": "2026-08-07",
                        "data_snapshot_time": "2026-08-07 13:30:00",
                        "period_start_date": "2026-07-09",
                        "period_end_date": "2026-08-07",
                        "item_count": 1,
                        "items": [],
                    }
                },
                "recommendations": [],
                "actions": [],
                "write_performed": False,
                "live_allowed": False,
            }

        router._capture_runtime_emit = fake_capture
        try:
            result = router.route_feishu_command(
                "查看推广通数据",
                role="owner",
                hotel_id="puyue",
                render=False,
            )
        finally:
            router._capture_runtime_emit = original_capture

        self.assertEqual(result["intent"], "s8_promotion_display")
        self.assertEqual(result["skill_id"], "S8")
        self.assertEqual(result["node_id"], "N012")
        self.assertEqual(result["runtime_command"], "promotion-plan --display-only")
        self.assertEqual(result["data_source_type"], "mysql_db")
        self.assertTrue(result["business_result_generated"])
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["formal_approval_allowed"])
        self.assertFalse(result["live_allowed"])
        self.assertFalse(result["write_performed"])
        self.assertNotEqual(result.get("skill_id"), "S11")

    def test_s8_text_is_display_only_and_uses_business_names(self) -> None:
        text = _render_s8_display_text(
            {
                "intent": "s8_promotion_display",
                "skill_id": "S8",
                "evidence": {
                    "promotion_display": {
                        "source_status": "ok",
                        "source_table": "meituan_ota_promotion_performance_30d",
                        "data_snapshot_time": "2026-08-07 13:30:00",
                        "period_start_date": "2026-07-09",
                        "period_end_date": "2026-08-07",
                        "items": [
                            {
                                "plan_name": "暑期推广计划",
                                "launch_name": "周末投放单元",
                                "promotion_name": "推广通",
                                "spend_amount": 100,
                                "cash_spend_amount": 80,
                                "exposure_count": 1000,
                                "click_count": 100,
                                "booking_order_count": 10,
                                "room_night_count": 12,
                                "booking_order_amount": 1200,
                                "cost_per_booking": 10,
                                "cost_per_room_night": 8.3333,
                                "average_booking_order_amount": 120,
                                "promotion_adr": 100,
                                "roas": 12,
                                "cash_roas": 15,
                                "booking_conversion_rate_pct": 10,
                                "promotion_amount_after_spend": 1100,
                                "click_rate_pct": 10,
                            }
                        ],
                    }
                },
            }
        )

        self.assertIn("推广计划：暑期推广计划", text)
        self.assertIn("投放单元：周末投放单元", text)
        self.assertIn("推广产品：推广通", text)
        self.assertIn("ROAS 12", text)
        self.assertIn("点击率（来源值）10.00%", text)
        self.assertIn("不生成建议、审批、任务或执行动作", text)
        self.assertNotIn("建议：", text)


if __name__ == "__main__":
    unittest.main()

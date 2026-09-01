from __future__ import annotations

import unittest

from runtime.algorithms.s08_promotion_display import (
    NOT_COMPUTABLE,
    build_s8_promotion_display,
)


class TestS8PromotionDisplay(unittest.TestCase):
    def test_builds_display_metrics_from_only_the_source_row(self) -> None:
        result = build_s8_promotion_display(
            {
                "status": "ok",
                "payload": {
                    "source_status": "ok",
                    "source_table": "meituan_ota_promotion_performance_30d",
                    "data_business_date": "2026-08-06",
                    "data_snapshot_time": "2026-08-07 09:30:00",
                    "rows": [
                        {
                            "plan_id": "plan-1",
                            "plan_name": "计划A",
                            "launch_id": "launch-1",
                            "launch_name": "单元A",
                            "promotion_name": "推广通",
                            "period_start_date": "2026-07-08",
                            "period_end_date": "2026-08-06",
                            "snapshot_time": "2026-08-07 09:30:00",
                            "spend_amount": 1000,
                            "cash_spend_amount": 800,
                            "exposure_count": 10000,
                            "click_count": 500,
                            "booking_order_count": 25,
                            "room_night_count": 30,
                            "booking_order_amount": 6000,
                            "click_rate_pct": 5,
                            "cost_per_click": 2,
                        }
                    ],
                },
            }
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["item_count"], 1)
        self.assertEqual(result["period_start_date"], "2026-07-08")
        self.assertEqual(result["period_end_date"], "2026-08-06")
        item = result["items"][0]
        self.assertEqual(item["cost_per_booking"], 40.0)
        self.assertEqual(item["cost_per_room_night"], 33.3333)
        self.assertEqual(item["average_booking_order_amount"], 240.0)
        self.assertEqual(item["promotion_adr"], 200.0)
        self.assertEqual(item["roas"], 6.0)
        self.assertEqual(item["promotion_amount_after_spend"], 5000.0)
        self.assertEqual(item["cash_roas"], 7.5)
        self.assertEqual(item["booking_conversion_rate_pct"], 5.0)

    def test_zero_denominators_are_not_computable(self) -> None:
        result = build_s8_promotion_display(
            {
                "status": "ok",
                "payload": {
                    "source_status": "ok",
                    "rows": [
                        {
                            "spend_amount": 0,
                            "cash_spend_amount": 0,
                            "click_count": 0,
                            "booking_order_count": 0,
                            "room_night_count": 0,
                            "booking_order_amount": 0,
                        }
                    ],
                },
            }
        )

        item = result["items"][0]
        self.assertEqual(item["cost_per_booking"], NOT_COMPUTABLE)
        self.assertEqual(item["cost_per_room_night"], NOT_COMPUTABLE)
        self.assertEqual(item["average_booking_order_amount"], NOT_COMPUTABLE)
        self.assertEqual(item["promotion_adr"], NOT_COMPUTABLE)
        self.assertEqual(item["roas"], NOT_COMPUTABLE)
        self.assertEqual(item["cash_roas"], NOT_COMPUTABLE)
        self.assertEqual(item["booking_conversion_rate_pct"], NOT_COMPUTABLE)
        self.assertEqual(item["promotion_amount_after_spend"], 0.0)

    def test_does_not_create_status_planning_or_action_fields(self) -> None:
        result = build_s8_promotion_display(
            {
                "status": "ok",
                "payload": {
                    "source_status": "ok",
                    "rows": [
                        {
                            "plan_name": "计划A",
                            "promotion_status": "RUNNING",
                            "budget_recommendation": 2000,
                            "promotion_action": "increase",
                        }
                    ],
                },
            }
        )

        item = result["items"][0]
        self.assertNotIn("promotion_status", item)
        self.assertNotIn("budget_recommendation", item)
        self.assertNotIn("promotion_action", item)
        self.assertNotIn("recommendations", result)
        self.assertNotIn("actions", result)

    def test_propagates_source_data_gap_without_items(self) -> None:
        result = build_s8_promotion_display(
            {
                "status": "data_gap",
                "reason": "source_query_failed",
                "payload": {
                    "source_status": "unavailable",
                    "source_table": "meituan_ota_promotion_performance_30d",
                    "rows": [],
                },
            }
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["reason"], "source_query_failed")
        self.assertEqual(result["item_count"], 0)
        self.assertEqual(result["items"], [])


if __name__ == "__main__":
    unittest.main()

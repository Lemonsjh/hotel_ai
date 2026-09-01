from __future__ import annotations

import unittest

from runtime.sales_progress.deviation_service import _capacity_line, _target_line
from runtime.sales_progress.metrics import (
    build_gross_booking_context,
    build_hour_distribution_context,
    build_peer_demand_context,
)
from runtime.sales_progress.service import build_deviation


class SalesProgressContextTests(unittest.TestCase):
    def test_gross_booking_curve_is_diagnostic_only(self) -> None:
        result = build_gross_booking_context(
            [
                {
                    "stay_date": "2026-08-01",
                    "booking_hour": 9,
                    "gross_created_rooms": 3,
                    "booking_rows": 2,
                }
            ]
        )
        self.assertEqual(result["status"], "available")
        self.assertEqual(
            result["usage"], "diagnostic_only_not_committed_sold"
        )
        self.assertFalse(result["cancellation_timeline_validated"])

    def test_userprofile_hour_distribution_is_context_only(self) -> None:
        result = build_hour_distribution_context(
            [
                {"bucket_label": f"{hour:02d}:00", "rate_pct": 25}
                for hour in range(4)
            ]
        )
        self.assertEqual(result["status"], "available")
        self.assertTrue(result["rate_total_valid"])
        self.assertIn("committed_sold", result["not_valid_for"])

    def test_competition_window_never_infers_market_total(self) -> None:
        result = build_peer_demand_context(
            [
                {
                    "metric_code": "booking_order_count",
                    "metric_name": "预订订单数",
                    "metric_unit": "order",
                    "period_start_date": "2026-07-01",
                    "period_end_date": "2026-07-30",
                    "hotel_value": 20,
                    "competitor_avg": 30,
                    "competitor_rank": 5,
                    "competition_circle_hotel_count": 10,
                }
            ]
        )
        self.assertEqual(result["usage"], "peer_demand_proxy_only")
        self.assertFalse(result["market_total_inference_allowed"])

    def test_unstable_room_scope_blocks_public_deviation(self) -> None:
        result = build_deviation(
            object(),
            hotel_id="hotel-a",
            target_date="2026-08-08",
            as_of_datetime="2026-08-08 16:00:00",
            baseline={"status": "ok", "expected_room_type_ids": []},
        )
        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(
            result["reason"], "stable_room_type_scope_unavailable"
        )

    def test_capacity_and_target_lines_have_distinct_fields(self) -> None:
        capacity = _capacity_line(
            8, 20, {"median": 0.5, "p25": 0.4, "p80": 0.6}
        )
        target = _target_line(
            8, 16, {"median": 0.6, "p25": 0.5, "p80": 0.7}
        )
        self.assertIn("remaining_capacity_rooms", capacity)
        self.assertNotIn("remaining_target_gap", capacity)
        self.assertIn("remaining_target_gap", target)
        self.assertEqual(target["remaining_target_gap"], 8)
        self.assertIn("checkpoint_room_gap", target)


if __name__ == "__main__":
    unittest.main()

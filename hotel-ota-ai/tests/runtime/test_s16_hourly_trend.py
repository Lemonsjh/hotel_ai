from __future__ import annotations

import unittest

from runtime.algorithms.progress_trend import calculate_progress_trend
from runtime.demo_today_generator import generate_today_demo_dataset


class TestS16HourlyTrend(unittest.TestCase):
    def test_accelerating_pickup_reduces_high_risk_conclusion(self) -> None:
        trend = calculate_progress_trend(
            [
                {"hour": "09:00", "sold_rooms": 10, "target_sold_rooms": 14},
                {"hour": "10:00", "sold_rooms": 13, "target_sold_rooms": 17},
                {"hour": "11:00", "sold_rooms": 17, "target_sold_rooms": 20},
            ]
        )

        self.assertEqual(trend["pickup_speed"], "accelerating")
        self.assertEqual(trend["risk_level"], "medium")
        self.assertGreater(trend["remaining_sales_window"], 0)

    def test_missing_hourly_data_is_partial_not_fabricated(self) -> None:
        trend = calculate_progress_trend([])

        self.assertEqual(trend["status"], "partial")
        self.assertIn("hourly_business_snapshots", trend["missing_fields"])
        self.assertIsNone(trend["pickup_speed"])

    def test_generated_today_demo_contains_hourly_business_snapshots(self) -> None:
        dataset = generate_today_demo_dataset(business_date="2026-06-15", seed=20260615, profile="normal")
        progress = dataset["progress_deviation"]

        self.assertIn("hourly_business_snapshots", progress)
        self.assertGreaterEqual(len(progress["hourly_business_snapshots"]), 6)
        trend = calculate_progress_trend(progress["hourly_business_snapshots"])
        self.assertIn(trend["risk_level"], {"low", "medium", "high"})


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from marketing_diagnosis.db_loader_v4 import _previous_year_date
from marketing_diagnosis.visual_diagnosis_v6 import build_visual_diagnosis


class Jl02BusinessDateYoyTest(unittest.TestCase):
    def test_previous_year_date_handles_same_day_and_leap_day(self):
        self.assertEqual(_previous_year_date("2026-07-14"), "2025-07-14")
        self.assertEqual(_previous_year_date("2024-02-29"), "2023-02-28")

    def test_yoy_uses_business_date_not_snapshot_year(self):
        sections = {
            "hotel_performance_daily": [
                {
                    "business_date": "2025-07-14",
                    "metric_name": "房费",
                    "value_day": 700,
                    "value_month": 7000,
                    "value_year": 80000,
                    "snapshot_time": "2026-07-14 08:00:00",
                },
                {
                    "business_date": "2025-07-14",
                    "metric_name": "房费",
                    "value_day": 800,
                    "value_month": 8000,
                    "value_year": 90000,
                    "snapshot_time": "2026-07-14 09:00:00",
                },
                {
                    "business_date": "2026-07-14",
                    "metric_name": "房费",
                    "value_day": 900,
                    "value_month": 9000,
                    "value_year": 100000,
                    "snapshot_time": "2026-07-14 08:00:00",
                },
                {
                    "business_date": "2026-07-14",
                    "metric_name": "房费",
                    "value_day": 1000,
                    "value_month": 10000,
                    "value_year": 110000,
                    "snapshot_time": "2026-07-14 10:00:00",
                },
                {
                    "business_date": "2025-07-14",
                    "metric_name": "平均房价",
                    "value_day": 120,
                    "value_month": 130,
                    "value_year": 125,
                    "snapshot_time": "2026-07-14 09:00:00",
                },
                {
                    "business_date": "2026-07-14",
                    "metric_name": "平均房价",
                    "value_day": 150,
                    "value_month": 160,
                    "value_year": 155,
                    "snapshot_time": "2026-07-14 10:00:00",
                },
            ]
        }

        result = build_visual_diagnosis(sections)
        item = next(
            value
            for value in result["items"]
            if value["standard_item_id"] == 1
        )
        fields = {value["label"]: value for value in item["fields"]}
        records = {value["metric_name"]: value for value in item["records"]}

        self.assertEqual(fields["本期值"]["value"], 10000)
        self.assertEqual(fields["去年同期值"]["value"], 8000)
        self.assertAlmostEqual(fields["YOY"]["value"], 0.25)
        self.assertIn("2025-07-14", fields["去年同期值"]["note"])
        self.assertEqual(item["item_score"], 10)
        self.assertEqual(records["平均房价"]["previous_value"], 130)
        self.assertEqual(
            item["source_fields"],
            [
                "business_date",
                "metric_name",
                "value_day",
                "value_month",
                "value_year",
                "snapshot_time",
            ],
        )


if __name__ == "__main__":
    unittest.main()

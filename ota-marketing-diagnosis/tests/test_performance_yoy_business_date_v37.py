from __future__ import annotations

import unittest

from marketing_diagnosis.performance_yoy_v37 import patch_performance_yoy
from marketing_diagnosis.reporting_v25 import _performance_card


class PerformanceYoyBusinessDateTests(unittest.TestCase):
    def _result(self):
        return {
            "items": [
                {
                    "standard_item_id": 1,
                    "item_name": "月度经营趋势 YOY",
                    "base_score": 10,
                    "participates_in_score": True,
                    "fields": [],
                    "records": [],
                }
            ]
        }

    def _sections(self):
        return {
            "hotel_performance_daily": [
                {
                    "business_date": "2026-07-15",
                    "category": "总营业指标",
                    "metric_name": "房费",
                    "value_day": 999,
                    "value_month": 10130,
                    "value_year": 99999,
                    "snapshot_time": "2026-07-16 10:00:00",
                },
                {
                    "business_date": "2026-07-15",
                    "category": "门店收入",
                    "metric_name": "房费",
                    "value_day": 4421.65,
                    "value_month": 64868.69,
                    "value_year": 703848.40,
                    "snapshot_time": "2026-07-16 10:00:00",
                },
                {
                    "business_date": "2026-07-15",
                    "category": "总营业指标",
                    "metric_name": "RevPar",
                    "value_day": 142.63,
                    "value_month": 139.50,
                    "value_year": 115.84,
                    "snapshot_time": "2026-07-16 10:00:00",
                },
                {
                    "business_date": "2025-07-15",
                    "category": "总营业指标",
                    "metric_name": "房费",
                    "value_day": 500,
                    "value_month": 10130,
                    "value_year": 100000,
                    "snapshot_time": "2026-07-16 10:00:00",
                },
                {
                    "business_date": "2025-07-15",
                    "category": "门店收入",
                    "metric_name": "房费",
                    "value_day": 4007.22,
                    "value_month": 62616.49,
                    "value_year": 780581.21,
                    "snapshot_time": "2026-07-16 10:00:00",
                },
                {
                    "business_date": "2025-07-15",
                    "category": "总营业指标",
                    "metric_name": "RevPar",
                    "value_day": 129.27,
                    "value_month": 134.66,
                    "value_year": 128.47,
                    "snapshot_time": "2026-07-16 10:00:00",
                },
            ]
        }

    def test_headline_revenue_uses_store_income_category(self):
        result = self._result()
        patch_performance_yoy(result, self._sections())
        item = result["items"][0]
        fields = {field["label"]: field["value"] for field in item["fields"]}

        self.assertEqual(fields["本期本月值"], 64868.69)
        self.assertEqual(fields["去年本月值"], 62616.49)
        self.assertAlmostEqual(fields["本月YOY"], 62616.49 / 64868.69)
        self.assertNotEqual(fields["去年本月值"], 10130)

    def test_records_split_prior_day_month_year_and_yoy(self):
        result = self._result()
        patch_performance_yoy(result, self._sections())
        item = result["items"][0]
        revenue = next(
            record
            for record in item["records"]
            if record["category"] == "门店收入" and record["metric_name"] == "房费"
        )

        self.assertEqual(revenue["previous_value_day"], 4007.22)
        self.assertEqual(revenue["previous_value_month"], 62616.49)
        self.assertEqual(revenue["previous_value_year"], 780581.21)
        self.assertAlmostEqual(revenue["yoy_day"], 4007.22 / 4421.65)
        self.assertAlmostEqual(revenue["yoy_month"], 62616.49 / 64868.69)
        self.assertAlmostEqual(revenue["yoy_year"], 780581.21 / 703848.40)

    def test_report_has_all_three_prior_periods_and_yoy_columns(self):
        result = self._result()
        patch_performance_yoy(result, self._sections())
        html = _performance_card(result["items"][0])

        for header in (
            "去年本日",
            "本日YOY",
            "去年本月",
            "本月YOY",
            "去年本年",
            "本年YOY",
        ):
            self.assertIn(f"<th>{header}</th>", html)
        self.assertIn("门店收入", html)
        self.assertIn("96.53%", html)
        self.assertIn("YOY＝去年同期÷今年同期", html)


if __name__ == "__main__":
    unittest.main()

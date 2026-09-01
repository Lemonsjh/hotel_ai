from __future__ import annotations

import unittest

from marketing_diagnosis.performance_yoy_v40 import METRIC_ORDER, patch_performance_yoy
from marketing_diagnosis.reporting_v28 import _records_table


class PerformanceTotalMetricsTests(unittest.TestCase):
    def _result(self):
        return {
            "items": [
                {
                    "standard_item_id": 1,
                    "item_name": "月度经营趋势 YOY",
                    "base_score": 10,
                    "data_status": "success",
                    "score_ratio": 1,
                    "item_score": 10,
                    "fields": [],
                }
            ]
        }

    def _row(self, day, metric, daily, monthly, yearly, category="总营业指标", snapshot="2026-07-16 08:00:00"):
        return {
            "business_date": day,
            "category": category,
            "metric_name": metric,
            "room_type_id": None,
            "value_day": daily,
            "value_month": monthly,
            "value_year": yearly,
            "snapshot_time": snapshot,
        }

    def test_uses_exact_dates_total_category_and_fixed_order(self):
        rows = []
        for index, metric in enumerate(METRIC_ORDER, start=1):
            rows.append(self._row("2026-07-16", metric, index, index * 10, index * 100))
            rows.append(self._row("2025-07-16", metric, index / 2, index * 5, index * 50, snapshot="2025-07-16 08:00:00"))

        # These rows must never appear in the customer table.
        rows.append(self._row("2026-07-16", "小计", 999, 999, 999))
        rows.append(self._row("2026-07-16", "房费", 888, 888, 888, category="门店收入"))
        rows.append(self._row("2025-07-15", "房费", 777, 777, 777))

        result = self._result()
        patch_performance_yoy(result, {"hotel_performance_daily": rows})
        item = result["items"][0]

        self.assertEqual([record["metric_name"] for record in item["records"]], list(METRIC_ORDER))
        self.assertEqual(item["fields"][0]["value"], "2026-07-16")
        self.assertEqual(item["fields"][1]["value"], "2025-07-16")
        revenue = next(record for record in item["records"] if record["metric_name"] == "房费")
        self.assertEqual(revenue["value_day"], 7)
        self.assertEqual(revenue["previous_value_day"], 3.5)
        self.assertAlmostEqual(revenue["yoy_day"], 0.5)
        self.assertEqual(revenue["value_month"], 70)
        self.assertEqual(revenue["previous_value_month"], 35)
        self.assertEqual(revenue["value_year"], 700)
        self.assertEqual(revenue["previous_value_year"], 350)

    def test_report_uses_daily_monthly_yearly_wording(self):
        item = self._result()["items"][0]
        item["records"] = [
            {
                "metric_name": "房费",
                "value_day": 4000,
                "previous_value_day": 3500,
                "yoy_day": 0.875,
                "value_month": 62616.49,
                "previous_value_month": 60000,
                "yoy_month": 0.9582,
                "value_year": 780581.21,
                "previous_value_year": 700000,
                "yoy_year": 0.8968,
            }
        ]
        html = _records_table(item)
        for header in (
            "日度",
            "同期日度",
            "日度YOY",
            "月度",
            "同期月度",
            "月度YOY",
            "年度",
            "同期年度",
            "年度YOY",
        ):
            self.assertIn(f"<th>{header}</th>", html)
        self.assertNotIn("去年本月", html)
        self.assertNotIn("本年YOY", html)


if __name__ == "__main__":
    unittest.main()

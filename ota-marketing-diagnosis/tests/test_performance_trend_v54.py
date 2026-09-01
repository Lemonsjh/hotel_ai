from __future__ import annotations

import unittest

from marketing_diagnosis.performance_trend_v54 import (
    _growth,
    build_performance_trend_periods,
)
from marketing_diagnosis.reporting_v37 import _detail_table, _performance_card


class PerformanceTrendV54Tests(unittest.TestCase):
    def _row(
        self,
        day: str,
        metric: str,
        value: float,
        *,
        category: str = "总营业指标",
        room_type_id=None,
    ) -> dict:
        return {
            "business_date": day,
            "category": category,
            "room_type_id": room_type_id,
            "metric_name": metric,
            "value_month": value,
            "snapshot_time": f"{day} 23:59:59",
        }

    def _rows(self) -> list[dict]:
        rows: list[dict] = []
        values = {
            "2026-05-31": {
                "房费": 129151.87,
                "平均房价": 152.57,
                "出租率": 88.09,
                "RevPar": 134.39,
            },
            "2025-05-31": {
                "房费": 136778.15,
                "平均房价": 175.69,
                "出租率": 81.01,
                "RevPar": 142.33,
            },
            "2026-06-30": {
                "房费": 113032.47,
                "平均房价": 139.89,
                "出租率": 86.88,
                "RevPar": 121.54,
            },
            "2025-06-30": {
                "房费": 121477.24,
                "平均房价": 149.79,
                "出租率": 87.20,
                "RevPar": 130.62,
            },
            "2026-07-16": {
                "房费": 69076.50,
                "平均房价": 148.23,
                "出租率": 93.95,
                "RevPar": 139.27,
            },
            "2025-07-16": {
                "房费": 66719.96,
                "平均房价": 156.25,
                "出租率": 86.09,
                "RevPar": 134.52,
            },
        }
        for day, metrics in values.items():
            for metric, value in metrics.items():
                rows.append(self._row(day, metric, value))

        # These rows must be ignored even though their dates and metrics match.
        rows.append(self._row("2026-07-16", "房费", 999999, category="门店收入"))
        rows.append(self._row("2026-07-16", "平均房价", 999, room_type_id="ROOM-1"))
        return rows

    def test_reads_direct_value_month_from_total_operating_metrics_only(self):
        periods = build_performance_trend_periods(self._rows(), "2026-07-16")
        self.assertEqual(len(periods), 3)
        self.assertEqual(periods[0]["current_range"], "2026/05/01—2026/05/31")
        self.assertEqual(periods[1]["current_range"], "2026/06/01—2026/06/30")
        self.assertEqual(periods[2]["current_range"], "2026/07/01—2026/07/16")

        july = periods[2]
        revenue = next(metric for metric in july["metrics"] if metric["key"] == "revenue")
        adr = next(metric for metric in july["metrics"] if metric["key"] == "adr")
        self.assertEqual(revenue["current"], 69076.50)
        self.assertEqual(revenue["previous"], 66719.96)
        self.assertAlmostEqual(
            revenue["yoy"],
            (69076.50 - 66719.96) / 66719.96,
        )
        self.assertEqual(adr["current"], 148.23)
        self.assertNotEqual(revenue["current"], 999999)
        self.assertNotEqual(adr["current"], 999)

    def test_yoy_growth_uses_difference_divided_by_prior_year(self):
        self.assertAlmostEqual(_growth(120, 100), 0.20)
        self.assertAlmostEqual(_growth(80, 100), -0.20)
        self.assertEqual(_growth(100, 100), 0.0)
        self.assertIsNone(_growth(100, 0))
        self.assertIsNone(_growth(None, 100))

    def test_each_metric_header_is_one_cell_like_the_sample(self):
        periods = build_performance_trend_periods(self._rows(), "2026-07-16")
        html = _detail_table(periods)

        for label in ("ADR", "出租率", "RevPAR", "房费（元）"):
            expected = (
                f"<th><strong>{label}</strong>"
                "<span>本期 / 去年同期</span><em>YOY</em></th>"
            )
            self.assertIn(expected, html)

        self.assertEqual(html.count("<span>本期 / 去年同期</span>"), 4)
        self.assertEqual(html.count("<em>YOY</em>"), 4)
        self.assertNotIn("<th>指标名称</th>", html)
        self.assertNotIn("<th>本期 / 去年同期</th>", html)
        self.assertNotIn("<th>YOY</th>", html)
        self.assertIn("2026/05/01—2026/05/31", html)
        self.assertIn("129,151.87", html)
        self.assertIn("136,778.15", html)
        self.assertIn("↓ -5.58%", html)

    def test_chart_dropdown_only_controls_chart_and_table_keeps_all_metrics(self):
        periods = build_performance_trend_periods(self._rows(), "2026-07-16")
        item = {
            "standard_item_id": 1,
            "item_name": "月度经营趋势 YOY",
            "base_score": 10,
            "item_score": 8,
            "data_status": "success",
            "trend_periods": periods,
        }
        html = _performance_card(item)
        self.assertIn("performance-select-v54", html)
        self.assertIn("value='revenue'>房费</option>", html)
        self.assertIn("value='adr'>ADR</option>", html)
        self.assertIn("value='occupancy'>出租率</option>", html)
        self.assertIn("value='revpar'>RevPAR</option>", html)
        self.assertIn("performance-detail-table-v54", html)
        self.assertEqual(html.count("<span>本期 / 去年同期</span>"), 4)
        self.assertIn("指标直接读取总营业指标", html)


if __name__ == "__main__":
    unittest.main()

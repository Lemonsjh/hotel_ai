from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v24 import _information_card, _information_points
from marketing_diagnosis.visual_diagnosis_v15 import _information_daily_records


class InformationScoreHosLayoutTests(unittest.TestCase):
    def test_information_history_deduplicates_days_and_keeps_latest_snapshot(self):
        records = _information_daily_records(
            {
                "ota_funnel": [
                    {
                        "platform": "meituan",
                        "period_type": "日",
                        "business_date": "2026-07-14",
                        "snapshot_time": "2026-07-14 09:00:00",
                        "content_score": 90,
                    },
                    {
                        "platform": "meituan",
                        "period_type": "日",
                        "business_date": "2026-07-14",
                        "snapshot_time": "2026-07-14 18:00:00",
                        "content_score": 95,
                    },
                    {
                        "platform": "meituan",
                        "period_type": "日",
                        "business_date": "2026-07-15",
                        "snapshot_time": "2026-07-15 18:00:00",
                        "content_score": 107,
                    },
                ]
            }
        )
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["content_score"], 95)
        self.assertEqual(records[1]["content_score"], 107)

    def test_information_points_preserve_real_zero(self):
        points = _information_points(
            {
                "daily_records": [
                    {"business_date": "2026-07-14", "content_score": 0},
                    {"business_date": "2026-07-15", "content_score": 107},
                ]
            }
        )
        self.assertEqual(points[0]["value"], 0)
        self.assertEqual(points[1]["value"], 107)

    def test_information_card_matches_hos_layout_structure(self):
        item = {
            "standard_item_id": 8,
            "item_name": "信息分数据",
            "base_score": 5,
            "participates_in_score": True,
            "data_status": "success",
            "item_score": 5,
            "source_table": "hotel_puyue.meituan_ota_business_metrics",
            "source_fields": ["metric_name=信息分", "metric_value", "business_date"],
            "daily_records": [
                {"business_date": "2026-07-11", "content_score": 102},
                {"business_date": "2026-07-12", "content_score": 103},
                {"business_date": "2026-07-13", "content_score": 104},
                {"business_date": "2026-07-14", "content_score": 106},
                {"business_date": "2026-07-15", "content_score": 107},
            ],
            "fields": [
                {"label": "展示范围", "value": "2026-07-11 至 2026-07-15"},
                {"label": "是否有信息分", "value": "有"},
                {"label": "有效数据天数", "value": 5},
                {"label": "近30天平均分", "value": 104.4},
                {"label": "最新信息分", "value": 107},
            ],
        }
        html = _information_card(item)
        for text in (
            "最多近30天 信息分趋势",
            "统计结果",
            "起始日期",
            "截止日期",
            "是否有信息分",
            "有效数据天数",
            "最新信息分",
            "近30天平均分",
            "2026-07-11",
            "2026-07-15",
            "107.00",
        ):
            self.assertIn(text, html)
        self.assertIn("hos-v2-layout", html)
        self.assertIn("info-v24-point", html)
        self.assertIn("5分", html)


if __name__ == "__main__":
    unittest.main()

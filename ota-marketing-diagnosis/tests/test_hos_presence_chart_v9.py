from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v12 import _hos_card
from marketing_diagnosis.visual_diagnosis_v5 import build_visual_diagnosis


class HosPresenceChartTest(unittest.TestCase):
    def test_hos_presence_gets_full_score(self):
        sections = {
            "ota_funnel": [
                {
                    "platform": "meituan",
                    "period_type": "日",
                    "business_date": "2026-07-11",
                    "hos_score": 5.6,
                    "hos_score_rank": 2,
                    "snapshot_time": "2026-07-11 12:00:00",
                },
                {
                    "platform": "meituan",
                    "period_type": "日",
                    "business_date": "2026-07-12",
                    "hos_score": 5.6,
                    "hos_score_rank": 2,
                    "snapshot_time": "2026-07-12 12:00:00",
                },
            ]
        }
        result = build_visual_diagnosis(sections)
        item = next(value for value in result["items"] if value["standard_item_id"] == 6)
        fields = {value["label"]: value["value"] for value in item["fields"]}

        self.assertEqual(item["item_score"], 3.0)
        self.assertEqual(item["score_ratio"], 1.0)
        self.assertEqual(fields["是否有HOS评分"], "有")
        self.assertEqual(fields["有效评分天数"], 2)

        html = _hos_card(item)
        self.assertIn("起始日期", html)
        self.assertIn("截止日期", html)
        self.assertIn("hos-v2-axis-label", html)
        self.assertIn("hos-v2-tooltip", html)
        self.assertIn("data-value='5.60'", html)
        self.assertIn("已有评分", html)

    def test_meituan_data_without_hos_score_gets_zero(self):
        sections = {
            "ota_funnel": [
                {
                    "platform": "meituan",
                    "period_type": "日",
                    "business_date": "2026-07-11",
                    "views": 100,
                }
            ]
        }
        result = build_visual_diagnosis(sections)
        item = next(value for value in result["items"] if value["standard_item_id"] == 6)
        fields = {value["label"]: value["value"] for value in item["fields"]}

        self.assertEqual(item["item_score"], 0.0)
        self.assertEqual(item["data_status"], "zero")
        self.assertEqual(fields["是否有HOS评分"], "无")


if __name__ == "__main__":
    unittest.main()

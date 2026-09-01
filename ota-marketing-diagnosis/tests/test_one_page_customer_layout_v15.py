from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v14 import (
    _exposure_content,
    _summary_collapsible,
    _user_source_content,
)


class OnePageCustomerLayoutTest(unittest.TestCase):
    def test_exposure_chart_uses_existing_ratio_value(self):
        item = {
            "fields": [
                {"label": "整体曝光（近30天）", "value": 62019},
                {"label": "非广告曝光", "value": 56469},
                {"label": "广告曝光", "value": 5550},
                {"label": "广告曝光占比", "value": 0.08949},
            ]
        }
        content = _exposure_content(item)
        self.assertIn("8.95%", content)
        self.assertIn("62,019.00", content)
        self.assertIn("conic-gradient", content)

    def test_user_source_chart_keeps_all_existing_values(self):
        item = {
            "fields": [
                {"label": "统计月份", "value": "2026-07"},
                {"label": "本地占比", "value": 0.6169},
                {"label": "异地占比", "value": 0.3831},
                {"label": "新客占比", "value": 0.5806},
                {"label": "老客占比", "value": 0.4194},
            ]
        }
        content = _user_source_content(item)
        for expected in ("2026-07", "61.69%", "38.31%", "58.06%", "41.94%"):
            self.assertIn(expected, content)
        self.assertIn("地域来源", content)
        self.assertIn("新老客户结构", content)

    def test_summary_is_collapsed_and_omits_database_source(self):
        result = {
            "visual_diagnosis": {
                "items": [
                    {
                        "standard_item_id": 1,
                        "item_name": "月度经营趋势 YOY",
                        "base_score": 10,
                        "item_score": 8,
                        "participates_in_score": True,
                        "data_status": "success",
                        "source_table": "hotel_puyue.jl02_hotel_performance_daily",
                    },
                    {
                        "standard_item_id": 5,
                        "item_name": "用户来源数据",
                        "base_score": 0,
                        "item_score": None,
                        "participates_in_score": False,
                        "data_status": "success",
                        "source_table": "hotel_puyue.meituan_ota_user_source_monthly",
                    },
                ]
            }
        }
        content = _summary_collapsible(result)
        self.assertIn("<details id='summary'", content)
        self.assertNotIn("<details id='summary' open", content)
        self.assertIn("<th>诊断内容</th>", content)
        self.assertNotIn("数据库来源", content)
        self.assertNotIn("hotel_puyue.", content)
        self.assertIn("仅展示", content)


if __name__ == "__main__":
    unittest.main()

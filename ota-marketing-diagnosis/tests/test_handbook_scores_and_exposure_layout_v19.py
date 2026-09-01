from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v16 import _exposure_content
from marketing_diagnosis.visual_diagnosis_v9 import (
    _patch_joined_rights_score,
    _patch_review_score,
    _patch_room_name_score,
    _patch_scan_order_score,
    _recalculate_totals,
)


def item(number, base, fields):
    return {
        "standard_item_id": number,
        "item_name": f"item-{number}",
        "base_score": base,
        "participates_in_score": True,
        "data_status": "pending_rule",
        "score_ratio": None,
        "item_score": None,
        "fields": fields,
    }


class HandbookScoreTest(unittest.TestCase):
    def test_items_7_11_13_14_receive_documented_scores(self):
        result = {
            "items": [
                item(7, 8, [{"label": "月扫码订单", "value": 162}]),
                item(
                    11,
                    4,
                    [
                        {"label": "独享·电竞单人间", "value": 8},
                        {"label": "乐享·亲子三人间", "value": 8},
                        {"label": "汇赢·麻将双床房", "value": 8},
                    ],
                ),
                item(
                    13,
                    10,
                    [
                        {"label": "美团评分", "value": 4.8},
                        {"label": "大众点评评分", "value": 4.3},
                    ],
                ),
                item(
                    14,
                    4,
                    [
                        {"label": "已报名权益数量", "value": 5},
                        {"label": "延迟退房", "value": "全部房型生效"},
                    ],
                ),
            ]
        }

        _patch_scan_order_score(result)
        _patch_room_name_score(result)
        _patch_review_score(result)
        _patch_joined_rights_score(result)
        _recalculate_totals(result)

        scores = {
            row["standard_item_id"]: row["item_score"]
            for row in result["items"]
        }
        self.assertEqual(scores[7], 8.0)
        self.assertEqual(scores[11], 4.0)
        self.assertEqual(scores[13], 8.0)
        self.assertEqual(scores[14], 2.4)
        self.assertEqual(result["raw_score"], 22.4)
        self.assertEqual(result["connected_base_score"], 26.0)

    def test_undefined_scan_order_interval_stays_pending(self):
        result = {"items": [item(7, 8, [{"label": "月扫码订单", "value": 120}])]}
        _patch_scan_order_score(result)
        self.assertIsNone(result["items"][0]["item_score"])
        self.assertEqual(result["items"][0]["data_status"], "pending_rule")


class ExposureLayoutTest(unittest.TestCase):
    def test_four_metrics_use_two_by_two_grid_with_donut(self):
        html = _exposure_content(
            {
                "fields": [
                    {"label": "整体曝光（近30天）", "value": 61169},
                    {"label": "非广告曝光", "value": 55619},
                    {"label": "广告曝光", "value": 5550},
                    {"label": "广告曝光占比", "value": 0.0907},
                ]
            }
        )
        self.assertIn("exposure-metrics-v16", html)
        self.assertEqual(html.count("exposure-metric-v16"), 4)
        self.assertIn("9.07%", html)
        self.assertIn("exposure-donut-ring-v16", html)


if __name__ == "__main__":
    unittest.main()

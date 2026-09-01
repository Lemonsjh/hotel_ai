from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v19 import _manual_crown_card
from marketing_diagnosis.visual_diagnosis_v12 import (
    _patch_flow_score,
    _patch_promotion_score,
    _patch_room_name_score,
)


def _item(number: int, base: float, fields: list[dict] | None = None) -> dict:
    return {
        "standard_item_id": number,
        "item_name": f"item-{number}",
        "base_score": base,
        "participates_in_score": True,
        "data_status": "pending_rule",
        "score_ratio": None,
        "item_score": None,
        "fields": fields or [],
    }


class FinalRequiredScoresTest(unittest.TestCase):
    def test_flow_scores_when_daily_data_exists(self) -> None:
        result = {"items": [_item(4, 15)]}
        sections = {
            "ota_funnel": [
                {
                    "platform": "meituan",
                    "period_type": "日",
                    "business_date": "2026-07-14",
                    "snapshot_time": "2026-07-14 10:00:00",
                    "exposure": 300,
                    "peer_exposure": 100,
                    "views": 270,
                    "peer_views": 30,
                    "paid_orders": 270,
                    "peer_paid_orders": 3,
                }
            ]
        }
        _patch_flow_score(result, sections)
        item = result["items"][0]
        self.assertEqual(item["item_score"], 15.0)
        self.assertEqual(item["data_status"], "success")

    def test_flow_missing_subitem_is_zero_not_pending(self) -> None:
        result = {"items": [_item(4, 15)]}
        sections = {
            "ota_funnel": [
                {
                    "platform": "meituan",
                    "period_type": "日",
                    "business_date": "2026-07-14",
                    "exposure": 300,
                    "peer_exposure": 100,
                    "views": 100,
                    "peer_views": 50,
                }
            ]
        }
        _patch_flow_score(result, sections)
        item = result["items"][0]
        self.assertIsNotNone(item["item_score"])
        self.assertNotEqual(item["data_status"], "pending_rule")

    def test_promotion_below_threshold_scores_zero(self) -> None:
        result = {
            "items": [
                _item(
                    9,
                    8,
                    [
                        {"label": "近30天推广投入", "value": 500},
                        {"label": "本月美团EBK订单金额", "value": 53358.04},
                        {"label": "ROI", "value": 106.71608},
                    ],
                )
            ]
        }
        _patch_promotion_score(result)
        item = result["items"][0]
        self.assertEqual(item["item_score"], 0.0)
        self.assertEqual(item["data_status"], "zero")

    def test_room_names_are_strictly_scored(self) -> None:
        result = {
            "items": [
                _item(
                    11,
                    4,
                    [
                        {"label": "独享·电竞单人间", "value": 8},
                        {"label": "乐享·亲子三人间", "value": 8},
                        {"label": "舒享丨上下铺麻将房", "value": 10},
                    ],
                )
            ]
        }
        _patch_room_name_score(result)
        item = result["items"][0]
        self.assertEqual(item["item_score"], 4.0)
        self.assertEqual(item["data_status"], "success")

    def test_manual_crown_has_three_scored_options(self) -> None:
        result = {
            "hotel_name": "测试酒店",
            "period_start": "2026-06-16",
            "period_end": "2026-07-15",
            "visual_diagnosis": {
                "items": [
                    {"standard_item_id": 4, "base_score": 15, "participates_in_score": True, "item_score": 9},
                    {"standard_item_id": 22, "base_score": 1, "participates_in_score": True, "item_score": None},
                ]
            },
        }
        html = _manual_crown_card(result)
        self.assertIn("黑金挂冠（1分）", html)
        self.assertIn("普通挂冠（0.5分）", html)
        self.assertIn("无挂冠（0分）", html)
        self.assertIn("if(type==='普通挂冠')return 0.5", html)
        self.assertIn("updateTotal(score)", html)


if __name__ == "__main__":
    unittest.main()

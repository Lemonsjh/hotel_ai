from __future__ import annotations

import unittest

from marketing_diagnosis.visual_diagnosis_v10 import (
    _patch_flow_score,
    _patch_page_entry_score,
    _patch_room_efficiency_score,
    _patch_room_name_score,
)


def _item(number: int, base: float, fields: list[dict]) -> dict:
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


class HandbookScoresItems241011Test(unittest.TestCase):
    def test_room_efficiency_three_tiers(self) -> None:
        result = {"items": [_item(2, 8, [{"label": "低效房型占比", "value": 0.0}])]}
        _patch_room_efficiency_score(result)
        self.assertEqual(result["items"][0]["item_score"], 8.0)

        result = {"items": [_item(2, 8, [{"label": "低效房型占比", "value": 0.2}])]}
        _patch_room_efficiency_score(result)
        self.assertEqual(result["items"][0]["item_score"], 4.8)

        result = {"items": [_item(2, 8, [{"label": "低效房型占比", "value": 31}])]}
        _patch_room_efficiency_score(result)
        self.assertEqual(result["items"][0]["item_score"], 0.0)

    def test_flow_four_equal_weight_components(self) -> None:
        fields = [
            {"label": "曝光人数", "value": 210},
            {"label": "曝光人数同行均值", "value": 100},
            {"label": "浏览人数", "value": 150},
            {"label": "浏览人数同行均值", "value": 100},
            {"label": "曝光-浏览转化率", "value": 12},
            {"label": "曝光-浏览转化率同行均值", "value": 10},
            {"label": "浏览-支付转化率", "value": 8},
            {"label": "浏览-支付转化率同行均值", "value": 10},
        ]
        result = {"items": [_item(4, 15, fields)]}
        _patch_flow_score(result)
        self.assertEqual(result["items"][0]["score_ratio"], 0.6)
        self.assertEqual(result["items"][0]["item_score"], 9.0)
        self.assertEqual(result["items"][0]["data_status"], "success")

    def test_page_suffix_landmark_scores_full(self) -> None:
        fields = [
            {"label": "酒店展示名称", "value": "璞悦·奢电竞酒店(贵阳花溪公园店)"},
            {"label": "检测到的后缀", "value": "贵阳花溪公园店"},
            {"label": "热门商圈词命中", "value": None},
        ]
        result = {"items": [_item(10, 3, fields)]}
        _patch_page_entry_score(result)
        item = result["items"][0]
        self.assertEqual(item["item_score"], 3.0)
        self.assertEqual(item["data_status"], "success")
        self.assertIn("花溪公园", str(fields[2]["value"]))

    def test_room_names_all_pass(self) -> None:
        fields = [
            {"label": "独享·电竞单人间", "value": 8},
            {"label": "乐享·亲子三人间", "value": 8},
            {"label": "舒享丨上下铺麻将房", "value": 10},
        ]
        result = {"items": [_item(11, 4, fields)]}
        _patch_room_name_score(result)
        self.assertEqual(result["items"][0]["item_score"], 4.0)
        self.assertEqual(result["items"][0]["data_status"], "success")


if __name__ == "__main__":
    unittest.main()

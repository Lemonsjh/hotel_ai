from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v23 import _flow_card, _flow_table


class FlowTableHeaderTests(unittest.TestCase):
    def _item(self):
        return {
            "standard_item_id": 4,
            "item_name": "流量数据分析",
            "base_score": 15,
            "participates_in_score": True,
            "data_status": "success",
            "item_score": 7.5,
            "source_table": "hotel_puyue.meituan_ota_business_metrics",
            "source_fields": ["metric_code", "metric_value", "peer_average"],
            "fields": [
                {"label": "曝光人数", "value": 16976},
                {"label": "曝光人数同行均值", "value": 7545},
                {"label": "曝光人数同行排名（取值日：2026-07-15）", "value": "2/20"},
                {"label": "浏览人数", "value": 1576},
                {"label": "浏览人数同行均值", "value": 775},
                {"label": "浏览人数同行排名（取值日：2026-07-15）", "value": "3/20"},
                {"label": "支付订单数", "value": 118},
                {"label": "支付订单数同行均值", "value": 61},
                {"label": "支付订单数同行排名（取值日：2026-07-15）", "value": "4/20"},
                {"label": "曝光-浏览转化率", "value": 0.09283},
                {"label": "曝光-浏览转化率同行均值", "value": 0.10272},
                {"label": "曝光-浏览转化率同行排名（取值日：2026-07-15）", "value": "5/20"},
                {"label": "浏览-支付转化率", "value": 0.07487},
                {"label": "浏览-支付转化率同行均值", "value": 0.07871},
                {"label": "浏览-支付转化率同行排名（取值日：2026-07-15）", "value": "6/20"},
            ],
        }

    def test_original_flow_headers_are_preserved(self):
        html = _flow_table(self._item())
        expected = [
            "日期",
            "我的酒店曝光人数",
            "竞争圈平均曝光人数",
            "我的酒店浏览人数",
            "竞争圈平均浏览人数",
            "我的酒店曝光-浏览转化率",
            "竞争圈平均曝光-浏览转化率",
            "我的酒店支付订单数",
            "竞争圈平均支付订单数",
            "我的酒店浏览-支付转化率",
            "竞争圈平均浏览-支付转化率",
        ]
        for header in expected:
            self.assertIn(f"<th>{header}</th>", html)
        self.assertIn("20260715", html)
        self.assertIn("16,976", html)
        self.assertIn("9.28%", html)

    def test_flow_card_keeps_score_and_rank_information(self):
        html = _flow_card(self._item())
        self.assertIn("当前得分", html)
        self.assertIn("7.5分", html)
        self.assertIn("曝光人数同行排名", html)
        self.assertIn("2/20", html)
        self.assertIn("flow-table-v23", html)


if __name__ == "__main__":
    unittest.main()

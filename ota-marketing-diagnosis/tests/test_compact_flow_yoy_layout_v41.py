from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v29 import (
    COMPACT_LAYOUT_STYLE,
    _flow_summary_card,
    _flow_summary_item,
)


class CompactFlowAndYoyLayoutTests(unittest.TestCase):
    def _item(self):
        return {
            "standard_item_id": 4,
            "item_name": "流量数据分析",
            "base_score": 15,
            "item_score": 7.5,
            "data_status": "success",
            "fields": [
                {"label": "曝光人数同行排名（取值日：2026-07-16）", "value": "2/20"},
                {"label": "浏览人数同行排名（取值日：2026-07-16）", "value": "3/20"},
                {"label": "曝光-浏览转化率同行排名（取值日：2026-07-16）", "value": "4/20"},
                {"label": "支付订单数同行排名（取值日：2026-07-16）", "value": "5/20"},
                {"label": "浏览-支付转化率同行排名（取值日：2026-07-16）", "value": "6/20"},
            ],
            "daily_records": [
                {
                    "business_date": "2026-07-15",
                    "exposure": 100,
                    "peer_exposure": 50,
                    "views": 10,
                    "peer_views": 5,
                    "paid_orders": 2,
                    "peer_paid_orders": 1,
                },
                {
                    "business_date": "2026-07-16",
                    "exposure": 200,
                    "peer_exposure": 100,
                    "views": 20,
                    "peer_views": 10,
                    "paid_orders": 4,
                    "peer_paid_orders": 2,
                },
            ],
        }

    def test_summary_is_recalculated_from_daily_records(self):
        item = _flow_summary_item(self._item())
        fields = {
            str(field.get("label")).split("（取值日：", 1)[0]: field.get("value")
            for field in item["fields"]
        }
        self.assertEqual(fields["曝光人数"], 300)
        self.assertEqual(fields["曝光人数同行均值"], 150)
        self.assertEqual(fields["浏览人数"], 30)
        self.assertEqual(fields["支付订单数"], 6)
        self.assertAlmostEqual(fields["曝光-浏览转化率"], 0.1)
        self.assertAlmostEqual(fields["浏览-支付转化率"], 0.2)
        self.assertEqual(item["daily_records"], [])
        self.assertEqual(item["records"], [])

    def test_customer_table_contains_exactly_one_aggregate_row(self):
        html = _flow_summary_card(self._item())
        self.assertEqual(html.count("<tbody><tr>"), 1)
        self.assertIn("近30天", html)
        self.assertNotIn("20260715", html)
        self.assertNotIn("20260716", html)
        self.assertIn("300", html)
        self.assertIn("10.00%", html)
        self.assertIn("2/20", html)

    def test_yoy_rows_are_compact_and_category_caption_hidden(self):
        self.assertIn("padding:8px 12px!important", COMPACT_LAYOUT_STYLE)
        self.assertIn("height:auto!important", COMPACT_LAYOUT_STYLE)
        self.assertIn(".performance-category-v25", COMPACT_LAYOUT_STYLE)
        self.assertIn("display:none!important", COMPACT_LAYOUT_STYLE)


if __name__ == "__main__":
    unittest.main()

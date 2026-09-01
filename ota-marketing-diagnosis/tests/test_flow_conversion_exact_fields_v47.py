from __future__ import annotations

import unittest

from marketing_diagnosis.db_loader_v12 import _apply_exact_rank_fields
from marketing_diagnosis.reporting_v33 import FLOW_HEADER_STYLE, _direct_flow_card
from marketing_diagnosis.visual_diagnosis_v20 import (
    FLOW_SOURCE_FIELDS,
    FLOW_SOURCE_TABLE,
    build_visual_diagnosis,
)


class ExactFlowConversionFieldsTests(unittest.TestCase):
    def _mapped_row(self):
        row = {
            "platform": "meituan",
            "business_date": "2026-07-16",
            "period_type": "日",
            "stats_period_type": "日",
            "period_days": 30,
            "source_table": "meituan_ota_flow_conversion_30d",
            "exposure": 16976,
            "peer_exposure": 7545,
            "views": 1576,
            "peer_views": 775,
            "exposure_to_view_rate": 0.0928,
            "peer_exposure_to_view_rate": 0.1027,
            "paid_orders": 147,
            "peer_paid_orders": 63,
            "payment_conversion_rate": 0.0933,
            "peer_payment_conversion_rate": 0.0813,
            "exposure_metric_code": "FLOW_EXPOSURE_UV",
            "views_metric_code": "FLOW_INTENTION_UV",
            "paid_orders_metric_code": "FLOW_PAY_ORDER_CNT",
            "exposure_to_view_rate_metric_code": "FLOW_INTENTION_PER_EXPOSURE",
            "payment_conversion_rate_metric_code": "FLOW_PAY_ORDER_PER_INTENTION",
        }
        return _apply_exact_rank_fields(
            row,
            {
                "exposure_peer_rank": "2/20",
                "browse_peer_rank": "3/20",
                "pay_order_peer_rank": "4/20",
                "exposure_to_browse_peer_rank": "14/20",
                "browse_to_pay_peer_rank": "10/20",
            },
        )

    def test_exact_confirmed_rank_columns_map_to_canonical_rank_fields(self):
        row = self._mapped_row()
        self.assertEqual(row["exposure_rank_raw"], "2/20")
        self.assertEqual(row["views_rank_raw"], "3/20")
        self.assertEqual(row["paid_orders_rank_raw"], "4/20")
        self.assertEqual(row["exposure_to_view_rate_rank_raw"], "14/20")
        self.assertEqual(row["payment_conversion_rate_rank_raw"], "10/20")

    def test_item_04_uses_confirmed_table_fields_and_displays_all_ranks(self):
        visual = build_visual_diagnosis({"ota_funnel": [self._mapped_row()]})
        item = next(
            item for item in visual["items"] if item["standard_item_id"] == 4
        )
        values = {
            str(field.get("label") or "").split("（取值日：", 1)[0]: field.get("value")
            for field in item["fields"]
        }

        self.assertEqual(item["source_table"], FLOW_SOURCE_TABLE)
        self.assertEqual(item["source_fields"], FLOW_SOURCE_FIELDS)
        self.assertEqual(values["曝光人数"], 16976)
        self.assertEqual(values["曝光人数同行均值"], 7545)
        self.assertEqual(values["浏览人数"], 1576)
        self.assertEqual(values["浏览人数同行均值"], 775)
        self.assertAlmostEqual(values["曝光-浏览转化率"], 0.0928)
        self.assertAlmostEqual(values["曝光-浏览转化率同行均值"], 0.1027)
        self.assertEqual(values["支付订单数"], 147)
        self.assertEqual(values["支付订单数同行均值"], 63)
        self.assertAlmostEqual(values["浏览-支付转化率"], 0.0933)
        self.assertAlmostEqual(values["浏览-支付转化率同行均值"], 0.0813)
        self.assertEqual(values["曝光人数同行排名"], "2/20")
        self.assertEqual(values["浏览人数同行排名"], "3/20")
        self.assertEqual(values["支付订单数同行排名"], "4/20")
        self.assertEqual(values["曝光-浏览转化率同行排名"], "14/20")
        self.assertEqual(values["浏览-支付转化率同行排名"], "10/20")

    def test_report_keeps_headers_on_one_line_and_one_30_day_row(self):
        visual = build_visual_diagnosis({"ota_funnel": [self._mapped_row()]})
        item = next(
            item for item in visual["items"] if item["standard_item_id"] == 4
        )
        html = _direct_flow_card(item)
        for header in (
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
        ):
            self.assertIn(f"<th>{header}</th>", html)
        self.assertIn("近30天", html)
        self.assertIn("white-space:nowrap!important", FLOW_HEADER_STYLE)
        self.assertIn("min-width:2100px!important", FLOW_HEADER_STYLE)


if __name__ == "__main__":
    unittest.main()

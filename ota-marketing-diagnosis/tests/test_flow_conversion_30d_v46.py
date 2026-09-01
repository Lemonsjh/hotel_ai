from __future__ import annotations

import unittest

from marketing_diagnosis.db_loader_v10 import (
    _map_flow_conversion_row,
    _percent_ratio,
    _strip_existing_meituan_flow,
)
from marketing_diagnosis.reporting_v33 import FLOW_HEADER_STYLE, _direct_flow_card


class FlowConversion30dTests(unittest.TestCase):
    def _source(self):
        return {
            "business_date": "2026-07-11",
            "exposure_uv": 4033,
            "peer_exposure_uv": 1544,
            "browse_uv": 421,
            "peer_browse_uv": 175,
            "exposure_to_browse_rate_pct": 10.44,
            "peer_exposure_to_browse_rate_pct": 11.33,
            "pay_order_count": 30,
            "peer_pay_order_count": 15,
            "browse_to_pay_rate_pct": 7.13,
            "peer_browse_to_pay_rate_pct": 8.57,
            "exposure_uv_rank": "2/20",
            "browse_uv_rank": "2/20",
            "exposure_to_browse_rate_pct_rank": "14/20",
            "pay_order_count_rank": "2/20",
            "browse_to_pay_rate_pct_rank": "10/20",
        }

    def test_percentage_fields_are_always_converted_from_percent_units(self):
        self.assertAlmostEqual(_percent_ratio(10.44), 0.1044)
        self.assertAlmostEqual(_percent_ratio("7.13%"), 0.0713)
        self.assertAlmostEqual(_percent_ratio(0.5), 0.005)
        self.assertIsNone(_percent_ratio(None))

    def test_exact_database_fields_map_to_item_04_schema(self):
        row = _map_flow_conversion_row(
            self._source(),
            "meituan_ota_flow_conversion_30d",
        )
        self.assertEqual(row["source_table"], "meituan_ota_flow_conversion_30d")
        self.assertEqual(row["business_date"], "2026-07-11")
        self.assertEqual(row["exposure"], 4033)
        self.assertEqual(row["peer_exposure"], 1544)
        self.assertEqual(row["views"], 421)
        self.assertEqual(row["peer_views"], 175)
        self.assertEqual(row["paid_orders"], 30)
        self.assertEqual(row["peer_paid_orders"], 15)
        self.assertAlmostEqual(row["exposure_to_view_rate"], 0.1044)
        self.assertAlmostEqual(row["peer_exposure_to_view_rate"], 0.1133)
        self.assertAlmostEqual(row["payment_conversion_rate"], 0.0713)
        self.assertAlmostEqual(row["peer_payment_conversion_rate"], 0.0857)
        self.assertEqual(row["exposure_rank_raw"], "2/20")
        self.assertEqual(row["views_rank_raw"], "2/20")
        self.assertEqual(row["exposure_to_view_rate_rank_raw"], "14/20")
        self.assertEqual(row["paid_orders_rank_raw"], "2/20")
        self.assertEqual(row["payment_conversion_rate_rank_raw"], "10/20")
        self.assertEqual(row["exposure_metric_code"], "FLOW_EXPOSURE_UV")
        self.assertEqual(
            row["payment_conversion_rate_metric_code"],
            "FLOW_PAY_ORDER_PER_INTENTION",
        )

    def test_old_meituan_flow_is_removed_without_losing_other_metrics(self):
        rows = [
            {
                "platform": "meituan",
                "business_date": "2026-07-11",
                "period_type": "日",
                "exposure": 100,
                "views": 20,
                "paid_orders": 3,
                "hos_score": 4.8,
                "content_score": 92,
            },
            {
                "platform": "meituan",
                "period_type": "scan_order_summary",
                "scan_order_count": 8,
            },
            {
                "platform": "ctrip",
                "business_date": "2026-07-11",
                "views": 50,
                "paid_orders": 5,
            },
        ]
        cleaned = _strip_existing_meituan_flow(rows)
        self.assertEqual(len(cleaned), 3)
        self.assertNotIn("exposure", cleaned[0])
        self.assertNotIn("views", cleaned[0])
        self.assertEqual(cleaned[0]["hos_score"], 4.8)
        self.assertEqual(cleaned[0]["content_score"], 92)
        self.assertEqual(cleaned[1]["scan_order_count"], 8)
        self.assertEqual(cleaned[2]["views"], 50)

    def test_report_uses_direct_rate_fields_and_single_line_headers(self):
        item = {
            "standard_item_id": 4,
            "item_name": "流量数据分析",
            "base_score": 15,
            "item_score": 9.75,
            "data_status": "success",
            "fields": [
                {"label": "曝光人数", "value": 100},
                {"label": "曝光人数同行均值", "value": 80},
                {"label": "浏览人数", "value": 20},
                {"label": "浏览人数同行均值", "value": 16},
                {"label": "曝光-浏览转化率", "value": 0.1044},
                {"label": "曝光-浏览转化率同行均值", "value": 0.1133},
                {"label": "支付订单数", "value": 4},
                {"label": "支付订单数同行均值", "value": 3},
                {"label": "浏览-支付转化率", "value": 0.0713},
                {"label": "浏览-支付转化率同行均值", "value": 0.0857},
                {"label": "曝光人数同行排名（取值日：2026-07-11）", "value": "2/20"},
                {"label": "浏览人数同行排名（取值日：2026-07-11）", "value": "2/20"},
                {"label": "曝光-浏览转化率同行排名（取值日：2026-07-11）", "value": "14/20"},
                {"label": "支付订单数同行排名（取值日：2026-07-11）", "value": "2/20"},
                {"label": "浏览-支付转化率同行排名（取值日：2026-07-11）", "value": "10/20"},
            ],
            # These counts imply 20%, but the report must display the direct DB rate 10.44%.
            "daily_records": [
                {
                    "business_date": "2026-07-11",
                    "exposure": 100,
                    "views": 20,
                    "paid_orders": 4,
                }
            ],
        }
        html = _direct_flow_card(item)
        self.assertIn("近30天", html)
        self.assertIn("10.44%", html)
        self.assertIn("7.13%", html)
        self.assertNotIn("20.00%", html)
        self.assertIn("2/20", html)
        self.assertIn("14/20", html)
        self.assertIn("white-space:nowrap!important", FLOW_HEADER_STYLE)
        self.assertIn("min-width:2100px!important", FLOW_HEADER_STYLE)


if __name__ == "__main__":
    unittest.main()

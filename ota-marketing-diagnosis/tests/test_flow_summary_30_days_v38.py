from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v26 import _flow_summary_card


class FlowSummaryThirtyDaysTests(unittest.TestCase):
    def test_flow_table_has_only_one_aggregate_row(self):
        item = {
            "standard_item_id": 4,
            "item_name": "流量数据分析",
            "base_score": 15,
            "participates_in_score": True,
            "data_status": "success",
            "item_score": 7.5,
            "source_table": "hotel_puyue.meituan_ota_business_metrics",
            "source_fields": ["metric_code", "metric_value", "peer_average"],
            "fields": [
                {"label": "曝光人数", "value": 17187},
                {"label": "曝光人数同行均值", "value": 7545},
                {"label": "曝光人数同行排名（取值日：2026-07-15）", "value": "2/20"},
                {"label": "浏览人数", "value": 1619},
                {"label": "浏览人数同行均值", "value": 775},
                {"label": "浏览人数同行排名（取值日：2026-07-15）", "value": "2/20"},
                {"label": "支付订单数", "value": 147},
                {"label": "支付订单数同行均值", "value": 63},
                {"label": "支付订单数同行排名（取值日：2026-07-15）", "value": "2/20"},
                {"label": "曝光-浏览转化率", "value": 0.0942},
                {"label": "曝光-浏览转化率同行均值", "value": 0.1028},
                {"label": "曝光-浏览转化率同行排名（取值日：2026-07-15）", "value": "14/20"},
                {"label": "浏览-支付转化率", "value": 0.0908},
                {"label": "浏览-支付转化率同行均值", "value": 0.0813},
                {"label": "浏览-支付转化率同行排名（取值日：2026-07-15）", "value": "10/20"},
            ],
            "daily_records": [
                {"business_date": "2026-07-14", "exposure": 8000},
                {"business_date": "2026-07-15", "exposure": 9187},
            ],
        }

        html = _flow_summary_card(item)

        self.assertIn("<td>近30天</td>", html)
        self.assertNotIn("20260714", html)
        self.assertNotIn("20260715", html)
        self.assertEqual(html.count("<tbody><tr>"), 1)
        self.assertIn("17,187", html)
        self.assertIn("9.42%", html)


if __name__ == "__main__":
    unittest.main()

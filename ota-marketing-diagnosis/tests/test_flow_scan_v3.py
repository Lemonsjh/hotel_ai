import unittest

from marketing_diagnosis.db_loader_v2 import _pivot_funnel_precise
from marketing_diagnosis.visual_diagnosis_v3 import build_visual_diagnosis


class FlowAndScanV3Tests(unittest.TestCase):
    def test_exposure_people_is_summed_by_day_without_alias_overwrite(self):
        values = {
            "2026-07-11": 3190,
            "2026-07-12": 4033,
            "2026-07-13": 2860,
            "2026-07-14": 564,
        }
        rows = []
        for day, exposure in values.items():
            rows.extend([
                {
                    "business_date": day,
                    "stats_period_type": "日",
                    "metric_name": "曝光人数",
                    "metric_value": exposure,
                    "peer_average": 1000,
                    "competitor_rank": "4/20" if day == "2026-07-11" else None,
                    "snapshot_time": f"{day} 12:00:00",
                },
                {
                    "business_date": day,
                    "stats_period_type": "日",
                    "metric_name": "曝光量",
                    "metric_value": exposure - 45,
                    "peer_average": 900,
                    "snapshot_time": f"{day} 13:00:00",
                },
                {
                    "business_date": day,
                    "stats_period_type": "日",
                    "metric_name": "浏览人数",
                    "metric_value": 100,
                    "peer_average": 80,
                },
                {
                    "business_date": day,
                    "stats_period_type": "日",
                    "metric_name": "支付订单数",
                    "metric_value": 10,
                    "peer_average": 8,
                },
                {
                    "business_date": day,
                    "stats_period_type": "日",
                    "metric_name": "曝光-浏览转化率",
                    "metric_value": 0.1,
                    "peer_average": 0.08,
                },
                {
                    "business_date": day,
                    "stats_period_type": "日",
                    "metric_name": "浏览-支付转化率",
                    "metric_value": 0.1,
                    "peer_average": 0.08,
                },
            ])

        pivoted = _pivot_funnel_precise(
            rows,
            "meituan",
            "meituan_ota_business_metrics",
        )
        item = build_visual_diagnosis({"ota_funnel": pivoted})["items"][3]
        fields = {field["label"]: field["value"] for field in item["fields"]}

        self.assertEqual(fields["曝光人数"], 10647)
        self.assertEqual(fields["曝光人数同行排名"], "4/20")

    def test_scan_order_item_uses_count_summary(self):
        visual = build_visual_diagnosis({
            "ota_funnel": [{
                "platform": "meituan",
                "period_type": "scan_order_summary",
                "business_date": "2026-07-14",
                "scan_order_count": 23,
                "scan_order_date_column": "business_date",
                "scan_order_period_start": "2026-06-15",
                "scan_order_period_end": "2026-07-14",
            }],
        })
        item = visual["items"][6]

        self.assertEqual(item["fields"][0]["value"], 23)
        self.assertEqual(
            item["source_table"],
            "hotel_puyue.meituan_ota_scan_order_detail",
        )
        self.assertEqual(item["data_status"], "pending_rule")


if __name__ == "__main__":
    unittest.main()

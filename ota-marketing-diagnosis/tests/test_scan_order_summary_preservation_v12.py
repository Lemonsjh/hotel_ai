from __future__ import annotations

import unittest

from marketing_diagnosis.db_loader_v5 import _upsert_scan_order_summary
from marketing_diagnosis.visual_diagnosis_v3 import build_visual_diagnosis


class ScanOrderSummaryPreservationTest(unittest.TestCase):
    def test_summary_survives_meituan_funnel_rebuild(self):
        dataset = {
            "ota_funnel": [
                {
                    "platform": "meituan",
                    "period_type": "日",
                    "business_date": "2026-07-15",
                    "exposure": 364,
                },
                {
                    "platform": "ctrip",
                    "period_type": "日",
                    "business_date": "2026-07-15",
                    "views": 20,
                },
            ]
        }
        summary = {
            "platform": "meituan",
            "period_type": "scan_order_summary",
            "business_date": "2026-07-15",
            "scan_order_count": 86,
            "scan_order_date_column": "business_date",
            "scan_order_period_start": "2026-06-16",
            "scan_order_period_end": "2026-07-15",
        }

        _upsert_scan_order_summary(dataset, summary)
        _upsert_scan_order_summary(dataset, summary)

        summaries = [
            row
            for row in dataset["ota_funnel"]
            if row.get("period_type") == "scan_order_summary"
        ]
        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["scan_order_count"], 86)
        self.assertTrue(any(row.get("exposure") == 364 for row in dataset["ota_funnel"]))
        self.assertTrue(any(row.get("platform") == "ctrip" for row in dataset["ota_funnel"]))

    def test_visual_item_reads_preserved_count(self):
        sections = {
            "ota_funnel": [
                {
                    "platform": "meituan",
                    "period_type": "scan_order_summary",
                    "business_date": "2026-07-15",
                    "scan_order_count": 86,
                    "scan_order_date_column": "business_date",
                    "scan_order_period_start": "2026-06-16",
                    "scan_order_period_end": "2026-07-15",
                }
            ]
        }

        result = build_visual_diagnosis(sections)
        item = next(value for value in result["items"] if value["standard_item_id"] == 7)
        field = next(value for value in item["fields"] if value["label"] == "月扫码订单")

        self.assertEqual(field["value"], 86)
        self.assertNotEqual(item["data_status"], "missing")


if __name__ == "__main__":
    unittest.main()

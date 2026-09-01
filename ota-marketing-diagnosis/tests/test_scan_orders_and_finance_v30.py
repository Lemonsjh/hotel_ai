from __future__ import annotations

import unittest

from marketing_diagnosis.data_v4 import normalize_dataset
from marketing_diagnosis.db_loader_v8 import _detail_spend


class ScanOrdersAndFinanceRegressionTest(unittest.TestCase):
    def test_scan_orders_section_is_preserved_and_summarized(self) -> None:
        raw = {
            "scan_orders": [
                {
                    "order_id": f"ORDER-{index}",
                    "scan_time": "2026-07-15 12:00:00",
                    "source_table": "hotel_puyue.meituan_ota_scan_order_detail",
                }
                for index in range(163)
            ]
        }
        result = normalize_dataset(raw)
        self.assertEqual(len(result["sections"]["scan_orders"]), 163)
        summary = next(
            row
            for row in result["sections"]["ota_funnel"]
            if row.get("period_type") == "scan_order_summary"
        )
        self.assertEqual(summary["scan_order_count"], 163)

    def test_finance_varchar_range_uses_first_ten_date_characters(self) -> None:
        rows = [
            {
                "transaction_time": "2026-06-18 00:00:00-23:59:59",
                "transaction_type": "推广通支出",
                "transaction_amount": -100,
            },
            {
                "transaction_time": "2026-06-23 00:00:00-23:59:59",
                "transaction_type": "推广通支出",
                "transaction_amount": -100,
            },
            {
                "transaction_time": "2026-07-02 00:00:00-23:59:59",
                "transaction_type": "推⼴通⽀出",
                "transaction_amount": -100,
            },
            {
                "transaction_time": "2026-07-07 00:00:00-23:59:59",
                "transaction_type": "推广通支出",
                "transaction_amount": -100,
            },
            {
                "transaction_time": "2026-07-08 00:00:00-23:59:59",
                "transaction_type": "推广通支出",
                "transaction_amount": -100,
            },
            {
                "transaction_time": "2026-05-01 00:00:00-23:59:59",
                "transaction_type": "推广通支出",
                "transaction_amount": -999,
            },
        ]
        spend, count = _detail_spend(
            rows,
            "transaction_amount",
            "transaction_time",
            "2026-06-16",
            "2026-07-15",
        )
        self.assertEqual(count, 5)
        self.assertEqual(spend, 500)


if __name__ == "__main__":
    unittest.main()

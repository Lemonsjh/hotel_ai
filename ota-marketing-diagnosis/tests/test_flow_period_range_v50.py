from __future__ import annotations

import unittest

from marketing_diagnosis.db_loader_v14 import _flow_period, attach_flow_period_range
from marketing_diagnosis.reporting_v36 import _patch_flow_card, _period_label


class FlowPeriodRangeTests(unittest.TestCase):
    def test_business_date_generates_inclusive_30_day_range(self):
        start, end, label = _flow_period(
            {
                "business_date": "2026-07-16",
                "period_days": 30,
            }
        )
        self.assertEqual(start, "2026-06-17")
        self.assertEqual(end, "2026-07-16")
        self.assertEqual(label, "2026-06-17 至 2026-07-16")

    def test_explicit_source_range_wins(self):
        start, end, label = _flow_period(
            {
                "period_start": "2026-06-15",
                "period_end": "2026-07-14",
                "business_date": "2026-07-16",
            }
        )
        self.assertEqual(start, "2026-06-15")
        self.assertEqual(end, "2026-07-14")
        self.assertEqual(label, "2026-06-15 至 2026-07-14")

    def test_dataset_and_report_use_statistical_period_not_single_date(self):
        dataset = {
            "ota_funnel": [
                {
                    "source_table": "meituan_ota_flow_conversion_30d",
                    "business_date": "2026-07-16",
                    "period_days": 30,
                }
            ]
        }
        attach_flow_period_range(dataset)
        item = {"daily_records": dataset["ota_funnel"]}
        self.assertEqual(_period_label(item), "2026-06-17 至 2026-07-16")

        card = """
        <article class='diagnosis-card' id='rule-4'>
          <table class='flow-table-v23'>
            <thead><tr><th>日期</th><th>曝光人数</th></tr></thead>
            <tbody><tr><td>20260716</td><td>79072</td></tr></tbody>
          </table>
          <p class='flow-table-caption-v23'>按业务日期逐日展示。</p>
        </article>
        """
        patched = _patch_flow_card(card, _period_label(item))
        self.assertIn("<th>统计周期</th>", patched)
        self.assertIn("2026-06-17 至 2026-07-16", patched)
        self.assertNotIn("<th>日期</th>", patched)
        self.assertNotIn("20260716", patched)
        self.assertNotIn("flow-table-caption-v23", patched)


if __name__ == "__main__":
    unittest.main()

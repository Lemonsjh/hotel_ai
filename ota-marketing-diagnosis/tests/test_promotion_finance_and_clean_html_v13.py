from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v13 import CUSTOMER_CLEAN_STYLE
from marketing_diagnosis.visual_diagnosis_v7 import (
    _promotion_spend,
    build_visual_diagnosis,
)


class PromotionFinanceAndCleanHtmlTest(unittest.TestCase):
    def test_uploaded_csv_period_spend_is_positive_500(self):
        rows = [
            {"transaction_type": "推广通支出", "transaction_amount": -100},
            {"transaction_type": "推广通支出", "transaction_amount": -100},
            {"transaction_type": "推广通支出", "transaction_amount": -100},
            {"transaction_type": "推广通支出", "transaction_amount": -100},
            {"transaction_type": "推广通支出", "transaction_amount": -100},
            {"transaction_type": "充值", "transaction_amount": 1400},
        ]
        self.assertEqual(_promotion_spend(rows), 500)

    def test_promotion_item_uses_real_expense_sum(self):
        sections = {
            "promotion_finance": [
                {"transaction_type": "推广通支出", "transaction_amount": -100}
                for _ in range(5)
            ],
            "promotion_revenue": [
                {"period_month": "2026-07", "room_revenue": 53358.04}
            ],
        }
        result = build_visual_diagnosis(sections)
        item = next(
            row
            for row in result["items"]
            if row["standard_item_id"] == 9
        )
        fields = {field["label"]: field["value"] for field in item["fields"]}

        self.assertEqual(fields["近30天推广投入"], 500)
        self.assertAlmostEqual(fields["ROI"], 53358.04 / 500)
        self.assertEqual(item["item_score"], None)
        self.assertEqual(item["data_status"], "pending_rule")

    def test_customer_html_hides_formula_and_source_blocks(self):
        self.assertIn(".metric-row > div > span", CUSTOMER_CLEAN_STYLE)
        self.assertIn(".field-standard-note", CUSTOMER_CLEAN_STYLE)
        self.assertIn(".result-area > .notice", CUSTOMER_CLEAN_STYLE)
        self.assertIn("display: none !important", CUSTOMER_CLEAN_STYLE)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from marketing_diagnosis.db_loader_v8 import (
    _normalized_transaction_type,
    _promotion_spend_summary_unicode,
)


class FakeCursor:
    def __init__(self):
        self.calls: list[tuple[str, list[object]]] = []
        self._rows: list[dict] = []

    def execute(self, sql, params=None):
        params = list(params or [])
        self.calls.append((sql, params))
        if sql.startswith("SHOW COLUMNS"):
            self._rows = [
                {"Field": "hotel_id"},
                {"Field": "transaction_time"},
                {"Field": "transaction_type"},
                {"Field": "transaction_amount"},
            ]
            return

        # First detail query applies hotel_id=puyue and intentionally finds no rows.
        if "`hotel_id` = %s" in sql:
            self._rows = []
            return

        # Hotel-scoped schema fallback: compatibility ideographs visually equal
        # “推广通支出” and must normalize to the standard text.
        self._rows = [
            {
                "transaction_type": "推⼴通⽀出",
                "amount_value": -100,
                "transaction_date_value": "2026-06-18 00:00:00-23:59:59",
                "source_hotel_id": "",
            },
            {
                "transaction_type": "推\u200b广 通 支出",
                "amount_value": -100,
                "transaction_date_value": "2026-06-23 00:00:00-23:59:59",
                "source_hotel_id": None,
            },
            {
                "transaction_type": "推广通支出",
                "amount_value": -100,
                "transaction_date_value": "2026-07-02 00:00:00-23:59:59",
                "source_hotel_id": "legacy",
            },
            {
                "transaction_type": " 推广通支出 ",
                "amount_value": -100,
                "transaction_date_value": "2026-07-07 00:00:00-23:59:59",
                "source_hotel_id": "legacy",
            },
            {
                "transaction_type": "推⼴通⽀出",
                "amount_value": -100,
                "transaction_date_value": "2026-07-08 00:00:00-23:59:59",
                "source_hotel_id": "legacy",
            },
        ]

    def fetchall(self):
        return list(self._rows)


class DirectMatchCursor:
    def __init__(self):
        self.calls: list[tuple[str, list[object]]] = []
        self._rows: list[dict] = []

    def execute(self, sql, params=None):
        params = list(params or [])
        self.calls.append((sql, params))
        if sql.startswith("SHOW COLUMNS"):
            self._rows = [
                {"Field": "hotel_id"},
                {"Field": "transaction_time"},
                {"Field": "transaction_type"},
                {"Field": "transaction_amount"},
            ]
            return
        self._rows = [
            {
                "transaction_type": " 推广通支出 ",
                "amount_value": -100,
                "transaction_date_value": f"2026-07-{day:02d} 12:00:00",
                "source_hotel_id": "puyue",
            }
            for day in range(1, 6)
        ]

    def fetchall(self):
        return list(self._rows)


class PromotionSpendUnicodeNfkcTest(unittest.TestCase):
    def test_compatibility_ideographs_normalize(self):
        self.assertEqual(_normalized_transaction_type("推⼴通⽀出"), "推广通支出")
        self.assertEqual(_normalized_transaction_type("推\u200b广 通 支出"), "推广通支出")

    def test_hotel_scoped_fallback_restores_500(self):
        cursor = FakeCursor()
        summary, diag = _promotion_spend_summary_unicode(
            cursor,
            "meituan_ota_promotion_finance_detail",
            "puyue",
            "2026-06-16",
            "2026-07-15",
            schema_is_hotel_scoped=True,
        )
        self.assertIsNotNone(summary)
        self.assertEqual(summary["transaction_amount"], 500)
        self.assertEqual(summary["transaction_count"], 5)
        self.assertEqual(diag["match_mode"], "unicode_detail_schema_scoped")
        self.assertIn("LEFT(CAST(`transaction_time` AS CHAR), 10)", cursor.calls[-1][0])

    def test_direct_query_filters_hotel_and_period_and_sums_absolute_spend(self):
        cursor = DirectMatchCursor()
        summary, diag = _promotion_spend_summary_unicode(
            cursor,
            "meituan_ota_promotion_finance_detail",
            "puyue",
            "2026-06-16",
            "2026-07-15",
        )

        self.assertIsNotNone(summary)
        self.assertEqual(summary["transaction_amount"], 500)
        self.assertEqual(summary["transaction_count"], 5)
        self.assertTrue(summary["promotion_spend_summary"])
        self.assertEqual(diag["status"], "ok")
        sql, params = cursor.calls[-1]
        self.assertIn("`hotel_id` = %s", sql)
        self.assertIn("LEFT(CAST(`transaction_time` AS CHAR), 10) >= %s", sql)
        self.assertIn("LEFT(CAST(`transaction_time` AS CHAR), 10) <= %s", sql)
        self.assertEqual(params, ["puyue", "2026-06-16", "2026-07-15"])

    def test_no_match_does_not_create_false_zero(self):
        class EmptyCursor(FakeCursor):
            def execute(self, sql, params=None):
                params = list(params or [])
                self.calls.append((sql, params))
                if sql.startswith("SHOW COLUMNS"):
                    self._rows = [
                        {"Field": "transaction_time"},
                        {"Field": "transaction_type"},
                        {"Field": "transaction_amount"},
                    ]
                else:
                    self._rows = []

        summary, diag = _promotion_spend_summary_unicode(
            EmptyCursor(),
            "meituan_ota_promotion_finance_detail",
            "puyue",
            "2026-06-16",
            "2026-07-15",
            schema_is_hotel_scoped=True,
        )
        self.assertIsNone(summary)
        self.assertEqual(diag["status"], "empty")
        self.assertFalse(diag["summary_applied"])


if __name__ == "__main__":
    unittest.main()

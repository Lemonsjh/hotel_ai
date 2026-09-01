from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.adapters.database import _mysql_latest_metrics


ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "database-source.example.json"


class TestMetricGroupSchemaDrift(unittest.TestCase):
    def test_meituan_business_metrics_example_does_not_require_metric_group(self) -> None:
        profile = json.loads(CONFIG.read_text(encoding="utf-8"))["profiles"]["puyue_mysql_prod"]
        columns = profile["columns"]["meituan_business_metrics"]

        self.assertNotIn("metric_group", columns)
        self.assertNotIn("metric_display_name", columns)
        self.assertIn("metric_name", columns)
        self.assertIn("metric_value", columns)

    def test_metric_query_omits_missing_optional_metric_dimension_columns(self) -> None:
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params):
                self.sql = sql
                self.params = params

            def fetchall(self):
                return [{"metric_name": "间夜数", "metric_value": 23, "business_date": "2026-06-26"}]

        class Conn:
            def __init__(self):
                self.cursor_obj = Cursor()

            def cursor(self):
                return self.cursor_obj

        profile = {
            "tables": {"daily_metrics": "meituan_ota_business_metrics"},
            "columns": {
                "daily_metrics": {
                    "hotel_name": "hotel_name",
                    "business_date": "business_date",
                    "metric_name": "metric_name",
                    "metric_value": "metric_value",
                    "period_type": "period_type",
                }
            },
            "metric_aliases": {"room_nights": ["间夜数"]},
        }
        conn = Conn()

        result = _mysql_latest_metrics(conn, profile, "xingfeng", monthly=False)

        self.assertNotIn("metric_group", conn.cursor_obj.sql)
        self.assertNotIn("metric_item", conn.cursor_obj.sql)
        self.assertNotIn("metric_display_name", conn.cursor_obj.sql)
        self.assertEqual(result["normalized_metrics"]["room_nights"], 23)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from runtime.adapters.database import _col, _hotel_name, _hotel_names, _mysql_latest_metrics


class TestHotelIdContract(unittest.TestCase):
    def test_hotel_id_column_is_preferred_over_hotel_name_for_runtime_filter(self) -> None:
        columns = {"hotel_id": "hotel_id", "hotel_name": "hotel_name"}

        self.assertEqual(_col(columns, "hotel_name"), "hotel_id")

    def test_configured_hotel_names_are_available_for_legacy_scope(self) -> None:
        profile = {
            "hotel_ids": {
                "hotel-a": {
                    "hotel_name": "Example Hotel",
                    "display_name": "Example Display",
                    "aliases": ["Example Alias"],
                }
            }
        }

        self.assertEqual(_hotel_name(profile, "hotel-a"), "Example Hotel")
        self.assertEqual(_hotel_names(profile, "hotel-a"), ["Example Hotel", "Example Display", "Example Alias", "hotel-a"])

    def test_metric_query_uses_hotel_id_when_mapping_contains_hotel_id(self) -> None:
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
                    "hotel_id": "hotel_id",
                    "business_date": "business_date",
                    "metric_name": "metric_name",
                    "metric_value": "metric_value",
                    "period_type": "period_type",
                }
            },
            "metric_aliases": {"room_nights": ["间夜数"]},
        }
        conn = Conn()

        result = _mysql_latest_metrics(conn, profile, "Example Hotel", monthly=False, hotel_id="hotel-a")

        self.assertIn("`hotel_id` = %s", conn.cursor_obj.sql)
        self.assertNotIn("`hotel_name` = %s", conn.cursor_obj.sql)
        self.assertNotIn("hotel_name = %s", conn.cursor_obj.sql)
        self.assertEqual(conn.cursor_obj.params[0], "hotel-a")
        self.assertEqual(result["normalized_metrics"]["room_nights"], 23)

    def test_horizontal_metric_query_uses_hotel_id_when_available(self) -> None:
        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql, params):
                self.sql = sql
                self.params = params

            def fetchall(self):
                return [
                    {
                        "hotel_name": "Example Hotel",
                        "business_date": "2026-06-29",
                        "snapshot_time": "2026-06-30 10:00:00",
                        "dimension_type": "总营业指标",
                        "dimension_name": "总营业指标",
                        "room_count": 31,
                        "sold_rooms": 30,
                        "occupancy_rate": 96.77,
                    }
                ]

        class Conn:
            def __init__(self):
                self.cursor_obj = Cursor()

            def cursor(self):
                return self.cursor_obj

        profile = {
            "tables": {"daily_metrics": "jy01_hotel_statistics_daily"},
            "columns": {
                "daily_metrics": {
                    "hotel_id": "hotel_id",
                    "hotel_name": "hotel_name",
                    "business_date": "business_date",
                    "snapshot_time": "snapshot_time",
                    "dimension_type": "dimension_type",
                    "dimension_name": "dimension_name",
                    "room_count": "room_count",
                    "sold_rooms": "sold_rooms",
                    "occupancy_rate": "occupancy_rate",
                }
            },
        }
        conn = Conn()

        result = _mysql_latest_metrics(
            conn,
            profile,
            "Example Hotel",
            monthly=False,
            date="2026-06-29",
            hotel_id="hotel-a",
        )

        self.assertIn("`hotel_id` = %s", conn.cursor_obj.sql)
        self.assertEqual(conn.cursor_obj.params[0], "hotel-a")
        self.assertEqual(result["normalized_metrics"]["sold_rooms"], 30)


if __name__ == "__main__":
    unittest.main()

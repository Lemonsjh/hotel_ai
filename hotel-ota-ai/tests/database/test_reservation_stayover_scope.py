from __future__ import annotations

import argparse
import unittest

from runtime.adapters import database


class Cursor:
    def __init__(self, rows=None):
        self.executions: list[tuple[str, tuple]] = []
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=()):
        self.executions.append((sql, tuple(params)))

    def fetchone(self):
        return {"raw_row_count": 1}

    def fetchall(self):
        return list(self.rows)


class Conn:
    def __init__(self, rows=None):
        self.cursor_obj = Cursor(rows=rows)

    def cursor(self):
        return self.cursor_obj


class TestReservationStayoverScope(unittest.TestCase):
    def test_reservation_snapshot_prefers_hotel_id_scope(self) -> None:
        profile = {
            "tables": {"reservation_snapshot": "jd01_booking_detail"},
            "hotel_ids": {"hotel-a": {"hotel_name": "Example Hotel", "aliases": ["Example Alias"]}},
            "columns": {
                "reservation_snapshot": {
                    "hotel_id": "hotel_id",
                    "hotel_name": "hotel_name",
                    "business_date": "business_date",
                    "room_count": "room_count",
                    "status": "booking_status",
                    "source_platform": "source_platform",
                }
            },
        }
        conn = Conn(rows=[{"new_arrival_rooms": 2, "business_date": "2026-06-30"}])

        result = database._query_mysql_reservation_snapshot(
            conn,
            argparse.Namespace(hotel_id="hotel-a", date="2026-06-30", source_platform=None),
            profile,
        )

        raw_sql, raw_params = conn.cursor_obj.executions[0]
        self.assertIn("`hotel_id` = %s", raw_sql)
        self.assertEqual(raw_params[0], "hotel-a")
        self.assertEqual(result["new_arrival_rooms"], 2)

    def test_reservation_snapshot_treats_checked_in_arrivals_as_active(self) -> None:
        profile = {
            "tables": {"reservation_snapshot": "jd01_booking_detail"},
            "hotel_ids": {"hotel-a": {"hotel_name": "Example Hotel"}},
            "columns": {
                "reservation_snapshot": {
                    "hotel_id": "hotel_id",
                    "arrival_time": "arrival_time",
                    "room_count": "room_count",
                    "booking_status": "booking_status",
                    "source_platform": "source_platform",
                }
            },
        }
        conn = Conn(rows=[{"new_arrival_rooms": 3, "business_date": "2026-06-30"}])

        database._query_mysql_reservation_snapshot(
            conn,
            argparse.Namespace(hotel_id="hotel-a", date="2026-06-30", source_platform=None),
            profile,
        )

        _, params = conn.cursor_obj.executions[-1]
        self.assertIn("已入住", params)

    def test_reservation_snapshot_splits_checked_in_by_departure_and_reserved_by_arrival(self) -> None:
        profile = {
            "tables": {"reservation_snapshot": "jd01_booking_detail"},
            "hotel_ids": {"hotel-a": {"hotel_name": "Example Hotel"}},
            "columns": {
                "reservation_snapshot": {
                    "hotel_id": "hotel_id",
                    "arrival_time": "arrival_time",
                    "departure_time": "departure_time",
                    "room_count": "room_count",
                    "booking_status": "booking_Status",
                    "source_platform": "source_platform",
                    "snapshot_time": "snapshot_time",
                }
            },
        }
        conn = Conn(
            rows=[
                {
                    "new_arrival_rooms": 16,
                    "jd01_checked_in_departure_after_as_of": 13,
                    "jd01_reserved_arrival_today": 3,
                    "business_date": "2026-07-03 20:00:00",
                    "as_of_time": "2026-07-03 16:25:00",
                }
            ]
        )

        result = database._query_mysql_reservation_snapshot(
            conn,
            argparse.Namespace(hotel_id="hotel-a", date="2026-07-03", source_platform=None, as_of_time="2026-07-03 16:25:00"),
            profile,
        )

        sql_text = "\n".join(sql for sql, _ in conn.cursor_obj.executions)
        _, params = conn.cursor_obj.executions[-1]
        self.assertIn("`departure_time` > %s", sql_text)
        self.assertIn("DATE(`arrival_time`) = %s", sql_text)
        self.assertIn("booking_Status", sql_text)
        self.assertNotIn("`snapshot_time` = (SELECT MAX(`snapshot_time`)", sql_text)
        self.assertIn("2026-07-03 16:25:00", params)
        self.assertEqual(result["new_arrival_rooms"], 16)
        self.assertEqual(result["jd01_checked_in_departure_after_as_of"], 13)
        self.assertEqual(result["jd01_reserved_arrival_today"], 3)
        self.assertEqual(result["as_of_time"], "2026-07-03 16:25:00")

    def test_reservation_snapshot_deduplicates_realtime_components_by_order_id(self) -> None:
        profile = {
            "tables": {"reservation_snapshot": "jd01_booking_detail"},
            "hotel_ids": {"hotel-a": {"hotel_name": "Example Hotel"}},
            "columns": {
                "reservation_snapshot": {
                    "hotel_id": "hotel_id",
                    "order_id": "order_id",
                    "arrival_time": "arrival_time",
                    "departure_time": "departure_time",
                    "room_count": "room_count",
                    "booking_status": "booking_status",
                    "source_platform": "source_platform",
                }
            },
        }
        conn = Conn(
            rows=[
                {
                    "new_arrival_rooms": 2,
                    "jd01_checked_in_departure_after_as_of": 1,
                    "jd01_reserved_arrival_today": 1,
                    "business_date": "2026-07-04 20:00:00",
                    "as_of_time": "2026-07-04 20:14:44",
                }
            ]
        )

        result = database._query_mysql_reservation_snapshot(
            conn,
            argparse.Namespace(hotel_id="hotel-a", date="2026-07-04", source_platform=None, as_of_time="2026-07-04 20:14:44"),
            profile,
        )

        sql_text = "\n".join(sql for sql, _ in conn.cursor_obj.executions)
        self.assertIn("GROUP BY `order_id`", sql_text)
        self.assertIn("MAX(CASE WHEN TRIM(`booking_status`)", sql_text)
        self.assertIn("AS deduped", sql_text)
        self.assertNotIn("SUM(CASE WHEN TRIM(`booking_status`)", sql_text)
        self.assertEqual(result["new_arrival_rooms"], 2)

    def test_reservation_snapshot_excludes_cancelled_same_day_arrivals_by_order_id(self) -> None:
        profile = {
            "tables": {"reservation_snapshot": "jd01_booking_detail"},
            "hotel_ids": {"hotel-a": {"hotel_name": "Example Hotel"}},
            "columns": {
                "reservation_snapshot": {
                    "hotel_id": "hotel_id",
                    "order_id": "order_id",
                    "arrival_time": "arrival_time",
                    "departure_time": "departure_time",
                    "room_count": "room_count",
                    "booking_status": "booking_status",
                    "source_platform": "source_platform",
                }
            },
        }
        conn = Conn(
            rows=[
                {
                    "new_arrival_rooms": 2,
                    "jd01_checked_in_departure_after_as_of": 1,
                    "jd01_reserved_arrival_today": 1,
                    "jd01_cancelled_arrival_today": 1,
                    "business_date": "2026-07-04 20:00:00",
                    "as_of_time": "2026-07-04 20:14:44",
                }
            ]
        )

        result = database._query_mysql_reservation_snapshot(
            conn,
            argparse.Namespace(hotel_id="hotel-a", date="2026-07-04", source_platform=None, as_of_time="2026-07-04 20:14:44"),
            profile,
        )

        sql_text = "\n".join(sql for sql, _ in conn.cursor_obj.executions)
        _, params = conn.cursor_obj.executions[-1]
        self.assertIn("jd01_cancelled_arrival_today", sql_text)
        self.assertIn("GREATEST(", sql_text)
        self.assertIn("DATE(`arrival_time`) = %s", sql_text)
        self.assertIn("取消", params)
        self.assertEqual(result["jd01_cancelled_arrival_today"], 1)
        self.assertEqual(result["jd01_reserved_arrival_today"], 1)

    def test_stayover_snapshot_prefers_hotel_id_scope(self) -> None:
        profile = {
            "tables": {"stayover_snapshot": "jd04_inhouse_extension"},
            "hotel_ids": {"hotel-a": {"hotel_name": "Example Hotel", "aliases": ["Example Alias"]}},
            "columns": {
                "stayover_snapshot": {
                    "hotel_id": "hotel_id",
                    "hotel_name": "hotel_name",
                    "business_date": "business_date",
                    "room_no": "room_no",
                    "status": "stay_status",
                    "source_platform": "source_platform",
                }
            },
        }
        conn = Conn(rows=[{"stayover_rooms": 3, "business_date": "2026-06-30"}])

        result = database._query_mysql_stayover_snapshot(
            conn,
            argparse.Namespace(hotel_id="hotel-a", date="2026-06-30", source_platform=None),
            profile,
        )

        raw_sql, raw_params = conn.cursor_obj.executions[0]
        self.assertIn("`hotel_id` = %s", raw_sql)
        self.assertEqual(raw_params[0], "hotel-a")
        self.assertEqual(result["stayover_rooms"], 3)

    def test_stayover_snapshot_filters_checkout_after_as_of_time(self) -> None:
        profile = {
            "tables": {"stayover_snapshot": "jd04_inhouse_extension"},
            "hotel_ids": {"hotel-a": {"hotel_name": "Example Hotel"}},
            "columns": {
                "stayover_snapshot": {
                    "hotel_id": "hotel_id",
                    "room_no": "room_no",
                    "checkout_time": "checkout_time",
                    "checkin_time": "checkin_time",
                    "status": "status",
                    "source_platform": "source_platform",
                    "snapshot_time": "snapshot_time",
                }
            },
        }
        conn = Conn(rows=[{"stayover_rooms": 7, "business_date": "2026-07-04 20:00:00"}])

        result = database._query_mysql_stayover_snapshot(
            conn,
            argparse.Namespace(hotel_id="hotel-a", date="2026-07-04", source_platform=None, as_of_time="2026-07-04 16:25:00"),
            profile,
        )

        sql_text = "\n".join(sql for sql, _ in conn.cursor_obj.executions)
        _, params = conn.cursor_obj.executions[-1]
        self.assertIn("`checkout_time` > %s", sql_text)
        self.assertNotIn("`snapshot_time` = (SELECT MAX(`snapshot_time`)", sql_text)
        self.assertIn("2026-07-04 16:25:00", params)
        self.assertEqual(result["stayover_rooms"], 7)
        self.assertEqual(result["jd04_checkout_after_as_of"], 7)
        self.assertEqual(result["as_of_time"], "2026-07-04 16:25:00")


if __name__ == "__main__":
    unittest.main()

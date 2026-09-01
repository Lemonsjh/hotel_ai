from __future__ import annotations

import argparse
import unittest

from runtime.adapters import database


class _Cursor:
    def __init__(self, rows: list[dict] | None = None, sqls: list[str] | None = None) -> None:
        self.rows = rows or []
        self.sqls = sqls if sqls is not None else []
        self.sql = ""
        self.params: tuple = ()

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.sql = sql
        self.params = params
        self.sqls.append(sql)

    def fetchall(self) -> list[dict]:
        return self.rows

    def fetchone(self) -> dict | None:
        return None


class _Connection:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.sqls: list[str] = []
        self.cursor_obj = _Cursor(rows, self.sqls)

    def cursor(self) -> _Cursor:
        return self.cursor_obj


class _ChannelConfigCursor(_Cursor):
    def __init__(self, sqls: list[str]) -> None:
        super().__init__([], sqls)
        self._fetchone_row: dict | None = None

    def execute(self, sql: str, params: tuple = ()) -> None:
        super().execute(sql, params)
        if "FROM `hotels`" in sql:
            self._fetchone_row = {"config_json": '{"channels":["meituan"]}'}
            self.rows = []
        elif "FROM `meituan_ota_business_metrics`" in sql:
            self._fetchone_row = None
            self.rows = [
                {
                    "hotel_id": "puyue",
                    "source_platform": "meituan",
                    "business_date": "2026-06-30",
                    "snapshot_time": "2026-06-30 10:00:00",
                    "metric_name": "exposure",
                    "metric_value": 100,
                }
            ]
        elif "FROM `ctrip_ota_business_metrics`" in sql:
            self._fetchone_row = None
            self.rows = [
                {
                    "hotel_id": "puyue",
                    "source_platform": "ctrip",
                    "business_date": "2026-06-30",
                    "snapshot_time": "2026-06-30 10:00:00",
                    "metric_name": "exposure",
                    "metric_value": 999,
                }
            ]
        else:
            self._fetchone_row = None
            self.rows = []

    def fetchone(self) -> dict | None:
        return self._fetchone_row


class _ChannelConfigConnection:
    def __init__(self) -> None:
        self.sqls: list[str] = []

    def cursor(self) -> _ChannelConfigCursor:
        return _ChannelConfigCursor(self.sqls)


class TestDatabaseV4LatestScope(unittest.TestCase):
    def test_latest_business_date_is_scoped_by_source_platform(self) -> None:
        conn = _Connection()
        profile = {
            "hotel_aliases": {"puyue": "璞悦酒店"},
            "platform_aliases": {"meituan": ["美团"]},
            "tables": {"meituan_business_metrics": "meituan_ota_business_metrics"},
            "columns": {
                "meituan_business_metrics": {
                    "hotel_name": "hotel_name",
                    "source_platform": "source_platform",
                    "business_date": "business_date",
                    "snapshot_time": "snapshot_time",
                    "metric_name": "metric_name",
                    "metric_value": "metric_value",
                }
            },
        }
        args = argparse.Namespace(hotel_id="puyue", date=None, source_platform="meituan")

        database._query_mysql_v4_rows(
            conn,
            args,
            profile,
            template="ota_business_metrics",
            table_keys=("meituan_business_metrics",),
        )

        sql = conn.cursor_obj.sql
        self.assertIn("MAX(`business_date`)", sql)
        self.assertIn(
            "SELECT MAX(`business_date`) FROM `meituan_ota_business_metrics` WHERE `hotel_name` IN (%s) AND (TRIM(`source_platform`) IN",
            sql,
        )
        self.assertIn("TRIM(`source_platform`) IN", sql)
        self.assertGreaterEqual(conn.cursor_obj.params.count("美团"), 2)

    def test_snapshot_time_only_explicit_date_uses_latest_snapshot_of_that_day(self) -> None:
        conn = _Connection()
        profile = {
            "hotel_aliases": {"puyue": "璞悦酒店"},
            "platform_aliases": {"meituan": ["美团"]},
            "tables": {"meituan_activity_product_detail": "meituan_ota_activity_product_detail"},
            "columns": {
                "meituan_activity_product_detail": {
                    "hotel_name": "hotel_name",
                    "source_platform": "source_platform",
                    "snapshot_time": "snapshot_time",
                    "room_type_name": "room_type_name",
                    "ota_sale_price": "ota_sale_price",
                }
            },
        }
        args = argparse.Namespace(hotel_id="puyue", date="2026-06-27", source_platform="meituan")

        database._query_mysql_v4_rows(
            conn,
            args,
            profile,
            template="ota_activity_product_detail",
            table_keys=("meituan_activity_product_detail",),
        )

        sql = conn.cursor_obj.sql
        self.assertIn("DATE(`snapshot_time`) = %s", sql)
        self.assertIn("`snapshot_time` = (SELECT MAX(`snapshot_time`)", sql)
        self.assertIn("TRIM(`source_platform`) IN", sql)
        self.assertIn("2026-06-27", conn.cursor_obj.params)

    def test_explicit_as_of_time_bounds_the_latest_snapshot(self) -> None:
        conn = _Connection()
        profile = {
            "tables": {"meituan_business_metrics": "meituan_ota_business_metrics"},
            "columns": {"meituan_business_metrics": {
                "hotel_id": "hotel_id", "business_date": "business_date", "snapshot_time": "snapshot_time",
                "metric_code": "metric_code", "metric_value": "metric_value",
            }},
        }
        args = argparse.Namespace(hotel_id="puyue", date="2026-08-03", source_platform=None, as_of_time="2026-08-03 20:00:00")

        database._query_mysql_v4_rows(conn, args, profile, template="ota_business_metrics", table_keys=("meituan_business_metrics",))

        self.assertIn("`snapshot_time` <= %s", conn.cursor_obj.sql)
        self.assertIn("2026-08-03 20:00:00", conn.cursor_obj.params)

    def test_ota_rows_skip_disabled_channel_tables_from_hotel_config(self) -> None:
        conn = _ChannelConfigConnection()
        profile = {
            "tables": {
                "ctrip_business_metrics": "ctrip_ota_business_metrics",
                "meituan_business_metrics": "meituan_ota_business_metrics",
            },
            "columns": {
                "ctrip_business_metrics": {
                    "hotel_id": "hotel_id",
                    "source_platform": "source_platform",
                    "business_date": "business_date",
                    "snapshot_time": "snapshot_time",
                    "metric_name": "metric_name",
                    "metric_value": "metric_value",
                },
                "meituan_business_metrics": {
                    "hotel_id": "hotel_id",
                    "source_platform": "source_platform",
                    "business_date": "business_date",
                    "snapshot_time": "snapshot_time",
                    "metric_name": "metric_name",
                    "metric_value": "metric_value",
                },
            },
        }
        args = argparse.Namespace(hotel_id="puyue", date="2026-06-30", source_platform=None)

        result = database._query_mysql_v4_rows(
            conn,
            args,
            profile,
            template="ota_business_metrics",
            table_keys=("ctrip_business_metrics", "meituan_business_metrics"),
        )

        executed_sql = "\n".join(conn.sqls)
        self.assertNotIn("ctrip_ota_business_metrics", executed_sql)
        self.assertIn("meituan_ota_business_metrics", executed_sql)
        self.assertEqual(result["enabled_ota_channels"], ["meituan"])
        self.assertEqual(result["skipped_channel_table_keys"], ["ctrip_business_metrics"])

    def test_ota_price_mapping_derives_product_type_price_guard_candidates(self) -> None:
        args = argparse.Namespace(hotel_id="puyue", date="2026-06-30", source_platform="meituan")
        rows = [
            {
                "hotel_id": "puyue",
                "source_platform": "meituan",
                "business_date": "2026-06-30",
                "snapshot_time": "2026-06-30 10:00:00",
                "room_type_name": "至臻电竞双床房",
                "ota_product_id": "mt-listed",
                "ota_product_name": "至臻电竞双床房 标准价",
                "ota_sale_price": 334,
                "is_super_deal": 0,
            },
            {
                "hotel_id": "puyue",
                "source_platform": "meituan",
                "business_date": "2026-06-30",
                "snapshot_time": "2026-06-30 10:00:00",
                "room_type_name": "至臻电竞双床房",
                "ota_product_id": "mt-deal",
                "ota_product_name": "至臻电竞双床房 超级团购",
                "ota_sale_price": 99,
                "is_super_deal": 1,
            },
            {
                "hotel_id": "puyue",
                "source_platform": "meituan",
                "business_date": "2026-06-30",
                "snapshot_time": "2026-06-30 10:00:00",
                "room_type_name": "至臻电竞双床房",
                "ota_product_id": "mt-hour",
                "ota_product_name": "至臻电竞双床房 钟点房3小时",
                "ota_sale_price": 88,
                "is_super_deal": 0,
                "is_hour_room": 1,
            },
        ]
        raw = {"rows": rows, "row_count": 3, "risk_flags": []}
        coverage = {"requested_platform": "meituan", "tables": {}, "meituan": {"table_row_count": 3, "hotel_row_count": 3}}

        from unittest import mock

        with mock.patch.object(database, "_ota_price_mapping_coverage", return_value=coverage), mock.patch.object(
            database, "_query_mysql_v4_rows", return_value=raw
        ):
            result = database._query_mysql_ota_price_mapping(object(), args, {})

        candidates = {
            item["ota_product_id"]: item["product_price_guard_candidate"]
            for item in result["price_snapshots"]
        }
        self.assertEqual(candidates["mt-listed"]["product_type"], "listed_full_day")
        self.assertEqual(candidates["mt-listed"]["max_increase_pct"], 0.2)
        self.assertEqual(candidates["mt-listed"]["floor_price"], 267.2)
        self.assertEqual(candidates["mt-listed"]["ceiling_price"], 400.8)
        self.assertEqual(candidates["mt-deal"]["product_type"], "super_deal")
        self.assertEqual(candidates["mt-deal"]["max_increase_pct"], 0.15)
        self.assertEqual(candidates["mt-deal"]["floor_price"], 84.15)
        self.assertEqual(candidates["mt-deal"]["ceiling_price"], 113.85)
        self.assertEqual(candidates["mt-hour"]["product_type"], "hour_room")
        self.assertFalse(candidates["mt-hour"]["full_day_price_guard_applicable"])
        snapshots = {item["ota_product_id"]: item for item in result["price_snapshots"]}
        self.assertEqual(snapshots["mt-hour"]["is_hour_room"], 1)
        self.assertTrue(all(item["activation_required"] for item in candidates.values()))
        self.assertTrue(all(not item["execution_allowed"] for item in candidates.values()))


if __name__ == "__main__":
    unittest.main()

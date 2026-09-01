from __future__ import annotations

import argparse
import json
import unittest
from pathlib import Path

from runtime.adapters import database


class _Cursor:
    def __init__(self) -> None:
        self.sql = ""
        self.params: tuple = ()
        self.executions: list[tuple[str, tuple]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.sql = sql
        self.params = params
        self.executions.append((sql, params))

    def fetchall(self) -> list[dict]:
        return []


class _Connection:
    def __init__(self) -> None:
        self.cursor_obj = _Cursor()

    def cursor(self) -> _Cursor:
        return self.cursor_obj


class _RowsConnection(_Connection):
    def __init__(self, rows: list[dict]) -> None:
        super().__init__()
        self.cursor_obj.rows = rows
        self.cursor_obj.fetchall = lambda: self.cursor_obj.rows


class TestOperatingSnapshotScope(unittest.TestCase):
    def test_runtime_contract_matches_published_s2_contract(self) -> None:
        root = Path(__file__).resolve().parents[1]
        contract = json.loads((root / "contracts" / "s2_pms_forecast_contract.json").read_text(encoding="utf-8"))

        self.assertEqual(contract["contract_version"], "pms_room_type_forecast_v1")
        self.assertEqual(contract["source_table"], database.PMS_S2_FORECAST_CONTRACT["tables"]["pms_room_type_forecast"])
        runtime_columns = database.PMS_S2_FORECAST_CONTRACT["columns"]["pms_room_type_forecast"]
        self.assertTrue(set(contract["required_columns"]).issubset(runtime_columns.values()))

    def test_operating_snapshot_prefers_pms_forecast_and_separates_committed_from_physical(self) -> None:
        conn = _RowsConnection(
            [
                {
                    "stay_date": "2026-08-03",
                    "room_type_id": "rt-1",
                    "room_type_name": "King",
                    "total_rooms": 20,
                    "available_rooms": 3,
                    "occupied_rooms": 14,
                    "overbooking_rooms": 2,
                    "room_revenue": 3800,
                    "snapshot_time": "2026-08-03 10:00:00",
                }
            ]
        )
        profile = {
            "platform_aliases": {"pms": ["pms"]},
            "tables": {"pms_room_type_forecast": "pms_room_type_forecast"},
            "columns": {
                "pms_room_type_forecast": {
                    "hotel_id": "hotel_id", "source_platform": "source_platform", "snapshot_time": "snapshot_time",
                    "stay_date": "stay_date", "room_type_id": "room_type_id", "room_type_name": "room_type_name",
                    "total_rooms": "total_rooms", "available_rooms": "available_rooms", "occupied_rooms": "occupied_rooms",
                    "overbooking_rooms": "overbooking_rooms", "room_revenue": "room_revenue",
                }
            },
        }

        payload = database._query_mysql_operating_snapshot(
            conn,
            argparse.Namespace(hotel_id="hotel-001", date="2026-08-03", source_platform="pms"),
            profile,
        )

        self.assertIn("pms_room_type_forecast", conn.cursor_obj.sql)
        self.assertIn("`hotel_id` = %s", conn.cursor_obj.sql)
        self.assertIn("DATE(`stay_date`) = %s", conn.cursor_obj.sql)
        self.assertEqual(payload["committed_sold_rooms"], 19)
        self.assertEqual(payload["physical_occupied_rooms"], 14)
        self.assertEqual(payload["committed_occupancy_rate"], 0.95)
        self.assertEqual(payload["s2_contract"], "pms_room_type_forecast_v1")
        self.assertEqual(payload["tenant_filter_mode"], "hotel_id")

    def test_operating_snapshot_honors_as_of_cutoff(self) -> None:
        conn = _Connection()

        database._query_mysql_operating_snapshot(
            conn,
            argparse.Namespace(
                hotel_id="hotel-001",
                date="2026-08-03",
                as_of_time="2026-08-03 10:30:00",
                source_platform="pms",
            ),
            {},
        )

        self.assertIn("`snapshot_time` <= %s", conn.cursor_obj.sql)
        self.assertIn("2026-08-03 10:30:00", conn.cursor_obj.params)

    def test_operating_snapshot_uses_fixed_pms_contract_without_profile_mapping(self) -> None:
        conn = _Connection()
        profile = {
            "hotel_ids": {"puyue": {"hotel_name": "璞悦酒店"}},
            "platform_aliases": {"pms": ["pms"]},
            "tables": {
                "room_status_snapshot": "kf11_room_status_snapshot",
                "daily_metrics": "jy01_hotel_statistics_daily",
            },
            "columns": {
                "room_status_snapshot": {
                    "hotel_id": "hotel_id",
                    "hotel_name": "hotel_name",
                    "source_platform": "source_platform",
                    "snapshot_time": "snapshot_time",
                    "room_status": "room_status",
                    "room_no": "room_no",
                },
                "daily_metrics": {
                    "hotel_id": "hotel_id",
                    "hotel_name": "hotel_name",
                    "business_date": "business_date",
                    "snapshot_time": "snapshot_time",
                    "dimension_type": "dimension_type",
                    "dimension_name": "dimension_name",
                    "room_count": "room_count",
                },
            },
        }

        database._query_mysql_operating_snapshot(
            conn,
            argparse.Namespace(hotel_id="puyue", date=None, source_platform="pms"),
            profile,
        )

        first_sql, first_params = conn.cursor_obj.executions[0]
        self.assertIn("pms_room_type_forecast", first_sql)
        self.assertNotIn("kf11_room_status_snapshot", first_sql)
        self.assertIn("`hotel_id` = %s", first_sql)
        self.assertEqual(first_params[0], "puyue")

    def test_room_status_snapshot_uses_pms_date_and_latest_snapshot_scope(self) -> None:
        conn = _Connection()
        profile = {
            "hotel_aliases": {"puyue": "璞悦酒店"},
            "platform_aliases": {"pms": ["pms"]},
            "tables": {"room_status_snapshot": "kf11_room_status_snapshot"},
            "columns": {
                "room_status_snapshot": {
                    "hotel_id": "hotel_id",
                    "hotel_name": "hotel_name",
                    "source_platform": "source_platform",
                    "business_date": "business_date",
                    "snapshot_time": "snapshot_time",
                    "room_status": "room_status",
                    "room_count": "room_count",
                }
            },
        }
        args = argparse.Namespace(hotel_id="puyue", date="2026-06-27", source_platform="pms")

        database._query_mysql_v4_rows(
            conn,
            args,
            profile,
            template="operating_snapshot",
            table_keys=("room_status_snapshot",),
        )

        sql = conn.cursor_obj.sql
        self.assertIn("`hotel_id` = %s", sql)
        self.assertIn("DATE(`business_date`) = %s", sql)
        self.assertIn("TRIM(`source_platform`) IN", sql)
        self.assertIn("`snapshot_time` = (SELECT MAX(`snapshot_time`)", sql)
        self.assertEqual(conn.cursor_obj.params[0], "puyue")
        self.assertIn("2026-06-27", conn.cursor_obj.params)
        self.assertGreaterEqual(conn.cursor_obj.params.count("pms"), 2)


if __name__ == "__main__":
    unittest.main()

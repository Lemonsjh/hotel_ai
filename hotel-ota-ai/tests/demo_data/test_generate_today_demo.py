from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.demo_today_generator import generate_today_demo_dataset, generate_today_demo_result


class TestGenerateTodayDemo(unittest.TestCase):
    def test_dataset_is_deterministic_and_safely_marked(self) -> None:
        first = generate_today_demo_dataset(business_date="2026-06-12", seed=20260612, profile="normal")
        second = generate_today_demo_dataset(business_date="2026-06-12", seed=20260612, profile="normal")
        self.assertEqual(first["business_snapshot"], second["business_snapshot"])
        manifest = first["generated_demo_manifest"]
        self.assertEqual(manifest["data_source_type"], "synthetic_today_demo")
        self.assertEqual(manifest["freshness_status"], "synthetic_current_day")
        self.assertTrue(manifest["synthetic_data"])
        self.assertFalse(manifest["real_pms_data"])
        self.assertFalse(manifest["real_ota_data"])
        self.assertFalse(manifest["approval_data_allowed"])
        self.assertFalse(manifest["live_allowed"])
        self.assertGreaterEqual(len(first["room_types"]["room_types"]), 8)
        self.assertGreaterEqual(len(first["competitors"]["competitors"]), 5)
        self.assertGreaterEqual(len(first["price_history"]["price_history"]), 56)
        self.assertGreaterEqual(len(first["reputation"]["reviews"]), 20)
        self.assertGreaterEqual(len(first["customer_segments"]["segments"]), 5)
        for key in [
            "business_snapshot",
            "sales_baseline",
            "progress_deviation",
            "orders_aggregate",
            "market_context",
            "competitors",
            "external_ota_report_fields",
            "room_types",
        ]:
            self.assertEqual(first[key]["business_date"], manifest["business_date"])
            self.assertEqual(first[key]["demo_dataset_id"], manifest["demo_dataset_id"])
        orders = first["orders_aggregate"]
        baseline = first["sales_baseline"]
        progress = first["progress_deviation"]
        market = first["market_context"]
        self.assertIn("expected_occupancy_tonight", orders)
        self.assertIn("stayover_rooms", orders)
        self.assertIn("departure_rooms", orders)
        self.assertIn("reservation_details", orders)
        self.assertEqual(baseline["active_target_source"], "synthetic_today_demo")
        self.assertEqual(baseline["synthetic_today_target_room_nights"], baseline["daily_target_room_nights"])
        self.assertFalse(baseline["sample_target_active"])
        self.assertIn("baseline_price_by_room_type", baseline)
        self.assertGreaterEqual(len(baseline["baseline_price_by_room_type"]), 8)
        for field in [
            "regional_heat_index",
            "historical_same_period_score",
            "traffic_state",
            "current_traffic_score",
            "date_environment_score",
        ]:
            self.assertIn(field, market)
        self.assertIn(market["traffic_state"], {"peak", "valley", "normal"})
        self.assertGreaterEqual(len(progress["hourly_business_snapshots"]), 8)
        for point in progress["hourly_business_snapshots"]:
            for field in [
                "business_date",
                "snapshot_at",
                "as_of_time",
                "hour",
                "sold_rooms",
                "orders_cumulative",
                "occupancy_rate",
                "target_sold_rooms",
                "available_rooms",
                "time_grain",
                "data_source_type",
                "freshness_status",
            ]:
                self.assertIn(field, point)
            self.assertEqual(point["business_date"], manifest["business_date"])
            self.assertEqual(point["time_grain"], "as_of_time")
            self.assertEqual(point["data_source_type"], "synthetic_today_demo")
            self.assertEqual(point["freshness_status"], "synthetic_current_day")
        for room in first["room_types"]["room_types"]:
            self.assertIn("baseline_price", room)
            self.assertIn("expected_occupancy_tonight", room)
            self.assertLessEqual(room["floor_price"], room["conservative_price"])
            self.assertLessEqual(room["conservative_price"], room["ceiling_price"])

    def test_write_fixtures_and_sqlite_are_demo_only(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            output_dir = Path(tmp) / "fixtures"
            db_path = str(Path(tmp) / "today-demo.sqlite")
            args = argparse.Namespace(
                business_date="2026-06-12",
                seed=20260612,
                profile="normal",
                hotel_id="puyue-demo",
                write_db=True,
                write_fixtures=True,
                dry_run=False,
                output_dir=str(output_dir),
                db=db_path,
            )
            result = generate_today_demo_result(args)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data_source_type"], "synthetic_today_demo")
            self.assertFalse(result["approval_data_allowed"])
            self.assertFalse(result["live_allowed"])
            self.assertIn("room_types", result["inserted_tables"])
            self.assertIn("inserted_rows", result)
            self.assertIn("latest_business_date", result)
            self.assertIn("latest_generated_demo_run_id", result)
            self.assertEqual(result["latest_business_date"], "2026-06-12")
            self.assertEqual(result["generated_rows"]["room_types"], 8)
            self.assertTrue((output_dir / "generated_demo_manifest.json").exists())
            self.assertEqual(len(list((output_dir / "nodes").glob("N*.json"))), 22)
            self.assertEqual(len(list((output_dir / "scenarios").glob("SC*.json"))), 10)
            manifest = json.loads((output_dir / "generated_demo_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["data_source_type"], "synthetic_today_demo")
            with closing(sqlite3.connect(db_path)) as conn:
                room_count = conn.execute("SELECT COUNT(*) FROM room_types").fetchone()[0]
                snapshot_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
            self.assertEqual(room_count, 8)
            self.assertGreaterEqual(snapshot_count, 14)

    def test_dry_run_does_not_write_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "dry"
            args = argparse.Namespace(
                business_date="2026-06-12",
                seed=20260612,
                profile="normal",
                hotel_id="puyue-demo",
                write_db=True,
                write_fixtures=True,
                dry_run=True,
                output_dir=str(output_dir),
                db=str(Path(tmp) / "dry.sqlite"),
            )
            result = generate_today_demo_result(args)
            self.assertTrue(result["dry_run"])
            self.assertFalse(result["write_db"])
            self.assertFalse(result["write_fixtures"])
            self.assertFalse(output_dir.exists())

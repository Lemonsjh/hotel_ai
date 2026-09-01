from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing

from runtime.cli import main


def capture_main(argv: list[str]) -> dict:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    payload = json.loads(buffer.getvalue())
    payload["_exit_code"] = code
    return payload


class TestDemoSeedConsistency(unittest.TestCase):
    def test_seed_demo_writes_sqlite_and_snapshot_matches_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "hotel_ops.sqlite")
            result = capture_main(["--db", db_path, "seed-demo"])
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["hotel_id"], "puyue-demo")
            self.assertIn("run_id", result)
            self.assertIn("db_path", result)
            self.assertIn("inserted_rows", result)
            self.assertIn("latest_business_date", result)
            self.assertEqual(result["latest_business_date"], "2026-06-11")

            with closing(sqlite3.connect(db_path)) as conn:
                conn.row_factory = sqlite3.Row
                king = conn.execute(
                    "SELECT floor_price, ceiling_price FROM room_types WHERE hotel_id=? AND room_type_id='KING'",
                    ("puyue-demo",),
                ).fetchone()
                self.assertEqual(king["floor_price"], 158)
                self.assertEqual(king["ceiling_price"], 238)
                snapshot_row = conn.execute(
                    "SELECT payload_json FROM snapshots WHERE hotel_id=? ORDER BY id DESC LIMIT 1",
                    ("puyue-demo",),
                ).fetchone()
            snapshot = json.loads(snapshot_row["payload_json"])
            self.assertEqual(snapshot["total_rooms"], 50)
            self.assertEqual(snapshot["sold_rooms"], 34)
            self.assertEqual(snapshot["occupancy_rate"], 68)

            s02 = capture_main(["--db", db_path, "--demo", "snapshot", "--hotel-id", "puyue-demo"])
            self.assertEqual(s02["status"], "ok")
            self.assertEqual(s02["payload"]["total_rooms"], 50)
            self.assertEqual(s02["payload"]["sold_rooms"], 34)
            self.assertEqual(s02["payload"]["occupancy_rate"], 68)

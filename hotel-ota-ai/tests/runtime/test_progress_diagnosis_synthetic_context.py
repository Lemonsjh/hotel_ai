from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from runtime.decisions.deviation import deviation
from runtime.demo_mode import build_demo_node_result
from runtime.demo_today_generator import generate_today_demo_result


def _seed_synthetic_today(db_path: str, *, business_date: str = "2026-06-16") -> None:
    generate_today_demo_result(
        argparse.Namespace(
            business_date=business_date,
            seed=20260616,
            profile="normal",
            hotel_id="puyue-demo",
            write_db=True,
            write_fixtures=False,
            dry_run=False,
            output_dir=None,
            db=db_path,
        )
    )


def _capture_json(func, namespace: argparse.Namespace) -> dict:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(namespace)
    return json.loads(buffer.getvalue())


class TestProgressDiagnosisSyntheticContext(unittest.TestCase):
    def test_deviation_uses_latest_synthetic_sqlite_when_requested(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            result = _capture_json(
                deviation,
                argparse.Namespace(
                    hotel_id="puyue-demo",
                    db=db_path,
                    date="2026-06-16",
                    use_generated_today=True,
                    strict_generated_today=False,
                    as_of_time="16:40",
                ),
            )

        self.assertIn(result["status"], {"ok", "preview_only"})
        self.assertEqual(result["node_id"], "N011")
        self.assertEqual(result["skill_id"], "S16")
        self.assertEqual(result["context_source"], "sqlite_synthetic_today_demo")
        self.assertEqual(result["data_source_type"], "synthetic_today_demo")
        self.assertEqual(result["business_date"], "2026-06-16")
        self.assertEqual(result["as_of_time"], "16:40")
        self.assertGreaterEqual(len(result["actual_hourly_sales"]), 8)
        self.assertGreaterEqual(len(result["target_hourly_curve"]), 8)
        self.assertLess(result["as_of_actual_sold_rooms"], 34)
        self.assertFalse(result["formal_approval_created"])
        self.assertFalse(result["live_allowed"])

    def test_demo_node_n011_exposes_actual_hourly_sales_and_target_curve(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            node = build_demo_node_result(
                "N011",
                db_path=db_path,
                use_generated_today=True,
                as_of_time="16:40",
                as_of_time_source="test",
            )

        result = node["node_result"]
        self.assertEqual(result["node_id"], "N011")
        self.assertEqual(result["skill_id"], "S16")
        self.assertEqual(result["context_source"], "sqlite_synthetic_today_demo")
        self.assertGreaterEqual(len(result["actual_hourly_sales"]), 8)
        self.assertGreaterEqual(len(result["target_hourly_curve"]), 8)
        self.assertIn("as_of_checkpoint_gap", result)
        self.assertFalse(result["formal_approval_created"])
        self.assertFalse(result["live_allowed"])

    def test_deviation_still_reports_data_gap_without_synthetic_or_real_data(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "empty.sqlite")

            result = _capture_json(
                deviation,
                argparse.Namespace(
                    hotel_id="puyue-demo",
                    db=db_path,
                    date="2026-06-16",
                    use_generated_today=True,
                    strict_generated_today=True,
                    as_of_time="16:40",
                ),
            )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["blocked_reason"], "strict_generated_today_no_static_fallback")
        self.assertFalse(result["formal_approval_created"])
        self.assertFalse(result["live_allowed"])

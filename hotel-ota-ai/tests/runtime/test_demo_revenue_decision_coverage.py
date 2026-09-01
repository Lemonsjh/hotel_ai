from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from runtime.cli import main
from runtime.cli import build_parser


def capture_main(argv: list[str]) -> dict:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    payload = json.loads(buffer.getvalue())
    payload["_exit_code"] = code
    return payload


class TestDemoRevenueDecisionCoverage(unittest.TestCase):
    def test_generator_keeps_its_synthetic_hotel_default(self) -> None:
        args = build_parser().parse_args(["generate-today-demo", "--write-db"])

        self.assertEqual(args.hotel_id, "puyue-demo")

    def test_demo_revenue_decision_uses_latest_generated_sqlite_and_is_preview_only(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "latest-demo.sqlite")
            generated = capture_main(
                [
                    "--db",
                    db_path,
                    "generate-today-demo",
                    "--business-date",
                    "2026-06-15",
                    "--seed",
                    "20260615",
                    "--write-db",
                ]
            )
            result = capture_main(["--db", db_path, "--demo", "revenue-decision", "--hotel-id", "puyue-demo"])

        self.assertEqual(generated["status"], "ok")
        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(result["data_source_type"], "synthetic_today_demo")
        self.assertEqual(result["run_context"]["context_source"], "sqlite_synthetic_today_demo")
        self.assertFalse(result["formal_approval_allowed"])
        self.assertFalse(result["formal_approval_created"])
        self.assertFalse(result["live_allowed"])
        self.assertEqual(result["live_execution_count"], 0)
        self.assertTrue(result["approval_preview_allowed"])
        self.assertIn("demo_approval_preview_id", result)
        self.assertIn("expected_occupancy_tonight", result)
        self.assertIn("baseline_price_by_room_type", result)
        self.assertTrue(result["demo_required_inputs_covered"])

    def test_strict_generated_today_revenue_returns_data_gap_when_no_generated_run_exists(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "empty.sqlite")
            result = capture_main(
                [
                    "--db",
                    db_path,
                    "--demo",
                    "demo-node",
                    "--node",
                    "N015",
                    "--use-generated-today",
                    "--strict-generated-today",
                ]
            )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["blocked_reason"], "strict_generated_today_no_static_fallback")


if __name__ == "__main__":
    unittest.main()

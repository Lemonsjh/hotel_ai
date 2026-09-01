from __future__ import annotations

import argparse
import io
import json
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest import mock

from runtime.decisions.baseline import _curve_policy, _hourly_curve, baseline
from runtime.storage import connect
from tests.runtime.test_sales_progress_real_field import FakeRepository


def _capture(args: argparse.Namespace) -> dict:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        baseline(args)
    return json.loads(buffer.getvalue())


class BaselineHourlyCurveTests(unittest.TestCase):
    def test_legacy_anchor_helper_is_advisory_only(self) -> None:
        curve = _hourly_curve(29)
        self.assertEqual(curve[-1]["target_room_nights"], 29)
        policy = _curve_policy("derived_default_anchor")
        self.assertTrue(policy["default_anchor_curve"])
        self.assertFalse(policy["s16_deviation_allowed"])
        self.assertEqual(policy["baseline_status"], "advisory_only")

    def test_real_field_policy_authorizes_s16_comparison(self) -> None:
        policy = _curve_policy("pms_room_type_hourly_status")
        self.assertTrue(policy["historical_curve"])
        self.assertTrue(policy["s16_deviation_allowed"])
        self.assertEqual(policy["baseline_status"], "real_field_baseline")

    def test_baseline_uses_real_hourly_rows_and_persists_compatibility_contract(self) -> None:
        repo = FakeRepository()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch(
            "runtime.decisions.baseline.DirectSalesProgressRepository.from_environment",
            return_value=repo,
        ):
            db_path = str(Path(tmp) / "baseline.sqlite")
            result = _capture(
                argparse.Namespace(
                    db=db_path,
                    hotel_id="hotel-a",
                    date=repo.target.isoformat(),
                    as_of_time=f"{repo.target} 23:59:59",
                )
            )
        payload = result["baseline"]
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["hourly_curve_source"], "pms_room_type_hourly_status")
        self.assertEqual(len(payload["hourly_target_curve"]), 24)
        self.assertFalse(payload["sample_target_active"])
        self.assertEqual(payload["hourly_curve"], payload["hourly_target_curve"])
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                "SELECT payload_json FROM baselines WHERE hotel_id=? AND business_date=?",
                ("hotel-a", repo.target.isoformat()),
            ).fetchone()
        self.assertIsNotNone(row)


if __name__ == "__main__":
    unittest.main()

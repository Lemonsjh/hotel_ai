from __future__ import annotations

import argparse
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.decisions.baseline import baseline
from runtime.decisions.deviation import deviation
from tests.runtime.test_sales_progress_real_field import FakeRepository


def capture_json(func, namespace: argparse.Namespace) -> dict:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(namespace)
    return json.loads(buffer.getvalue())


class TestRoomNightProgressContract(unittest.TestCase):
    def test_s15_emits_real_field_contract_with_legacy_aliases(self) -> None:
        repo = FakeRepository()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch(
            "runtime.decisions.baseline.DirectSalesProgressRepository.from_environment",
            return_value=repo,
        ):
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            result = capture_json(
                baseline,
                argparse.Namespace(
                    hotel_id="hotel-a",
                    date=repo.target.isoformat(),
                    as_of_time=f"{repo.target} 23:59:59",
                    db=db_path,
                ),
            )
        payload = result["baseline"]
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["target_room_nights"], payload["target_orders"])
        self.assertEqual(payload["hourly_target_curve"], payload["hourly_curve"])
        self.assertEqual(payload["hourly_curve_source"], "pms_room_type_hourly_status")
        self.assertEqual(len(payload["hourly_target_curve"]), 24)
        self.assertEqual(len(payload["progress_checkpoints"]), 6)
        self.assertIn("room_types", payload["sales_baseline"])
        self.assertFalse(payload["sample_target_active"])

    def test_s16_uses_forecast_committed_sold_not_occupied_or_jd01_jd04(self) -> None:
        repo = FakeRepository()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch(
            "runtime.decisions.baseline.DirectSalesProgressRepository.from_environment",
            return_value=repo,
        ), mock.patch(
            "runtime.decisions.deviation.DirectSalesProgressRepository.from_environment",
            return_value=repo,
        ):
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            capture_json(
                baseline,
                argparse.Namespace(
                    hotel_id="hotel-a",
                    date=repo.target.isoformat(),
                    as_of_time=f"{repo.target} 23:59:59",
                    db=db_path,
                ),
            )
            result = capture_json(
                deviation,
                argparse.Namespace(
                    hotel_id="hotel-a",
                    date=repo.target.isoformat(),
                    as_of_time=f"{repo.target} 16:30:00",
                    db=db_path,
                ),
            )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["actual_room_nights"], 14)
        self.assertEqual(result["actual_orders"], 14)
        self.assertEqual(result["actual_source"], "pms_room_type_forecast.committed_sold")
        self.assertNotEqual(result["actual_room_nights"], 9)
        self.assertIn("hotel_result", result)
        self.assertEqual(len(result["room_type_results"]), 2)
        self.assertIn("structure_summary", result)
        self.assertEqual(
            result["room_night_gap"],
            result["actual_room_nights"] - result["checkpoint_target_room_nights"],
        )

    def test_future_stay_date_is_not_compared_to_same_day_curve(self) -> None:
        repo = FakeRepository()
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, mock.patch(
            "runtime.decisions.baseline.DirectSalesProgressRepository.from_environment",
            return_value=repo,
        ), mock.patch(
            "runtime.decisions.deviation.DirectSalesProgressRepository.from_environment",
            return_value=repo,
        ):
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            capture_json(
                baseline,
                argparse.Namespace(
                    hotel_id="hotel-a",
                    date=repo.target.isoformat(),
                    as_of_time=f"{repo.target} 23:59:59",
                    db=db_path,
                ),
            )
            result = capture_json(
                deviation,
                argparse.Namespace(
                    hotel_id="hotel-a",
                    date=repo.target.isoformat(),
                    as_of_time="2026-08-07 16:00:00",
                    db=db_path,
                ),
            )
        self.assertEqual(result["status"], "not_applicable")
        self.assertEqual(result["reason"], "future_stay_date_requires_lead_time_baseline")
        self.assertEqual(result["progress_status"], "data_gap")


if __name__ == "__main__":
    unittest.main()

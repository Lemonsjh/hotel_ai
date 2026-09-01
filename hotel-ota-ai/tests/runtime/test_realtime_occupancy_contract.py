from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.common import json_dumps
from runtime.cli import main
from runtime.decisions.baseline import baseline
from runtime.decisions.deviation import deviation
from runtime.decisions.realtime_occupancy import build_realtime_occupancy
from runtime.decisions.pricing import expected_occupancy_result
from runtime.storage import connect, init_schema


TARGET_DATE = "2026-07-02"
AS_OF_TIME = "2026-07-02 13:00:00"


def _capture_json(func, *args):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(*args)
    return json.loads(buffer.getvalue())


def _realtime_template(template: str, hotel_id: str, **kwargs):
    if template == "operating_snapshot":
        return {
            "status": "ok",
            "payload": {
                "total_rooms": 5,
                "maintenance_rooms": 1,
                "dirty_rooms": 2,
                "unavailable_rooms_tonight": 3,
                "freshness_status": "fresh",
                "data_business_date": TARGET_DATE,
                "data_snapshot_time": AS_OF_TIME,
            },
        }
    if template == "reservation_snapshot":
        return {
            "status": "ok",
            "payload": {
                "new_arrival_rooms": 2,
                "jd01_reserved_raw_arrival_today": 2,
                "jd01_cancelled_arrival_today": 1,
                "freshness_status": "fresh",
                "data_business_date": TARGET_DATE,
                "data_snapshot_time": AS_OF_TIME,
                "realtime_rows": [
                    {
                        "room_no": "101",
                        "order_id": "A",
                        "booking_status": "已入住",
                        "arrival_time": "2026-07-01 15:00:00",
                        "departure_time": "2026-07-02 18:00:00",
                    },
                    {
                        "room_no": "102",
                        "order_id": "B",
                        "booking_status": "预订",
                        "arrival_time": "2026-07-02 15:00:00",
                        "departure_time": "2026-07-03 12:00:00",
                    },
                    {
                        "room_no": "105",
                        "order_id": "C",
                        "booking_status": "取消",
                        "arrival_time": "2026-07-02 15:00:00",
                    },
                ],
            },
        }
    if template == "stayover_snapshot":
        return {
            "status": "ok",
            "payload": {
                "stayover_rooms": 2,
                "freshness_status": "fresh",
                "data_business_date": TARGET_DATE,
                "data_snapshot_time": AS_OF_TIME,
                "realtime_rows": [
                    {"room_no": "102", "order_id": "DUP", "checkout_time": "2026-07-02 20:00:00"},
                    {"room_no": "104", "order_id": "D", "checkout_time": "2026-07-02 16:00:00"},
                    {"room_no": "106", "order_id": "OLD", "checkout_time": "2026-07-02 10:00:00"},
                ],
            },
        }
    if template in {"daily_metrics", "monthly_metrics", "operation_diagnosis", "order_snapshot"}:
        return {
            "status": "ok",
            "payload": {
                "normalized_metrics": {"room_nights": 4, "room_count": 5, "occupancy_rate": 0.8},
                "freshness_status": "fresh",
                "data_business_date": TARGET_DATE,
                "data_snapshot_time": AS_OF_TIME,
            },
        }
    return {"status": "data_gap", "reason": f"unexpected_template:{template}"}


class RealtimeOccupancyContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = os.environ.copy()
        os.environ["HOTEL_OTA_DB_SOURCE_ENABLE"] = "1"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_s5_expected_occupancy_uses_unified_realtime_formula(self) -> None:
        with mock.patch("runtime.decisions.pricing.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.pricing.database_template_result", side_effect=_realtime_template
        ):
            result = expected_occupancy_result(argparse.Namespace(hotel_id="puyue", date=TARGET_DATE, as_of_time=AS_OF_TIME))

        self.assertEqual(result["formula_version"], "jd01_jd04_kf11_realtime_occupancy_v1")
        self.assertEqual(result["actual_numerator_rooms"], 3)
        self.assertEqual(result["denominator_rooms"], 4)
        self.assertEqual(result["maintenance_rooms"], 1)
        self.assertEqual(result["dirty_rooms"], 2)
        self.assertEqual(result["expected_occupancy_tonight"], 0.75)
        self.assertEqual(result["sellable_rooms_tonight"], 4)
        self.assertIn("kf11_occupied_rooms", result)
        self.assertIn("kf11_formula_gap_rooms", result)
        self.assertEqual(
            result["reservation_adjustment_components"],
            {"jd01_reserved_raw_arrival_today": 2, "jd01_cancelled_arrival_today": 1},
        )
        self.assertFalse(result["duplicate_risk"])

    def test_realtime_occupancy_requires_business_as_of_time_not_snapshot_time(self) -> None:
        result = build_realtime_occupancy(
            operating_payload={
                "total_rooms": 31,
                "maintenance_rooms": 0,
                "data_snapshot_time": "2026-07-04 20:14:44",
            },
            reservation_payload={
                "jd01_checked_in_departure_after_as_of": 12,
                "jd01_reserved_arrival_today": 4,
                "data_snapshot_time": "2026-07-04 11:37:20",
            },
            stayover_payload={
                "jd04_checkout_after_as_of": 6,
                "data_snapshot_time": "2026-07-04 11:36:09",
            },
            business_date="2026-07-04",
            as_of_time=None,
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["reason"], "realtime_occupancy_as_of_time_required")
        self.assertIsNone(result.get("actual_occupancy_rate"))
        self.assertNotEqual(result.get("as_of_time"), "2026-07-04 20:14:44")

    def test_expected_occupancy_does_not_use_daily_metrics_as_realtime_fallback(self) -> None:
        calls: list[tuple[str, dict]] = []

        def fake_template(template: str, hotel_id: str, **kwargs):
            calls.append((template, dict(kwargs)))
            if template == "daily_metrics":
                return {
                    "status": "ok",
                    "payload": {
                        "normalized_metrics": {"room_count": 31, "room_nights": 17, "occupancy_rate": 0.5484},
                        "freshness_status": "stale",
                        "data_business_date": "2026-07-04",
                        "data_snapshot_time": "2026-07-04 23:59:00",
                    },
                }
            return {"status": "data_gap", "reason": f"{template}_missing", "payload": {}}

        with mock.patch("runtime.decisions.pricing.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.pricing.database_template_result", side_effect=fake_template
        ):
            result = expected_occupancy_result(
                argparse.Namespace(hotel_id="puyue", date="2026-07-05", as_of_time="2026-07-05 15:25:00")
            )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["data_business_date"], "2026-07-05")
        self.assertNotEqual(result.get("actual_occupancy_rate"), 0.5484)
        self.assertNotIn(("daily_metrics", {"date": "2026-07-05"}), calls)
        self.assertFalse(any(template == "daily_metrics" and kwargs.get("date") is None for template, kwargs in calls))

    def test_s16_deviation_uses_occupancy_rate_as_primary_progress_metric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "ops.sqlite")
            with contextlib.closing(connect(db_path)) as conn:
                init_schema(conn)
                with conn:
                    conn.execute(
                        """
                        INSERT INTO baselines (hotel_id, business_date, payload_json, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            "puyue",
                            TARGET_DATE,
                            json_dumps(
                                {
                                    "target_room_nights": 4,
                                    "target_room_count": 4,
                                    "target_daily_occupancy_rate": 1.0,
                                    "progress_checkpoints": [
                                        {
                                            "hour": 12,
                                            "checkpoint": "midday",
                                            "checkpoint_target_occupancy_rate": 0.8,
                                            "source_confidence": "high",
                                        }
                                    ],
                                    "freshness_status": "fresh",
                                    "data_business_date": TARGET_DATE,
                                }
                            ),
                            AS_OF_TIME,
                        ),
                    )
            with mock.patch("runtime.decisions.deviation.database_source_enabled", return_value=True), mock.patch(
                "runtime.decisions.deviation.database_template_result", side_effect=_realtime_template
            ), mock.patch("runtime.decisions.deviation._active_checkpoint", return_value={"hour": 12, "checkpoint": "midday", "ratio": 0.34}):
                result = _capture_json(deviation, argparse.Namespace(hotel_id="puyue", db=db_path, date=TARGET_DATE, as_of_time=AS_OF_TIME))

        self.assertEqual(result["formula_version"], "jd01_jd04_kf11_realtime_occupancy_v1")
        self.assertEqual(result["actual_occupancy_rate"], 0.75)
        self.assertEqual(result["target_occupancy_rate"], 0.8)
        self.assertEqual(result["occupancy_gap"], -0.05)
        self.assertEqual(result["progress_basis"], "occupancy_rate_checkpoint")
        self.assertIn("kf11_occupied_rooms", result)
        self.assertIn("kf11_formula_gap_rooms", result)
        self.assertEqual(result["actual_room_nights_evidence_role"], "auxiliary")
        self.assertFalse(result["pricing_candidate_allowed"])

    def test_baseline_fallback_curve_is_low_confidence_and_not_auto_pricing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "ops.sqlite")

            def fake_template(template: str, hotel_id: str, **kwargs):
                if template == "daily_metrics":
                    return {
                        "status": "ok",
                        "payload": {
                            "normalized_metrics": {"room_count": 31, "room_nights": 26, "occupancy_rate": 0.8387},
                            "freshness_status": "stale",
                            "data_business_date": "2026-06-30",
                            "data_snapshot_time": "2026-06-30 23:59:00",
                        },
                    }
                return {"status": "data_gap", "reason": f"{template}_missing"}

            with mock.patch("runtime.decisions.baseline.database_source_enabled", return_value=True), mock.patch(
                "runtime.decisions.baseline.database_template_result", side_effect=fake_template
            ), mock.patch("runtime.decisions.baseline.build_historical_hourly_curve", return_value={"status": "data_gap", "reason": "booking_curve_missing"}):
                result = _capture_json(baseline, argparse.Namespace(db=db_path, hotel_id="puyue", date=TARGET_DATE))

        payload = result["baseline"]
        self.assertEqual(payload["hourly_curve_source"], "fallback_ratio_curve")
        self.assertEqual(payload["source_confidence"], "low")
        self.assertFalse(payload["hourly_curve_policy"]["fallback_curve_allows_auto_pricing"])
        self.assertEqual(payload["sales_baseline"]["target_room_count"], 31)
        self.assertEqual(payload["target_daily_occupancy_rate"], 0.8387)
        checkpoints = payload["progress_checkpoints"]
        self.assertTrue(all("checkpoint_target_occupancy_rate" in item for item in checkpoints))

    def test_jy01_rs01_alignment_command_filters_room_fee_charge_subject(self) -> None:
        def fake_template(template: str, hotel_id: str, **kwargs):
            if template == "daily_metrics":
                return {
                    "status": "ok",
                    "payload": {
                        "normalized_metrics": {"room_count": 31, "room_nights": 26},
                        "freshness_status": "stale",
                        "data_business_date": TARGET_DATE,
                    },
                }
            if template == "room_fee_daily":
                return {
                    "status": "ok",
                    "payload": {
                        "rows": [
                            {"business_date": TARGET_DATE, "room_nights": 20, "charge_subject": "房费"},
                            {"business_date": TARGET_DATE, "room_nights": 6, "charge_subject": "房费"},
                            {"business_date": TARGET_DATE, "room_nights": 1, "charge_subject": "加收全天"},
                        ],
                        "freshness_status": "stale",
                        "data_business_date": TARGET_DATE,
                    },
                }
            return {"status": "data_gap", "reason": f"{template}_unexpected"}

        with mock.patch("runtime.decisions.daily_alignment.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.daily_alignment.database_template_result", side_effect=fake_template
        ):
            result = _capture_json(main, ["jy01-rs01-alignment", "--hotel-id", "puyue", "--date", TARGET_DATE])

        self.assertEqual(result["status"], "ok")
        row = result["alignment_rows"][0]
        self.assertEqual(row["business_date"], TARGET_DATE)
        self.assertEqual(row["jy01_room_count"], 31)
        self.assertEqual(row["jy01_room_nights"], 26)
        self.assertEqual(row["rs01_room_nights_room_fee_only"], 26)
        self.assertEqual(row["rs01_room_nights_all_charge_subjects"], 27)
        self.assertEqual(row["difference"], 0)
        self.assertEqual(row["match_status"], "match")
        self.assertIn("rs01_non_room_fee_charge_subjects_excluded", result["diagnostics"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import contextlib
import io
import json
import unittest
from unittest import mock

from runtime.decisions.deviation import deviation
from runtime.decisions.ota_health import conversion_diagnosis, ota_health
from runtime.decisions.pricing import revenue_decision


def _capture_json(func, args: argparse.Namespace) -> dict:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(args)
    return json.loads(buffer.getvalue())


def _data_gap_template(template: str, hotel_id: str, **kwargs) -> dict:
    return {"status": "data_gap", "reason": f"{template}_missing_real_data", "payload": {}}


class TestProductionSampleGuard(unittest.TestCase):
    def test_ota_health_db_enabled_real_scores_do_not_keep_sample_markers(self) -> None:
        def fake_template(template: str, hotel_id: str, **kwargs) -> dict:
            if template == "operation_diagnosis":
                return {
                    "status": "ok",
                    "payload": {
                        "hos_score": 8.7,
                        "ota_health_score": 82,
                        "data_source_type": "mysql_runtime",
                        "freshness_status": "fresh",
                        "business_status": "current",
                        "risk_flags": [],
                    },
                }
            if template == "operating_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "total_rooms": 31,
                        "maintenance_rooms": 0,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-02",
                        "data_snapshot_time": "2026-07-02 13:00:00",
                    },
                }
            if template == "reservation_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "new_arrival_rooms": 2,
                        "jd01_checked_in_departure_after_as_of": 0,
                        "jd01_reserved_arrival_today": 2,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-02",
                        "data_snapshot_time": "2026-07-02 13:00:00",
                    },
                }
            if template == "stayover_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "stayover_rooms": 1,
                        "jd04_checkout_after_as_of": 1,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-02",
                        "data_snapshot_time": "2026-07-02 13:00:00",
                    },
                }
            return _data_gap_template(template, hotel_id, **kwargs)

        with mock.patch("runtime.decisions.ota_health.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.ota_health.database_template_result", side_effect=fake_template
        ):
            result = _capture_json(ota_health, argparse.Namespace(hotel_id="puyue"))

        self.assertEqual(result["status"], "ok")
        evidence = result.get("evidence") or {}
        self.assertEqual(evidence.get("hos_score"), 8.7)
        self.assertEqual(evidence.get("ota_health_score"), 82)
        self.assertEqual(evidence.get("data_source_type"), "mysql_runtime")
        realtime = evidence.get("realtime_occupancy") or {}
        self.assertEqual(realtime.get("formula_version"), "jd01_jd04_kf11_realtime_occupancy_v1")
        self.assertEqual(realtime.get("actual_numerator_rooms"), 3)
        self.assertEqual(realtime.get("denominator_rooms"), 31)
        self.assertEqual(realtime.get("actual_occupancy_rate"), 0.0968)
        text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("sample_data", text)
        self.assertNotIn("demo_data", text)

    def test_ota_health_db_enabled_does_not_call_sample_snapshot(self) -> None:
        def fake_template(template: str, hotel_id: str, **kwargs) -> dict:
            if template == "operation_diagnosis":
                return {"status": "ok", "payload": {"hos_score": 8.7, "ota_health_score": 82, "freshness_status": "fresh", "business_status": "current"}}
            return _data_gap_template(template, hotel_id, **kwargs)

        with mock.patch("runtime.decisions.ota_health.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.ota_health.database_template_result", side_effect=fake_template
        ), mock.patch("runtime.decisions.ota_health.sample_snapshot", side_effect=AssertionError("sample_snapshot must not be called in production")):
            result = _capture_json(ota_health, argparse.Namespace(hotel_id="puyue"))

        self.assertEqual(result["status"], "ok")

    def test_conversion_diagnosis_db_enabled_missing_real_data_does_not_emit_sample_metrics(self) -> None:
        with mock.patch("runtime.decisions.ota_health.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.ota_health.database_template_result", side_effect=_data_gap_template
        ):
            result = _capture_json(conversion_diagnosis, argparse.Namespace(hotel_id="puyue", debug=False))

        self.assertEqual(result["status"], "data_gap")
        evidence = result.get("evidence") or {}
        self.assertIsNone(evidence.get("exposure"))
        self.assertIsNone(evidence.get("views"))
        self.assertIsNone(evidence.get("paid_orders"))
        self.assertIsNone(evidence.get("payment_conversion_rate"))
        text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("sample_data", text)
        self.assertNotIn("demo_data", text)

    def test_revenue_decision_db_enabled_missing_real_data_does_not_emit_sample_snapshot(self) -> None:
        args = argparse.Namespace(
            hotel_id="puyue",
            channel="Mtop",
            begin_date="2026-07-02",
            end_date="2026-07-02",
            date="2026-07-02",
            activity_discount_factors=None,
            pms_price=None,
            db=":memory:",
            demo=False,
        )
        with mock.patch("runtime.decisions.pricing.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.pricing.database_template_result", side_effect=_data_gap_template
        ):
            result = _capture_json(revenue_decision, args)

        self.assertEqual(result["status"], "data_gap")
        evidence = ((result.get("decision") or {}).get("evidence") or {})
        for key in ("market_orders_today", "market_orders_last_week_same_time", "hos_score", "ota_health_score", "demand_index"):
            self.assertNotIn(key, evidence)
        self.assertNotEqual(evidence.get("data_source_type"), "sample_data")
        self.assertNotIn("sample_data", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("demo_data", json.dumps(result, ensure_ascii=False))

    def test_deviation_db_enabled_missing_real_data_does_not_emit_sample_snapshot(self) -> None:
        args = argparse.Namespace(hotel_id="puyue", date="2026-07-02", db=":memory:", use_generated_today=False, strict_generated_today=False, as_of_time=None)
        with mock.patch("runtime.decisions.deviation.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.deviation.database_template_result", side_effect=_data_gap_template
        ):
            result = _capture_json(deviation, args)

        self.assertEqual(result["status"], "data_gap")
        evidence = result.get("evidence") or {}
        for key in ("market_orders_today", "market_orders_last_week_same_time", "hos_score", "ota_health_score", "demand_index"):
            self.assertNotIn(key, evidence)
        self.assertNotEqual(result.get("data_source"), "sample_data")
        text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("sample_data", text)
        self.assertNotIn("demo_data", text)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
import contextlib
import io
import json
import unittest
from unittest import mock

from runtime.decisions.deviation import deviation
from runtime.decisions.pricing import expected_occupancy_result
from runtime.decisions.realtime_occupancy import build_realtime_occupancy


class RealtimeOccupancySourceConflictTests(unittest.TestCase):
    def test_generic_aggregates_do_not_become_realtime_formula_evidence(self) -> None:
        result = build_realtime_occupancy(
            operating_payload={
                "total_rooms": 31,
                "maintenance_rooms": 0,
                "data_snapshot_time": "2026-07-04 16:25:00",
            },
            reservation_payload={
                "new_arrival_rooms": 5,
                "data_business_date": "2026-07-04",
                "data_snapshot_time": "2026-07-04 16:25:00",
            },
            stayover_payload={
                "stayover_rooms": 7,
                "data_business_date": "2026-07-04",
                "data_snapshot_time": "2026-07-04 16:25:00",
            },
            business_date="2026-07-04",
            as_of_time="2026-07-04 16:25:00",
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["reason"], "realtime_occupancy_formula_evidence_missing")
        self.assertNotIn("actual_occupancy_rate", result)
        self.assertEqual(
            result["missing_formula_components"],
            ["jd01_checked_in_departure_after_as_of", "jd01_reserved_arrival_today", "jd04_checkout_after_as_of"],
        )

    def test_explicit_sql_formula_components_are_valid_without_row_evidence(self) -> None:
        result = build_realtime_occupancy(
            operating_payload={
                "total_rooms": 31,
                "maintenance_rooms": 0,
                "rows": [
                    *[{"room_no": f"2{i:02d}", "room_status": "住脏"} for i in range(1, 17)],
                    *[{"room_no": f"3{i:02d}", "room_status": "空净"} for i in range(1, 16)],
                ],
            },
            reservation_payload={
                "jd01_checked_in_departure_after_as_of": 13,
                "jd01_reserved_raw_arrival_today": 5,
                "jd01_reserved_arrival_today": 2,
                "jd01_cancelled_arrival_today": 3,
                "data_business_date": "2026-07-04",
                "data_snapshot_time": "2026-07-04 16:25:00",
            },
            stayover_payload={
                "jd04_checkout_after_as_of": 1,
                "data_business_date": "2026-07-04",
                "data_snapshot_time": "2026-07-04 16:25:00",
            },
            business_date="2026-07-04",
            as_of_time="2026-07-04 16:25:00",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["actual_numerator_rooms"], 16)
        self.assertEqual(result["denominator_rooms"], 31)
        self.assertEqual(result["actual_occupancy_rate"], 0.5161)
        self.assertEqual(result["numerator_components"]["jd01_checked_in_departure_after_as_of"], 13)
        self.assertEqual(result["numerator_components"]["jd01_reserved_arrival_today"], 2)
        self.assertEqual(result["numerator_components"]["jd04_checkout_after_as_of"], 1)
        self.assertEqual(
            result["reservation_adjustment_components"],
            {"jd01_reserved_raw_arrival_today": 5, "jd01_cancelled_arrival_today": 3},
        )
        self.assertFalse(result["aggregate_fallback"])

    def test_kf11_occupied_rooms_is_auxiliary_not_realtime_occupancy_numerator(self) -> None:
        operating_payload = {
            "total_rooms": 31,
            "maintenance_rooms": 0,
            "dirty_rooms": 24,
            "data_snapshot_time": "2026-07-03 10:44:30",
            "rows": [
                *[
                    {
                        "room_no": f"2{i:02d}",
                        "room_status": "住脏",
                        "checkout_time": "2026-07-03 14:00:00",
                    }
                    for i in range(1, 25)
                ],
                *[
                    {
                        "room_no": f"3{i:02d}",
                        "room_status": "空净",
                    }
                    for i in range(1, 8)
                ],
            ],
        }
        reservation_payload = {
            "data_business_date": "2026-07-03",
            "data_snapshot_time": "2026-07-03 10:44:30",
            "realtime_rows": [
                {
                    "room_no": f"4{i:02d}",
                    "order_id": f"R{i}",
                    "booking_status": "reserved",
                    "arrival_time": "2026-07-03 15:00:00",
                    "departure_time": "2026-07-04 12:00:00",
                }
                for i in range(1, 6)
            ],
        }
        stayover_payload = {
            "data_business_date": "2026-07-03",
            "data_snapshot_time": "2026-07-03 10:44:30",
            "realtime_rows": [
                {
                    "room_no": f"5{i:02d}",
                    "order_id": f"S{i}",
                    "checkout_time": "2026-07-03 14:00:00",
                }
                for i in range(1, 8)
            ],
        }

        result = build_realtime_occupancy(
            operating_payload=operating_payload,
            reservation_payload=reservation_payload,
            stayover_payload=stayover_payload,
            business_date="2026-07-03",
            as_of_time="2026-07-03 11:06:14",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["kf11_occupied_rooms"], 24)
        self.assertEqual(result["actual_numerator_rooms"], 12)
        self.assertEqual(result["denominator_rooms"], 31)
        self.assertEqual(result["actual_occupancy_rate"], 0.3871)
        self.assertEqual(result["occupancy_rate_source"], "jd01_jd04_over_kf11_total_minus_maintenance")

    def test_deviation_uses_formula_rate_even_when_kf11_occupied_count_differs(self) -> None:
        def fake_template(template: str, hotel_id: str, **kwargs) -> dict:
            if template == "operating_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "total_rooms": 31,
                        "maintenance_rooms": 0,
                        "dirty_rooms": 24,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 10:44:30",
                        "rows": [
                            *[{"room_no": f"2{i:02d}", "room_status": "住脏"} for i in range(1, 25)],
                            *[{"room_no": f"3{i:02d}", "room_status": "空净"} for i in range(1, 8)],
                        ],
                    },
                }
            if template == "reservation_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "new_arrival_rooms": 5,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 10:44:30",
                        "realtime_rows": [
                            {
                                "room_no": f"4{i:02d}",
                                "order_id": f"R{i}",
                                "booking_status": "reserved",
                                "arrival_time": "2026-07-03 15:00:00",
                                "departure_time": "2026-07-04 12:00:00",
                            }
                            for i in range(1, 6)
                        ],
                    },
                }
            if template == "stayover_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "stayover_rooms": 7,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 10:44:30",
                        "realtime_rows": [
                            {
                                "room_no": f"5{i:02d}",
                                "order_id": f"S{i}",
                                "checkout_time": "2026-07-03 14:00:00",
                            }
                            for i in range(1, 8)
                        ],
                    },
                }
            if template == "daily_metrics":
                return {
                    "status": "ok",
                    "payload": {
                        "normalized_metrics": {"room_nights": 26, "room_count": 31},
                        "freshness_status": "stale",
                        "data_business_date": "2026-07-02",
                    },
                }
            return {"status": "data_gap", "reason": f"{template}_missing", "payload": {}}

        buffer = io.StringIO()
        with mock.patch("runtime.decisions.deviation.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.deviation.database_template_result", side_effect=fake_template
        ), contextlib.redirect_stdout(buffer):
            deviation(argparse.Namespace(hotel_id="puyue", db=":memory:", date="2026-07-03", as_of_time="2026-07-03 11:06:14"))

        result = json.loads(buffer.getvalue())
        self.assertEqual(result["actual_occupancy_rate"], 0.3871)
        self.assertEqual(result["actual_numerator_rooms"], 12)
        self.assertEqual(result["denominator_rooms"], 31)
        self.assertIsNone(result["source_conflict_reason"])
        text = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("sample_data", text)
        self.assertNotIn("market_orders_today", text)

    def test_expected_occupancy_uses_formula_rate_even_when_kf11_occupied_count_differs(self) -> None:
        def fake_template(template: str, hotel_id: str, **kwargs) -> dict:
            if template == "operating_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "total_rooms": 31,
                        "maintenance_rooms": 0,
                        "dirty_rooms": 0,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 10:44:30",
                    },
                }
            if template == "room_status_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "row_count": 31,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 10:44:30",
                        "rows": [
                            *[{"room_no": f"2{i:02d}", "room_status": "occupied"} for i in range(1, 25)],
                            *[{"room_no": f"3{i:02d}", "room_status": "vacant"} for i in range(1, 8)],
                        ],
                    },
                }
            if template == "reservation_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "new_arrival_rooms": 5,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 10:44:30",
                        "realtime_rows": [
                            {
                                "room_no": f"4{i:02d}",
                                "order_id": f"R{i}",
                                "booking_status": "reserved",
                                "arrival_time": "2026-07-03 15:00:00",
                                "departure_time": "2026-07-04 12:00:00",
                            }
                            for i in range(1, 6)
                        ],
                    },
                }
            if template == "stayover_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "stayover_rooms": 7,
                        "freshness_status": "fresh",
                        "data_business_date": "2026-07-03",
                        "data_snapshot_time": "2026-07-03 10:44:30",
                        "realtime_rows": [
                            {
                                "room_no": f"5{i:02d}",
                                "order_id": f"S{i}",
                                "checkout_time": "2026-07-03 14:00:00",
                            }
                            for i in range(1, 8)
                        ],
                    },
                }
            return {"status": "data_gap", "reason": f"{template}_missing", "payload": {}}

        with mock.patch("runtime.decisions.pricing.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.pricing.database_template_result", side_effect=fake_template
        ):
            result = expected_occupancy_result(
                argparse.Namespace(hotel_id="puyue", date="2026-07-03", as_of_time="2026-07-03 11:06:14")
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["expected_occupancy_status"], "confirmed")
        self.assertNotIn("pricing_blocked_reason", result)
        self.assertNotIn("source_conflict_reason", result)
        self.assertEqual(result["actual_occupancy_rate"], 0.3871)
        self.assertEqual(result["actual_numerator_rooms"], 12)
        self.assertEqual(result["denominator_rooms"], 31)

    def test_chinese_jd01_statuses_follow_realtime_formula(self) -> None:
        operating_payload = {
            "total_rooms": 31,
            "maintenance_rooms": 0,
            "rows": [
                *[{"room_no": f"2{i:02d}", "room_status": "住脏"} for i in range(1, 17)],
                *[{"room_no": f"3{i:02d}", "room_status": "空净"} for i in range(1, 12)],
                *[{"room_no": f"4{i:02d}", "room_status": "空脏"} for i in range(1, 5)],
            ],
        }
        reservation_payload = {
            "realtime_rows": [
                {
                    "room_no": "501",
                    "booking_status": "已入住",
                    "departure_time": "2026-07-03 18:00:00",
                    "arrival_time": "2026-07-02 20:00:00",
                },
                {
                    "room_no": "502",
                    "booking_status": "预订",
                    "arrival_time": "2026-07-03 20:00:00",
                    "departure_time": "2026-07-04 12:00:00",
                },
            ],
        }
        stayover_payload = {
            "realtime_rows": [
                {
                    "room_no": "503",
                    "checkout_time": "2026-07-03 19:00:00",
                }
            ],
        }

        result = build_realtime_occupancy(
            operating_payload=operating_payload,
            reservation_payload=reservation_payload,
            stayover_payload=stayover_payload,
            business_date="2026-07-03",
            as_of_time="2026-07-03 16:25:00",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["actual_numerator_rooms"], 3)
        self.assertEqual(result["denominator_rooms"], 31)
        self.assertEqual(result["actual_occupancy_rate"], 0.0968)
        self.assertEqual(result["kf11_occupied_rooms"], 16)

    def test_jd01_booking_status_casing_and_prior_arrivals_count_checked_in_rooms(self) -> None:
        operating_payload = {
            "total_rooms": 31,
            "maintenance_rooms": 0,
            "rows": [
                *[{"room_no": f"2{i:02d}", "room_status": "occupied"} for i in range(1, 17)],
                *[{"room_no": f"3{i:02d}", "room_status": "vacant"} for i in range(1, 16)],
            ],
        }
        reservation_payload = {
            "realtime_rows": [
                *[
                    {
                        "room_no": f"2{i:02d}",
                        "order_id": f"I{i}",
                        "booking_Status": "已入住",
                        "arrival_time": "2026-07-01 20:00:00",
                        "departure_time": "2026-07-03 18:00:00",
                    }
                    for i in range(1, 14)
                ],
                *[
                    {
                        "room_no": f"4{i:02d}",
                        "order_id": f"R{i}",
                        "booking_Status": "预订",
                        "arrival_time": "2026-07-03 20:00:00",
                        "departure_time": "2026-07-04 12:00:00",
                    }
                    for i in range(1, 3)
                ],
            ],
        }
        stayover_payload = {
            "realtime_rows": [
                {
                    "room_no": "501",
                    "order_id": "S1",
                    "checkout_time": "2026-07-03 19:00:00",
                }
            ],
        }

        result = build_realtime_occupancy(
            operating_payload=operating_payload,
            reservation_payload=reservation_payload,
            stayover_payload=stayover_payload,
            business_date="2026-07-03",
            as_of_time="2026-07-03 16:25:00",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["numerator_components"]["jd01_checked_in_departure_after_as_of"], 13)
        self.assertEqual(result["numerator_components"]["jd01_reserved_arrival_today"], 2)
        self.assertEqual(result["numerator_components"]["jd04_checkout_after_as_of"], 1)
        self.assertEqual(result["actual_numerator_rooms"], 16)
        self.assertEqual(result["denominator_rooms"], 31)
        self.assertEqual(result["actual_occupancy_rate"], 0.5161)


if __name__ == "__main__":
    unittest.main()

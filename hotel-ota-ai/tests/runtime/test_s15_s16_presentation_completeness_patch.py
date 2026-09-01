from __future__ import annotations

import unittest

from runtime.s15_s16_presentation_completeness_patch import (
    add_pickup_baselines,
    build_s15_user_message,
    build_s16_user_message,
    direct_output_contract,
    enrich_deviation,
)


class S15S16PresentationCompletenessTests(unittest.TestCase):
    def test_pickup_keeps_negative_values(self) -> None:
        hotel = {"hourly_points": [{"hour": 9}, {"hour": 10}]}
        rooms = {"r1": {"hourly_points": [{"hour": 9}, {"hour": 10}]}}
        hourly = {
            ("2026-07-01", 9): [
                {
                    "room_type_id": "r1",
                    "committed_sold": 2,
                    "source_observed_hour": 9,
                }
            ],
            ("2026-07-01", 10): [
                {
                    "room_type_id": "r1",
                    "committed_sold": 3,
                    "source_observed_hour": 10,
                }
            ],
            ("2026-07-02", 9): [
                {
                    "room_type_id": "r1",
                    "committed_sold": 4,
                    "source_observed_hour": 9,
                }
            ],
            ("2026-07-02", 10): [
                {
                    "room_type_id": "r1",
                    "committed_sold": 2,
                    "source_observed_hour": 10,
                }
            ],
        }
        add_pickup_baselines(
            ["2026-07-01", "2026-07-02"],
            hourly,
            hotel,
            rooms,
        )
        pickup = hotel["hourly_points"][1]["pickup"]
        self.assertEqual(pickup["sample_count"], 2)
        self.assertEqual(pickup["median"], -0.5)

    def test_same_fallback_batch_is_not_counted_as_zero_pickup(self) -> None:
        hotel = {"hourly_points": [{"hour": 9}, {"hour": 10}]}
        rooms = {"r1": {"hourly_points": [{"hour": 9}, {"hour": 10}]}}
        hourly = {
            ("2026-07-01", 9): [
                {
                    "room_type_id": "r1",
                    "committed_sold": 2,
                    "source_observed_hour": 9,
                }
            ],
            ("2026-07-01", 10): [
                {
                    "room_type_id": "r1",
                    "committed_sold": 2,
                    "source_observed_hour": 9,
                }
            ],
        }
        add_pickup_baselines(["2026-07-01"], hourly, hotel, rooms)
        self.assertEqual(
            hotel["hourly_points"][1]["pickup"]["sample_count"],
            0,
        )

    def test_non_adjacent_observed_hours_are_not_hourly_pickup(self) -> None:
        hotel = {"hourly_points": [{"hour": 11}, {"hour": 12}]}
        rooms = {"r1": {"hourly_points": [{"hour": 11}, {"hour": 12}]}}
        hourly = {
            ("2026-07-01", 11): [
                {
                    "room_type_id": "r1",
                    "committed_sold": 3,
                    "source_observed_hour": 10,
                }
            ],
            ("2026-07-01", 12): [
                {
                    "room_type_id": "r1",
                    "committed_sold": 5,
                    "source_observed_hour": 12,
                }
            ],
        }
        add_pickup_baselines(["2026-07-01"], hourly, hotel, rooms)
        self.assertEqual(
            hotel["hourly_points"][1]["pickup"]["sample_count"],
            0,
        )

    def test_deviation_exposes_remaining_thresholds_and_quality(self) -> None:
        enriched = enrich_deviation(
            {
                "status": "ok",
                "observed_hour": 19,
                "hotel_result": {
                    "total_rooms": 31,
                    "available_rooms": 3,
                    "committed_sold": 28,
                    "overbooking_rooms": 0,
                },
                "room_type_results": [{"room_type_id": "r1"}],
            },
            {
                "hotel": {
                    "hourly_points": [
                        {
                            "hour": 19,
                            "capacity_maturity": "weak",
                            "target_completion_maturity": "trend_only",
                            "capacity_confidence": 0.22,
                            "target_completion_confidence": 0.14,
                        }
                    ]
                },
                "room_types": {
                    "r1": {
                        "hourly_points": [
                            {
                                "hour": 19,
                                "capacity_maturity": "weak",
                                "target_completion_maturity": "trend_only",
                                "capacity_confidence": 0.22,
                                "target_completion_confidence": 0.14,
                                "combined_maturity": "trend_only",
                            }
                        ]
                    }
                },
            },
        )
        self.assertEqual(
            enriched["hotel_result"]["remaining_sellable_rooms"],
            3,
        )
        self.assertFalse(enriched["hotel_result"]["overbooking_risk"])
        self.assertEqual(enriched["thresholds_used"]["slow_max_pp"], -8.0)
        self.assertEqual(
            enriched["room_type_results"][0]["target_completion_maturity"],
            "trend_only",
        )

    def test_s15_view_shows_pickup_coverage_and_confidence(self) -> None:
        text = build_s15_user_message(
            {
                "status": "ok",
                "target_date": "2026-08-03",
                "as_of_datetime": "2026-08-03 19:26:00",
                "selected_dates": ["2026-07-01", "2026-07-02"],
                "selected_tier": "P5_same_week_type",
                "hotel": {
                    "effective_target_room_nights": 28,
                    "historical_revenue_target": {"median": 4151},
                    "target_series_dates": ["2026-07-01"],
                    "target_series_tier": "P4_same_weekday",
                    "capacity_series_confidence": 0.12,
                    "target_series_confidence": 0.18,
                    "baseline_health": {
                        "observed_hour_slots": [9],
                        "fallback_only_hour_slots": [10],
                        "missing_hour_slots": [0, 1, 2],
                        "hour_grid_coverage": 0.10,
                        "display_checkpoint_coverage": 0.20,
                        "object_maturity": "trend_only",
                    },
                    "hourly_points": [
                        {
                            "hour": 9,
                            "capacity": {
                                "median": 0.18,
                                "p25": 0.10,
                                "p80": 0.26,
                                "sample_count": 10,
                            },
                            "target_completion": {
                                "median": 0.21,
                                "p25": 0.15,
                                "p80": 0.30,
                                "sample_count": 8,
                            },
                            "pickup": {
                                "median": 1.0,
                                "p25": 0,
                                "p80": 2,
                                "sample_count": 5,
                            },
                            "capacity_confidence": 0.20,
                            "target_completion_confidence": 0.15,
                            "maturity": "weak",
                        }
                    ],
                },
                "room_types": {},
                "ota_baselines": {},
            }
        )
        self.assertIn("净增 +1.0间", text)
        self.assertIn("前序批次回退", text)
        self.assertIn("采集缺口", text)
        self.assertIn("小时网格覆盖 10.0%", text)
        self.assertIn("容量置信度 12%", text)
        self.assertIn("容量节奏＝承诺已售 ÷ 可售总房量", text)

    def test_s16_view_separates_inventory_from_historical_pace(self) -> None:
        text = build_s16_user_message(
            {
                "status": "ok",
                "target_date": "2026-08-03",
                "as_of_datetime": "2026-08-03 19:26:00",
                "checkpoint_gap_minutes": 28,
                "policy_version": "s16-deviation.v1",
                "hotel_result": {
                    "committed_sold": 28,
                    "total_rooms": 31,
                    "remaining_sellable_rooms": 3,
                    "effective_target_room_nights": 28,
                    "overbooking_risk": False,
                    "capacity_maturity": "weak",
                    "target_completion_maturity": "trend_only",
                    "capacity_confidence": 0.22,
                    "target_completion_confidence": 0.14,
                    "capacity_line": {
                        "actual_progress": 0.903,
                        "baseline_median": 0.516,
                        "baseline_p25": 0.419,
                        "baseline_p80": 0.619,
                        "delta_pp": 38.7,
                        "expected_sold": 16,
                        "room_gap": 12,
                        "status": "significant_fast",
                    },
                    "target_line": {
                        "actual_progress": 1.0,
                        "baseline_median": 0.621,
                        "baseline_p25": 0.571,
                        "baseline_p80": 0.655,
                        "delta_pp": 37.9,
                        "expected_sold": 17.4,
                        "room_gap": 10.6,
                        "remaining_target_gap": 0,
                        "status": "significant_fast",
                    },
                },
                "room_type_results": [],
                "structure_summary": {},
                "structure_reconciliation": {},
            }
        )
        self.assertIn("剩余可售 3间", text)
        self.assertIn("同时点应售 16间", text)
        self.assertIn("检查点领先 12间", text)
        self.assertIn("置信度 22%", text)
        self.assertIn("不推断晚间剩余需求", text)
        self.assertNotIn("22–25间的节奏空间", text)

    def test_direct_output_is_locked_and_has_no_ai_rewrite(self) -> None:
        contract = direct_output_contract({})
        self.assertFalse(contract["ai_analysis_allowed"])
        self.assertTrue(contract["must_send_authoritative_text_verbatim"])
        self.assertEqual(contract["analysis_handoff"], "S14")


if __name__ == "__main__":
    unittest.main()

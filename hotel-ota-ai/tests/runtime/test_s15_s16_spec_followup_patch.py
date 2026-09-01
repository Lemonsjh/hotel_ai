from __future__ import annotations

import unittest

from runtime.s15_s16_spec_followup_patch import (
    aligned_sales_lines,
    collector_health,
    platform_maturity,
)


class S15S16SpecFollowupPatchTests(unittest.TestCase):
    def test_exact_and_fallback_hours_are_not_mixed(self) -> None:
        health = collector_health(
            [
                {
                    "hour": 9,
                    "exact_sample_count": 5,
                    "fallback_sample_count": 1,
                    "capacity": {"sample_count": 6},
                    "target_completion": {"sample_count": 4},
                },
                {
                    "hour": 10,
                    "exact_sample_count": 0,
                    "fallback_sample_count": 4,
                    "capacity": {"sample_count": 4},
                    "target_completion": {"sample_count": 3},
                },
            ]
        )
        self.assertEqual(health["observed_hour_slots"], [9])
        self.assertEqual(health["fallback_only_hour_slots"], [10])
        self.assertIn(11, health["missing_hour_slots"])

    def test_recent_six_samples_can_recover_collector_maturity(self) -> None:
        points = []
        for hour in range(15):
            points.append(
                {
                    "hour": hour,
                    "exact_sample_count": 1,
                    "fallback_sample_count": 0,
                    "recent_exact_sample_count": 6,
                    "recent_sample_day_count": 6,
                }
            )
        health = collector_health(points)
        self.assertEqual(health["collector_coverage_ratio"], 15 / 24)
        self.assertEqual(health["recent_sample_coverage_ratio"], 90 / 144)
        self.assertTrue(health["recent_sample_recovered"])
        self.assertEqual(health["maturity_source"], "recent_6_samples")
        self.assertEqual(health["object_maturity"], "temporary")

    def test_fewer_than_six_samples_cannot_recover_maturity(self) -> None:
        points = [
            {
                "hour": hour,
                "recent_exact_sample_count": 5,
                "recent_sample_day_count": 5,
            }
            for hour in range(15)
        ]
        health = collector_health(points)
        self.assertFalse(health["recent_sample_recovered"])
        self.assertEqual(health["maturity_source"], "full_history")

    def test_platform_maturity_is_monotonic(self) -> None:
        self.assertEqual(platform_maturity(2), "trend_only")
        self.assertEqual(platform_maturity(5), "weak")
        self.assertEqual(platform_maturity(14), "temporary")
        self.assertEqual(platform_maturity(30), "stable")

    def test_complete_jl01_sum_is_hotel_primary_and_jy01_is_conflict_check(self) -> None:
        def previous(selected_dates, hourly, room_daily_rows, hotel_daily_rows):
            return (
                {
                    "hourly_points": [
                        {
                            "hour": 18,
                            "capacity": {"sample_count": 1},
                            "target_completion": {"sample_count": 1},
                        }
                    ]
                },
                {
                    "py01": {"hourly_points": [{"hour": 18}]},
                    "py02": {"hourly_points": [{"hour": 18}]},
                },
            )

        hourly = {
            ("2026-07-27", 18): [
                {
                    "room_type_id": "py01",
                    "total_rooms": 2.0,
                    "committed_sold": 2.0,
                    "is_exact_hour": True,
                    "checkpoint_gap_minutes": 0,
                },
                {
                    "room_type_id": "py02",
                    "total_rooms": 3.0,
                    "committed_sold": 1.0,
                    "is_exact_hour": True,
                    "checkpoint_gap_minutes": 0,
                },
            ]
        }
        hotel, _ = aligned_sales_lines(
            previous,
            ["2026-07-27"],
            hourly,
            [
                {"business_date": "2026-07-27", "room_type_id": "py01", "room_nights": 2},
                {"business_date": "2026-07-27", "room_type_id": "py02", "room_nights": 3},
            ],
            [{"business_date": "2026-07-27", "room_nights": 6}],
        )
        self.assertEqual(
            hotel["final_room_nights_source_by_date"]["2026-07-27"],
            "jl01_complete_canonical_sum",
        )
        self.assertEqual(hotel["historical_target_room_nights"]["median"], 5)
        self.assertEqual(len(hotel["hotel_room_type_final_conflicts"]), 1)
        self.assertAlmostEqual(hotel["hourly_points"][0]["target_completion"]["median"], 3 / 5)
        self.assertEqual(hotel["hourly_points"][0]["recent_sample_day_count"], 1)
        self.assertEqual(hotel["hourly_points"][0]["recent_exact_sample_count"], 1)

    def test_jy01_exact_total_is_hotel_only_fallback_when_jl01_incomplete(self) -> None:
        def previous(selected_dates, hourly, room_daily_rows, hotel_daily_rows):
            return (
                {"hourly_points": [{"hour": 18}]},
                {
                    "py01": {"hourly_points": [{"hour": 18}]},
                    "py02": {"hourly_points": [{"hour": 18}]},
                },
            )

        hourly = {
            ("2026-07-27", 18): [
                {
                    "room_type_id": "py01",
                    "total_rooms": 2.0,
                    "committed_sold": 2.0,
                    "is_exact_hour": False,
                    "checkpoint_gap_minutes": 60,
                },
                {
                    "room_type_id": "py02",
                    "total_rooms": 3.0,
                    "committed_sold": 1.0,
                    "is_exact_hour": False,
                    "checkpoint_gap_minutes": 60,
                },
            ]
        }
        hotel, _ = aligned_sales_lines(
            previous,
            ["2026-07-27"],
            hourly,
            [{"business_date": "2026-07-27", "room_type_id": "py01", "room_nights": 2}],
            [{"business_date": "2026-07-27", "room_nights": 6}],
        )
        self.assertEqual(
            hotel["final_room_nights_source_by_date"]["2026-07-27"],
            "jy01_exact_hotel_total_fallback",
        )
        self.assertEqual(hotel["historical_target_room_nights"]["median"], 6)
        self.assertEqual(hotel["hourly_points"][0]["exact_sample_count"], 0)
        self.assertEqual(hotel["hourly_points"][0]["fallback_sample_count"], 1)
        self.assertEqual(hotel["hourly_points"][0]["max_checkpoint_gap_minutes"], 60)


if __name__ == "__main__":
    unittest.main()

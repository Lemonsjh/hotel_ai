from __future__ import annotations

import unittest

from runtime.s15_s16_spec_alignment_patch import (
    build_ai_response_contract,
    build_s15_user_message,
    build_s16_user_message,
    collector_health,
    select_platform_dates,
)


class S15S16SpecAlignmentPatchTests(unittest.TestCase):
    def test_platform_dates_use_same_date_type_not_whole_window(self) -> None:
        contexts = {
            "2026-08-03": {
                "season_tag": "HIGH",
                "is_holiday": False,
                "is_weekend": False,
                "is_workday": True,
            },
            "2026-07-27": {
                "season_tag": "HIGH",
                "is_holiday": False,
                "is_weekend": False,
                "is_workday": True,
            },
            "2026-07-26": {
                "season_tag": "HIGH",
                "is_holiday": False,
                "is_weekend": True,
                "is_workday": False,
            },
            "2026-07-20": {
                "season_tag": "LOW",
                "is_holiday": False,
                "is_weekend": False,
                "is_workday": True,
            },
        }
        tier, dates = select_platform_dates(
            "2026-08-03",
            ["2026-07-27", "2026-07-26", "2026-07-20"],
            contexts,
        )
        self.assertEqual(tier, "M1_season_holiday_weekday")
        self.assertEqual(dates, ["2026-07-27"])

    def test_platform_dates_fall_back_to_same_week_type(self) -> None:
        tier, dates = select_platform_dates(
            "2026-08-06",
            ["2026-08-03", "2026-08-04", "2026-08-05"],
            {},
        )

        self.assertEqual(tier, "M5_same_week_type")
        self.assertEqual(
            dates,
            ["2026-08-05", "2026-08-04", "2026-08-03"],
        )

    def test_collector_health_retains_missing_hours_and_low_maturity(self) -> None:
        points = [
            {
                "hour": 9,
                "capacity": {"sample_count": 10},
                "target_completion": {"sample_count": 8},
            },
            {
                "hour": 18,
                "capacity": {"sample_count": 9},
                "target_completion": {"sample_count": 7},
            },
        ]
        health = collector_health(points)
        self.assertEqual(health["observed_hour_slots"], [9, 18])
        self.assertIn(0, health["missing_hour_slots"])
        self.assertIn(23, health["missing_hour_slots"])
        self.assertEqual(health["object_maturity"], "trend_only")

    def test_s15_shows_all_available_hours_and_hides_semantic_gaps(self) -> None:
        payload = {
            "status": "ok",
            "target_date": "2026-08-03",
            "as_of_datetime": "2026-08-03 18:55:00",
            "selected_dates": ["2026-07-27"],
            "hotel": {
                "effective_target_room_nights": 28,
                "historical_revenue_target": {"median": 4151},
                "baseline_health": {
                    "observed_hour_slots": [9, 11, 18],
                    "missing_hour_slots": [0, 1, 2],
                    "object_maturity": "trend_only",
                },
                "hourly_points": [
                    {
                        "hour": 9,
                        "capacity": {"median": 0.18, "p25": 0.10, "p80": 0.26, "sample_count": 10},
                        "target_completion": {"median": 0.21, "p25": 0.15, "p80": 0.28, "sample_count": 8},
                    },
                    {
                        "hour": 11,
                        "capacity": {"median": 0.22, "p25": 0.15, "p80": 0.30, "sample_count": 7},
                        "target_completion": {"median": 0.26, "p25": 0.19, "p80": 0.34, "sample_count": 6},
                    },
                    {
                        "hour": 18,
                        "capacity": {"median": 0.52, "p25": 0.43, "p80": 0.60, "sample_count": 9},
                        "target_completion": {"median": 0.62, "p25": 0.50, "p80": 0.70, "sample_count": 9},
                    },
                ],
            },
            "room_types": {},
            "ota_baselines": {},
            "unavailable_baseline_families": {
                "market_orders_baseline": "source_semantic_unavailable"
            },
        }
        text = build_s15_user_message(payload)
        self.assertIn("09时", text)
        self.assertIn("11时", text)
        self.assertIn("18时", text)
        self.assertIn("缺少真实小时样本", text)
        self.assertIn("整体成熟度仅作趋势参考", text)
        self.assertNotIn("市场总订单", text)
        self.assertNotIn("暂无法形成稳定基准", text)

    def test_s16_keeps_capacity_line_and_omits_unavailable_target_line(self) -> None:
        report = {
            "status": "ok",
            "target_date": "2026-08-03",
            "as_of_datetime": "2026-08-03 18:55:00",
            "checkpoint_gap_minutes": 59,
            "hotel_result": {
                "committed_sold": 25,
                "total_rooms": 31,
                "effective_target_room_nights": 28,
                "capacity_line": {
                    "actual_progress": 25 / 31,
                    "baseline_median": 0.452,
                    "baseline_p25": 0.427,
                    "baseline_p80": 0.529,
                    "delta_pp": 35.45,
                    "expected_sold": 14.012,
                    "room_gap": 10.988,
                    "status": "significant_fast",
                },
                "target_line": {
                    "actual_progress": 25 / 28,
                    "baseline_median": 0.539,
                    "baseline_p25": 0.487,
                    "baseline_p80": 0.583,
                    "delta_pp": 35.39,
                    "expected_sold": 15.092,
                    "room_gap": 9.908,
                    "status": "significant_fast",
                },
            },
            "room_type_results": [
                {
                    "room_type_id": "py01",
                    "room_type_name": "测试房型",
                    "capacity_line": {
                        "actual_progress": 1.0,
                        "baseline_median": 0.5,
                        "delta_pp": 50,
                        "expected_sold": 2,
                        "room_gap": 2,
                        "status": "significant_fast",
                    },
                    "target_line": {"status": "unavailable"},
                }
            ],
            "structure_summary": {
                "capacity_line_available_count": 1,
                "capacity_slow_room_type_count": 0,
                "capacity_fast_room_type_count": 1,
                "target_line_available_count": 0,
                "target_slow_room_type_count": 0,
                "target_fast_room_type_count": 0,
                "labels": [],
            },
        }
        text = build_s16_user_message(report)
        self.assertIn("测试房型", text)
        self.assertIn("容量", text)
        self.assertIn("两条可用节奏线均为明显超前", text)
        self.assertNotIn("参考完成线可判断0个", text)
        self.assertNotIn("暂不可判断", text)

    def test_ai_contract_hides_only_semantic_gaps_but_retains_coverage(self) -> None:
        contract = build_ai_response_contract(
            {
                "intent": "sales_baseline_demo",
                "room_types": {"py01": {}, "py02": {}},
            }
        )
        self.assertTrue(contract["retain_low_sample_and_incomplete_coverage"])
        self.assertTrue(contract["hide_semantically_unavailable_families"])
        self.assertTrue(contract["must_preserve_all_available_hour_slots"])
        self.assertEqual(contract["required_room_type_ids"], ["py01", "py02"])
        self.assertFalse(contract["additional_database_queries_allowed"])


if __name__ == "__main__":
    unittest.main()

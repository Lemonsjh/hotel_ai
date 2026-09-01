from __future__ import annotations

import os
import unittest

from runtime.s15_s16_ai_analysis_patch import (
    _PATCH_VERSION,
    build_ai_response_contract,
    enhanced_structure_summary,
    merge_room_daily_fallback,
)


class S15S16AiAnalysisPatchTests(unittest.TestCase):
    def test_jl01_primary_wins_over_vertical_fallback(self) -> None:
        primary = [
            {
                "business_date": "2026-07-01",
                "room_type_id": "py01",
                "room_nights": 3,
            }
        ]
        vertical = [
            {
                "id": 10,
                "business_date": "2026-07-01",
                "room_type_id": "py01",
                "dimension_type": "房型",
                "dimension_name": "房型一",
                "room_nights": 8,
                "snapshot_time": "2026-07-02 01:00:00",
            }
        ]
        merged = merge_room_daily_fallback(primary, vertical)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["room_nights"], 3)
        self.assertEqual(
            merged[0]["final_room_nights_source"],
            "jl01_room_type_performance_daily",
        )

    def test_vertical_fallback_requires_unambiguous_room_nights(self) -> None:
        vertical = [
            {
                "id": 1,
                "business_date": "2026-07-01",
                "room_type_id": "py02",
                "dimension_type": "房型A",
                "dimension_name": "房型二",
                "room_nights": 2,
                "snapshot_time": "2026-07-02 01:00:00",
            },
            {
                "id": 2,
                "business_date": "2026-07-01",
                "room_type_id": "py02",
                "dimension_type": "渠道房型",
                "dimension_name": "房型二",
                "room_nights": 5,
                "snapshot_time": "2026-07-02 01:01:00",
            },
        ]
        self.assertEqual(merge_room_daily_fallback([], vertical), [])

    def test_vertical_fallback_accepts_agreeing_dimensions(self) -> None:
        vertical = [
            {
                "id": 1,
                "hotel_id": "hotel-puyue",
                "business_date": "2026-07-01",
                "room_type_id": "py03",
                "dimension_type": "房型",
                "dimension_name": "房型三",
                "room_nights": 4,
                "room_revenue": 500,
                "snapshot_time": "2026-07-02 01:00:00",
            },
            {
                "id": 2,
                "hotel_id": "hotel-puyue",
                "business_date": "2026-07-01",
                "room_type_id": "py03",
                "dimension_type": "房型复核",
                "dimension_name": "房型三",
                "room_nights": 4,
                "room_revenue": 500,
                "snapshot_time": "2026-07-02 01:01:00",
            },
        ]
        merged = merge_room_daily_fallback([], vertical)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["room_nights"], 4)
        self.assertEqual(
            merged[0]["final_room_nights_source"],
            "jy01_unambiguous_room_dimension_fallback",
        )

    def test_structure_counts_use_capacity_when_target_lines_missing(self) -> None:
        rows = [
            {
                "room_type_id": "slow",
                "effective_target_room_nights": None,
                "capacity_line": {"status": "severe_slow", "room_gap": -1},
                "target_line": {"status": "unavailable"},
            },
            {
                "room_type_id": "fast",
                "effective_target_room_nights": None,
                "capacity_line": {"status": "significant_fast", "room_gap": 2},
                "target_line": {"status": "unavailable"},
            },
        ]
        summary = enhanced_structure_summary(rows, "unavailable")
        self.assertEqual(summary["structure_basis"], "capacity_line_fallback")
        self.assertEqual(summary["slow_room_type_count"], 1)
        self.assertEqual(summary["fast_room_type_count"], 1)
        self.assertEqual(summary["target_line_available_count"], 0)
        self.assertEqual(summary["capacity_line_available_count"], 2)
        self.assertEqual(summary["labels"], summary["structure_labels"])

    def test_ai_contract_requires_every_room_and_single_runtime_call(self) -> None:
        contract = build_ai_response_contract(
            {
                "intent": "progress_deviation_demo",
                "room_type_results": [
                    {"room_type_id": "py01"},
                    {"room_type_id": "py02"},
                ],
            }
        )
        self.assertEqual(contract["required_room_type_count"], 2)
        self.assertEqual(contract["required_room_type_ids"], ["py01", "py02"])
        self.assertTrue(contract["must_preserve_every_room_type"])
        self.assertEqual(contract["maximum_runtime_tool_calls"], 1)
        self.assertFalse(contract["additional_database_queries_allowed"])
        self.assertEqual(contract["contract_version"], _PATCH_VERSION)

    def test_daily_baseline_cache_default_is_one_day(self) -> None:
        self.assertEqual(os.environ.get("HOTEL_OTA_S15_CACHE_TTL_SECONDS"), "86400")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import datetime as dt
import unittest

from runtime.algorithms.s5_real_reply import _reason_labels
from runtime.sales_progress.hour_grid_evidence import compute_hour_grid_evidence
from runtime.s5_limited_preview_patch import apply_limited_evidence_previews
from runtime.s5_time_evidence_policy_patch import apply_s5_time_evidence_policy


def _history_rows() -> tuple[list[str], list[dict[str, object]]]:
    dates = [
        (dt.date(2026, 7, 1) + dt.timedelta(days=index)).isoformat()
        for index in range(14)
    ]
    counts = {
        9: 10,
        10: 10,
        11: 10,
        12: 10,
        13: 10,
        14: 10,
        15: 11,
        16: 11,
        17: 8,
        18: 8,
        19: 8,
        20: 6,
        21: 4,
        22: 4,
        23: 3,
    }
    rows: list[dict[str, object]] = []
    for hour, count in counts.items():
        for day in dates[:count]:
            rows.append(
                {
                    "stay_date": day,
                    "snapshot_hour": hour,
                    "snapshot_time": f"{day} {hour:02d}:00:00",
                    "room_type_id": "room-1",
                    "total_rooms": 10,
                    "available_rooms": 5,
                    "overbooking_rooms": 0,
                }
            )
    return dates, rows


def _s15(
    *,
    global_coverage: float,
    decision_count: int,
    decision_coverage: float,
    decision_maturity: str,
) -> dict[str, object]:
    decision = {
        "status": "ok",
        "hour": 10,
        "exact_sample_count": decision_count,
        "exact_coverage_ratio": decision_coverage,
        "maturity": decision_maturity,
    }
    return {
        "status": "ok",
        "baseline": {
            "target_date": "2026-08-06",
            "sample_maturity": "weak",
            "hour_grid_health": {
                "status": "ok",
                "selected_date_count": 14,
                "exact_cell_count": round(global_coverage * 336),
                "total_cell_count": 336,
                "exact_coverage_ratio": global_coverage,
                "maturity": "trend_only" if global_coverage < 0.40 else "weak",
            },
            "decision_hour_evidence": decision,
            "room_types": {
                "room-1": {
                    "price_baseline": {
                        "median": 90,
                        "p20": 80,
                    },
                    "decision_hour_evidence": decision,
                }
            },
        },
    }


def _strong_candidate() -> dict[str, object]:
    return {
        "room_type_id": "room-1",
        "current_price": 100,
        "candidate_price": 105,
        "conservative_price": 105,
        "execution_price": 105,
        "actual_change_pct": 0.05,
        "configured_change_pct": 0.05,
        "price_action": "increase",
        "action_type": "raise_price",
        "strong_pricing_rule_status": "triggered",
        "sales_progress_delta_pp": 10,
        "total_rooms": 10,
        "remaining_room_ratio": 0.20,
        "market_not_cold": True,
        "effective_price_ceiling": 120,
        "product_sellable": True,
        "guard_valid": True,
        "reference_only": False,
        "auto_execution_eligible": True,
        "approval_required": True,
        "handoff_to": "S6",
        "eligibility": "eligible_for_s6_dry_run",
    }


def _hold_candidate() -> dict[str, object]:
    return {
        "room_type_id": "room-1",
        "current_price": 100,
        "candidate_price": 100,
        "conservative_price": 100,
        "execution_price": 100,
        "actual_change_pct": 0.0,
        "configured_change_pct": 0.0,
        "price_action": "hold",
        "action_type": "hold",
        "strong_pricing_rule_status": "not_triggered",
        "sales_progress_delta_pp": 3.41,
        "total_rooms": 11,
        "remaining_room_ratio": 0.09,
        "product_sellable": True,
        "guard_valid": True,
        "reference_only": True,
        "auto_execution_eligible": False,
        "approval_required": False,
        "handoff_to": None,
        "eligibility": "preview_only_strong_rule_not_satisfied",
        "blocked_reason": "strong_pricing_rule_not_satisfied",
        "limited_preview_blockers": ["room_type_sales_progress_within_hold_band"],
    }


class HourGridEvidenceTests(unittest.TestCase):
    def test_exact_grid_and_decision_hour_are_separate(self) -> None:
        dates, rows = _history_rows()
        evidence = compute_hour_grid_evidence(
            rows,
            selected_dates=dates,
            expected_room_type_ids=["room-1"],
            decision_hour=10,
        )

        grid = evidence["hour_grid_health"]
        decision = evidence["decision_hour_evidence"]
        self.assertEqual(grid["exact_cell_count"], 123)
        self.assertEqual(grid["total_cell_count"], 336)
        self.assertEqual(grid["exact_coverage_ratio"], 0.3661)
        self.assertFalse(grid["formal_minimum_met"])
        self.assertEqual(grid["missing_all_hours"], list(range(9)))
        self.assertEqual(decision["exact_sample_count"], 10)
        self.assertEqual(decision["exact_coverage_ratio"], 0.7143)
        self.assertEqual(decision["maturity"], "temporary")
        self.assertTrue(decision["formal_maturity_allowed"])


class S5TimeEvidencePolicyTests(unittest.TestCase):
    def test_low_global_grid_keeps_business_trigger_and_s6_handoff(self) -> None:
        result = {
            "hotel_id": "hotel-1",
            "target_stay_date": "2026-08-06",
            "data_business_date": "2026-08-06",
            "freshness_status": "fresh",
            "candidates": [_strong_candidate()],
        }
        adjusted = apply_s5_time_evidence_policy(
            result,
            s15_result=_s15(
                global_coverage=0.3661,
                decision_count=10,
                decision_coverage=0.7143,
                decision_maturity="temporary",
            ),
        )

        candidate = adjusted["candidates"][0]
        self.assertEqual(candidate["strong_pricing_rule_status"], "triggered")
        self.assertEqual(candidate["price_action"], "increase")
        self.assertEqual(candidate["candidate_price"], 105)
        self.assertEqual(candidate["execution_price"], 105)
        self.assertEqual(candidate["eligibility"], "eligible_for_s6_dry_run")
        self.assertTrue(candidate["auto_execution_eligible"])
        self.assertEqual(candidate["handoff_to"], "S6")
        self.assertFalse(candidate["formal_time_evidence_sufficient"])
        self.assertEqual(candidate["s15_time_evidence_confidence"], "limited")
        self.assertFalse(candidate["s15_time_evidence_can_block_s5"])
        self.assertEqual(candidate["s15_time_evidence_role"], "confidence_only")
        self.assertIn(
            "global_hour_grid_below_formal_threshold",
            candidate["s15_time_evidence_quality_flags"],
        )
        self.assertFalse(candidate.get("limited_evidence_preview", False))
        self.assertEqual(adjusted["eligible_for_s6_count"], 1)
        self.assertFalse(adjusted["s15_time_evidence_can_block_s5"])
        self.assertEqual(
            adjusted["s5_pricing_trigger_basis"],
            [
                "sales_progress",
                "inventory",
                "market",
                "traffic",
                "second_conversion",
                "price",
            ],
        )

    def test_weak_decision_hour_is_quality_only_for_strong_candidate(self) -> None:
        result = {
            "hotel_id": "hotel-1",
            "target_stay_date": "2026-08-06",
            "data_business_date": "2026-08-06",
            "freshness_status": "fresh",
            "candidates": [_strong_candidate()],
        }
        adjusted = apply_s5_time_evidence_policy(
            result,
            s15_result=_s15(
                global_coverage=0.3661,
                decision_count=2,
                decision_coverage=0.1429,
                decision_maturity="trend_only",
            ),
        )

        candidate = adjusted["candidates"][0]
        self.assertEqual(candidate["strong_pricing_rule_status"], "triggered")
        self.assertEqual(candidate["execution_price"], 105)
        self.assertEqual(candidate["eligibility"], "eligible_for_s6_dry_run")
        self.assertTrue(candidate["auto_execution_eligible"])
        self.assertEqual(candidate["s15_time_evidence_confidence"], "weak")
        self.assertIn(
            "decision_hour_evidence_insufficient_for_preview",
            candidate["s15_time_evidence_quality_flags"],
        )
        self.assertEqual(adjusted["eligible_for_s6_count"], 1)

    def test_hold_keeps_business_reason_and_time_quality_separate(self) -> None:
        result = {
            "hotel_id": "hotel-1",
            "target_stay_date": "2026-08-06",
            "data_business_date": "2026-08-06",
            "freshness_status": "fresh",
            "candidates": [_hold_candidate()],
        }
        adjusted = apply_s5_time_evidence_policy(
            result,
            s15_result=_s15(
                global_coverage=0.20,
                decision_count=0,
                decision_coverage=0.0,
                decision_maturity="trend_only",
            ),
        )

        candidate = adjusted["candidates"][0]
        self.assertEqual(candidate["price_action"], "hold")
        self.assertEqual(candidate["candidate_price"], 100)
        self.assertEqual(candidate["execution_price"], 100)
        self.assertEqual(
            candidate["limited_preview_blockers"],
            ["room_type_sales_progress_within_hold_band"],
        )
        self.assertIn(
            "global_hour_grid_below_formal_threshold",
            candidate["s15_time_evidence_quality_flags"],
        )
        self.assertEqual(
            _reason_labels(candidate),
            ["房型销售进度处于维持区间"],
        )

    def test_legacy_s15_hold_cause_is_migrated_to_quality_metadata(self) -> None:
        candidate = {
            **_hold_candidate(),
            "blocked_reason": "s15_time_evidence_not_formal",
            "limited_preview_blockers": [
                "baseline_maturity_not_limited_preview",
                "room_type_sales_progress_within_hold_band",
            ],
        }
        result = {
            "hotel_id": "hotel-1",
            "target_stay_date": "2026-08-06",
            "data_business_date": "2026-08-06",
            "freshness_status": "fresh",
            "candidates": [candidate],
        }
        adjusted = apply_s5_time_evidence_policy(
            result,
            s15_result=_s15(
                global_coverage=0.20,
                decision_count=0,
                decision_coverage=0.0,
                decision_maturity="trend_only",
            ),
        )

        output = adjusted["candidates"][0]
        self.assertEqual(output["price_action"], "hold")
        self.assertEqual(
            output["limited_preview_blockers"],
            ["room_type_sales_progress_within_hold_band"],
        )
        self.assertEqual(output["blocked_reason"], "strong_pricing_rule_not_satisfied")
        self.assertIn(
            "baseline_maturity_not_limited_preview",
            output["s15_time_evidence_quality_flags"],
        )
        self.assertIn(
            "s15_time_evidence_not_formal",
            output["s15_time_evidence_quality_flags"],
        )
        self.assertFalse(output["s15_time_evidence_can_block_s5"])
        self.assertEqual(
            _reason_labels(output),
            ["房型销售进度处于维持区间"],
        )

    def test_legacy_s15_blocked_reason_is_removed_from_triggered_candidate(self) -> None:
        candidate = {
            **_strong_candidate(),
            "blocked_reason": "s15_time_evidence_not_formal",
            "limited_preview_blockers": ["baseline_maturity_not_limited_preview"],
        }
        result = {
            "hotel_id": "hotel-1",
            "target_stay_date": "2026-08-06",
            "data_business_date": "2026-08-06",
            "freshness_status": "fresh",
            "candidates": [candidate],
        }
        adjusted = apply_s5_time_evidence_policy(
            result,
            s15_result=_s15(
                global_coverage=0.20,
                decision_count=2,
                decision_coverage=0.1429,
                decision_maturity="trend_only",
            ),
        )

        output = adjusted["candidates"][0]
        self.assertEqual(output["strong_pricing_rule_status"], "triggered")
        self.assertEqual(output["price_action"], "increase")
        self.assertEqual(output["execution_price"], 105)
        self.assertEqual(output["eligibility"], "eligible_for_s6_dry_run")
        self.assertEqual(output["limited_preview_blockers"], [])
        self.assertNotIn("blocked_reason", output)
        self.assertIn(
            "baseline_maturity_not_limited_preview",
            output["s15_time_evidence_quality_flags"],
        )
        self.assertIn(
            "s15_time_evidence_not_formal",
            output["s15_time_evidence_quality_flags"],
        )

    def test_formal_evidence_marks_confidence_without_changing_candidate(self) -> None:
        result = {
            "hotel_id": "hotel-1",
            "target_stay_date": "2026-08-06",
            "data_business_date": "2026-08-06",
            "freshness_status": "fresh",
            "candidates": [_strong_candidate()],
        }
        adjusted = apply_s5_time_evidence_policy(
            result,
            s15_result=_s15(
                global_coverage=0.50,
                decision_count=10,
                decision_coverage=0.7143,
                decision_maturity="temporary",
            ),
        )

        candidate = adjusted["candidates"][0]
        self.assertEqual(candidate["strong_pricing_rule_status"], "triggered")
        self.assertEqual(candidate["execution_price"], 105)
        self.assertEqual(candidate["eligibility"], "eligible_for_s6_dry_run")
        self.assertTrue(candidate["formal_time_evidence_sufficient"])
        self.assertEqual(candidate["s15_time_evidence_confidence"], "formal")
        self.assertEqual(candidate["s15_time_evidence_quality_flags"], [])
        self.assertEqual(adjusted["eligible_for_s6_count"], 1)

    def test_limited_preview_patch_no_longer_invents_price_movement(self) -> None:
        candidate = {
            **_hold_candidate(),
            "sales_progress_delta_pp": -20,
            "remaining_room_ratio": 0.70,
            "traffic_status": "healthy",
            "second_conversion_weak": True,
            "price_high": True,
            "effective_price_floor": 80,
        }
        result = {
            "target_stay_date": "2026-08-06",
            "data_business_date": "2026-08-06",
            "freshness_status": "fresh",
            "candidates": [candidate],
        }
        adjusted = apply_limited_evidence_previews(
            result,
            s15_result=_s15(
                global_coverage=0.20,
                decision_count=4,
                decision_coverage=0.50,
                decision_maturity="weak",
            ),
        )

        output = adjusted["candidates"][0]
        self.assertEqual(output["price_action"], "hold")
        self.assertEqual(output["candidate_price"], 100)
        self.assertEqual(output["execution_price"], 100)
        self.assertFalse(output.get("limited_evidence_preview", False))
        self.assertEqual(adjusted["limited_evidence_preview_count"], 0)
        self.assertFalse(adjusted["s5_limited_preview_generation_enabled"])


if __name__ == "__main__":
    unittest.main()

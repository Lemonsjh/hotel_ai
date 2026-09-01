from __future__ import annotations

import unittest
from typing import Any

from runtime.s5_strong_pricing_rules_patch import (
    DEFAULT_THRESHOLDS,
    _traffic_evidence,
    evaluate_strong_pricing_rule,
)


class S5StrongPricingRuleTests(unittest.TestCase):
    def test_traffic_uses_projected_browse_ratio_before_raw_cumulative_ratio(self) -> None:
        evidence = _traffic_evidence(
            {
                "dynamic_diagnosis": {
                    "browse": {"ratio": 0.45},
                    "meituan_pace_insights": {
                        "browse_projection": {
                            "projected_ratio_vs_history": 0.96,
                            "linear_projection_only": False,
                        }
                    },
                }
            },
            DEFAULT_THRESHOLDS,
        )

        self.assertEqual(evidence["traffic_status"], "healthy")
        self.assertEqual(evidence["browse_ratio"], 0.96)
        self.assertEqual(
            evidence["traffic_evidence_source"],
            "hourly_completion_browse_projection",
        )

    def test_raise_price_when_progress_ahead_inventory_tight_and_market_not_cold(self) -> None:
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=200),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=160, median=180),
            s16_result=self._s16(
                delta_pp=10,
                total_rooms=20,
                remaining_rooms=4,
                market_ratio=0.96,
                browse_ratio=0.95,
                second_weak=False,
                current_price=200,
                estimated_net_price=180,
            ),
            as_of_time="2026-08-05T17:00:00+08:00",
        )

        self.assertEqual(rule["status"], "triggered")
        self.assertEqual(rule["action_type"], "raise_price")
        self.assertEqual(rule["price_action"], "increase")
        self.assertEqual(rule["configured_change_pct"], 0.03)
        self.assertEqual(rule["target_price"], 206.0)
        self.assertEqual(rule["observe_minutes"], 120)
        self.assertEqual(rule["observe_until"], "2026-08-05T19:00:00+08:00")
        self.assertTrue(rule["room_type_inventory_tight"])
        self.assertTrue(rule["market_not_cold"])

    def test_lower_price_when_progress_behind_inventory_loose_and_conversion_weak(self) -> None:
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=240),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=160, median=180),
            s16_result=self._s16(
                delta_pp=-12,
                total_rooms=20,
                remaining_rooms=12,
                market_ratio=0.96,
                browse_ratio=0.95,
                second_weak=True,
                current_price=240,
                estimated_net_price=216,
            ),
            as_of_time="2026-08-05T17:00:00+08:00",
        )

        self.assertEqual(rule["status"], "triggered")
        self.assertEqual(rule["action_type"], "lower_room_price")
        self.assertEqual(rule["price_action"], "decrease")
        self.assertEqual(rule["configured_change_pct"], 0.06)
        self.assertEqual(rule["target_price"], 226.0)
        self.assertGreaterEqual(rule["target_price"], rule["effective_price_floor"])
        self.assertEqual(rule["observe_minutes"], 90)
        self.assertEqual(rule["observe_until"], "2026-08-05T18:30:00+08:00")
        self.assertTrue(rule["room_type_inventory_loose"])
        self.assertTrue(rule["second_conversion_weak"])
        self.assertTrue(rule["price_high"])

    def test_single_room_type_can_lower_when_all_business_conditions_are_met(self) -> None:
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=240),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=160, median=180),
            s16_result=self._s16(
                delta_pp=-12,
                total_rooms=1,
                remaining_rooms=1,
                market_ratio=0.96,
                browse_ratio=0.95,
                second_weak=True,
                current_price=240,
                estimated_net_price=216,
            ),
        )

        self.assertEqual(rule["status"], "triggered")
        self.assertEqual(rule["action_type"], "lower_room_price")
        self.assertTrue(rule["room_type_inventory_loose"])

    def test_weak_traffic_forbids_price_down_and_prefers_promotion(self) -> None:
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=240),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=160, median=180),
            s16_result=self._s16(
                delta_pp=-12,
                total_rooms=20,
                remaining_rooms=12,
                market_ratio=0.80,
                browse_ratio=0.75,
                second_weak=True,
                current_price=240,
                estimated_net_price=216,
            ),
        )

        self.assertEqual(rule["status"], "blocked")
        self.assertEqual(rule["action_type"], "hold")
        self.assertEqual(rule["traffic_status"], "weak")
        self.assertEqual(rule["blocked_reason"], "traffic_weak_price_down_forbidden")
        self.assertEqual(rule["recommended_alternative_action"], "promotion_review")
        self.assertEqual(rule["handoff_to"], "S8")

    def test_recovering_traffic_allows_manual_preview_only(self) -> None:
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=240),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=160, median=180),
            s16_result=self._s16(
                delta_pp=-12,
                total_rooms=20,
                remaining_rooms=12,
                market_ratio=0.88,
                browse_ratio=0.85,
                second_weak=True,
                current_price=240,
                estimated_net_price=216,
            ),
        )

        self.assertEqual(rule["status"], "preview_only")
        self.assertEqual(rule["action_type"], "hold")
        self.assertEqual(rule["traffic_status"], "recovering")
        self.assertEqual(
            rule["blocked_reason"],
            "traffic_recovering_manual_preview_only",
        )
        self.assertTrue(rule["preview_price_down_allowed"])
        self.assertEqual(rule["manual_preview_price"], 226.0)

    def test_rounded_down_target_never_crosses_effective_floor(self) -> None:
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=190, floor_price=150),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=168.01, median=170),
            s16_result=self._s16(
                delta_pp=-25,
                total_rooms=20,
                remaining_rooms=12,
                market_ratio=1.0,
                browse_ratio=0.95,
                second_weak=True,
                current_price=190,
                estimated_net_price=190,
            ),
        )

        self.assertEqual(rule["status"], "triggered")
        self.assertGreaterEqual(rule["target_price"], rule["effective_price_floor"])

    def test_raise_uses_net_price_p80_headroom(self) -> None:
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=236),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=160, median=180, p80=216),
            s16_result=self._s16(
                delta_pp=10,
                total_rooms=20,
                remaining_rooms=4,
                market_ratio=0.96,
                browse_ratio=0.95,
                second_weak=False,
                current_price=236,
                estimated_net_price=212.4,
            ),
        )

        self.assertEqual(rule["status"], "not_triggered")
        self.assertFalse(rule["raise_price_has_headroom"])
        self.assertEqual(rule["baseline_price_p80_raw_equivalent"], 240)

    def test_overbooking_forbids_price_decrease(self) -> None:
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=240),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=160, median=180),
            s16_result=self._s16(
                delta_pp=-12,
                total_rooms=20,
                remaining_rooms=12,
                market_ratio=0.96,
                browse_ratio=0.95,
                second_weak=True,
                current_price=240,
                estimated_net_price=216,
                overbooking_rooms=1,
            ),
        )

        self.assertEqual(rule["status"], "blocked")
        self.assertEqual(rule["blocked_reason"], "overbooking_price_down_forbidden")

    def test_second_conversion_uses_s5_rule_on_s16_typed_evidence(self) -> None:
        s16 = self._s16(
            delta_pp=-12,
            total_rooms=20,
            remaining_rooms=12,
            market_ratio=0.96,
            browse_ratio=0.95,
            second_weak=False,
            current_price=240,
            estimated_net_price=216,
        )
        # S16's diagnosis conclusion is deliberately false here. S5 must
        # recompute from the typed rate, own P25 and peer index instead.
        second = s16["dynamic_diagnosis"]["second_conversion"]
        second.update(
            {
                "current": 0.04,
                "baseline_p25": 0.06,
                "conversion_index_vs_market": 0.80,
                "is_weak": False,
                "comparison_allowed": True,
            }
        )
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=240),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=160, median=180),
            s16_result=s16,
        )

        self.assertTrue(rule["second_conversion_weak"])
        self.assertEqual(
            rule["second_conversion_decision_source"],
            "s5_from_s16_typed_evidence",
        )
        self.assertEqual(rule["status"], "triggered")

    def test_raw_list_price_never_replaces_missing_net_price(self) -> None:
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=600),
            product_row=self._product_row(),
            s15_result=self._s15_reference(p20=160, median=180),
            s16_result=self._s16(
                delta_pp=-12,
                total_rooms=20,
                remaining_rooms=12,
                market_ratio=0.96,
                browse_ratio=0.95,
                second_weak=True,
                current_price=600,
                estimated_net_price=None,
            ),
        )

        self.assertIsNone(rule["price_ratio_vs_avg"])
        self.assertFalse(rule["price_high"])
        self.assertEqual(
            rule["price_comparison_basis"],
            "activity_net_unavailable_no_raw_price_fallback",
        )
        self.assertEqual(rule["status"], "not_triggered")

    def test_room_type_history_can_support_product_handoff(self) -> None:
        product = self._product_row()
        product.pop("same_ota_product_history_available")
        rule = evaluate_strong_pricing_rule(
            self._candidate(current_price=200),
            product_row=product,
            s15_result=self._s15_reference(p20=160, median=180),
            s16_result=self._s16(
                delta_pp=10,
                total_rooms=20,
                remaining_rooms=4,
                market_ratio=0.96,
                browse_ratio=0.95,
                second_weak=False,
                current_price=200,
                estimated_net_price=180,
            ),
        )

        self.assertFalse(rule["same_ota_product_history_available"])
        self.assertEqual(rule["status"], "triggered")

    @staticmethod
    def _candidate(
        *,
        current_price: float,
        floor_price: float = 150,
        ceiling_price: float = 300,
    ) -> dict[str, Any]:
        return {
            "hotel_id": "puyue",
            "room_type_id": "RT-1",
            "room_type_name": "豪华大床房",
            "channel": "meituan",
            "ota_product_id": "P-1",
            "ota_product_name": "豪华大床房含早",
            "current_price": current_price,
            "floor_price": floor_price,
            "ceiling_price": ceiling_price,
            "configured_floor_price": floor_price,
            "configured_ceiling_price": ceiling_price,
            "max_increase_pct": 0.10,
            "max_decrease_pct": 0.10,
            "min_increase_pct": 0.01,
            "min_decrease_pct": 0.01,
            "s6_task_mapping_ready": True,
            "price_guard_source": "active_price_guard_policy",
            "price_guard_policy_id": "PG-1",
            "price_guard_policy_version": "1",
            "price_guard_policy_state": "active",
        }

    @staticmethod
    def _product_row() -> dict[str, Any]:
        return {
            "room_type_id": "RT-1",
            "channel": "meituan",
            "ota_product_id": "P-1",
            "ota_product_name": "豪华大床房含早",
            "product_type": "listed_full_day",
            "price_editable_flag": True,
            "mapping_status": "CONFIRMED",
            "match_rule": "PRODUCT_ID",
            "mapping_active": True,
            "mapping_resolution_status": "mapped",
            "same_ota_product_history_available": True,
        }

    @staticmethod
    def _s15_reference(*, p20: float, median: float, p80: float | None = None) -> dict[str, Any]:
        return {
            "status": "ok",
            "baseline": {
                "baseline_package": {
                    "target_date": "2026-08-05",
                    "hotel_final_sales_target": 18,
                    "sample_maturity": "mature",
                    "data_gaps": [],
                    "room_type_transaction_references": [
                        {
                            "room_type_id": "RT-1",
                            "p20": p20,
                            "median": median,
                            "p80": p80 if p80 is not None else median * 1.2,
                            "sample_count": 30,
                        }
                    ],
                }
            },
        }

    @staticmethod
    def _s16(
        *,
        delta_pp: float,
        total_rooms: float,
        remaining_rooms: float,
        market_ratio: float,
        browse_ratio: float,
        second_weak: bool,
        current_price: float,
        estimated_net_price: float | None,
        overbooking_rooms: float = 0,
    ) -> dict[str, Any]:
        return {
            "status": "ok",
            "dynamic_diagnosis": {
                "target_date": "2026-08-05",
                "sales": {
                    "sales_progress_delta_pp": delta_pp,
                    "checkpoint_room_gap": delta_pp / 4,
                    "remaining_target_gap": max(-delta_pp / 2, 0),
                },
                "room_structure": {
                    "room_type_results": [
                        {
                            "room_type_id": "RT-1",
                            "room_type_name": "豪华大床房",
                            "sales_progress_delta_pp": delta_pp,
                            "total_rooms": total_rooms,
                            "committed_sold": total_rooms - remaining_rooms,
                            "available_rooms": remaining_rooms,
                            "overbooking_rooms": overbooking_rooms,
                        }
                    ]
                },
                "market": {
                    "market_heat_ratio": market_ratio,
                    "status": "normal" if market_ratio >= 0.90 else "cold",
                    "market_orders": 100 * market_ratio,
                    "baseline_market_orders": 100,
                    "comparison_allowed": True,
                },
                "browse": {
                    "ratio": browse_ratio,
                    "status": "normal" if browse_ratio >= 0.90 else "weak",
                },
                "second_conversion": {
                    "is_weak": second_weak,
                    "sample_level": "strong",
                    "browse_users": 100,
                    "pay_orders": 5,
                    "current": 0.04 if second_weak else 0.07,
                    "baseline_p25": 0.06,
                    "conversion_index_vs_market": 0.80 if second_weak else 1.0,
                    "ratio": 0.75 if second_weak else 1.0,
                    "status": "weak" if second_weak else "normal",
                    "comparison_allowed": True,
                },
                "product_prices": [
                    {
                        "ota_product_id": "P-1",
                        "room_type_id": "RT-1",
                        "raw_price": current_price,
                        "current_price": current_price,
                        # Test inputs express the expected hotel net revenue.
                        # S5 now applies its fixed 0.85 member expectation to
                        # the upstream activity-net observation.
                        "estimated_activity_net_price": (
                            estimated_net_price / 0.85
                            if estimated_net_price is not None
                            else None
                        ),
                        "commission_rate": 0.10,
                        "combined_activity_factor": 1.0,
                    }
                ],
            },
        }


if __name__ == "__main__":
    unittest.main()

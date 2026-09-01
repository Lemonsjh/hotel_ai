from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.algorithms.s5_real_candidates import (
    _s15_baseline,
    _s16_progress,
    build_s5_real_candidates,
)


class S5UpstreamContractAdapterTests(unittest.TestCase):
    def test_reads_current_s15_baseline_package(self) -> None:
        package = {
            "target_date": "2026-08-04",
            "hotel_final_sales_target": 32,
            "sample_maturity": "stable",
            "data_gaps": [],
        }

        payload, available, reason = _s15_baseline(
            {
                "status": "ok",
                "target_date": "2026-08-04",
                "baseline_package": package,
            },
            target_stay_date="2026-08-04",
        )

        self.assertTrue(available)
        self.assertIsNone(reason)
        self.assertEqual(payload, package)

    def test_reads_current_s16_dynamic_diagnosis_sales(self) -> None:
        progress = _s16_progress(
            {
                "status": "ok",
                "target_date": "2026-08-04",
                "dynamic_diagnosis": {
                    "status": "ok",
                    "target_date": "2026-08-04",
                    "sales": {
                        "checkpoint_room_gap": -3.5,
                        "remaining_target_gap": 8,
                    },
                },
            },
            target_stay_date="2026-08-04",
        )

        self.assertTrue(progress["available"])
        self.assertTrue(progress["complete"])
        self.assertEqual(progress["as_of_checkpoint_gap"], -3.5)
        self.assertEqual(progress["daily_remaining_gap"], 8)
        self.assertEqual(progress["source"], "s16_dynamic_diagnosis.sales")

    def test_partial_s16_is_consumed_when_progress_fields_are_missing(self) -> None:
        progress = _s16_progress(
            {
                "status": "partial",
                "target_date": "2026-08-05",
                "dynamic_diagnosis": {
                    "status": "partial",
                    "target_date": "2026-08-05",
                    "sales": {
                        "status": "unavailable",
                        "checkpoint_room_gap": None,
                        "remaining_target_gap": None,
                    },
                },
            },
            target_stay_date="2026-08-05",
        )

        self.assertTrue(progress["available"])
        self.assertFalse(progress["complete"])
        self.assertEqual(progress["source"], "s16_dynamic_diagnosis.sales")
        self.assertEqual(
            progress["missing_fields"],
            ["checkpoint_room_gap", "remaining_target_gap"],
        )

    def test_current_contract_target_date_mismatch_is_rejected(self) -> None:
        _, baseline_available, baseline_reason = _s15_baseline(
            {
                "status": "ok",
                "baseline_package": {
                    "target_date": "2026-08-03",
                    "hotel_final_sales_target": 30,
                    "sample_maturity": "stable",
                },
            },
            target_stay_date="2026-08-04",
        )
        progress = _s16_progress(
            {
                "status": "ok",
                "dynamic_diagnosis": {
                    "status": "ok",
                    "target_date": "2026-08-03",
                    "sales": {
                        "checkpoint_room_gap": -2,
                        "remaining_target_gap": 5,
                    },
                },
            },
            target_stay_date="2026-08-04",
        )

        self.assertFalse(baseline_available)
        self.assertEqual(baseline_reason, "s15_baseline_contract_incomplete")
        self.assertFalse(progress["available"])
        self.assertEqual(progress["reason"], "s16_target_date_mismatch")

    def test_legacy_s15_and_s16_shapes_remain_supported(self) -> None:
        _, baseline_available, baseline_reason = _s15_baseline(
            {
                "status": "ok",
                "baseline": {
                    "target_date": "2026-08-04",
                    "target_room_nights": 28,
                    "hourly_curve_policy": {"s16_deviation_allowed": True},
                    "hotel": {
                        "baseline_health": {"object_maturity": "stable"},
                        "capacity_series_confidence": 0.8,
                        "target_series_confidence": 0.8,
                    },
                },
            },
            target_stay_date="2026-08-04",
        )
        progress = _s16_progress(
            {
                "status": "ok",
                "target_date": "2026-08-04",
                "as_of_checkpoint_gap": -1,
                "daily_remaining_gap": 4,
            },
            target_stay_date="2026-08-04",
        )

        self.assertTrue(baseline_available)
        self.assertIsNone(baseline_reason)
        self.assertTrue(progress["available"])
        self.assertTrue(progress["complete"])
        self.assertEqual(progress["source"], "s16_progress_deviation")

    @patch(
        "runtime.algorithms.s5_real_candidates.is_price_task_mapping_ready",
        return_value={
            "ready_for_price_task": True,
            "blocked_reason": None,
            "mapping_trust_basis": "mapping_status_confirmed",
        },
    )
    @patch(
        "runtime.algorithms.s5_real_candidates.build_s5_decision_ref",
        return_value={"decision_id": "s5-test"},
    )
    @patch(
        "runtime.algorithms.s5_real_candidates.calculate_revenue_recommendation",
        return_value={
            "risk_level": "medium",
            "action_type": "DECREASE",
            "current_price": 300,
            "candidate_price": 285,
        },
    )
    @patch(
        "runtime.algorithms.s5_real_candidates.find_algorithm_rule",
        return_value={"algorithm": {"thresholds": {}}},
    )
    @patch(
        "runtime.algorithms.s5_real_candidates._market_context",
        return_value={"platforms": {}, "comparison_contract_version": "test"},
    )
    def test_missing_s16_does_not_block_active_guard_s6_dry_run(
        self,
        _market_context,
        _find_rule,
        _recommendation,
        _decision_ref,
        _mapping_ready,
    ) -> None:
        def query(template: str, hotel_id: str, **kwargs):
            if template == "operating_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "source_status": "ok",
                        "data_business_date": "2026-08-05",
                        "freshness_status": "fresh",
                        "committed_occupancy_rate": 0.5,
                        "room_type_forecasts": [
                            {
                                "room_type_id": "room-1",
                                "total_rooms": 10,
                                "committed_sold_rooms": 5,
                            }
                        ],
                    },
                }
            if template == "ota_price_mapping":
                return {
                    "status": "ok",
                    "payload": {
                        "source_status": "ok",
                        "business_date": "2026-08-05",
                        "price_snapshots": [
                            {
                                "channel": "meituan",
                                "ota_product_id": "product-1",
                                "ota_product_name": "测试商品",
                                "room_type_id": "room-1",
                                "room_type_name": "测试房型",
                                "current_price": 300,
                                "business_date": "2026-08-05",
                                "snapshot_time": "2026-08-05 00:04:40",
                                "price_editable_flag": True,
                                "mapping_status": "CONFIRMED",
                                "mapping_active": True,
                            }
                        ],
                    },
                }
            if template == "ota_business_metrics":
                return {"status": "ok", "payload": {"source_status": "ok"}}
            return {"status": "data_gap", "reason": "no_rows", "payload": {}}

        def resolve_guard(*args, **kwargs):
            return {
                "source": "active_price_guard_policy",
                "policy_id": "guard-1",
                "version": "v1",
                "policy_state": "active",
                "floor_price": 250,
                "ceiling_price": 350,
            }

        result = build_s5_real_candidates(
            query=query,
            resolve_guard=resolve_guard,
            control_db_path="/tmp/control.db",
            hotel_id="hotel-1",
            target_stay_date="2026-08-05",
            as_of_time="2026-08-05 00:07:10",
            s15_result={
                "status": "ok",
                "baseline_package": {
                    "target_date": "2026-08-05",
                    "hotel_final_sales_target": 30,
                    "sample_maturity": "stable",
                    "data_gaps": [],
                },
            },
            s16_result=None,
        )

        candidate = result["candidates"][0]
        self.assertEqual(candidate["eligibility"], "eligible_for_s6_dry_run")
        self.assertTrue(candidate["reference_only"])
        self.assertEqual(candidate["candidate_strength"], "partial")
        self.assertIn("missing_s16_progress_deviation", candidate["quality_flags"])
        self.assertEqual(result["eligible_for_s6_count"], 1)


if __name__ == "__main__":
    unittest.main()

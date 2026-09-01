from __future__ import annotations

import unittest

from runtime.s15_s16_responsibility_patch import (
    _baseline_message,
    _dynamic_message,
    _finalize_baseline,
    _valid_cached,
)
from runtime.s16_dynamic_diagnosis import build_s16_dynamic_diagnosis


class FakeRepository:
    def ota_business_metrics(self, platform, hotel_id, start_date, end_date, as_of_datetime):
        return [
            {
                "hotel_id": hotel_id,
                "business_date": start_date,
                "snapshot_time": f"{start_date} 12:00:00",
                "metric_code": "FLOW_EXPOSURE_UV",
                "metric_value": 500,
            },
            {
                "hotel_id": hotel_id,
                "business_date": start_date,
                "snapshot_time": f"{start_date} 12:00:00",
                "metric_code": "FLOW_INTENTION_UV",
                "metric_value": 80,
            },
            {
                "hotel_id": hotel_id,
                "business_date": start_date,
                "snapshot_time": f"{start_date} 12:00:00",
                "metric_code": "FLOW_PAY_ORDER_CNT",
                "metric_value": 4,
                "peer_average": 10,
                "competitor_rank": "3/20",
            },
        ]

    def ota_price_mapping(self, *args, **kwargs):
        return []


class FinalResponsibilityTest(unittest.TestCase):
    def baseline_payload(self):
        return {
            "status": "ok",
            "target_date": "2026-08-04",
            "as_of_datetime": "2026-08-04 09:00:00",
            "hotel": {
                "effective_target_room_nights": 30,
                "hourly_points": [],
            },
            "room_types": {
                "R1": {
                    "room_type_name": "大床房",
                    "effective_target_room_nights": 12,
                    "hourly_points": [],
                    "price_baseline": {"p20": 120, "median": 150, "p80": 190, "sample_count": 20},
                }
            },
            "operating_analysis": {
                "platform_reference": {
                    "selected_dates": ["2026-07-14", "2026-07-21", "2026-07-28"],
                    "history_day_count": 21,
                    "baseline_confidence_level": "weak",
                    "baselines": {
                        "browse_uv": {"median": 100, "sample_count": 3},
                        "first_conversion": {"median": 0.2, "sample_count": 3},
                        "second_conversion": {"median": 0.08, "p25": 0.06, "sample_count": 3},
                        "lead_price_metric": {"median": 128, "sample_count": 3},
                    },
                },
                "market": {"baseline_estimated_market_orders": 200, "sample_count": 3},
                "market_share": {"baseline_estimated_market_share": 0.08, "sample_count": 3},
                "second_conversion": {"rolling_30d_peer": {"peer_second_conversion": 0.09}},
                "diagnosis": ["sales_progress_slow"],
                "actions": [{"action_type": "suggest_room_price_reduction"}],
            },
        }

    def test_s15_materialization_excludes_dynamic_analysis(self):
        result = _finalize_baseline(self.baseline_payload())
        self.assertNotIn("operating_analysis", result)
        self.assertFalse(result["baseline_package"]["dynamic_diagnosis_included"])
        self.assertFalse(result["baseline_package"]["actions_included"])
        text = _baseline_message(result)
        self.assertIn("只展示历史基准", text)
        self.assertNotIn("建议降价", text)
        self.assertNotIn("sales_progress_slow", text)

    def test_finalized_package_is_cacheable_but_old_mixed_payload_is_not(self):
        self.assertTrue(_valid_cached(_finalize_baseline(self.baseline_payload())))
        self.assertFalse(_valid_cached(self.baseline_payload()))

    def test_s16_keeps_partial_day_facts_without_strong_comparison(self):
        baseline = _finalize_baseline(self.baseline_payload())
        progress = {
            "status": "ok",
            "hotel_id": "hotel-a",
            "target_date": "2026-08-04",
            "as_of_datetime": "2026-08-04 12:30:00",
            "hotel_result": {
                "committed_sold": 8,
                "total_rooms": 30,
                "available_rooms": 22,
                "target_line": {
                    "delta_pp": -12,
                    "expected_sold": 12,
                    "room_gap": -4,
                    "remaining_target_gap": 22,
                },
                "capacity_line": {"delta_pp": -8},
            },
            "room_type_results": [],
            "structure_summary": {"labels": []},
        }
        diagnosis = build_s16_dynamic_diagnosis(
            FakeRepository(),
            baseline=baseline,
            progress_report=progress,
            hotel_id="hotel-a",
            target_date="2026-08-04",
            as_of_datetime="2026-08-04 12:30:00",
        )
        self.assertFalse(diagnosis["period_comparable"])
        self.assertEqual(diagnosis["browse"]["status"], "period_not_comparable")
        self.assertFalse(diagnosis["auto_execution_eligible"])

    def test_router_separates_snapshot_baseline_and_dynamic_judgment(self):
        from runtime import feishu_command_router as router

        self.assertEqual(router._detect_intent("今天经营怎么样"), "progress_deviation_demo")
        self.assertEqual(router._detect_intent("查看完整基准数据包"), "sales_baseline_demo")
        self.assertNotEqual(router._detect_intent("经营快照"), "progress_deviation_demo")
        self.assertNotEqual(router._detect_intent("经营快照"), "sales_baseline_demo")
        self.assertNotEqual(router._detect_intent("调价 dry-run"), "progress_deviation_demo")
        self.assertNotEqual(router._detect_intent("调价 dry-run"), "sales_baseline_demo")

    def test_public_s16_text_hides_internal_terms(self):
        report = {
            "target_date": "2026-08-04",
            "dynamic_diagnosis": {
                "target_date": "2026-08-04",
                "sales": {"status": "slow", "committed_sold": 8, "total_rooms": 30, "current_expected_sold": 12, "sales_progress_delta_pp": -12, "checkpoint_room_gap": -4},
                "room_structure": {"room_type_results": []},
                "market": {"status": "period_not_comparable", "estimated_market_orders": 194, "baseline_median": 200},
                "market_share": {"status": "period_not_comparable", "current_estimated_market_share": 0.05, "baseline_median": 0.08},
                "browse": {"status": "period_not_comparable", "current": 80, "baseline_median": 100},
                "first_conversion": {"status": "period_not_comparable", "current": 0.16, "baseline_median": 0.2},
                "second_conversion": {"status": "period_not_comparable", "current": 0.05, "baseline_median": 0.08},
                "product_prices": [{"product_type": "普通全天房", "ota_product_name": "标准大床房", "current_price": 168}],
                "primary_issue": {"code": "DATA_NOT_COMPARABLE"},
                "secondary_issues": [],
                "action_candidates": [],
                "data_limitations": ["当前平台数据为日内累计，与历史完整日统计周期不同，暂不直接判断强弱。"],
            },
        }
        text = _dynamic_message(report)
        for forbidden in ("period_mismatch", "canonical", "metric code", "M4_same_weekday_daily", "WEAK_REFERENCE"):
            self.assertNotIn(forbidden, text)
        self.assertIn("暂无同一商品可比历史", text)


if __name__ == "__main__":
    unittest.main()

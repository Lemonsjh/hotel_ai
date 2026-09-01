from __future__ import annotations

import unittest
from pathlib import Path

from runtime.algorithms.activity_decision import calculate_activity_decision
from runtime.algorithms.competitor_alert import calculate_competitor_alert
from runtime.algorithms.conversion_funnel import calculate_conversion_funnel
from runtime.algorithms.data_gap_impact import DATA_GAP_IMPACT_MATRIX, DATA_GAP_IMPACT_SOURCE, field_gap_report
from runtime.algorithms.demand_index import WEIGHTS as DEMAND_WEIGHTS, calculate_demand_index
from runtime.algorithms.inventory import calculate_room_type_inventory
from runtime.algorithms.ota_health_score import WEIGHTS as HEALTH_WEIGHTS, calculate_ota_health_score
from runtime.algorithms.review_classifier import classify_review
from runtime.algorithms.roi_decision import calculate_roi_decision
from runtime.algorithms.run_context import build_run_context


class TestV27AlgorithmDeepening(unittest.TestCase):
    def setUp(self) -> None:
        self.context = build_run_context()

    def test_demand_index_uses_required_weights(self) -> None:
        self.assertEqual(
            DEMAND_WEIGHTS,
            {
                "date_environment": 0.20,
                "regional_heat": 0.15,
                "historical_same_period": 0.15,
                "booking_progress": 0.20,
                "current_traffic": 0.10,
                "current_conversion": 0.10,
                "room_type_inventory_pressure": 0.10,
            },
        )
        result = calculate_demand_index(self.context)
        self.assertEqual(result["formula_version"], "revised_first_formula_v27")
        self.assertIn("sub_scores", result)
        self.assertEqual(set(result["sub_scores"]), set(DEMAND_WEIGHTS))
        self.assertIn("calibration_rules", result)
        self.assertNotIn("history", result["sub_scores"])
        self.assertIn("deprecated_legacy_formula", result)
        self.assertIn("weighted_score", result)
        self.assertIn(result["demand_level"], {"strong", "normal", "weak"})
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])

    def test_demand_index_peak_valley_calibration_applies_to_platform_flags(self) -> None:
        low_valley_context = {
            "facts": {
                "business_snapshot": {"sold_rooms": 5},
                "sales_baseline": {"target_sold_rooms": 40},
                "progress_deviation": {},
                "orders_aggregate": {
                    "today_order_count": 6,
                    "last_week_same_day_order_count": 40,
                },
                "price_history": {"price_history": [{"occupancy": 0.9}]},
                "market_context": {
                    "traffic_state": "valley",
                    "regional_heat_index": 95,
                    "holiday_flag": True,
                    "event_signal": "city_event",
                },
                "external_ota_report_fields": {
                    "exposure": 1000,
                    "views": 800,
                    "clicks": 500,
                    "paid_orders": 200,
                },
                "room_types": {"room_types": [{"available_rooms": 1, "total_rooms": 50}]},
            }
        }
        valley_result = calculate_demand_index(low_valley_context)
        self.assertLessEqual(valley_result["demand_index"], 50)
        self.assertIn("platform_valley_cap", valley_result["calibration_applied"])

        high_peak_context = {
            "facts": {
                "business_snapshot": {"sold_rooms": 36},
                "sales_baseline": {"target_sold_rooms": 40},
                "progress_deviation": {},
                "orders_aggregate": {
                    "today_order_count": 38,
                    "last_week_same_day_order_count": 40,
                },
                "price_history": {"price_history": [{"occupancy": 0.2}]},
                "market_context": {
                    "traffic_state": "peak",
                    "regional_heat_index": 10,
                },
                "external_ota_report_fields": {
                    "exposure": 1000,
                    "views": 100,
                    "clicks": 20,
                    "paid_orders": 1,
                },
                "room_types": {"room_types": [{"available_rooms": 45, "total_rooms": 50}]},
            }
        }
        peak_result = calculate_demand_index(high_peak_context)
        self.assertGreaterEqual(peak_result["demand_index"], 50)
        self.assertIn("platform_peak_floor", peak_result["calibration_applied"])

    def test_inventory_formula_is_structured(self) -> None:
        result = calculate_room_type_inventory(self.context["facts"]["room_types"])
        self.assertEqual(result["algorithm"], "room_type_sellable_inventory_v1")
        self.assertEqual(result["total_inventory"], 50)
        self.assertGreaterEqual(result["sellable_inventory"], 0)

    def test_conversion_funnel_has_no_unknown_percentages(self) -> None:
        result = calculate_conversion_funnel(self.context["facts"]["external_ota_report_fields"])
        self.assertIn("payment_conversion_rate", result["rates"])
        self.assertIsInstance(result["rates"]["payment_conversion_rate"], float)
        self.assertNotIn("?", str(result))

    def test_health_score_uses_v27_weights(self) -> None:
        self.assertEqual(HEALTH_WEIGHTS["traffic"], 0.20)
        self.assertEqual(HEALTH_WEIGHTS["conversion"], 0.25)
        result = calculate_ota_health_score(self.context)
        self.assertIn("ota_health_score", result)
        self.assertIn(result["ota_health_level"], {"healthy", "watch", "risk"})
        self.assertFalse(result["today_label_allowed"])

    def test_competitor_alert_never_triggers_direct_price(self) -> None:
        result = calculate_competitor_alert(self.context)
        self.assertIn("alert_level", result)
        self.assertFalse(result["direct_price_trigger_allowed"])

    def test_activity_and_roi_are_dry_run_only(self) -> None:
        activity = calculate_activity_decision(self.context)
        roi = calculate_roi_decision(self.context)
        self.assertFalse(activity["live_allowed"])
        self.assertIn(activity["decision"], {"join", "keep", "cancel", "adjust", "block"})
        self.assertFalse(roi["live_allowed"])
        self.assertIn("roi", roi)

    def test_review_classifier_blocks_publish_without_manual_approval(self) -> None:
        result = classify_review({"rating": 3.2, "review_text": "dirty room and slow response, refund requested"})
        self.assertEqual(result["sentiment"], "negative")
        self.assertTrue(result["needs_manager_escalation"])
        self.assertTrue(result["compensation_requires_manual_approval"])
        self.assertFalse(result["live_allowed"])

    def test_review_classifier_tags_chinese_hotel_issues(self) -> None:
        result = classify_review({"rating": 3.0, "review_text": "房间脏，有异味，隔音差，前台态度不好，要求退款"})

        self.assertEqual(result["sentiment"], "negative")
        self.assertIn("hygiene", result["issue_tags"])
        self.assertIn("noise", result["issue_tags"])
        self.assertIn("service", result["issue_tags"])
        self.assertIn("compensation", result["issue_tags"])
        self.assertTrue(result["needs_manager_escalation"])
        self.assertTrue(result["compensation_requires_manual_approval"])

    def test_data_gap_impact_matrix_exists_in_runtime_and_contracts(self) -> None:
        self.assertEqual(DATA_GAP_IMPACT_SOURCE, "contracts/v27/data_gap_impact_matrix.yaml")
        self.assertIn("S4/S9", DATA_GAP_IMPACT_MATRIX)
        self.assertEqual(
            DATA_GAP_IMPACT_MATRIX["S4/S9"]["required_fields"],
            [
                "date_environment_score",
                "regional_heat_index",
                "historical_same_period_score",
                "booking_progress",
                "current_traffic_score",
                "payment_conversion_rate",
                "room_type_inventory_pressure",
            ],
        )
        self.assertIn("S5", DATA_GAP_IMPACT_MATRIX)
        self.assertEqual(DATA_GAP_IMPACT_MATRIX["S5"]["node_ids"], ["N015"])
        gap = field_gap_report("S5", {"current_price", "floor_price"})
        self.assertEqual(gap["status"], "data_gap")
        self.assertIn("S6", gap["blocked_downstream"])
        contract = Path("contracts/v27/data_gap_impact_matrix.yaml")
        self.assertTrue(contract.exists())
        self.assertIn("S14/S14-EXT", contract.read_text(encoding="utf-8"))

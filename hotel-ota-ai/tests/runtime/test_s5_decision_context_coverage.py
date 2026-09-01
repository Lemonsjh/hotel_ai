from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from runtime.algorithms.run_context import build_run_context
from runtime.algorithms.s5_decision_context import build_s5_decision_context
from runtime.demo_mode import build_demo_node_result
from runtime.demo_today_generator import generate_today_demo_result


class TestS5DecisionContextCoverage(unittest.TestCase):
    def test_static_fallback_reports_partial_s5_context(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "empty-static.sqlite")
            context = build_run_context(db_path=db_path)

        decision_context = build_s5_decision_context(context, scenario_id="SC03")

        self.assertEqual(context["context_source"], "static_demo_fixtures")
        self.assertEqual(context["data_source_type"], "demo_data")
        self.assertEqual(decision_context["decision_strength"], "partial")
        self.assertIn("cannot_confirm_price_is_primary_issue", decision_context["not_allowed_conclusions"])

    def test_static_fallback_never_reports_full_even_when_static_fields_are_present(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "empty-static.sqlite")
            context = build_run_context(db_path=db_path)

        facts = context.setdefault("facts", {})
        facts.setdefault("orders_aggregate", {})["expected_occupancy_tonight"] = 0.68
        facts.setdefault("orders_aggregate", {})["reservation_details"] = [{"room_type_id": "KING", "room_nights": 2}]
        facts.setdefault("sales_baseline", {})["baseline_price_by_room_type"] = [
            {"room_type_id": "KING", "baseline_price": 184}
        ]
        facts.setdefault("sales_baseline", {})["hourly_target_curve"] = [
            {"time": "16:00", "target_room_nights": 9}
        ]

        decision_context = build_s5_decision_context(context, scenario_id="SC03")

        self.assertEqual(decision_context["context_source"], "static_demo_fixtures")
        self.assertEqual(decision_context["decision_strength"], "partial")
        self.assertIn("cannot_confirm_price_is_primary_issue", decision_context["not_allowed_conclusions"])

    def test_generated_sqlite_s5_context_includes_cross_signals(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "generated.sqlite")
            generate_today_demo_result(
                argparse.Namespace(
                    business_date="2026-06-15",
                    seed=20260615,
                    profile="normal",
                    hotel_id="puyue-demo",
                    write_db=True,
                    write_fixtures=False,
                    dry_run=False,
                    output_dir=None,
                    db=db_path,
                )
            )
            context = build_run_context(db_path=db_path, hotel_id="puyue-demo")
            decision_context = build_s5_decision_context(context, scenario_id="SC03")
            node = build_demo_node_result("N015", db_path=db_path, as_of_time="16:00", as_of_time_source="test")

        self.assertEqual(decision_context["context_source"], "sqlite_synthetic_today_demo")
        self.assertGreaterEqual(decision_context["runtime_feed_coverage"], 0.85)
        self.assertIn("our_price_index", decision_context["competitor_context"])
        self.assertEqual(decision_context["market_context"]["demand_formula_version"], "revised_first_formula_v27")
        self.assertIn("booking_progress", decision_context["market_context"]["demand_sub_scores"])
        self.assertIn("regional_heat", decision_context["market_context"]["demand_sub_scores"])
        self.assertIn("next_peak_window", decision_context["traffic_timing_context"])
        self.assertIn("diagnosis_status", decision_context["diagnosis_constraint_context"])
        self.assertIn("contract_input_coverage", node["node_result"])
        self.assertEqual(node["node_result"]["demand_formula_version"], "revised_first_formula_v27")
        self.assertIn("booking_progress", node["node_result"]["demand_sub_scores"])
        self.assertIn("algorithm_usage_coverage", node["node_result"])
        self.assertIn("competitor_context", node["node_result"])
        self.assertIn("as_of_checkpoint_gap", node["node_result"]["algorithm_used_inputs"])
        self.assertIn("daily_remaining_gap", node["node_result"]["algorithm_used_inputs"])
        self.assertIn("pickup_speed", node["node_result"]["algorithm_used_inputs"])
        self.assertNotIn("progress_gap", node["node_result"]["algorithm_used_inputs"])
        self.assertFalse(node["node_result"]["direct_price_trigger_allowed"])


if __name__ == "__main__":
    unittest.main()

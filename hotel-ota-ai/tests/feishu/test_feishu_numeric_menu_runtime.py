from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from runtime.demo_today_generator import generate_today_demo_result
from runtime.feishu_output_renderer import render_feishu_output
from runtime.feishu_command_router import route_feishu_command


def _seed_synthetic_today(db_path: str) -> None:
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


class TestFeishuNumericMenuRuntime(unittest.TestCase):
    def test_numeric_menu_routes_to_runtime_nodes_and_latest_synthetic_demo(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            cases = {
                "1": ("run_s02", "N005", "S2"),
                "2": ("sales_baseline_demo", "N010", "S15"),
                "3": ("progress_deviation_demo", "N011", "S16"),
                "4": ("market_context_demo", "N006", "S4"),
                "5": ("ota_diagnosis_demo", "N009", "S14"),
                "6": ("competition_alert", "N007", "S7"),
                "7": ("reputation_demo", "N008", "S12"),
                "9": ("revenue_decision_demo", "N015", "S5"),
                "10": ("price_execution_dry_run", "N016", "S6"),
                "11": ("promotion_suggestion", "N021", "S11"),
                "12": ("roi_demo", "N013", "S10"),
                "13": ("traffic_peak_demo", "N020", "S9"),
                "14": ("customer_analysis_demo", "N014", "S17"),
            }

            for message, (intent, node_id, skill_id) in cases.items():
                with self.subTest(message=message):
                    result = route_feishu_command(message, role="operator", db_path=db_path)
                    self.assertEqual(result["intent"], intent)
                    self.assertEqual(result["node_id"], node_id)
                    self.assertEqual(result["skill_id"], skill_id)
                    self.assertTrue(result["generated_by_runtime"])
                    allowed_statuses = {"ok", "preview_only", "partial", "data_gap"} if message in {"4", "6", "10", "11"} else {"ok", "preview_only", "partial"}
                    self.assertIn(result["status"], allowed_statuses)
                    if message in {"4", "6"}:
                        self.assertEqual(result["runtime_command"], "market-context" if message == "4" else "competition-alert")
                        continue
                    if message == "11":
                        self.assertEqual(result["runtime_command"], "promotion-suggestion --read-only")
                        self.assertFalse(result["live_allowed"])
                        self.assertFalse(result["write_performed"])
                        self.assertNotIn("demo_dataset_id", result)
                        continue
                    if message == "10" and result["status"] == "data_gap":
                        self.assertEqual(result["blocked_reason"], "database_source_disabled")
                        continue
                    run_context = result.get("run_context") or {}
                    self.assertEqual(run_context.get("context_source"), "sqlite_synthetic_today_demo")
                    self.assertEqual(run_context.get("business_date"), "2026-06-15")
                    self.assertFalse(run_context.get("fallback_used"))
                    self.assertEqual(result.get("data_source_type"), "synthetic_today_demo")
                    self.assertNotEqual(result.get("blocked_reason"), "database_source_disabled")

    def test_numeric_status_and_admin_actions_are_runtime_safe(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            status = route_feishu_command("15", role="operator", db_path=db_path)
            self.assertEqual(status["intent"], "runtime_status")
            self.assertEqual(status["context_source"], "sqlite_synthetic_today_demo")
            self.assertEqual(status["demo_chain_context_date"], "2026-06-15")
            self.assertFalse(status["db_source_enable_required_for_demo"])
            self.assertNotIn("DB_SOURCE_ENABLE=1", status["suggested_next_step"])

            generated = route_feishu_command("16", role="operator", db_path=db_path)
            self.assertEqual(generated["intent"], "seed_demo")
            self.assertEqual(generated["status"], "ok")
            self.assertTrue(generated["generated_today_demo_ready"])
            self.assertFalse(generated["live_allowed"])

            model = route_feishu_command("17", role="operator", db_path=db_path)
            self.assertEqual(model["intent"], "model_config_request")
            self.assertEqual(model["status"], "blocked")
            self.assertFalse(model["model_config_changed"])

    def test_revenue_decision_discloses_contract_and_algorithm_usage(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            result = route_feishu_command("9", role="operator", db_path=db_path)

        self.assertEqual(result["intent"], "revenue_decision_demo")
        self.assertEqual(result["node_id"], "N015")
        self.assertEqual(result["run_context"]["context_source"], "sqlite_synthetic_today_demo")
        self.assertEqual(result["data_source_type"], "synthetic_today_demo")
        self.assertEqual(result["conversion_problem"], True)
        self.assertIn("conversion_problem", result["algorithm_used_inputs"])
        self.assertIn("competitor_context", result["algorithm_used_inputs"])
        self.assertIn("traffic_timing_context", result["algorithm_used_inputs"])
        self.assertIn("field_usage_states", result)
        self.assertEqual(result["field_usage_states"]["conversion_problem"], "used_by_algorithm")
        self.assertIn(result["decision_strength"], {"full", "partial", "preview_only"})
        self.assertIn("conversion_health_context", result)
        self.assertIn("competitor_context", result)
        self.assertIn("traffic_timing_context", result)

    def test_revenue_rendering_hides_coverage_and_algorithm_inputs(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)
            result = route_feishu_command("9", role="owner", db_path=db_path)

        rendered = render_feishu_output(result, "owner_business")
        self.assertIn("contract_input_coverage", result)
        self.assertIn("algorithm_used_inputs", result)
        for internal_field in [
            "contract_input_coverage",
            "runtime_feed_coverage",
            "algorithm_usage_coverage",
            "algorithm_used_inputs",
            "conversion_problem",
        ]:
            self.assertNotIn(internal_field, rendered["text"])

    def test_gateway_restart_questions_do_not_claim_restart_or_execute_actions(self) -> None:
        result = route_feishu_command("gateway restart status", role="admin")
        self.assertEqual(result["intent"], "self_check")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["restart_attempted"])
        self.assertFalse(result["restart_success_claimed"])
        self.assertEqual(result["cron_diagnostics"]["gateway_status"], "unknown")

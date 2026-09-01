from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from runtime.algorithms.run_context import build_run_context
from runtime.demo_mode import build_all_demo_chains_result, build_all_demo_nodes_result, build_demo_node_result
from runtime.demo_today_generator import generate_today_demo_result
from runtime.feishu_command_router import route_feishu_command


class TestSyntheticTodayRunContext(unittest.TestCase):
    def test_demo_node_can_read_latest_synthetic_today_sqlite(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "synthetic.sqlite")
            generate_today_demo_result(
                argparse.Namespace(
                    business_date="2026-06-12",
                    seed=20260612,
                    profile="normal",
                    hotel_id="puyue-demo",
                    write_db=True,
                    write_fixtures=False,
                    dry_run=False,
                    output_dir=None,
                    db=db_path,
                )
            )
            context = build_run_context(db_path=db_path, hotel_id="puyue-demo", use_generated_today=True)
            self.assertTrue(context["use_generated_today"])
            self.assertEqual(context["data_source_type"], "synthetic_today_demo")
            self.assertEqual(context["core_metrics"]["total_rooms"], 50)
            self.assertEqual(context["context_source"], "sqlite_synthetic_today_demo")
            self.assertFalse(context["fallback_used"])
            self.assertIn("generated_demo_run_id", context)
            self.assertIn("generated_at", context)

            default_context = build_run_context(db_path=db_path, hotel_id="puyue-demo")
            self.assertTrue(default_context["use_generated_today"])
            self.assertFalse(default_context["requested_generated_today"])
            self.assertEqual(default_context["context_source"], "sqlite_synthetic_today_demo")
            self.assertFalse(default_context["fallback_used"])

            node = build_demo_node_result("N005", db_path=db_path, use_generated_today=True)
            self.assertEqual(node["node_result"]["data_source_type"], "synthetic_today_demo")
            self.assertEqual(node["node_result"]["total_rooms"], 50)

            nodes = build_all_demo_nodes_result(db_path=db_path, use_generated_today=True)
            self.assertEqual(nodes["total_nodes"], 22)
            self.assertEqual(nodes["failed_nodes"], 1)
            self.assertEqual(nodes["passed_nodes"], 21)
            self.assertEqual(nodes["run_context"]["context_source"], "sqlite_synthetic_today_demo")
            self.assertTrue(nodes["use_generated_today"])
            self.assertTrue(nodes["requested_generated_today"])
            self.assertEqual(nodes["context_warnings"], [])
            chains = build_all_demo_chains_result(db_path=db_path, use_generated_today=True)
            self.assertEqual(chains["total_scenarios"], 10)
            self.assertEqual(chains["failed_scenarios"], 2)
            self.assertEqual(chains["passed_scenarios"], 8)
            self.assertEqual(chains["run_context"]["context_source"], "sqlite_synthetic_today_demo")
            self.assertTrue(chains["use_generated_today"])
            self.assertTrue(chains["requested_generated_today"])
            self.assertEqual(chains["context_warnings"], [])

            routed = route_feishu_command(
                "S02 demo",
                role="operator",
                db_path=db_path,
            )
            self.assertEqual(routed["core_metrics"]["total_rooms"], 50)
            self.assertEqual(routed["data_source_type"], "synthetic_today_demo")

    def test_all_demo_outputs_explain_static_fallback_when_generated_today_missing(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "empty.sqlite")
            nodes = build_all_demo_nodes_result(db_path=db_path, use_generated_today=True)
            chains = build_all_demo_chains_result(db_path=db_path, use_generated_today=True)

        self.assertEqual(nodes["run_context"]["context_source"], "static_demo_fixtures")
        self.assertFalse(nodes["use_generated_today"])
        self.assertTrue(nodes["requested_generated_today"])
        self.assertTrue(nodes["run_context"]["fallback_used"])
        self.assertIn("generated_today_demo_not_found", nodes["context_warnings"])
        self.assertEqual(chains["run_context"]["context_source"], "static_demo_fixtures")
        self.assertFalse(chains["use_generated_today"])
        self.assertTrue(chains["requested_generated_today"])
        self.assertTrue(chains["run_context"]["fallback_used"])
        self.assertIn("generated_today_demo_not_found", chains["context_warnings"])

    def test_strict_generated_today_returns_data_gap_instead_of_static_fallback(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "empty.sqlite")
            context = build_run_context(db_path=db_path, use_generated_today=True, strict_generated_today=True)
            nodes = build_all_demo_nodes_result(db_path=db_path, use_generated_today=True, strict_generated_today=True)
            chains = build_all_demo_chains_result(db_path=db_path, use_generated_today=True, strict_generated_today=True)

        self.assertEqual(context["status"], "data_gap")
        self.assertEqual(context["context_source"], "missing_sqlite_synthetic_today_demo")
        self.assertTrue(context["requested_generated_today"])
        self.assertFalse(context["use_generated_today"])
        self.assertIn("generated_today_demo_not_found", context["context_warnings"])
        self.assertEqual(nodes["status"], "data_gap")
        self.assertEqual(nodes["failed_nodes"], 22)
        self.assertEqual(nodes["context_source"], "missing_sqlite_synthetic_today_demo")
        self.assertEqual(chains["status"], "data_gap")
        self.assertEqual(chains["failed_scenarios"], 10)
        self.assertEqual(chains["context_source"], "missing_sqlite_synthetic_today_demo")

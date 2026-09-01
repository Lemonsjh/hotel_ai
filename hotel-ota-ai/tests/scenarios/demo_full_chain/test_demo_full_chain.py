from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from runtime.cli import main


def capture_main(argv: list[str]) -> dict:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    payload = json.loads(buffer.getvalue())
    payload["_exit_code"] = code
    return payload


def capture_static_fixture_main(argv: list[str]) -> dict:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = str(Path(tmp) / "empty-static.sqlite")
        return capture_main(["--db", db_path, *argv])


class TestDemoFullChain(unittest.TestCase):
    def test_all_demo_chains_cover_all_nodes_and_keep_safety_flags(self) -> None:
        payload = capture_static_fixture_main(["--demo", "demo-chain", "--all"])
        self.assertEqual(payload["_exit_code"], 0)
        self.assertEqual(payload["mode"], "demo-chain")
        self.assertEqual(payload["context_source"], "static_demo_fixtures")
        self.assertEqual(payload["run_context"]["context_source"], "static_demo_fixtures")
        self.assertEqual(payload["total_scenarios"], 10)
        self.assertEqual(payload["passed_scenarios"], 8)
        self.assertEqual(payload["failed_scenarios"], 2)
        self.assertFalse(payload["formal_approval_created"])
        self.assertEqual(payload["live_execution_count"], 0)
        self.assertEqual(len(payload["chains"]), 10)
        self.assertEqual(payload["data_source_type"], "demo_data")
        self.assertFalse(payload["approval_data_allowed"])
        self.assertFalse(payload["live_allowed"])

        covered_nodes: set[str] = set()
        for chain in payload["chains"]:
            self.assertEqual(chain["data_source_type"], "demo_data")
            self.assertFalse(chain["approval_data_allowed"])
            self.assertFalse(chain["live_allowed"])
            self.assertEqual(chain["missing_nodes"], [])
            self.assertFalse(set(chain["forbidden_nodes"]) & set(chain["executed_nodes"]))
            covered_nodes.update(chain["scenario"]["nodes"])
        self.assertEqual(covered_nodes, {f"N{index:03d}" for index in range(1, 23)})

    def test_all_demo_nodes_are_available(self) -> None:
        payload = capture_static_fixture_main(["--demo", "demo-node", "--all"])
        self.assertEqual(payload["_exit_code"], 0)
        self.assertEqual(payload["mode"], "demo-node")
        self.assertEqual(payload["context_source"], "static_demo_fixtures")
        self.assertEqual(payload["run_context"]["context_source"], "static_demo_fixtures")
        self.assertEqual(payload["total_nodes"], 22)
        self.assertEqual(payload["passed_nodes"], 21)
        self.assertEqual(payload["failed_nodes"], 1)
        self.assertFalse(payload["formal_approval_created"])
        self.assertEqual(payload["live_execution_count"], 0)
        self.assertEqual(len(payload["nodes"]), 22)
        for node in payload["nodes"]:
            self.assertEqual(node["data_source_type"], "demo_data")
            self.assertFalse(node["approval_data_allowed"])
            self.assertFalse(node["live_allowed"])
            self.assertTrue(node["blocked_for_live"])
        n022 = next(node for node in payload["nodes"] if node["node_id"] == "N022")
        self.assertEqual(n022["node_result"]["blocked_reason"], "s14_ext_migrated_to_independent_service")

        s5 = next(node for node in payload["nodes"] if node["node_id"] == "N015")
        self.assertEqual(s5["node_result"]["status"], "preview_only")
        self.assertEqual(s5["node_result"]["handoff_to"], "S6")
        s6 = next(node for node in payload["nodes"] if node["node_id"] == "N016")
        self.assertIn("dry_run_preview", s6)
        s11 = next(node for node in payload["nodes"] if node["node_id"] == "N021")
        self.assertIn("dry_run_preview", s11)

    def test_s14_ext_demo_chain_returns_migrated_notice(self) -> None:
        payload = capture_static_fixture_main(["--demo", "demo-chain", "--scenario", "SC10"])
        self.assertEqual(payload["_exit_code"], 0)
        self.assertEqual(payload["context_source"], "static_demo_fixtures")
        self.assertIn("external_diagnosis", payload["fixtures"])
        report = payload["fixtures"]["external_diagnosis"]
        self.assertEqual(report["html_report_preview_status"], "generated")
        self.assertFalse(report["live_allowed"])

        n022 = next(node for node in payload["node_results"] if node["node_id"] == "N022")
        self.assertEqual(n022["node_result"]["skill_id"], "S14-EXT")
        self.assertEqual(n022["node_result"]["status"], "blocked")
        self.assertEqual(n022["node_result"]["blocked_reason"], "s14_ext_migrated_to_independent_service")
        self.assertTrue(n022["node_result"]["external_isolated"])
        self.assertEqual(n022["node_result"]["html_report_preview_status"], "migrated")
        self.assertNotIn("artifact_path", n022["node_result"])
        self.assertNotIn("report_url", n022["node_result"])
        self.assertNotIn("field_coverage_report", n022["node_result"])

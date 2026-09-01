from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.approval_guard import validate_demo_safe_approval_payload
from runtime.cli import main
from runtime.data_gate import evaluate_data_gate
from runtime.demo_mode import (
    formal_approval_allowed,
    is_demo_mode,
    live_execution_allowed,
    mark_demo_payload,
)
from runtime.field_contract_loader import load_field_registry, load_node_io_contract, load_source_mapping


ROOT = Path(__file__).resolve().parents[1]


def read_json(path: str) -> dict:
    with (ROOT / path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


class EnvMixin:
    def setUp(self) -> None:
        self._old_env = os.environ.copy()
        os.environ.pop("HOTEL_OTA_DEMO_MODE", None)
        os.environ.pop("HOTEL_OTA_ALLOW_DEMO_PLACEHOLDER", None)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old_env)


class TestV27ArchitectureRegistries(unittest.TestCase):
    def test_registry_counts_and_key_entities_match_v27_scope(self) -> None:
        nodes = read_json("architecture/node_registry.json")["nodes"]
        edges = read_json("architecture/edge_registry.json")["edges"]
        agents = read_json("architecture/agent_registry.json")["agents"]
        scenarios = read_json("architecture/scenario_chain_registry.json")["scenarios"]

        self.assertEqual(len(nodes), 22)
        self.assertEqual(len(edges), 67)
        self.assertEqual(len(scenarios), 10)
        self.assertEqual({agent["agent_id"] for agent in agents}, {f"A{i}" for i in range(7)})
        self.assertTrue(any(node["id"] == "N022" and node.get("skill_id") == "S14-EXT" for node in nodes))

    def test_edges_and_scenarios_reference_registered_nodes_and_edges(self) -> None:
        node_ids = {node["id"] for node in read_json("architecture/node_registry.json")["nodes"]}
        edges = read_json("architecture/edge_registry.json")["edges"]
        edge_ids = {edge["edge_id"] for edge in edges}
        scenarios = read_json("architecture/scenario_chain_registry.json")["scenarios"]

        for edge in edges:
            self.assertIn(edge["source_node_id"], node_ids)
            self.assertIn(edge["target_node_id"], node_ids)
            self.assertTrue(edge.get("why"))

        for scenario in scenarios:
            self.assertTrue(scenario["demo_supported"])
            self.assertTrue((ROOT / "examples" / "demo_data" / "scenarios" / f"{scenario['id']}.json").exists())
            self.assertTrue(set(scenario["nodes"]).issubset(node_ids))
            self.assertTrue(set(scenario["required_edges"]).issubset(edge_ids))
            self.assertIn("live_allowed=false", scenario["demo_expected_outputs"])


class TestContractsAndDemoGate(EnvMixin, unittest.TestCase):
    def test_contracts_are_machine_readable_and_keep_field_statuses_open(self) -> None:
        fields = load_field_registry()
        node_io = load_node_io_contract()
        source_mapping = load_source_mapping()

        statuses = set(fields["supported_statuses"])
        self.assertTrue({"confirmed_exact", "confirmed_alias", "candidate_inferred", "project_only", "config_only"}.issubset(statuses))
        self.assertGreaterEqual(len(fields["fields"]), 290)
        self.assertEqual(fields["source_version"], "V27_project_repair_executable_contract")
        self.assertEqual(len(node_io["nodes"]), 22)
        self.assertGreaterEqual(source_mapping["source_field_count"], 500)

    def test_demo_mode_can_be_enabled_by_env_or_cli_flag(self) -> None:
        class Args:
            demo = False

        self.assertFalse(is_demo_mode(Args()))
        os.environ["HOTEL_OTA_DEMO_MODE"] = "1"
        self.assertTrue(is_demo_mode(Args()))

        class CliArgs:
            demo = True

        os.environ.pop("HOTEL_OTA_DEMO_MODE")
        self.assertTrue(is_demo_mode(CliArgs()))

    def test_demo_payload_is_blocked_from_formal_approval_and_live(self) -> None:
        payload = mark_demo_payload({"dry_run_summary": {"price": 388}})

        self.assertEqual(payload["data_source_type"], "demo_data")
        self.assertFalse(payload["approval_data_allowed"])
        self.assertFalse(payload["live_allowed"])
        self.assertFalse(formal_approval_allowed(payload))
        self.assertFalse(live_execution_allowed(payload))

        approval_gate = validate_demo_safe_approval_payload(payload, "price_update")
        self.assertFalse(approval_gate["allowed"])
        self.assertEqual(approval_gate["template_id"], "demo-data")

    def test_data_gate_allows_demo_preview_but_blocks_approval_and_live(self) -> None:
        result = evaluate_data_gate(
            mark_demo_payload({"hotel_id": "demo-hotel", "data_business_date": "2026-06-11"}),
            hard_required=["hotel_id", "data_business_date"],
        )

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["allowed"])
        self.assertTrue(result["demo_mode"])
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])
        self.assertEqual(result["missing_fields"], [])

    def test_data_gate_blocks_missing_hard_required_real_payload(self) -> None:
        result = evaluate_data_gate(
            {"data_source_type": "ota_api", "freshness_status": "fresh", "business_status": "current"},
            hard_required=["hotel_id", "data_business_date"],
        )

        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["allowed"])
        self.assertEqual(set(result["missing_fields"]), {"hotel_id", "data_business_date"})
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])

    def test_demo_chain_cli_outputs_full_demo_safety_metadata(self) -> None:
        payload = capture_static_fixture_main(["--demo", "demo-chain", "--scenario", "SC01"])

        self.assertEqual(payload["_exit_code"], 0)
        self.assertEqual(payload["scenario_id"], "SC01")
        self.assertEqual(payload["context_source"], "static_demo_fixtures")
        self.assertEqual(payload["data_source_type"], "demo_data")
        self.assertFalse(payload["approval_data_allowed"])
        self.assertFalse(payload["live_allowed"])
        self.assertIn("operating_snapshot", payload["fixtures"])

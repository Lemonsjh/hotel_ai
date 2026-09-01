from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
EXPECTED_AGENT_MAPPING = {
    "N010": "A2",
    "N011": "A2",
    "N015": "A3",
    "N016": "A4",
    "N018": "A5",
    "N019": "A6",
    "N022": "A2",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestV26NodeIoContract(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(ROOT / "contracts" / "v26" / "node_io_contract.yaml")
        self.registry = load_json(ROOT / "contracts" / "v26" / "field_registry.yaml")
        self.field_keys = {field["canonical_key"] for field in self.registry["fields"]}

    def test_n001_to_n022_have_inputs_outputs_and_v26_mapping(self) -> None:
        nodes = {node["node_id"]: node for node in self.contract["nodes"]}
        self.assertEqual(set(nodes), {f"N{index:03d}" for index in range(1, 23)})
        for node_id, node in nodes.items():
            with self.subTest(node=node_id):
                self.assertTrue(node["input_fields"])
                self.assertTrue(node["output_fields"])
                self.assertIn("direct_trigger", node)
                self.assertIn("chain_trigger", node)
                self.assertIn("blueprint_basis", node)
                for field in node["input_fields"] + node["output_fields"]:
                    self.assertIn(field["canonical_key"], self.field_keys)

    def test_key_agent_assignments_match_v26(self) -> None:
        nodes = {node["node_id"]: node for node in self.contract["nodes"]}
        for node_id, agent_id in EXPECTED_AGENT_MAPPING.items():
            with self.subTest(node=node_id):
                self.assertEqual(nodes[node_id]["agent_id"], agent_id)

    def test_execution_node_boundaries_are_encoded(self) -> None:
        nodes = {node["node_id"]: node for node in self.contract["nodes"]}
        n016_inputs = {field["canonical_key"] for field in nodes["N016"]["input_fields"]}
        self.assertTrue({"approval_id", "candidate_price", "price_floor", "price_ceiling", "freshness_status", "live_switch"}.issubset(n016_inputs))
        n015_outputs = {field["canonical_key"] for field in nodes["N015"]["output_fields"]}
        self.assertIn("price_recommendations", n015_outputs)

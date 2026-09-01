from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV27EdgePayloadContract(unittest.TestCase):
    def test_edges_reference_registered_nodes_and_have_payload_mapping(self) -> None:
        nodes = {node["id"] for node in json.loads((ROOT / "architecture" / "node_registry.json").read_text(encoding="utf-8"))["nodes"]}
        contract = json.loads((ROOT / "contracts" / "v27" / "edge_payload_contract.yaml").read_text(encoding="utf-8"))
        self.assertEqual(contract["edge_count"], 67)
        for edge in contract["edges"]:
            with self.subTest(edge=edge["edge_id"]):
                self.assertIn(edge["source_node_id"], nodes)
                self.assertIn(edge["target_node_id"], nodes)
                self.assertTrue(edge["why"])
                self.assertTrue(edge["payload"])
                self.assertTrue(edge["source_output_mapping_required"])
                self.assertTrue(edge["target_input_mapping_required"])

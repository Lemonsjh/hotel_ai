from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV27NodeIoContract(unittest.TestCase):
    def test_nodes_cover_n001_to_n022_and_reference_known_fields(self) -> None:
        registry = json.loads((ROOT / "contracts" / "v27" / "field_registry.yaml").read_text(encoding="utf-8"))
        contract = json.loads((ROOT / "contracts" / "v27" / "node_io_contract.yaml").read_text(encoding="utf-8"))
        field_keys = {field["canonical_key"] for field in registry["fields"]}
        nodes = {node["node_id"]: node for node in contract["nodes"]}
        self.assertEqual(set(nodes), {f"N{index:03d}" for index in range(1, 23)})
        for node_id, node in nodes.items():
            with self.subTest(node=node_id):
                self.assertTrue(node["input_fields"])
                self.assertTrue(node["output_fields"])
                self.assertIn("direct_trigger", node)
                self.assertIn("chain_trigger", node)
                for field in node["input_fields"] + node["output_fields"]:
                    self.assertIn(field["canonical_key"], field_keys)

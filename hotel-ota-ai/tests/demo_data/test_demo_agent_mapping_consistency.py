from __future__ import annotations

import unittest

from runtime.agent_mapping_loader import load_node_agent_mapping
from runtime.demo_mode import build_all_demo_nodes_result


class TestDemoAgentMappingConsistency(unittest.TestCase):
    def test_demo_node_agent_ids_match_registry(self) -> None:
        mapping = load_node_agent_mapping()
        payload = build_all_demo_nodes_result()
        self.assertEqual(payload["total_nodes"], 22)
        for node in payload["nodes"]:
            self.assertEqual(node["agent_id"], mapping[node["node_id"]]["agent_id"], node["node_id"])
        self.assertEqual(mapping["N010"]["agent_id"], "A2")
        self.assertEqual(mapping["N011"]["agent_id"], "A2")
        self.assertEqual(mapping["N015"]["agent_id"], "A3")
        self.assertEqual(mapping["N016"]["agent_id"], "A4")
        self.assertEqual(mapping["N018"]["agent_id"], "A5")
        self.assertEqual(mapping["N019"]["agent_id"], "A6")

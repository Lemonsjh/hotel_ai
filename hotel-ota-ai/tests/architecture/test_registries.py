from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(path: str) -> dict:
    with (ROOT / path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestArchitectureRegistries(unittest.TestCase):
    def test_v27_counts_and_registered_scope(self) -> None:
        nodes = load("architecture/node_registry.json")["nodes"]
        edges = load("architecture/edge_registry.json")["edges"]
        scenarios = load("architecture/scenario_chain_registry.json")["scenarios"]

        self.assertEqual(len(nodes), 22)
        self.assertEqual(len(edges), 67)
        self.assertEqual(len(scenarios), 10)
        self.assertTrue(all(edge.get("why") for edge in edges))
        self.assertEqual({scenario["scenario_id"] for scenario in scenarios}, {f"SC{index:02d}" for index in range(1, 11)})
        self.assertNotIn("SC11", {scenario["id"] for scenario in scenarios})
        self.assertNotIn("SC12", {scenario["id"] for scenario in scenarios})

    def test_skill_alignment_covers_s1_to_s17_and_s14_ext(self) -> None:
        alignment = load("architecture/skill_node_alignment.json")["skills"]
        skill_ids = {item["skill_id"] for item in alignment}
        self.assertEqual(len(alignment), 18)
        self.assertTrue({f"S{i}" for i in range(1, 18)}.issubset(skill_ids))
        self.assertIn("S14-EXT", skill_ids)

        for item in alignment:
            self.assertTrue((ROOT / item["demo_node_fixture"]).exists())
            self.assertTrue((ROOT / item["algorithm_rules_ref"]).exists())
            self.assertEqual(item["demo_safety"]["data_source_type"], "demo_data")
            self.assertFalse(item["demo_safety"]["approval_data_allowed"])
            self.assertFalse(item["demo_safety"]["live_allowed"])

    def test_drawio_page_registry_records_known_page_mismatch(self) -> None:
        content = (ROOT / "architecture" / "drawio_page_registry.md").read_text(encoding="utf-8")
        self.assertIn("P13", content)
        self.assertIn("P14", content)

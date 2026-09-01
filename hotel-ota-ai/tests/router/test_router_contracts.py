from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load(path: str) -> dict:
    with (ROOT / path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


class TestScenarioRouter(unittest.TestCase):
    def test_router_routes_match_scenario_registry(self) -> None:
        router = load("router/scenario_router.yaml")
        scenarios = {item["id"]: item for item in load("architecture/scenario_chain_registry.json")["scenarios"]}
        edges = {edge["edge_id"] for edge in load("architecture/edge_registry.json")["edges"]}
        nodes = {node["id"] for node in load("architecture/node_registry.json")["nodes"]}

        self.assertEqual({route["scenario_id"] for route in router["routes"]}, set(scenarios))
        for route in router["routes"]:
            scenario = scenarios[route["scenario_id"]]
            self.assertEqual(route["required_edges"], scenario["required_edges"])
            self.assertTrue(set(route["required_edges"]).issubset(edges))
            self.assertTrue(set(route["optional_edges"]).issubset(edges))
            self.assertTrue(set(route["nodes"]).issubset(nodes))
            self.assertTrue(route["demo_fixture_id"].startswith("demo_sc"))

    def test_intent_cases_have_registered_expected_routes(self) -> None:
        cases = load("router/intent_cases.json")["cases"]
        scenario_ids = {item["id"] for item in load("architecture/scenario_chain_registry.json")["scenarios"]}

        self.assertEqual(len(cases), 10)
        for case in cases:
            self.assertIn(case["expected_route"], scenario_ids)
            self.assertEqual(case["demo_fixture_id"], f"demo_{case['scenario_id'].lower()}")


from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestV27ScenarioChainContract(unittest.TestCase):
    def test_sc01_to_sc10_have_runtime_demo_policy(self) -> None:
        contract = load_json(ROOT / "contracts" / "v27" / "scenario_chain_contract.yaml")
        scenarios = {scenario["scenario_id"]: scenario for scenario in contract["scenarios"]}
        self.assertEqual(set(scenarios), {f"SC{index:02d}" for index in range(1, 11)})
        for scenario_id, scenario in scenarios.items():
            with self.subTest(scenario=scenario_id):
                self.assertTrue(scenario["nodes"])
                self.assertTrue(scenario["skills"])
                self.assertTrue(scenario["agents"])
                self.assertTrue(scenario["required_edges"])
                self.assertTrue(scenario["demo_supported"])
                self.assertFalse(scenario["demo_policy"]["live_allowed"])

    def test_future_scenarios_are_not_implemented(self) -> None:
        registry = load_json(ROOT / "architecture" / "scenario_chain_registry.json")
        scenario_ids = {item["scenario_id"] for item in registry["scenarios"]}
        self.assertEqual(scenario_ids, {f"SC{index:02d}" for index in range(1, 11)})
        self.assertNotIn("SC11", scenario_ids)
        self.assertNotIn("SC12", scenario_ids)

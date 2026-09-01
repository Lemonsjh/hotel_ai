from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV27ScenarioChainContract(unittest.TestCase):
    def test_scenarios_cover_sc01_to_sc10_and_are_demo_supported(self) -> None:
        contract = json.loads((ROOT / "contracts" / "v27" / "scenario_chain_contract.yaml").read_text(encoding="utf-8"))
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

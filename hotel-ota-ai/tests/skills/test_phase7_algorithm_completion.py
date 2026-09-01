from __future__ import annotations

import json
import unittest
from pathlib import Path

from runtime.algorithm_rule_loader import load_all_algorithm_rules, validate_algorithm_rule


ROOT = Path(__file__).resolve().parents[2]


class TestPhase7AlgorithmCompletion(unittest.TestCase):
    def test_all_skill_algorithm_rules_are_implemented_and_valid(self) -> None:
        rules = load_all_algorithm_rules()
        expected = {f"S{index}" for index in range(1, 18)} | {"S14-EXT"}

        self.assertTrue(expected.issubset(set(rules)))
        for skill_id in expected:
            result = validate_algorithm_rule(rules[skill_id])
            self.assertTrue(result["valid"], f"{skill_id}: {result['missing']}")
            self.assertGreaterEqual(len(rules[skill_id]["algorithm"]["ordered_steps"]), 4)
            self.assertIn("treat_demo_data_as_real_today_data", rules[skill_id]["forbidden_actions"])

    def test_phase7_completion_matrix_matches_rules_and_behavior_cases(self) -> None:
        matrix = json.loads((ROOT / "architecture" / "phase7_skill_algorithm_completion.json").read_text(encoding="utf-8"))
        self.assertEqual(matrix["status"], "implemented")
        self.assertEqual(len(matrix["skills"]), 18)

        for row in matrix["skills"]:
            self.assertTrue((ROOT / row["algorithm_rules_ref"]).exists())
            self.assertTrue((ROOT / row["behavior_cases_ref"]).exists())
            cases = json.loads((ROOT / row["behavior_cases_ref"]).read_text(encoding="utf-8"))
            self.assertEqual(cases["skill_id"], row["skill_id"])
            self.assertGreaterEqual(len(cases["cases"]), 2)


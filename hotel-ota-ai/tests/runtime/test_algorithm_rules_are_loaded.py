from __future__ import annotations

import unittest

from runtime.algorithm_rule_loader import find_algorithm_rule, load_all_algorithm_rules, rule_execution_status


class TestAlgorithmRulesAreLoaded(unittest.TestCase):
    def test_all_skill_rules_are_discoverable(self) -> None:
        rules = load_all_algorithm_rules()
        expected = {f"S{index}" for index in range(1, 18)} | {"S14-EXT"}
        self.assertTrue(expected.issubset(rules))

    def test_rule_lookup_by_skill_and_node(self) -> None:
        by_skill = find_algorithm_rule(skill_id="S5")
        by_node = find_algorithm_rule(node_id="N015")
        self.assertEqual(by_skill["owner_skill"], "S5")
        self.assertEqual(by_node["owner_skill"], "S5")
        self.assertEqual(by_skill["node_id"], "N015")

    def test_runtime_execution_status_is_not_overstated(self) -> None:
        revenue = rule_execution_status(skill_id="S5")
        execution = rule_execution_status(skill_id="S6")

        self.assertEqual(revenue["runtime_execution_status"], "executed")
        self.assertIn("runtime/decisions/revenue_decision.py", revenue["executed_by_runtime"])
        self.assertEqual(execution["runtime_execution_status"], "executed")
        self.assertTrue(execution["executed_by_runtime"])


if __name__ == "__main__":
    unittest.main()

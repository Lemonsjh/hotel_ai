from __future__ import annotations

import unittest

from runtime.skill_orchestrator import run_skill_with_dependencies


class TestSkillDependencyOrchestrator(unittest.TestCase):
    def test_runs_dependencies_before_target_skill(self) -> None:
        calls: list[str] = []

        def runner(skill: str, hotel_id: str, context: dict) -> dict:
            calls.append(skill)
            return {"status": "ok", "skill": skill, "hotel_id": hotel_id}

        result = run_skill_with_dependencies(
            target_skill="S16_PROGRESS_DEVIATION",
            hotel_id="xingfeng",
            context={},
            runner=runner,
        )

        self.assertFalse(result["blocked"])
        self.assertEqual(calls, ["S2_OPERATING_SNAPSHOT", "S15_SALES_BASELINE", "S16_PROGRESS_DEVIATION"])
        self.assertEqual([item["skill"] for item in result["dependency_runs"]], ["S2_OPERATING_SNAPSHOT", "S15_SALES_BASELINE"])

    def test_blocks_target_when_dependency_has_data_gap(self) -> None:
        calls: list[str] = []

        def runner(skill: str, hotel_id: str, context: dict) -> dict:
            calls.append(skill)
            if skill == "S2_OPERATING_SNAPSHOT":
                return {"status": "data_gap", "reason": "operating_snapshot_missing"}
            return {"status": "ok", "skill": skill}

        result = run_skill_with_dependencies(
            target_skill="S16_PROGRESS_DEVIATION",
            hotel_id="xingfeng",
            context={},
            runner=runner,
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["blocked_reason"], "dependency_data_gap")
        self.assertEqual(result["blocking_dependency"], "S2_OPERATING_SNAPSHOT")
        self.assertEqual(calls, ["S2_OPERATING_SNAPSHOT"])
        self.assertIsNone(result["final_result"])

    def test_revenue_decision_dependency_order(self) -> None:
        calls: list[str] = []

        def runner(skill: str, hotel_id: str, context: dict) -> dict:
            calls.append(skill)
            return {"status": "ok", "skill": skill}

        result = run_skill_with_dependencies(
            target_skill="S5_REVENUE_DECISION",
            hotel_id="xingfeng",
            context={},
            runner=runner,
        )

        self.assertFalse(result["blocked"])
        self.assertEqual(
            calls,
            [
                "S2_OPERATING_SNAPSHOT",
                "S4_MARKET_CONTEXT",
                "S15_SALES_BASELINE",
                "S16_PROGRESS_DEVIATION",
                "OTA_PRICE_MAPPING",
                "S5_REVENUE_DECISION",
            ],
        )

    def test_missing_runner_blocks_safely(self) -> None:
        result = run_skill_with_dependencies(
            target_skill="S16_PROGRESS_DEVIATION",
            hotel_id="xingfeng",
            context={},
            runner=None,
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["blocked_reason"], "skill_runner_missing")


if __name__ == "__main__":
    unittest.main()

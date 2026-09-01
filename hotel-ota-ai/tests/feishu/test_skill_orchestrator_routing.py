from __future__ import annotations

import unittest

from runtime.feishu_command_router import route_feishu_command


class TestSkillOrchestratorRouting(unittest.TestCase):
    def test_progress_deviation_route_records_required_dependencies(self) -> None:
        result = route_feishu_command("3", role="owner")

        self.assertEqual(result["intent"], "progress_deviation_demo")
        self.assertEqual(result["node_id"], "N011")
        self.assertEqual(
            [item["skill"] for item in result["dependency_runs"]],
            ["S2_OPERATING_SNAPSHOT", "S15_SALES_BASELINE"],
        )
        self.assertEqual(result["orchestrated_target_skill"], "S16_PROGRESS_DEVIATION")

    def test_revenue_route_records_required_dependencies(self) -> None:
        result = route_feishu_command("9", role="owner")

        self.assertEqual(result["intent"], "revenue_decision_demo")
        self.assertEqual(result["node_id"], "N015")
        self.assertEqual(
            [item["skill"] for item in result["dependency_runs"]],
            [
                "S2_OPERATING_SNAPSHOT",
                "S4_MARKET_CONTEXT",
                "S15_SALES_BASELINE",
                "S16_PROGRESS_DEVIATION",
                "OTA_PRICE_MAPPING",
            ],
        )
        self.assertEqual(result["orchestrated_target_skill"], "S5_REVENUE_DECISION")


if __name__ == "__main__":
    unittest.main()

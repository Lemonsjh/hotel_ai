from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "architecture" / "algorithm_coverage_matrix.md"


class TestAlgorithmCoverageMatrix(unittest.TestCase):
    def test_core_algorithm_blueprints_are_mapped_to_runtime_and_tests(self) -> None:
        text = MATRIX.read_text(encoding="utf-8")
        for skill_id in ["S4", "S5", "S7", "S9", "S14", "S16"]:
            with self.subTest(skill_id=skill_id):
                self.assertIn(skill_id, text)
        for reference in [
            "docs/architecture_reference/v27/01-需求指数与流量峰谷算法.md",
            "docs/architecture_reference/v27/02-调价建议算法.md",
            "docs/architecture_reference/v27/03-OTA健康诊断算法.md",
            "docs/architecture_reference/v27/04-流量转化诊断算法.md",
            "docs/architecture_reference/v27/06-竞对预警算法.md",
            "runtime/algorithms/s5_decision_context.py",
            "runtime/algorithms/time_aware_progress.py",
        ]:
            with self.subTest(reference=reference):
                self.assertIn(reference, text)

    def test_matrix_defines_non_code_statuses(self) -> None:
        text = MATRIX.read_text(encoding="utf-8")
        self.assertIn("not_allowed_conclusions", text)
        self.assertIn("degradation_policy", text)
        self.assertIn("algorithm_usage_coverage", text)
        self.assertIn("formula_version=revised_first_formula_v27", text)
        self.assertIn("date_environment=0.20", text)
        self.assertIn("room_type_inventory_pressure=0.10", text)


if __name__ == "__main__":
    unittest.main()

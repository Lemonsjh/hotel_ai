from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TestSkillCoverageMatrix(unittest.TestCase):
    def test_skill_docs_cover_s1_to_s17(self) -> None:
        paths = [
            ROOT / "docs" / "skill_coverage_matrix.md",
            ROOT / "docs" / "skill_to_table_mapping.md",
            ROOT / "docs" / "skill_transform_plan.md",
        ]
        for path in paths:
            text = path.read_text(encoding="utf-8")
            for index in range(1, 18):
                self.assertIn(f"S{index}", text, f"{path} missing S{index}")

    def test_transform_plan_states_capability_order(self) -> None:
        text = (ROOT / "docs" / "skill_transform_plan.md").read_text(encoding="utf-8")
        for label in ("direct", "derived", "external", "estimated", "hidden"):
            self.assertIn(label, text)

    def test_transform_plan_lists_shared_derived_contexts(self) -> None:
        text = (ROOT / "docs" / "skill_transform_plan.md").read_text(encoding="utf-8")
        for context_name in (
            "operating_snapshot_context",
            "progress_context",
            "price_context",
            "ota_health_context",
            "promotion_context",
            "promotion_roi_context",
            "reputation_context",
            "customer_order_context",
            "competitor_context",
            "sales_baseline_context",
        ):
            self.assertIn(context_name, text)


if __name__ == "__main__":
    unittest.main()

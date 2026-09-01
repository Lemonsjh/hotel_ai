from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RULE_PATH = ROOT / "runtime" / "algorithm_rules" / "promotion_rules.yaml"
CASES_PATH = (
    ROOT
    / "skills"
    / "hotel-ota"
    / "s08-promotion-planning"
    / "references"
    / "v20_behavior_cases.json"
)
TABLE_MAPPING_PATH = ROOT / "docs" / "skill_to_table_mapping.md"
COVERAGE_PATH = ROOT / "docs" / "skill_coverage_matrix.md"
TRANSFORM_PATH = ROOT / "docs" / "skill_transform_plan.md"
SOURCE_TABLE = "meituan_ota_promotion_performance_30d"


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _table_row(text: str, prefix: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(prefix))


class TestS8RuleContract(unittest.TestCase):
    def test_algorithm_rule_is_display_only_and_single_source(self) -> None:
        rule = _load_json(RULE_PATH)

        self.assertEqual(rule["owner_skill"], "S8")
        self.assertEqual(rule["data_gate"]["hard_required"], ["hotel_id"])
        self.assertEqual(rule["data_gate"]["soft_required"], ["as_of_time"])
        self.assertIn(SOURCE_TABLE, rule["algorithm"]["objective"])
        self.assertGreaterEqual(len(rule["algorithm"]["ordered_steps"]), 4)

        output_contract = set(rule["algorithm"]["output_contract"])
        self.assertIn("promotion_display", output_contract)
        self.assertIn("recommendations_empty", output_contract)
        self.assertIn("actions_empty", output_contract)
        self.assertNotIn("promotion_plan", output_contract)
        self.assertNotIn("budget_band", output_contract)
        self.assertNotIn("promotion_action", output_contract)

        forbidden = set(rule["forbidden_actions"])
        self.assertIn("treat_demo_data_as_real_today_data", forbidden)
        self.assertIn(
            "read_any_table_other_than_meituan_ota_promotion_performance_30d",
            forbidden,
        )
        self.assertIn("display_or_infer_promotion_status", forbidden)
        self.assertIn("call_other_skill_for_s8_business_output", forbidden)
        self.assertEqual(rule["runtime_execution_status"], "display_only_read_path")

    def test_behavior_cases_are_identical_to_rule_cases(self) -> None:
        rule = _load_json(RULE_PATH)
        cases = _load_json(CASES_PATH)

        self.assertEqual(cases["skill_id"], "S8")
        self.assertEqual(cases["cases"], rule["demo_behavior_cases"])
        self.assertEqual(
            {item["case_id"] for item in cases["cases"]},
            {"s8_demo_source_rejected", "s8_missing_hotel_id"},
        )

    def test_s8_document_rows_match_display_only_boundary(self) -> None:
        mapping_text = TABLE_MAPPING_PATH.read_text(encoding="utf-8")
        mapping_row = _table_row(mapping_text, "| S8 |")
        self.assertIn(SOURCE_TABLE, mapping_row)
        for forbidden_term in (
            "ctrip_ota_promotion_activity",
            "meituan_ota_promotion_activity",
            "activity_product_detail",
        ):
            self.assertNotIn(forbidden_term, mapping_row)
        self.assertIn("no status inference", mapping_row)
        self.assertIn("recommendation", mapping_row)
        self.assertIn("approval", mapping_row)
        self.assertIn("execution", mapping_row)

        coverage_text = COVERAGE_PATH.read_text(encoding="utf-8")
        coverage_row = _table_row(coverage_text, "| S8 |")
        self.assertEqual(coverage_row, "| S8 | yes | yes | no | no | no |")

        transform_text = TRANSFORM_PATH.read_text(encoding="utf-8")
        transform_row = _table_row(transform_text, "| S8 推广通展示 |")
        self.assertIn(SOURCE_TABLE, transform_row)
        self.assertIn("recommendations=[]", transform_row)
        self.assertIn("actions=[]", transform_row)
        self.assertIn("不规划、不审批、不执行", transform_row)


if __name__ == "__main__":
    unittest.main()

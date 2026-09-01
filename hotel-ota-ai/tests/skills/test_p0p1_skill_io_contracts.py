from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P0P1_SKILLS = {
    "S1",
    "S2",
    "S3",
    "S4",
    "S5",
    "S6",
    "S14",
    "S15",
    "S16",
    "S14-EXT",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestP0P1SkillIoContracts(unittest.TestCase):
    def test_p0p1_skills_reference_node_io_and_algorithm_rules(self) -> None:
        alignment = load_json(ROOT / "architecture" / "skill_node_alignment.json")
        rows = {row["skill_id"]: row for row in alignment["skills"]}
        self.assertTrue(P0P1_SKILLS.issubset(rows))

        for skill_id in P0P1_SKILLS:
            row = rows[skill_id]
            with self.subTest(skill_id=skill_id):
                self.assertTrue((ROOT / row["field_registry_ref"]).exists())
                self.assertTrue((ROOT / row["node_io_contract_ref"]).exists())
                self.assertTrue((ROOT / row["algorithm_rules_ref"]).exists())
                self.assertTrue((ROOT / row["demo_node_fixture"]).exists())
                self.assertIn("treat_demo_data_as_real_today_data", row["forbidden_actions"])
                self.assertFalse(row["demo_safety"]["approval_data_allowed"])
                self.assertFalse(row["demo_safety"]["live_allowed"])

    def test_p0p1_skill_rules_include_buildable_specs(self) -> None:
        alignment = load_json(ROOT / "architecture" / "skill_node_alignment.json")
        rows = {row["skill_id"]: row for row in alignment["skills"] if row["skill_id"] in P0P1_SKILLS}

        for row in rows.values():
            rules_path = ROOT / "skills" / "hotel-ota" / row["skill_dir"] / "references" / "rules.md"
            text = rules_path.read_text(encoding="utf-8")
            with self.subTest(skill_id=row["skill_id"]):
                self.assertIn("V27 可施工算法规格", text)
                self.assertIn("hard_required", text)
                self.assertIn("blocked_for_live", text)
                self.assertIn("forbidden_actions", text)


if __name__ == "__main__":
    unittest.main()

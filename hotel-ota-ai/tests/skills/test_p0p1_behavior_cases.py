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


class TestP0P1BehaviorCases(unittest.TestCase):
    def test_each_p0p1_skill_has_at_least_three_behavior_cases(self) -> None:
        alignment = json.loads((ROOT / "architecture" / "skill_node_alignment.json").read_text(encoding="utf-8"))
        rows = {row["skill_id"]: row for row in alignment["skills"] if row["skill_id"] in P0P1_SKILLS}

        for row in rows.values():
            path = ROOT / "skills" / "hotel-ota" / row["skill_dir"] / "references" / "v20_behavior_cases.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            with self.subTest(skill_id=row["skill_id"]):
                self.assertEqual(payload["skill_id"], row["skill_id"])
                self.assertGreaterEqual(len(payload["cases"]), 3)

                case_text = json.dumps(payload, ensure_ascii=False)
                self.assertIn("demo", case_text.lower())
                self.assertRegex(case_text, r"blocked|preview|dry_run|simulation")


if __name__ == "__main__":
    unittest.main()

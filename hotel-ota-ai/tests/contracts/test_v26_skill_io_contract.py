from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestV26SkillIoContract(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = load_json(ROOT / "contracts" / "v26" / "skill_io_contract.yaml")
        self.skills = {skill["skill_id"]: skill for skill in self.contract["skills"]}

    def test_core_skills_and_extension_exist(self) -> None:
        self.assertEqual(set(self.skills), {f"S{index}" for index in range(1, 18)} | {"S14-EXT"})

    def test_each_skill_has_development_io(self) -> None:
        for skill_id, skill in self.skills.items():
            with self.subTest(skill=skill_id):
                self.assertTrue(skill["node_ids"])
                self.assertTrue(skill["agent_id"])
                self.assertTrue(skill["input_fields"])
                self.assertTrue(skill["output_fields"])
                self.assertTrue(skill["runtime_command"])

    def test_critical_skill_boundaries(self) -> None:
        self.assertIn("只给建议", self.skills["S5"]["error_handling"])
        self.assertIn("demo_data", self.skills["S6"]["error_handling"])
        self.assertIn("只预警", self.skills["S7"]["error_handling"])
        self.assertIn("demo下只预览", self.skills["S11"]["error_handling"])
        self.assertEqual(self.skills["S14-EXT"]["agent_id"], "A2")

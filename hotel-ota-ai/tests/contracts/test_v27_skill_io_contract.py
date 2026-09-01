from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestV27SkillIoContract(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = json.loads((ROOT / "contracts" / "v27" / "field_registry.yaml").read_text(encoding="utf-8"))
        self.contract = json.loads((ROOT / "contracts" / "v27" / "skill_io_contract.yaml").read_text(encoding="utf-8"))
        self.field_keys = {field["canonical_key"] for field in self.registry["fields"]}

    def test_all_skills_have_development_io_and_runtime_command(self) -> None:
        skills = {skill["skill_id"]: skill for skill in self.contract["skills"]}
        self.assertEqual(set(skills), {f"S{index}" for index in range(1, 18)} | {"S14-EXT"})
        skill_dirs = {
            path.name.split("-", 1)[0].upper().replace("S0", "S") if path.name.startswith("s0") else path.name.split("-", 1)[0].upper(): path
            for path in (ROOT / "skills" / "hotel-ota").iterdir()
            if path.is_dir() and path.name.startswith("s")
        }
        skill_dirs["S14-EXT"] = ROOT / "skills" / "hotel-ota" / "s14-ext-third-party-diagnosis"
        for skill_id, skill in skills.items():
            with self.subTest(skill=skill_id):
                self.assertTrue(skill["node_ids"])
                self.assertTrue(skill["agent_id"])
                self.assertTrue(skill["input_fields"])
                self.assertTrue(skill["output_fields"])
                self.assertIn("runtime_command", skill)
                self.assertTrue((skill_dirs[skill_id] / "references" / "runtime_commands.md").exists())
                self.assertIn("error_handling", skill)
                self.assertTrue((skill_dirs[skill_id] / "references" / "rules.md").exists())
                for field in skill["input_fields"] + skill["output_fields"]:
                    self.assertIn(field["canonical_key"], self.field_keys)

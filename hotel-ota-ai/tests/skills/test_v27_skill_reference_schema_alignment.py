from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "skills" / "hotel-ota"


class TestV27SkillReferenceSchemaAlignment(unittest.TestCase):
    def _skill_dirs(self) -> list[Path]:
        return sorted(path for path in SKILLS.iterdir() if (path / "references" / "v27_alignment.json").exists())

    def test_every_skill_input_schema_uses_v27_wrapper(self) -> None:
        skill_dirs = self._skill_dirs()
        self.assertEqual(len(skill_dirs), 18)
        for skill_dir in skill_dirs:
            with self.subTest(skill=skill_dir.name):
                alignment = json.loads((skill_dir / "references" / "v27_alignment.json").read_text(encoding="utf-8"))
                schema = json.loads((skill_dir / "references" / "input_schema.json").read_text(encoding="utf-8"))

                self.assertEqual(schema.get("schema_version"), "v27-wrapper")
                self.assertEqual(schema.get("canonical_source"), "contracts/v27/node_io_contract.yaml")
                self.assertEqual(schema.get("secondary_source"), "contracts/v27/skill_io_contract.yaml")
                self.assertEqual(schema.get("alignment_source"), "references/v27_alignment.json")
                self.assertEqual(schema.get("skill_id"), alignment["skill_id"])
                self.assertEqual(schema.get("node_ids"), alignment["node_ids"])
                self.assertEqual(schema.get("input_field_ids"), alignment["input_field_ids"])
                self.assertNotIn("business_fields", schema.get("properties") or {})
                self.assertIn("deprecated_legacy_fields", schema)

    def test_every_skill_output_schema_uses_v27_wrapper(self) -> None:
        for skill_dir in self._skill_dirs():
            with self.subTest(skill=skill_dir.name):
                alignment = json.loads((skill_dir / "references" / "v27_alignment.json").read_text(encoding="utf-8"))
                schema = json.loads((skill_dir / "references" / "output_schema.json").read_text(encoding="utf-8"))

                self.assertEqual(schema.get("schema_version"), "v27-wrapper")
                self.assertEqual(schema.get("canonical_source"), "contracts/v27/node_io_contract.yaml")
                self.assertEqual(schema.get("secondary_source"), "contracts/v27/skill_io_contract.yaml")
                self.assertEqual(schema.get("alignment_source"), "references/v27_alignment.json")
                self.assertEqual(schema.get("skill_id"), alignment["skill_id"])
                self.assertEqual(schema.get("node_ids"), alignment["node_ids"])
                self.assertEqual(schema.get("output_field_ids"), alignment["output_field_ids"])
                self.assertIn("deprecated_legacy_outputs", schema)

    def test_s16_schema_uses_room_night_progress_contract(self) -> None:
        skill_dir = SKILLS / "s16-progress-deviation"
        schema = json.loads((skill_dir / "references" / "input_schema.json").read_text(encoding="utf-8"))
        output = json.loads((skill_dir / "references" / "output_schema.json").read_text(encoding="utf-8"))

        self.assertIn("N010_OUT001", schema["input_field_ids"])
        self.assertIn("N010_OUT002", schema["input_field_ids"])
        self.assertIn("N005_OUT009", schema["input_field_ids"])
        self.assertIn("N005_OUT010", schema["input_field_ids"])
        self.assertNotIn("target_orders", schema.get("properties") or {})
        self.assertIn("target_orders", schema["deprecated_legacy_fields"])
        self.assertIn("actual_orders", output["deprecated_legacy_outputs"])


if __name__ == "__main__":
    unittest.main()

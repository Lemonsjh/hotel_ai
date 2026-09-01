from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestSkillAlignment(unittest.TestCase):
    def test_every_skill_alignment_file_points_to_existing_assets(self) -> None:
        alignment_files = sorted((ROOT / "skills" / "hotel-ota").glob("*/references/v27_alignment.json"))
        self.assertEqual(len(alignment_files), 18)

        for path in alignment_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "contracts/v27/contract.json")
            self.assertEqual(data["field_registry_ref"], "contracts/v27/field_registry.yaml")
            self.assertEqual(data["node_io_contract_ref"], "contracts/v27/node_io_contract.yaml")
            self.assertTrue((ROOT / data["field_registry_ref"]).exists())
            self.assertTrue((ROOT / data["node_io_contract_ref"]).exists())
            self.assertIn("data_source_type=demo_data", data["demo_safety_fields"])

    def test_s14_ext_is_real_extension_skill_not_only_registry_entry(self) -> None:
        skill_dir = ROOT / "skills" / "hotel-ota" / "s14-ext-third-party-diagnosis"
        self.assertTrue((skill_dir / "SKILL.md").exists())
        for filename in ["input_schema.json", "output_schema.json", "rules.md", "examples.md", "runtime_commands.md", "v27_alignment.json"]:
            self.assertTrue((skill_dir / "references" / filename).exists())

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestV26FieldRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_json(ROOT / "contracts" / "v26" / "field_registry.yaml")
        self.fields = self.registry["fields"]

    def test_field_ids_and_canonical_keys_are_unique(self) -> None:
        field_ids = [field["field_id"] for field in self.fields]
        keys = [field["canonical_key"] for field in self.fields]
        self.assertEqual(len(field_ids), len(set(field_ids)))
        self.assertEqual(len(keys), len(set(keys)))

    def test_required_metadata_and_naming_are_complete(self) -> None:
        allowed_types = set(self.registry["supported_data_types"])
        allowed_statuses = set(self.registry["supported_statuses"])
        serialized = json.dumps(self.registry, ensure_ascii=False)
        self.assertNotIn("待命名字段", serialized)
        self.assertNotIn("字段覆盖率率", serialized)
        for field in self.fields:
            with self.subTest(field=field["field_id"]):
                self.assertRegex(field["canonical_key"], r"^[a-z][a-z0-9_]*$")
                self.assertTrue(field["project_field_name"])
                self.assertTrue(field["zh_name"])
                self.assertIn(field["data_type"], allowed_types)
                self.assertIn(field["source_match_status"], allowed_statuses)
                self.assertTrue(field["missing_policy"])
                self.assertIsInstance(field["governance"], dict)
                self.assertFalse(re.search(r"[\u4e00-\u9fff]", field["canonical_key"]))

    def test_v26_type_repairs_are_applied(self) -> None:
        fields = {field["canonical_key"]: field for field in self.fields}
        expected = {
            "intent_candidate": "string",
            "scenario_candidate": "string",
            "required_blueprints": "array",
            "required_skill_chain": "array",
            "algorithm_required_fields": "array",
            "price_snapshot": "object",
            "direct_price_action_blocked": "boolean",
            "sentiment": "enum",
            "time_windows": "array",
            "roi_decision": "object",
            "data_gaps": "array",
            "price_recommendations": "array",
            "data_gap_list": "array",
            "field_coverage_rate": "ratio",
        }
        for key, data_type in expected.items():
            with self.subTest(field=key):
                self.assertEqual(fields[key]["data_type"], data_type)

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ALLOWED_STATUSES = {
    "confirmed_exact",
    "confirmed_alias",
    "candidate_inferred",
    "project_only",
    "config_only",
    "algorithm_output",
    "upstream_output",
    "manual_required",
    "not_available",
    "deprecated",
}
ALLOWED_TYPES = {"string", "number", "integer", "boolean", "datetime", "date", "object", "array", "enum", "money", "ratio"}


class TestV27FieldRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = json.loads((ROOT / "contracts" / "v27" / "field_registry.yaml").read_text(encoding="utf-8"))
        self.fields = self.registry["fields"]

    def test_field_names_statuses_and_types_are_v27_clean(self) -> None:
        field_ids = [field["field_id"] for field in self.fields]
        self.assertEqual(len(field_ids), len(set(field_ids)))
        for field in self.fields:
            with self.subTest(field=field["field_id"]):
                self.assertRegex(field["canonical_key"], r"^[a-z][a-z0-9_]*$")
                self.assertIsNone(re.search(r"[\u4e00-\u9fff]", field["canonical_key"]))
                self.assertIn(field["source_match_status"], ALLOWED_STATUSES)
                self.assertIn(field["data_type"], ALLOWED_TYPES)

    def test_missing_fields_and_data_gaps_are_distinct_contract_fields(self) -> None:
        by_key = {field["canonical_key"]: field for field in self.fields}
        self.assertIn("missing_fields", by_key)
        self.assertIn("data_gaps", by_key)
        self.assertNotEqual(by_key["missing_fields"]["field_id"], by_key["data_gaps"]["field_id"])

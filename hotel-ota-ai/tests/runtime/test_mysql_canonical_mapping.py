from __future__ import annotations

import unittest

from runtime.adapters.database import inspect_canonical_mapping_draft, infer_canonical_field_candidates, validate_canonical_mapping_profile


class TestMySqlCanonicalMapping(unittest.TestCase):
    def test_mapping_draft_marks_sensitive_fields_and_never_writes(self) -> None:
        draft = inspect_canonical_mapping_draft(
            [
                {"column_name": "hotel_id", "data_type": "varchar"},
                {"column_name": "business_date", "data_type": "date"},
                {"column_name": "guest_name", "data_type": "varchar"},
            ],
            table="daily_metrics",
        )

        self.assertEqual(draft["status"], "ok")
        self.assertFalse(draft["write_performed"])
        self.assertFalse(draft["free_sql_allowed"])
        self.assertTrue(next(item for item in draft["columns"] if item["column_name"] == "guest_name")["sensitive"])
        self.assertIn("operation_diagnosis", draft["template_readiness"])
        self.assertIn("tables", draft["profile_draft"])
        self.assertIn("metric_aliases", draft["profile_draft"])
        self.assertTrue(draft["sensitive_column_flags"]["guest_name"])

    def test_column_names_get_safe_canonical_candidates(self) -> None:
        candidates = infer_canonical_field_candidates(
            ["hotel_name", "business_date", "room_type_id", "daily_price", "order_id", "room_nights", "updated_at", "guest_name"]
        )

        self.assertEqual(candidates["hotel_id"], ["hotel_name"])
        self.assertEqual(candidates["business_date"], ["business_date"])
        self.assertEqual(candidates["room_type_id"], ["room_type_id"])
        self.assertEqual(candidates["room_nights"], ["room_nights"])
        self.assertEqual(candidates["updated_at"], ["updated_at"])
        self.assertNotIn("order_id", candidates)
        self.assertNotIn("guest_name", str(candidates))

    def test_incomplete_profile_returns_data_gap_not_invented_mapping(self) -> None:
        result = validate_canonical_mapping_profile(
            {"mapping_version": 1, "canonical_fields": {"hotel_id": "hotel_name"}},
            required_fields=["hotel_id", "business_date", "room_type_id"],
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["missing_fields"], ["business_date", "room_type_id"])


if __name__ == "__main__":
    unittest.main()

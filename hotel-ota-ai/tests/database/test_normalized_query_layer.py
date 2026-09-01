from __future__ import annotations

import unittest

from runtime.adapters.normalized_query import (
    build_room_mapping_index,
    normalize_ota_price_row,
    normalize_rows_for_template,
    normalize_source_platform,
    resolve_room_type_mapping,
)
from runtime.adapters import database


class TestNormalizedQueryLayer(unittest.TestCase):
    def test_platform_aliases_are_normalized(self) -> None:
        self.assertEqual(normalize_source_platform("美团"), "meituan")
        self.assertEqual(normalize_source_platform("携程"), "ctrip")
        self.assertEqual(normalize_source_platform(""), "walkin")
        self.assertEqual(normalize_source_platform(None), "walkin")

    def test_product_id_confirmed_mapping_is_not_usable(self) -> None:
        mapping_index = build_room_mapping_index(
            [
                {
                    "id": "map-1",
                    "hotel_id": "hotel-a",
                    "room_type_id": "KING",
                    "room_type_name": "大床房",
                    "source_platform": "meituan",
                    "source_product_id": "mt-prod-1",
                    "mapping_status": "CONFIRMED",
                    "is_active": 1,
                    "price_editable_flag": 1,
                }
            ]
        )

        row = normalize_ota_price_row(
            {
                "hotel_id": "hotel-a",
                "channel_source": "美团",
                "ota_product_id": "mt-prod-1",
                "ota_product_name": "大床房-无早",
                "business_date": "2026-06-30",
                "snapshot_time": "2026-06-30 16:00:00",
            },
            mapping_index,
            requested_hotel_id="hotel-a",
            profile={},
        )

        self.assertEqual(row["mapping_resolution_status"], "mapping_status_unsupported")
        self.assertEqual(row["mapping_status"], "CONFIRMED")
        self.assertIsNone(row["room_type_id"])
        self.assertIsNone(row["mapping_id"])
        self.assertEqual(row["source_platform"], "meituan")
        self.assertEqual(row["source_product_id"], "mt-prod-1")
        self.assertIn("mapping_status_not_auto", row["risk_flags"])

    def test_auto_exact_product_match_exposes_room_type_for_reads(self) -> None:
        mapping_index = build_room_mapping_index(
            [
                {
                    "id": 28,
                    "hotel_id": "puyue",
                    "room_type_id": "py03",
                    "room_type_name": "至臻.电竞双床房",
                    "source_platform": "美团",
                    "source_room_type_id": "500579105",
                    "source_product_id": "2304257179",
                    "mapping_status": "AUTO",
                    "match_rule": "",
                    "is_active": 1,
                }
            ]
        )

        row = normalize_ota_price_row(
            {
                "hotel_id": "puyue",
                "channel_source": "美团",
                "ota_product_id": "2304257179",
                "business_date": "2026-06-30",
            },
            mapping_index,
            requested_hotel_id="puyue",
            profile={},
        )

        self.assertEqual(row["room_type_id"], "py03")
        self.assertEqual(row["mapping_resolution_status"], "mapped")
        self.assertEqual(row["mapping_status"], "AUTO")
        self.assertNotIn("mapping_unconfirmed", row["risk_flags"])

    def test_name_only_mapping_is_candidate_not_executable_mapping(self) -> None:
        mapping_index = build_room_mapping_index(
            [
                {
                    "id": "map-name",
                    "hotel_id": "hotel-a",
                    "room_type_id": "KING",
                    "room_type_name": "大床房",
                    "source_platform": "meituan",
                    "source_room_type_name": "大床房",
                    "mapping_status": "AUTO",
                    "is_active": 1,
                    "price_editable_flag": 1,
                }
            ]
        )

        resolved = resolve_room_type_mapping(
            {
                "hotel_id": "hotel-a",
                "source_platform": "meituan",
                "source_room_type_name": "大床房",
            },
            mapping_index,
        )

        self.assertEqual(resolved["mapping_resolution_status"], "mapping_pending")
        self.assertEqual(resolved["mapping_status"], "CANDIDATE")
        self.assertIn("mapping_candidate_name_match", resolved["risk_flags"])
        self.assertEqual(resolved["room_type_id"], "KING")
        self.assertIn("inferred_by_name", resolved["risk_flags"])

    def test_template_normalization_marks_source_metadata(self) -> None:
        rows = normalize_rows_for_template(
            "ota_price_mapping",
            [
                {
                    "hotel_id": "hotel-a",
                    "channel_source": "meituan",
                    "ota_product_id": "mt-prod-1",
                    "business_date": "2026-06-30",
                }
            ],
            build_room_mapping_index([]),
            {"hotel_id": "hotel-a"},
        )

        self.assertEqual(rows[0]["mapping_resolution_status"], "mapping_pending")
        self.assertEqual(rows[0]["freshness_status"], "fresh")
        self.assertEqual(rows[0]["tenant_filter_mode"], "hotel_id")

    def test_source_room_type_id_is_preserved_when_mapping_is_pending(self) -> None:
        rows = normalize_rows_for_template(
            "room_status_snapshot",
            [
                {
                    "hotel_id": "puyue",
                    "source_platform": "pms",
                    "room_type_id": "SOURCE-KING",
                    "room_type_name": "King",
                    "business_date": "2026-07-03",
                    "snapshot_time": "2026-07-03 10:44:30",
                }
            ],
            build_room_mapping_index([]),
            {"hotel_id": "puyue"},
        )

        self.assertEqual(rows[0]["room_type_id"], "SOURCE-KING")
        self.assertEqual(rows[0]["mapping_resolution_status"], "mapping_pending")
        self.assertIn("source_room_type_id_present", rows[0]["risk_flags"])

    def test_source_room_type_id_makes_ota_product_candidate_without_hardcoded_room(self) -> None:
        rows = normalize_rows_for_template(
            "ota_price_mapping",
            [
                {
                    "hotel_id": "puyue",
                    "channel_source": "meituan",
                    "room_type_id": "DYNAMIC-ROOM",
                    "room_type_name": "Dynamic Room",
                    "ota_product_id": "mt-dynamic-product",
                    "ota_product_name": "Dynamic Room Package",
                    "business_date": "2026-07-03",
                }
            ],
            build_room_mapping_index([]),
            {"hotel_id": "puyue"},
        )

        self.assertEqual(rows[0]["room_type_id"], "DYNAMIC-ROOM")
        self.assertEqual(rows[0]["source_product_id"], "mt-dynamic-product")
        self.assertEqual(rows[0]["mapping_resolution_status"], "mapped")
        self.assertNotIn("price_task_blocked", rows[0]["risk_flags"])

    def test_empty_hotel_id_can_use_legacy_hotel_name_scope(self) -> None:
        rows = normalize_rows_for_template(
            "daily_metrics",
            [
                {
                    "hotel_id": "",
                    "hotel_name": "Example Hotel",
                    "source_platform": "",
                    "business_date": "2026-06-30",
                    "snapshot_time": "2026-06-30 09:00:00",
                }
            ],
            build_room_mapping_index([]),
            {"hotel_id": "hotel-a", "legacy_hotel_names": {"hotel-a": "Example Hotel"}},
        )

        self.assertEqual(rows[0]["hotel_id"], "hotel-a")
        self.assertEqual(rows[0]["source_platform"], "walkin")
        self.assertEqual(rows[0]["tenant_filter_mode"], "hotel_id_empty_hotel_name_legacy")
        self.assertIn("legacy_hotel_name_filter", rows[0]["risk_flags"])

    def test_hotel_id_alias_list_can_scope_legacy_rows(self) -> None:
        rows = normalize_rows_for_template(
            "daily_metrics",
            [
                {
                    "hotel_id": "",
                    "hotel_name": "Example Hotel Alias",
                    "source_platform": "",
                    "business_date": "2026-06-30",
                }
            ],
            build_room_mapping_index([]),
            {
                "hotel_id": "hotel-a",
                "hotel_ids": {
                    "hotel-a": {
                        "hotel_name": "Example Hotel",
                        "display_name": "Example Display",
                        "aliases": ["Example Hotel Alias", "Example Short"],
                    }
                },
            },
        )

        self.assertEqual(rows[0]["hotel_id"], "hotel-a")
        self.assertEqual(rows[0]["tenant_filter_mode"], "hotel_id_empty_hotel_name_legacy")
        self.assertIn("legacy_hotel_name_filter", rows[0]["risk_flags"])

    def test_tenant_filter_clause_allows_empty_hotel_id_with_legacy_name(self) -> None:
        clause, params, mode, risks = database._tenant_filter_clause(
            {"hotel_id": "hotel_id", "hotel_name": "hotel_name"},
            hotel_id="hotel-a",
            hotel_name="Example Hotel",
        )

        self.assertIn("`hotel_id` = %s", clause)
        self.assertIn("TRIM(`hotel_id`) = ''", clause)
        self.assertEqual(params, ["hotel-a", "Example Hotel"])
        self.assertEqual(mode, "hotel_id_or_empty_hotel_name_legacy")
        self.assertEqual(risks, ["legacy_hotel_name_filter"])

    def test_tenant_filter_clause_accepts_configured_hotel_aliases(self) -> None:
        clause, params, mode, risks = database._tenant_filter_clause(
            {"hotel_id": "hotel_id", "hotel_name": "hotel_name"},
            hotel_id="hotel-a",
            hotel_name=["Example Hotel", "Example Hotel Alias"],
        )

        self.assertIn("`hotel_id` = %s", clause)
        self.assertIn("`hotel_name` IN", clause)
        self.assertEqual(params, ["hotel-a", "Example Hotel", "Example Hotel Alias"])
        self.assertEqual(mode, "hotel_id_or_empty_hotel_name_legacy")
        self.assertEqual(risks, ["legacy_hotel_name_filter"])


if __name__ == "__main__":
    unittest.main()

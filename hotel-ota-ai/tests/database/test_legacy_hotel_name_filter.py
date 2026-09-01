from __future__ import annotations

import unittest

from runtime.adapters.normalized_query import build_room_mapping_index, normalize_room_metric_row, resolve_hotel_scope


class TestLegacyHotelNameFilter(unittest.TestCase):
    def test_legacy_hotel_name_filter_is_read_only_and_flagged(self) -> None:
        scoped = resolve_hotel_scope(
            {"hotel_name": "测试酒店", "business_date": "2026-06-30"},
            requested_hotel_id="hotel-a",
            profile={"legacy_hotel_names": {"hotel-a": "测试酒店"}},
        )

        self.assertEqual(scoped["tenant_filter_mode"], "hotel_name_legacy")
        self.assertIn("legacy_hotel_name_filter", scoped["risk_flags"])
        self.assertEqual(scoped["hotel_id"], "hotel-a")

    def test_unmatched_legacy_hotel_name_does_not_cross_hotel_borrow(self) -> None:
        scoped = resolve_hotel_scope(
            {"hotel_name": "其他酒店", "business_date": "2026-06-30"},
            requested_hotel_id="hotel-a",
            profile={"legacy_hotel_names": {"hotel-a": "测试酒店"}},
        )

        self.assertEqual(scoped["tenant_filter_mode"], "unresolved")
        self.assertEqual(scoped["mapping_resolution_status"], "data_gap")
        self.assertIn("tenant_scope_unresolved", scoped["risk_flags"])

    def test_room_metric_without_room_id_uses_mapping_candidate_status(self) -> None:
        row = normalize_room_metric_row(
            {
                "hotel_name": "测试酒店",
                "channel_source": "",
                "room_type_name": "大床房",
                "business_date": "2026-06-30",
                "sold_rooms": 12,
            },
            build_room_mapping_index(
                [
                    {
                        "id": "map-name",
                        "hotel_name": "测试酒店",
                        "room_type_id": "KING",
                        "room_type_name": "大床房",
                        "source_platform": "walkin",
                        "source_room_type_name": "大床房",
                        "mapping_status": "CONFIRMED",
                        "is_active": 1,
                    }
                ]
            ),
            requested_hotel_id="hotel-a",
            profile={"legacy_hotel_names": {"hotel-a": "测试酒店"}},
        )

        self.assertEqual(row["tenant_filter_mode"], "hotel_name_legacy")
        self.assertEqual(row["mapping_resolution_status"], "mapping_pending")
        # Task#3③:名称候选暴露 room_type_id 供读反推,但标 inferred_by_name(低置信),状态仍 pending。
        self.assertEqual(row["room_type_id"], "KING")
        self.assertIn("inferred_by_name", row["risk_flags"])
        self.assertIn("legacy_hotel_name_filter", row["risk_flags"])


if __name__ == "__main__":
    unittest.main()

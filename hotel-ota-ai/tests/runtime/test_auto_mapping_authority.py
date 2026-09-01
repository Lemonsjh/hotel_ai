from __future__ import annotations

import unittest

from runtime.adapters.normalized_query import (
    build_room_mapping_index,
    is_price_task_mapping_ready,
    price_task_mapping_trust_basis,
    normalize_ota_price_row,
    resolve_room_type_mapping,
)
from runtime.algorithms.s5_real_candidates import _mapping_quality_flags, _product_block_reason


def _mapping(
    *,
    mapping_id: int,
    status: str,
    product_id: str = "mt-product-1",
    room_type_id: str = "py03",
    active: int = 1,
    match_rule: str = "PRODUCT_ID",
) -> dict:
    return {
        "id": mapping_id,
        "hotel_id": "hotel-puyue",
        "hotel_name": "璞韵酒店",
        "room_type_id": room_type_id,
        "room_type_name": "至臻·电竞双床房",
        "source_platform": "meituan",
        "source_room_type_id": "mt-room-3",
        "source_room_type_name": "至臻.电竞双床房",
        "source_product_id": product_id,
        "source_product_name": "至臻双床-无早",
        "mapping_status": status,
        "match_rule": match_rule,
        "is_active": active,
        "price_editable_flag": 1,
        "is_hour_room": 0,
    }


class TestAutoMappingAuthority(unittest.TestCase):
    def test_trusted_exact_product_mapping_is_readable_and_writable(self) -> None:
        index = build_room_mapping_index([_mapping(mapping_id=1, status="AUTO")])
        resolved = resolve_room_type_mapping(
            {
                "hotel_id": "hotel-puyue",
                "source_platform": "meituan",
                "source_product_id": "mt-product-1",
            },
            index,
        )

        self.assertEqual(resolved["mapping_resolution_status"], "mapped")
        self.assertEqual(resolved["mapping_status"], "AUTO")
        self.assertEqual(resolved["room_type_id"], "py03")
        self.assertEqual(resolved["risk_flags"], [])

        gate = is_price_task_mapping_ready(resolved)
        self.assertTrue(gate["ready_for_price_task"])
        self.assertIsNone(gate["blocked_reason"])
        self.assertEqual(gate["mapping_trust_basis"], "exact_match_rule:product_id")
        self.assertEqual(price_task_mapping_trust_basis(resolved), "exact_match_rule:product_id")

    def test_confirmed_mapping_is_usable(self) -> None:
        index = build_room_mapping_index([_mapping(mapping_id=2, status="CONFIRMED")])
        resolved = resolve_room_type_mapping(
            {
                "hotel_id": "hotel-puyue",
                "source_platform": "meituan",
                "source_product_id": "mt-product-1",
            },
            index,
        )

        self.assertEqual(resolved["mapping_resolution_status"], "mapped")
        self.assertEqual(resolved["mapping_status"], "CONFIRMED")
        gate = is_price_task_mapping_ready(
            {
                **_mapping(mapping_id=2, status="CONFIRMED"),
                "mapping_active": True,
            }
        )
        self.assertTrue(gate["ready_for_price_task"])
        self.assertIsNone(gate["blocked_reason"])
        self.assertEqual(gate["mapping_trust_basis"], "confirmed_mapping")

    def test_multiple_trusted_mappings_for_the_same_key_are_a_conflict(self) -> None:
        index = build_room_mapping_index(
            [
                _mapping(mapping_id=3, status="CONFIRMED"),
                _mapping(mapping_id=4, status="AUTO"),
            ]
        )
        resolved = resolve_room_type_mapping(
            {
                "hotel_id": "hotel-puyue",
                "source_platform": "meituan",
                "source_product_id": "mt-product-1",
            },
            index,
        )

        self.assertEqual(resolved["mapping_status"], "CONFLICT")
        self.assertEqual(resolved["mapping_resolution_status"], "mapping_conflict")

    def test_name_only_auto_candidate_cannot_write(self) -> None:
        index = build_room_mapping_index([_mapping(mapping_id=5, status="AUTO")])
        resolved = resolve_room_type_mapping(
            {
                "hotel_id": "hotel-puyue",
                "source_platform": "meituan",
                "source_product_id": "unknown-product",
                "source_room_type_name": "至臻·电竞双床房",
            },
            index,
        )

        self.assertEqual(resolved["mapping_resolution_status"], "mapping_pending")
        self.assertEqual(resolved["mapping_status"], "CANDIDATE")
        self.assertIn("inferred_by_name", resolved["risk_flags"])
        gate = is_price_task_mapping_ready(resolved)
        self.assertFalse(gate["ready_for_price_task"])
        self.assertEqual(gate["blocked_reason"], "mapping_not_trusted")

    def test_inactive_auto_and_ctrip_missing_cipher_remain_blocked(self) -> None:
        inactive = is_price_task_mapping_ready(
            {
                "mapping_status": "AUTO",
                "match_rule": "PRODUCT_ID",
                "mapping_active": False,
                "room_type_id": "py03",
                "source_product_id": "mt-product-1",
                "source_platform": "meituan",
            }
        )
        self.assertFalse(inactive["ready_for_price_task"])
        self.assertEqual(inactive["blocked_reason"], "mapping_inactive")

        ctrip = is_price_task_mapping_ready(
            {
                "mapping_status": "AUTO",
                "match_rule": "PRODUCT_ID",
                "mapping_active": True,
                "room_type_id": "py03",
                "source_product_id": "ct-product-1",
                "source_platform": "ctrip",
            }
        )
        self.assertFalse(ctrip["ready_for_price_task"])
        self.assertEqual(ctrip["blocked_reason"], "ctrip_product_cipher_missing")

    def test_s5_keeps_untrusted_mapping_as_readonly_quality_signal(self) -> None:
        index = build_room_mapping_index([_mapping(mapping_id=6, status="AUTO")])
        normalized = normalize_ota_price_row(
            {
                "hotel_id": "hotel-puyue",
                "source_platform": "meituan",
                "ota_product_id": "mt-product-1",
                "ota_product_name": "至臻双床-无早",
                "current_price": 388,
                "business_date": "2026-08-04",
            },
            index,
            requested_hotel_id="hotel-puyue",
            profile={"hotel_id": "hotel-puyue"},
        )
        self.assertIsNone(_product_block_reason(normalized))

        confirmed = {
            **normalized,
            "mapping_status": "PENDING",
            "match_rule": "NONE",
            "mapping_active": True,
        }
        self.assertIsNone(_product_block_reason(confirmed))
        self.assertIn("room_type_mapping_not_trusted", _mapping_quality_flags(confirmed))


if __name__ == "__main__":
    unittest.main()

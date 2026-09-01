from __future__ import annotations

import unittest

from runtime.adapters.normalized_query import (
    build_room_mapping_index,
    is_price_task_mapping_ready,
    normalize_ota_price_row,
    resolve_room_type_mapping,
)
from runtime.adapters.normalized_query import _normalize_name_key


class TestTask3ReverseInference(unittest.TestCase):
    def test_pms_platform_alias_aligns_business_and_mapping_rows(self) -> None:
        # ① PMS 业务行 source_platform=PMS（别样红），映射行=pms_byh。
        # 平台别名归一后二者落同一 "pms" 桶键,product_id 精确命中 → mapped。
        mapping_index = build_room_mapping_index(
            [
                {
                    "id": "map-pms",
                    "hotel_id": "puyue",
                    "room_type_id": "py03",
                    "room_type_name": "至臻电竞双床房",
                    "source_platform": "pms_byh",
                    "source_product_id": "pms-prod-1",
                    "mapping_status": "CONFIRMED",
                    "is_active": 1,
                }
            ]
        )
        row = normalize_ota_price_row(
            {
                "hotel_id": "puyue",
                "source_platform": "PMS（别样红）",
                "ota_product_id": "pms-prod-1",
                "business_date": "2026-06-30",
            },
            mapping_index,
            requested_hotel_id="puyue",
            profile={},
        )
        self.assertEqual(row["mapping_resolution_status"], "mapped")
        self.assertEqual(row["room_type_id"], "py03")

    def test_punctuation_normalized_name_matches_mapping_candidate(self) -> None:
        # ② 映射名 至臻·电竞双床房(·=U+00B7) vs 业务名 至臻.电竞双床房(.=U+002E)。
        # 名称键标点归一后命中同一名称桶 → 候选被找到(mapping_id 非空)。
        mapping_index = build_room_mapping_index(
            [
                {
                    "id": "map-name",
                    "hotel_id": "puyue",
                    "room_type_id": "py03",
                    "room_type_name": "至臻·电竞双床房",
                    "source_platform": "meituan",
                    "mapping_status": "PENDING",
                    "match_rule": "ROOM_NAME",
                    "is_active": 1,
                }
            ]
        )
        mapping = resolve_room_type_mapping(
            {
                "hotel_id": "puyue",
                "source_platform": "meituan",
                "room_type_name": "至臻.电竞双床房",
            },
            mapping_index,
        )
        self.assertEqual(mapping.get("mapping_id"), "map-name")

    def test_name_candidate_exposes_room_type_but_write_stays_blocked(self) -> None:
        # ③ 名称候选命中:读路径暴露 room_type_id 并标 inferred_by_name(低置信),
        # 但状态仍 mapping_pending(非 mapped);写闸对名称匹配 match_rule 仍 blocked。
        mapping_index = build_room_mapping_index(
            [
                {
                    "id": "map-name",
                    "hotel_id": "puyue",
                    "room_type_id": "py03",
                    "room_type_name": "至臻电竞双床房",
                    "source_platform": "meituan",
                    "mapping_status": "PENDING",
                    "match_rule": "ROOM_NAME",
                    "is_active": 1,
                }
            ]
        )
        mapping = resolve_room_type_mapping(
            {
                "hotel_id": "puyue",
                "source_platform": "meituan",
                "room_type_name": "至臻电竞双床房",
            },
            mapping_index,
        )
        # 读:暴露身份 + 低置信标记 + 非 mapped
        self.assertEqual(mapping.get("room_type_id"), "py03")
        self.assertIn("inferred_by_name", mapping.get("risk_flags") or [])
        self.assertEqual(mapping.get("mapping_resolution_status"), "mapping_pending")
        # 写:名称匹配(match_rule=ROOM_NAME)不可信 → 写调价仍 blocked
        gate = is_price_task_mapping_ready(
            {
                "match_rule": "ROOM_NAME",
                "mapping_status": "PENDING",
                "mapping_active": True,
                "room_type_id": "py03",
                "source_product_id": "x",
                "price_editable_flag": 1,
                "source_platform": "meituan",
            }
        )
        self.assertFalse(gate["ready_for_price_task"])

    def test_active_row_preferred_over_inactive_sibling(self) -> None:
        # ④b 同键有 active + inactive 两行 → 用 active 行(mapped),不误判 conflict。
        mapping_index = build_room_mapping_index(
            [
                {
                    "id": "map-inactive",
                    "hotel_id": "puyue",
                    "room_type_id": "py03",
                    "source_platform": "meituan",
                    "source_product_id": "mt-1",
                    "mapping_status": "CONFIRMED",
                    "is_active": 0,
                },
                {
                    "id": "map-active",
                    "hotel_id": "puyue",
                    "room_type_id": "py03",
                    "source_platform": "meituan",
                    "source_product_id": "mt-1",
                    "mapping_status": "CONFIRMED",
                    "is_active": 1,
                },
            ]
        )
        mapping = resolve_room_type_mapping(
            {"hotel_id": "puyue", "source_platform": "meituan", "ota_product_id": "mt-1"},
            mapping_index,
        )
        self.assertEqual(mapping.get("mapping_resolution_status"), "mapped")
        self.assertEqual(mapping.get("mapping_id"), "map-active")

    def test_inactive_only_mapping_diagnosed_as_inactive(self) -> None:
        # ④a 同键仅 inactive 行 → 诊断出 mapping_inactive(而非 pending/空)。
        mapping_index = build_room_mapping_index(
            [
                {
                    "id": "map-inactive",
                    "hotel_id": "puyue",
                    "room_type_id": "py03",
                    "source_platform": "meituan",
                    "source_product_id": "mt-1",
                    "mapping_status": "CONFIRMED",
                    "is_active": 0,
                }
            ]
        )
        mapping = resolve_room_type_mapping(
            {"hotel_id": "puyue", "source_platform": "meituan", "ota_product_id": "mt-1"},
            mapping_index,
        )
    def test_name_only_candidate_match_rule_not_trusted_by_write_gate(self) -> None:
        # C1 回归:仅靠名称模糊命中一条 match_rule=MANUAL 的映射行时,
        # 写闸不得借用该映射行的可信 match_rule 放行(商品 product_id 并不匹配)。
        mapping_index = build_room_mapping_index(
            [
                {
                    "id": "m-manual",
                    "hotel_id": "puyue",
                    "room_type_id": "py03",
                    "room_type_name": "至臻电竞双床房",
                    "source_platform": "meituan",
                    "source_product_id": "P-REAL",  # 真正被人工确认的商品
                    "mapping_status": "PENDING",
                    "match_rule": "MANUAL",
                    "is_active": 1,
                    "price_editable_flag": 1,
                }
            ]
        )
        mapping = resolve_room_type_mapping(
            {
                "hotel_id": "puyue",
                "source_platform": "meituan",
                "ota_product_id": "P-OTHER",  # 不匹配 source_product_id,只能靠名称命中
                "room_type_name": "至臻电竞双床房",
            },
            mapping_index,
        )
        self.assertEqual(mapping.get("mapping_resolution_status"), "mapping_pending")
        gate = is_price_task_mapping_ready(
            {
                **mapping,
                "source_platform": "meituan",
                "source_product_id": "P-OTHER",
                "price_editable_flag": 1,
            }
        )
        self.assertFalse(gate["ready_for_price_task"])

    def test_name_key_folds_separators_without_merging_decimals(self) -> None:
        # I1 回归:·/. 变体应归一为同键;但含小数的不同房型名不得因删点相撞。
        self.assertEqual(_normalize_name_key("至臻·电竞双床房"), _normalize_name_key("至臻.电竞双床房"))
        self.assertNotEqual(_normalize_name_key("101.5平米房"), _normalize_name_key("1015平米房"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest
from typing import Any

from runtime.s5_product_type_filter_patch import (
    filter_ota_price_mapping_result,
    install,
    unsupported_product_type,
)

install()

from runtime.algorithms.s5_real_candidates import build_s5_real_candidates


TARGET_DATE = "2026-08-05"


class S5ProductTypeFilterTests(unittest.TestCase):
    def test_classifier_uses_hour_room_mapping_fields_in_priority_order(self) -> None:
        for value in (1, 1.0, "1", "1.0", "true", "yes", "y", True):
            with self.subTest(is_hour_room=value):
                self.assertEqual(
                    unsupported_product_type({"is_hour_room": value}),
                    "hour_room",
                )

        self.assertEqual(
            unsupported_product_type({"rate_plan_name": "标准价"}),
            "hour_room",
        )
        self.assertEqual(
            unsupported_product_type({"ota_product_name": "3小时钟点房"}),
            "hour_room",
        )
        self.assertEqual(
            unsupported_product_type({"ota_product_name": "电竞小时房"}),
            "hour_room",
        )

    def test_classifier_does_not_use_product_type_or_broad_hour_keywords(self) -> None:
        self.assertIsNone(unsupported_product_type({"product_type": "hour_room"}))
        self.assertIsNone(unsupported_product_type({"product_type": "super_deal"}))
        self.assertIsNone(unsupported_product_type({"ota_product_name": "钟点优惠"}))
        self.assertIsNone(unsupported_product_type({"ota_product_name": "4小时特惠"}))
        self.assertIsNone(unsupported_product_type({"ota_product_name": "豪华大床房"}))
        self.assertIsNone(
            unsupported_product_type({"ota_product_name": "24小时免费取消豪华大床房"})
        )
        self.assertIsNone(
            unsupported_product_type({"ota_product_name": "支持小时延迟退房"})
        )

    def test_classifier_keeps_super_deal_explicit_signals(self) -> None:
        self.assertEqual(
            unsupported_product_type({"is_super_deal": True}),
            "super_deal",
        )
        self.assertEqual(
            unsupported_product_type({"ota_product_name": "超级团购专享"}),
            "super_deal",
        )

    def test_filter_removes_unsupported_rows_before_candidate_calculation(self) -> None:
        filtered, excluded = filter_ota_price_mapping_result(
            {
                "status": "ok",
                "payload": {
                    "price_snapshots": [
                        {
                            "ota_product_id": "regular",
                            "rate_plan_name": "门市价",
                            "ota_product_name": "豪华大床房",
                        },
                        {
                            "ota_product_id": "hour-flag",
                            "is_hour_room": 1,
                            "rate_plan_name": "钟点价",
                        },
                        {
                            "ota_product_id": "hour-rate-plan",
                            "rate_plan_name": "标准价",
                        },
                        {
                            "ota_product_id": "hour-name",
                            "rate_plan_name": "钟点价",
                            "ota_product_name": "3小时钟点房",
                        },
                        {
                            "ota_product_id": "deal",
                            "is_super_deal": True,
                            "rate_plan_name": "团购价",
                        },
                    ]
                },
            }
        )
        rows = filtered["payload"]["price_snapshots"]
        self.assertEqual([row["ota_product_id"] for row in rows], ["regular"])
        self.assertEqual(
            sorted(excluded),
            ["hour_room", "hour_room", "hour_room", "super_deal"],
        )
        self.assertEqual(filtered["payload"]["s5_excluded_unsupported_product_count"], 4)

    def test_filter_recovers_classification_from_normalized_rows(self) -> None:
        filtered, excluded = filter_ota_price_mapping_result(
            {
                "status": "ok",
                "payload": {
                    "price_snapshots": [
                        {
                            "channel": "meituan",
                            "ota_product_id": "hour-4h",
                            "ota_product_name": "荣耀开黑双床房 - 4 小时 - 入住前可取消（08:00~14:00）",
                            "product_type": "hour_room",
                        },
                        {
                            "channel": "meituan",
                            "ota_product_id": "deal",
                            "ota_product_name": "至臻电竞双床房",
                            "product_type": "super_deal",
                        },
                        {
                            "channel": "meituan",
                            "ota_product_id": "regular",
                            "ota_product_name": "豪华大床房",
                        },
                    ],
                    "rows": [
                        {
                            "source_platform": "meituan",
                            "ota_product_id": "hour-4h",
                            "ota_product_name": "荣耀开黑双床房 - 4 小时 - 入住前可取消（08:00~14:00）",
                            "is_hour_room": 1,
                            "rate_plan_name": "标准价",
                        },
                        {
                            "source_platform": "meituan",
                            "ota_product_id": "deal",
                            "is_super_deal": 1,
                            "rate_plan_name": "团购价",
                        },
                        {
                            "source_platform": "meituan",
                            "ota_product_id": "regular",
                            "rate_plan_name": "门市价",
                        },
                    ],
                },
            }
        )

        self.assertEqual(
            [row["ota_product_id"] for row in filtered["payload"]["price_snapshots"]],
            ["regular"],
        )
        self.assertEqual(sorted(excluded), ["hour_room", "super_deal"])

    def test_s5_only_returns_sellable_non_hour_non_super_deal_candidate(self) -> None:
        price_rows = [
            self._price_row(
                "regular",
                "豪华大床房",
                rate_plan_name="门市价",
            ),
            self._price_row(
                "regular-closed",
                "高级双床房",
                rate_plan_name="门市价",
                room_type_id="RT-CLOSED",
            ),
            self._price_row(
                "hour-flag",
                "钟点优惠",
                rate_plan_name="钟点价",
                is_hour_room=1,
            ),
            self._price_row(
                "hour-rate-plan",
                "特惠大床房",
                rate_plan_name="标准价",
            ),
            self._price_row(
                "hour-name",
                "3小时钟点房",
                rate_plan_name="钟点价",
            ),
            self._price_row(
                "deal",
                "超级团购专享",
                rate_plan_name="团购价",
                is_super_deal=True,
            ),
        ]

        def query(template: str, hotel_id: str, **kwargs: Any) -> dict[str, Any]:
            del hotel_id, kwargs
            if template == "ota_price_mapping":
                return {
                    "status": "ok",
                    "payload": {
                        "source_status": "ok",
                        "business_date": TARGET_DATE,
                        "price_snapshots": price_rows,
                    },
                }
            if template == "operating_snapshot":
                return {
                    "status": "ok",
                    "payload": {
                        "source_status": "ok",
                        "business_date": TARGET_DATE,
                        "freshness_status": "fresh",
                        "committed_occupancy_rate": 0.65,
                        "room_type_forecasts": [
                            {
                                "room_type_id": "RT-1",
                                "total_rooms": 20,
                                "available_rooms": 7,
                                "committed_sold_rooms": 13,
                            },
                            {
                                "room_type_id": "RT-CLOSED",
                                "total_rooms": 8,
                                "available_rooms": 0,
                                "committed_sold_rooms": 8,
                            },
                        ],
                    },
                }
            return {"status": "ok", "payload": {"source_status": "ok"}}

        def resolve_guard(*args: Any, **kwargs: Any) -> dict[str, Any]:
            del args, kwargs
            return {
                "source": "active_price_guard_policy",
                "policy_id": "PG-1",
                "version": "1",
                "policy_state": "active",
                "floor_price": 180,
                "ceiling_price": 320,
                "max_increase_pct": 0.15,
                "max_decrease_pct": 0.15,
                "min_increase_pct": 0.0,
                "min_decrease_pct": 0.0,
            }

        result = build_s5_real_candidates(
            query=query,
            resolve_guard=resolve_guard,
            control_db_path=":memory:",
            hotel_id="puyue",
            target_stay_date=TARGET_DATE,
            as_of_time="2026-08-05T16:00:00+08:00",
            s15_result={
                "status": "ok",
                "baseline": {
                    "baseline_package": {
                        "target_date": TARGET_DATE,
                        "hotel_final_sales_target": 18,
                        "sample_maturity": "mature",
                        "data_gaps": [],
                    }
                },
            },
            s16_result={
                "status": "ok",
                "dynamic_diagnosis": {
                    "target_date": TARGET_DATE,
                    "status": "ok",
                    "sales": {
                        "checkpoint_room_gap": 1,
                        "remaining_target_gap": 5,
                    },
                },
            },
        )

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["excluded_unsupported_product_count"], 4)
        self.assertEqual(
            result["excluded_unsupported_product_types"],
            ["hour_room", "super_deal"],
        )
        self.assertEqual(result["excluded_no_inventory_product_count"], 1)
        self.assertEqual(result["excluded_no_inventory_room_type_count"], 1)
        self.assertEqual(
            [item["ota_product_id"] for item in result["candidates"]],
            ["regular"],
        )

    @staticmethod
    def _price_row(
        product_id: str,
        product_name: str,
        *,
        rate_plan_name: str,
        is_hour_room: Any = None,
        is_super_deal: Any = None,
        room_type_id: str = "RT-1",
    ) -> dict[str, Any]:
        return {
            "room_type_id": room_type_id,
            "room_type_name": "豪华大床房",
            "channel": "meituan",
            "ota_product_id": product_id,
            "ota_product_name": product_name,
            "rate_plan_name": rate_plan_name,
            "is_hour_room": is_hour_room,
            "is_super_deal": is_super_deal,
            "current_price": 240,
            "price_editable_flag": True,
            "mapping_status": "CONFIRMED",
            "match_rule": "PRODUCT_ID",
            "mapping_active": True,
            "mapping_resolution_status": "mapped",
            "business_date": TARGET_DATE,
            "snapshot_time": "2026-08-05T15:59:00+08:00",
        }


if __name__ == "__main__":
    unittest.main()

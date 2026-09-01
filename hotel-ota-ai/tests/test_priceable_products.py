from __future__ import annotations

import unittest
from unittest import mock

from runtime.feishu_command_router import _detect_intent, _priceable_product_platform
from runtime.feishu_output_renderer import build_feishu_send_payload
from runtime.priceable_products import list_priceable_products


class TestPriceableProducts(unittest.TestCase):
    def test_router_recognizes_priceable_product_query_before_generic_price_intent(self) -> None:
        phrases = (
            "有哪些可调价商品",
            "当前有哪些可以进行调价的商品？",
            "哪些商品可以调价",
            "查询可调价商品",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(_detect_intent(phrase), "priceable_product_list")

    def test_router_extracts_one_explicit_ota_platform_only(self) -> None:
        self.assertEqual(_priceable_product_platform("美团可调价商品"), "meituan")
        self.assertEqual(_priceable_product_platform("携程可调价商品"), "ctrip")
        self.assertIsNone(_priceable_product_platform("美团和携程可调价商品"))

    def test_missing_price_bounds_does_not_hide_or_block_normal_product(self) -> None:
        source = {
            "status": "ok",
            "data_source_type": "mysql_db",
            "payload": {
                "source_status": "ok",
                "freshness_status": "fresh",
                "data_snapshot_time": "2026-08-03 12:00:00",
                "price_snapshots": [
                    {
                        "channel": "meituan",
                        "ota_product_id": "mt-1",
                        "ota_product_name": "美团大床房含早",
                        "current_price": 188,
                        "room_type_id": "rt-1",
                        "room_type_name": "PMS 大床房",
                        "row_risk_flags": [],
                    },
                    {
                        "channel": "ctrip",
                        "ota_product_id": "ct-2",
                        "ota_product_name": "携程标准间",
                        "current_price": 208,
                        "room_type_id": "rt-2",
                        "room_type_name": "PMS 标准间",
                        "row_risk_flags": [],
                    },
                ],
            },
        }

        def policy(*_args: object, **kwargs: object) -> dict:
            if kwargs["ota_product_id"] == "mt-1":
                return {"source": "active_price_guard_policy", "policy_id": "guard-1", "floor_price": 150, "ceiling_price": 220}
            return {"source": "default_policy", "policy_id": None, "floor_price": None, "ceiling_price": None}

        with mock.patch("runtime.priceable_products.database_source_enabled", return_value=True), mock.patch(
            "runtime.priceable_products.database_template_result", return_value=source
        ) as query, mock.patch("runtime.priceable_products.resolve_price_guard_policy", side_effect=policy):
            result = list_priceable_products(hotel_id="hotel-001", control_db_path=":memory:", as_of_time="2026-08-03 12:30:00")

        query.assert_any_call("ota_price_mapping", "hotel-001", as_of_time="2026-08-03 12:30:00", source_platform=None)
        self.assertEqual(result["product_count"], 2)
        self.assertEqual(result["eligible_product_count"], 2)
        product = next(item for item in result["products"] if item["ota_product_id"] == "ct-2")
        self.assertEqual(product["ota_product_name"], "携程标准间")
        self.assertEqual(product["current_price"], 208)
        self.assertEqual(product["product_state"], "eligible_for_price_request")
        self.assertEqual(product["state_reason"], "product_ready_for_price_request")

    def test_hour_room_and_super_deal_are_excluded_from_priceable_list(self) -> None:
        source = {
            "status": "ok",
            "payload": {
                "source_status": "ok",
                "price_snapshots": [
                    {"channel": "meituan", "ota_product_id": "normal", "ota_product_name": "标准大床房", "current_price": 300, "room_type_id": "rt-1"},
                    {"channel": "meituan", "ota_product_id": "hour", "ota_product_name": "电竞大床房 4 小时", "current_price": 88, "room_type_id": "rt-1", "is_hour_room": 1},
                    {"channel": "meituan", "ota_product_id": "deal", "ota_product_name": "标准大床房 超级团购 1", "current_price": 179, "room_type_id": "rt-1", "is_super_deal": 1},
                ],
            },
        }
        with mock.patch("runtime.priceable_products.database_source_enabled", return_value=True), mock.patch(
            "runtime.priceable_products.database_template_result", return_value=source
        ), mock.patch("runtime.priceable_products.resolve_price_guard_policy", return_value={"source": "default_policy"}):
            result = list_priceable_products(hotel_id="hotel-001", control_db_path=":memory:")

        self.assertEqual([item["ota_product_id"] for item in result["products"]], ["normal"])
        self.assertEqual(result["excluded_unsupported_product_count"], 2)
        self.assertEqual(result["excluded_unsupported_product_types"], ["hour_room", "super_deal"])

    def test_sold_out_room_type_is_excluded_from_priceable_list(self) -> None:
        prices = {
            "status": "ok",
            "payload": {
                "source_status": "ok",
                "price_snapshots": [
                    {"channel": "meituan", "ota_product_id": "closed-1", "ota_product_name": "售完大床房", "current_price": 300, "room_type_id": "rt-closed"},
                    {"channel": "meituan", "ota_product_id": "open-1", "ota_product_name": "可售双床房", "current_price": 320, "room_type_id": "rt-open"},
                ],
            },
        }
        operating = {
            "status": "ok",
            "payload": {
                "source_status": "ok",
                "room_type_forecasts": [
                    {"stay_date": "2026-08-03", "room_type_id": "rt-closed", "available_rooms": 0},
                    {"stay_date": "2026-08-03", "room_type_id": "rt-open", "available_rooms": 2},
                ],
            },
        }

        def query(template: str, *_args: object, **_kwargs: object) -> dict:
            return prices if template == "ota_price_mapping" else operating

        with mock.patch("runtime.priceable_products.database_source_enabled", return_value=True), mock.patch(
            "runtime.priceable_products.database_template_result", side_effect=query
        ), mock.patch("runtime.priceable_products.resolve_price_guard_policy", return_value={"source": "default_policy"}):
            result = list_priceable_products(
                hotel_id="hotel-001",
                control_db_path=":memory:",
                as_of_time="2026-08-03 12:30:00",
            )

        self.assertEqual([item["ota_product_id"] for item in result["products"]], ["open-1"])
        self.assertEqual(result["excluded_sold_out_product_count"], 1)
        self.assertEqual(result["excluded_sold_out_room_type_count"], 1)

    def test_renderer_uses_ota_product_name_not_pms_room_name(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "priceable_product_list",
                "status": "ok",
                "products": [
                    {
                        "channel": "meituan",
                        "ota_product_name": "美团大床房含早",
                        "current_price": 188,
                        "room_type_name": "PMS 大床房",
                        "price_request_eligible": False,
                        "state_reason": "price_guard_not_configured",
                    }
                ],
                "product_count": 1,
                "eligible_product_count": 0,
                "auth_role": "owner",
            },
            role="owner",
        )

        self.assertIn("美团大床房含早", payload["text"])
        self.assertIn("当前价 188", payload["text"])
        self.assertIn("仅查看", payload["text"])
        self.assertNotIn("PMS 大床房", payload["text"])

    def test_requested_platform_queries_and_displays_only_that_platform(self) -> None:
        source = {
            "status": "ok",
            "data_source_type": "mysql_db",
            "payload": {
                "source_status": "ok",
                "price_snapshots": [
                    {"channel": "meituan", "ota_product_id": "mt-1", "ota_product_name": "美团大床房", "current_price": 188, "room_type_id": "rt-1"},
                    {"channel": "ctrip", "ota_product_id": "ct-1", "ota_product_name": "携程大床房", "current_price": 208, "room_type_id": "rt-1"},
                ],
            },
        }
        with mock.patch("runtime.priceable_products.database_source_enabled", return_value=True), mock.patch(
            "runtime.priceable_products.database_template_result", return_value=source
        ) as query, mock.patch(
            "runtime.priceable_products.resolve_price_guard_policy",
            return_value={"source": "default_policy", "floor_price": None, "ceiling_price": None},
        ):
            result = list_priceable_products(
                hotel_id="hotel-001",
                control_db_path=":memory:",
                source_platform="meituan",
            )

        query.assert_any_call(
            "ota_price_mapping",
            "hotel-001",
            as_of_time=None,
            source_platform="meituan",
        )
        self.assertEqual(result["source_platform"], "meituan")
        self.assertEqual([item["ota_product_id"] for item in result["products"]], ["mt-1"])
        payload = build_feishu_send_payload({"intent": "priceable_product_list", **result}, role="owner")
        self.assertIn("美团 可调价商品清单", payload["text"])
        self.assertNotIn("携程大床房", payload["text"])


if __name__ == "__main__":
    unittest.main()

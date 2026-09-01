from __future__ import annotations

import unittest

from runtime import s16_meituan_projection_advisory_patch as s16_projection
from runtime.s15_market_metric_patch import market_point
from runtime.s15_price_scope_patch import analyze_price_scopes
from runtime.s15_s16_complete_output_patch import s15_message
from runtime.s15_s16_data_correctness_patch import select_batch
from runtime.sales_progress.presentation import attach_s15_user_view


class S15S16DataAndOutputRegressionTests(unittest.TestCase):
    def _current_rows(self) -> list[dict[str, object]]:
        return [
            {
                "room_type_id": "py01",
                "room_type_name": "房型一",
                "total_rooms": 5,
                "available_rooms": 3,
                "occupied_rooms": 1,
                "overbooking_rooms": 0,
                "snapshot_hour": "2026-08-04 10:00:00",
                "snapshot_time": "2026-08-04 10:05:00",
            },
            {
                "room_type_id": "py02",
                "room_type_name": "房型二",
                "total_rooms": 4,
                "available_rooms": 2,
                "occupied_rooms": 1,
                "overbooking_rooms": 0,
                "snapshot_hour": "2026-08-04 10:00:00",
                "snapshot_time": "2026-08-04 10:05:00",
            },
        ]

    def test_current_stale_complete_batch_is_usable_with_freshness_downgrade(self) -> None:
        selected = select_batch(
            self._current_rows(),
            expected_room_types=["py01", "py02"],
            requested_hour=17,
            as_of_datetime="2026-08-04 17:30:00",
        )
        self.assertEqual(selected.status, "ok")
        self.assertEqual(len(selected.rows), 2)
        self.assertEqual(selected.reason, "stale_checkpoint_used")
        self.assertGreater(selected.checkpoint_gap_minutes or 0, 120)

    def test_historical_missing_hour_is_not_carried_forward_past_limit(self) -> None:
        selected = select_batch(
            self._current_rows(),
            expected_room_types=["py01", "py02"],
            requested_hour=17,
            as_of_datetime=None,
        )
        self.assertEqual(selected.status, "data_gap")
        self.assertEqual(selected.reason, "checkpoint_gap_exceeds_limit")
        self.assertEqual(selected.rows, [])

    def test_market_estimate_uses_peer_enabled_pay_order_row(self) -> None:
        point = market_point(
            {
                "FLOW_PAY_ORDER_CNT": {
                    "metric_code": "FLOW_PAY_ORDER_CNT",
                    "metric_value": 22,
                    "peer_average": None,
                    "competitor_rank": None,
                },
                "PAY_ORDER_CNT": {
                    "metric_code": "PAY_ORDER_CNT",
                    "metric_value": 22,
                    "peer_average": 12.1,
                    "competitor_rank": "3/20",
                },
            }
        )
        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point["metric_code_used"], "PAY_ORDER_CNT")
        self.assertEqual(point["estimated_market_orders"], 242)
        self.assertEqual(point["peer_hotel_count"], 20)

    def test_price_scope_uses_normal_full_day_and_separates_special_products(self) -> None:
        payload = {
            "room_types": {
                "py01": {
                    "room_type_id": "py01",
                    "room_type_name": "房型一",
                    "price_baseline": {
                        "weighted_avg": 150,
                        "median": 145,
                        "p20": 120,
                        "p80": 180,
                    },
                }
            }
        }
        result = analyze_price_scopes(
            payload,
            [
                {
                    "room_type_id": "py01",
                    "ota_product_id": "normal",
                    "ota_sale_price": 200,
                    "product_scope": "normal_full_day",
                    "mapping_status": "AUTO",
                    "mapping_active": True,
                },
                {
                    "room_type_id": "py01",
                    "ota_product_id": "deal",
                    "ota_sale_price": 139,
                    "product_scope": "super_deal",
                    "mapping_status": "AUTO",
                    "mapping_active": True,
                },
                {
                    "room_type_id": "py01",
                    "ota_product_id": "hour",
                    "ota_sale_price": 88,
                    "product_scope": "hour_room",
                    "mapping_status": "AUTO",
                    "mapping_active": True,
                },
            ],
        )
        room = result["room_results"][0]
        self.assertEqual(room["current_price"], 200)
        self.assertEqual(room["comparison_scope"], "normal_full_day")
        self.assertEqual(room["super_deal_current_price"], 139)
        self.assertEqual(room["hour_room_current_price"], 88)
        self.assertIn("py01", result["high_room_type_ids"])

    def test_s16_advisory_displays_estimated_take_home_price_only(self) -> None:
        renderer = s16_projection._message_wrapper(lambda report: "五、建议动作\n- 保持观察")
        report = {
            "dynamic_diagnosis": {
                "estimated_price_advisories": [
                    {
                        "action_type": "estimated_price_increase_advisory",
                        "ota_product_name": "荣耀战场大床房",
                        "current_raw_price": 396,
                        "suggested_raw_price": 416,
                        "suggested_change_pct": 0.05,
                        "current_activity_net_estimate": 216,
                        "pms_transaction_median_reference": 210,
                        "observe_minutes": 60,
                    }
                ]
            }
        }

        text = renderer(report)

        self.assertIn("预估到手价 ¥216 → 建议约 ¥227", text)
        self.assertNotIn("美团底价", text)
        self.assertNotIn("¥396", text)
        self.assertNotIn("¥416", text)

    def test_s15_output_contains_complete_baseline_matrix_and_no_followup_question(self) -> None:
        payload = {
            "status": "ok",
            "target_date": "2026-08-04",
            "as_of_datetime": "2026-08-04 17:30:00",
            "selected_dates": ["2026-07-28", "2026-07-21"],
            "hotel": {
                "effective_target_room_nights": 10,
                "hourly_points": [
                    {
                        "hour": 17,
                        "capacity": {"median": 0.5, "sample_count": 2},
                        "target_completion": {"median": 0.6, "sample_count": 2},
                    }
                ],
            },
            "room_types": {
                "py01": {
                    "room_type_id": "py01",
                    "room_type_name": "房型一",
                    "effective_target_room_nights": 5,
                    "hourly_points": [
                        {
                            "hour": 17,
                            "capacity": {"median": 0.5},
                            "target_completion": {"median": 0.6},
                        }
                    ],
                    "price_baseline": {"p20": 100, "median": 120, "p80": 150},
                }
            },
            "operating_analysis": {
                "sales": {
                    "status": "slow",
                    "committed_sold": 4,
                    "total_rooms": 10,
                    "available_rooms": 6,
                    "remaining_inventory_ratio": 0.6,
                    "sales_progress_delta_pp": -10,
                    "capacity_progress_delta_pp": -5,
                    "checkpoint_gap_minutes": 30,
                    "room_type_results": [
                        {
                            "room_type_id": "py01",
                            "room_type_name": "房型一",
                            "committed_sold": 2,
                            "total_rooms": 5,
                            "target_line": {"status": "slow", "delta_pp": -10},
                            "capacity_line": {"status": "normal", "delta_pp": 0},
                        }
                    ],
                },
                "market": {"status": "normal"},
                "market_share": {"status": "normal"},
                "browse": {"status": "normal"},
                "first_conversion": {"status": "normal"},
                "second_conversion": {"status": "normal"},
                "price": {"room_results": []},
                "lead_price": {},
                "diagnosis": ["sales_progress_slow"],
                "actions": [{"action_type": "continue_observation"}],
            },
        }
        text = s15_message(payload)
        required = (
            "一、销售进度基准线（全店）",
            "二、销售进度基准线（全部房型）",
            "三、大盘订单基准线（估算）",
            "四、本店市场份额基准线（估算）",
            "五、浏览基准线（日级）",
            "六、一转基准线（日级：曝光→浏览）",
            "七、二转基准线（日级：浏览→支付）",
            "八、房型历史价格基准线与当前美团商品价",
            "九、引流价及排名基准线（日级）",
            "十、动作判断",
            "十一、基准健康与数据边界",
        )
        for section in required:
            self.assertIn(section, text)
        self.assertNotIn("需要我继续", text)
        self.assertNotIn("需要的话", text)

        attached = attach_s15_user_view(payload)
        self.assertFalse(attached["ai_analysis_allowed"])
        self.assertFalse(attached["ai_rewrite_allowed"])
        self.assertTrue(attached["must_send_text_verbatim"])
        self.assertEqual(attached["delivery_mode"], "authoritative_runtime_text")


if __name__ == "__main__":
    unittest.main()

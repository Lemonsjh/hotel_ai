from __future__ import annotations

import unittest

from runtime.derived_contexts import (
    build_competitor_context,
    build_customer_order_context,
    build_ota_health_context,
    build_operating_snapshot_context,
    build_price_context,
    build_progress_context,
    build_promotion_context,
    build_promotion_roi_context,
    build_reputation_context,
    build_sales_baseline_context,
)


class TestDerivedContexts(unittest.TestCase):
    def test_operating_context_derives_available_metrics_from_23_table_payloads(self) -> None:
        context = build_operating_snapshot_context(
            {
                "status": "ok",
                "payload": {
                    "hotel_id": "xingfeng",
                    "data_business_date": "2026-06-26",
                    "data_snapshot_time": "2026-06-26 22:20:18",
                    "room_count": 49,
                    "sold_rooms": 31,
                    "remaining_rooms": 18,
                    "room_revenue": 6200,
                    "room_nights": 31,
                    "occupancy_rate": None,
                    "adr": None,
                    "revpar": None,
                    "freshness_status": "fresh",
                    "business_status": "current",
                },
            },
            room_status_result={
                "status": "ok",
                "payload": {
                    "rooms": [
                        {"room_status": "occupied"},
                        {"room_status": "occupied"},
                        {"room_status": "vacant"},
                    ],
                    "source_table": "kf11_room_status_snapshot",
                },
            },
        )

        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["capability_level"], "derived")
        self.assertEqual(context["source_mode"], "mysql_runtime")
        self.assertIn("committed_occupancy_rate", context["derived_fields"])
        self.assertIn("adr", context["derived_fields"])
        self.assertEqual(context["core_metrics"]["occupancy_rate"], 0.6327)
        self.assertEqual(context["core_metrics"]["adr"], 200.0)
        self.assertEqual(context["core_metrics"]["revpar"], 126.53)
        self.assertTrue(context["commercial_visible"])
        self.assertIn("经营快照", context["commercial_sections"])
        self.assertNotIn("missing_fields", context)

    def test_operating_context_keeps_physical_room_status_separate_from_committed_sales(self) -> None:
        context = build_operating_snapshot_context(
            {
                "status": "ok",
                "payload": {
                    "hotel_id": "puyue",
                    "data_business_date": "2026-07-01",
                    "room_count": 11,
                    "sold_rooms": 11,
                    "remaining_rooms": 0,
                    "occupancy_rate": 1.0,
                    "room_revenue": 3300,
                    "room_nights": 11,
                },
            },
            room_status_result={
                "status": "ok",
                "payload": {
                    "rooms": [
                        *[{"room_no": f"8{index:02d}", "room_status": "occupied"} for index in range(1, 12)],
                        {"room_no": "812", "room_status": "vacant"},
                        {"room_no": "813", "room_status": "available"},
                        {"room_no": "814", "room_status": "空房"},
                    ],
                    "source_table": "kf11_room_status_snapshot",
                },
            },
        )

        self.assertEqual(context["core_metrics"]["total_rooms"], 11)
        self.assertEqual(context["core_metrics"]["sold_rooms"], 11)
        self.assertEqual(context["core_metrics"]["remaining_rooms"], 0)
        self.assertEqual(context["core_metrics"]["committed_occupancy_rate"], 1.0)
        self.assertEqual(context["core_metrics"]["physical_total_rooms"], 14)
        self.assertEqual(context["core_metrics"]["physical_occupied_rooms"], 11)
        self.assertEqual(context["core_metrics"]["physical_occupancy_rate"], 0.7857)
        self.assertIn("physical_room_status_snapshot", context["derived_fields"])
        self.assertIn("kf11_room_status_snapshot", context["used_tables"])

    def test_operating_context_derives_committed_sold_from_forecast_and_keeps_overbooking(self) -> None:
        context = build_operating_snapshot_context(
            {"payload": {"total_rooms": 30, "available_rooms": 4, "overbooking_rooms": 2, "room_revenue": 5600}},
            room_status_result={"payload": {"rooms": [{"room_no": "101", "room_status": "occupied"}]}},
        )

        core = context["core_metrics"]
        self.assertEqual(core["base_committed_sold_rooms"], 26)
        self.assertEqual(core["committed_sold_rooms"], 28)
        self.assertEqual(core["sold_rooms"], 28)
        self.assertEqual(core["committed_occupancy_rate"], 0.9333)
        self.assertEqual(core["physical_occupied_rooms"], 1)
        self.assertEqual(core["physical_occupancy_rate"], 1.0)
        self.assertEqual(core["adr"], 200.0)

    def test_operating_context_does_not_infer_committed_sales_from_physical_occupancy(self) -> None:
        context = build_operating_snapshot_context(
            {"payload": {"occupied_rooms": 8, "room_nights": 8}},
            room_status_result={"payload": {"rooms": [{"room_no": "101", "room_status": "occupied"}]}},
        )

        self.assertEqual(context["status"], "partial")
        self.assertIsNone(context["core_metrics"]["committed_sold_rooms"])
        self.assertEqual(context["core_metrics"]["physical_occupied_rooms"], 1)

    def test_progress_without_target_outputs_current_facts_not_gap(self) -> None:
        context = build_progress_context(
            {
                "status": "ok",
                "payload": {
                    "data_business_date": "2026-06-26",
                    "sold_rooms": 31,
                    "orders_today": 18,
                    "room_nights": 31,
                    "occupancy_rate": 0.6327,
                    "freshness_status": "fresh",
                    "business_status": "current",
                },
            },
            baseline_context=None,
        )

        self.assertEqual(context["status"], "partial")
        self.assertEqual(context["capability_level"], "derived")
        self.assertEqual(context["progress_granularity"], "daily")
        self.assertEqual(context["current_facts"]["actual_room_nights"], 31)
        self.assertEqual(context["commercial_sections"], ["当前进度事实"])
        self.assertIn("baseline_target_missing", context["internal_missing_fields"])
        self.assertNotIn("progress_gap", context)

    def test_progress_prefers_committed_sold_and_reports_physical_occupancy_separately(self) -> None:
        context = build_progress_context(
            {"payload": {"committed_sold_rooms": 20, "occupied_rooms": 7, "room_nights": 18}},
            baseline_context={"target_room_nights": 19},
        )

        self.assertEqual(context["current_facts"]["actual_committed_sold_rooms"], 20)
        self.assertEqual(context["current_facts"]["actual_physical_occupied_rooms"], 7)
        self.assertEqual(context["progress_actual_unit"], "committed_sold_rooms")
        self.assertEqual(context["progress_gap"], 1)

    def test_roi_without_ad_cost_is_estimated_and_commercial_safe(self) -> None:
        context = build_promotion_roi_context(
            revenue_context={"room_revenue": 6200, "room_nights": 31},
            activity_context={"active_campaign_count": 2},
            cost_context={},
        )

        self.assertEqual(context["status"], "partial")
        self.assertEqual(context["capability_level"], "estimated")
        self.assertIn("estimated_roi", context["estimated_fields"])
        self.assertIn("roi_cost_missing", context["internal_missing_fields"])
        self.assertEqual(context["commercial_sections"], ["ROI 保守测算参考"])
        self.assertTrue(context["commercial_visible"])


    def test_promotion_context_uses_activity_rows_without_exposing_gaps(self) -> None:
        context = build_promotion_context(
            {
                "data_source_type": "mysql_db",
                "captured_at": "2026-06-27 09:00:00",
                "payload": {
                    "rows": [
                        {"source_platform": "meituan", "activity_status": "active", "activity_name": "member discount", "room_type_name": "KING"},
                        {"source_platform": "ctrip", "activity_status": "paused", "activity_name": "long stay", "room_type_name": "TWIN"},
                    ],
                    "data_business_date": "2026-06-27",
                    "freshness_status": "fresh",
                    "business_status": "current",
                }
            },
            product_detail_result={"payload": {"rows": [{"room_type_name": "KING"}, {"room_type_name": "TWIN"}]}},
        )

        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["active_campaign_count"], 1)
        self.assertEqual(context["campaign_room_type_count"], 2)
        self.assertEqual(context["data_source_type"], "mysql_db")
        self.assertTrue(context["commercial_visible"])
        self.assertNotIn("missing_fields", context)

    def test_reputation_context_hides_reply_when_review_text_missing(self) -> None:
        context = build_reputation_context(
            {
                "payload": {
                    "rows": [
                        {"source_platform": "meituan", "rating_score": 4.6, "bad_review_count": 2, "unreplied_review_count": 1},
                        {"source_platform": "ctrip", "rating_score": 4.8, "bad_review_count": 0, "unreplied_review_count": 0},
                    ],
                    "data_snapshot_time": "2026-06-27 09:00:00",
                    "freshness_status": "fresh",
                    "business_status": "current",
                }
            },
            ranking_result={"payload": {"rows": [{"keyword": "service", "rank": 12}, {"keyword": "clean", "rank": 8}]}},
        )

        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["review_score"], 4.7)
        self.assertEqual(context["negative_review_count"], 2)
        self.assertIn("reply_strategy_only_without_review_text", context["risk_flags"])
        self.assertNotIn("reply_draft", context)

    def test_competitor_context_uses_rank_signals_without_fake_competitor_prices(self) -> None:
        context = build_competitor_context(
            {
                "payload": {
                    "rows": [
                        {"source_platform": "meituan", "peer_rank": 3, "peer_average": 4.5},
                        {"source_platform": "ctrip", "peer_rank": 15, "peer_average": 4.4},
                    ],
                    "freshness_status": "fresh",
                    "business_status": "current",
                    "data_business_date": "2026-06-27",
                }
            }
        )

        self.assertEqual(context["status"], "partial")
        self.assertEqual(context["rank_pressure_signal"], "medium")
        self.assertTrue(context["commercial_visible"])
        self.assertNotIn("competitor_prices", context)

    def test_price_context_uses_ota_mapping_without_exposing_product_cipher(self) -> None:
        context = build_price_context(
            {
                "payload": {
                    "rows": [
                        {
                            "source_platform": "ctrip",
                            "room_type_name": "KING",
                            "ota_product_id": "product-1",
                            "ota_sale_price": 188,
                            "commission_rate": 0.1,
                            "product_cipher": "secret-cipher",
                        }
                    ],
                    "data_business_date": "2026-06-27",
                    "freshness_status": "fresh",
                    "business_status": "current",
                }
            }
        )

        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["capability_level"], "derived")
        self.assertEqual(context["price_items"][0]["ota_current_price"], 188.0)
        self.assertEqual(context["price_items"][0]["product_cipher_status"], "present_hidden")
        self.assertNotIn("secret-cipher", str(context))
        self.assertIn("price_mapping_summary", context["commercial_sections"])

    def test_ota_health_context_combines_metrics_reviews_and_activity(self) -> None:
        context = build_ota_health_context(
            {
                "payload": {
                    "rows": [
                        {"metric_name": "exposure", "metric_value": 1200, "competitor_rank": 8, "peer_average": 4.5},
                        {"metric_name": "payment_conversion_rate", "metric_value": 0.032},
                    ],
                    "data_business_date": "2026-06-27",
                    "freshness_status": "fresh",
                    "business_status": "current",
                }
            },
            review_overview_result={"payload": {"rows": [{"review_score": 4.6, "negative_review_count": 2, "unreplied_review_count": 1}]}},
            promotion_context={"active_campaign_count": 1},
        )

        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["metrics"]["exposure"], 1200.0)
        self.assertEqual(context["metrics"]["payment_conversion_rate"], 0.032)
        self.assertEqual(context["review_score"], 4.6)
        self.assertIn("ota_health_summary", context["commercial_sections"])

    def test_customer_order_context_outputs_aggregates_only(self) -> None:
        context = build_customer_order_context(
            {
                "payload": {
                    "orders": [
                        {
                            "order_id": "private-order-1",
                            "room_type_name": "KING",
                            "customer_source": "OTA",
                            "guest_name": "private-guest",
                            "room_no": "801",
                            "room_nights": 2,
                            "price_detail": {"room_fee": 400},
                        },
                        {
                            "order_id": "private-order-2",
                            "room_type_name": "TWIN",
                            "customer_source": "Direct",
                            "room_nights": 1,
                            "price_detail": {"room_fee": 160},
                        },
                    ],
                    "data_business_date": "2026-06-27",
                }
            }
        )

        self.assertEqual(context["status"], "ok")
        self.assertEqual(context["unique_order_count"], 2)
        self.assertEqual(context["privacy_policy"], "aggregate_only_no_row_level_orders")
        self.assertNotIn("private-order", str(context))
        self.assertNotIn("private-guest", str(context))
        self.assertNotIn("801", str(context))

    def test_sales_baseline_context_uses_daily_or_monthly_without_hourly_curve(self) -> None:
        context = build_sales_baseline_context(
            {"payload": {"sold_rooms": 31, "orders_today": 18, "data_business_date": "2026-06-27"}},
            monthly_result={"payload": {"room_nights": 900, "room_count": 50, "period_month": "2026-06"}},
        )

        self.assertEqual(context["status"], "partial")
        self.assertEqual(context["progress_granularity"], "daily")
        self.assertEqual(context["monthly_average_room_nights"], 30.0)
        self.assertEqual(context["hourly_target_curve"], [])
        self.assertIn("sales_baseline_daily_reference", context["commercial_sections"])


if __name__ == "__main__":
    unittest.main()

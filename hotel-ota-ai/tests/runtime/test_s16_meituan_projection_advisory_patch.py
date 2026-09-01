from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.s16_meituan_projection_advisory_patch import (
    _message_wrapper,
    build_meituan_market_proxy,
    build_platform_pace_insights,
    build_price_advisories,
)


class FakeRepository:
    def _query(self, sql, params):
        if "FROM jd01_booking_detail" in sql:
            return [
                {
                    "own_orders": 22,
                    "latest_snapshot_time": "2026-08-04 18:55:00",
                }
            ]
        if "FROM meituan_ota_business_metrics" in sql:
            return [
                {
                    "metric_value": 22,
                    "peer_average": 12.1,
                    "competitor_rank": "3/20",
                    "snapshot_time": "2026-08-04 18:52:00",
                }
            ]
        raise AssertionError(sql)


class HourlyHistoryRepository:
    def __init__(self):
        self.calls = []

    def _query(self, sql, params):
        if "FROM meituan_ota_business_metrics_hourly" not in sql:
            raise AssertionError(sql)
        self.calls.append((sql, tuple(params)))
        return [
            {
                "business_date": "2026-08-04",
                "snapshot_hour": "2026-08-04 12:00:00",
                "metric_value": 30,
            },
            {
                "business_date": "2026-08-04",
                "snapshot_hour": "2026-08-04 23:00:00",
                "metric_value": 100,
            },
            {
                "business_date": "2026-08-11",
                "snapshot_hour": "2026-08-11 13:00:00",
                "metric_value": 40,
            },
            {
                "business_date": "2026-08-11",
                "snapshot_hour": "2026-08-11 23:00:00",
                "metric_value": 100,
            },
            {
                "business_date": "2026-08-17",
                "snapshot_hour": "2026-08-17 13:00:00",
                "metric_value": 80,
            },
            {
                "business_date": "2026-08-17",
                "snapshot_hour": "2026-08-17 23:00:00",
                "metric_value": 100,
            },
        ]


class S16MeituanProjectionAdvisoryPatchTests(unittest.TestCase):
    def test_jd01_meituan_orders_drive_market_and_share_estimates(self):
        proxy = build_meituan_market_proxy(
            FakeRepository(),
            hotel_id="puyue",
            target_date="2026-08-04",
            as_of_datetime="2026-08-04 18:57:00",
            baseline_market_orders=276.9,
            baseline_market_share=0.096,
        )
        self.assertEqual(proxy["status"], "available")
        self.assertEqual(proxy["platform"], "meituan")
        self.assertEqual(proxy["own_orders_proxy"], 22)
        self.assertAlmostEqual(
            proxy["current_estimated_market_orders"],
            242,
        )
        self.assertAlmostEqual(
            proxy["current_estimated_market_share"],
            22 / 242,
        )
        self.assertEqual(proxy["share_status"], "normal")
        self.assertEqual(
            proxy["market_projection"]["status"],
            "likely_above_history",
        )
        self.assertTrue(proxy["gross_orders_not_net_of_cancellation"])

    def test_partial_day_metrics_gain_directional_pace_analysis(self):
        dynamic = {
            "browse": {"current": 297, "baseline_median": 415},
            "first_conversion": {
                "current": 0.119,
                "baseline_median": 0.084,
                "exposure_users": 2496,
                "browse_users": 297,
            },
            "second_conversion": {
                "current": 0.04,
                "baseline_median": 0.067,
                "browse_users": 297,
                "pay_orders": 12,
            },
        }
        pace = build_platform_pace_insights(
            dynamic,
            target_date="2026-08-04",
            as_of_datetime="2026-08-04 18:57:00",
        )
        self.assertEqual(pace["platform"], "meituan")
        self.assertEqual(
            pace["browse_projection"]["status"],
            "likely_below_history",
        )
        self.assertTrue(pace["browse_projection"]["linear_projection_only"])
        self.assertEqual(
            pace["first_conversion_trend"]["status"],
            "currently_above_history",
        )
        self.assertEqual(
            pace["second_conversion_trend"]["status"],
            "currently_below_history",
        )
        self.assertGreater(
            pace["second_conversion_trend"][
                "additional_orders_needed_to_match_history"
            ],
            0,
        )
        self.assertTrue(pace["not_hourly_baseline"])
        self.assertFalse(pace["automatic_action_eligible"])

    def test_browse_projection_uses_similar_day_same_hour_completion_ratio(self):
        repository = HourlyHistoryRepository()
        dynamic = {
            "browse": {"current": 120, "baseline_median": 250},
            "first_conversion": {},
            "second_conversion": {},
        }
        pace = build_platform_pace_insights(
            dynamic,
            target_date="2026-08-18",
            as_of_datetime="2026-08-18 13:20:00",
            repository=repository,
            hotel_id="puyue",
        )

        projection = pace["browse_projection"]
        self.assertAlmostEqual(projection["projected_full_day"], 300)
        self.assertEqual(projection["status"], "likely_above_history")
        self.assertFalse(projection["linear_projection_only"])
        self.assertEqual(
            pace["projection_method"],
            "hourly_completion_ratio_with_linear_fallback",
        )
        self.assertEqual(len(repository.calls), 1)
        _, params = repository.calls[0]
        self.assertEqual(
            params,
            ("puyue", "2026-06-19", "2026-08-18", "INTENTION_UV"),
        )

    @patch("runtime.sales_progress.calendar.load_calendar_contexts")
    def test_hourly_projection_reuses_calendar_tag_date_selector(self, load_contexts):
        load_contexts.return_value = {
            "2026-08-18": {
                "season_tag": "平季",
                "is_holiday": 0,
                "is_workday": 1,
            },
            "2026-08-11": {
                "season_tag": "旺季",
                "is_holiday": 0,
                "is_workday": 1,
            },
            "2026-08-17": {
                "season_tag": "平季",
                "is_holiday": 0,
                "is_workday": 1,
            },
        }
        pace = build_platform_pace_insights(
            {
                "browse": {"current": 120, "baseline_median": 250},
                "first_conversion": {},
                "second_conversion": {},
            },
            target_date="2026-08-18",
            as_of_datetime="2026-08-18 13:20:00",
            repository=HourlyHistoryRepository(),
            hotel_id="puyue",
        )

        self.assertAlmostEqual(
            pace["browse_projection"]["projected_full_day"],
            150,
        )
        self.assertFalse(pace["browse_projection"]["linear_projection_only"])
        load_contexts.assert_called_once_with(
            load_contexts.call_args.args[0],
            "2026-06-19",
            "2026-08-18",
            "2026-08-18",
        )

    def test_room_pace_and_activity_net_reference_create_both_advisory_directions(self):
        dynamic = {
            "room_structure": {
                "room_type_results": [
                    {
                        "room_type_id": "py05",
                        "room_type_name": "开黑双床",
                        "sales_status": "significant_slow",
                        "total_rooms": 6,
                        "committed_sold": 1,
                    },
                    {
                        "room_type_id": "py03",
                        "room_type_name": "至臻双床",
                        "sales_status": "significant_fast",
                        "total_rooms": 5,
                        "committed_sold": 4,
                    },
                ]
            },
            "product_prices": [
                {
                    "product_type": "普通全天房",
                    "room_type_id": "py05",
                    "room_type_name": "开黑双床",
                    "ota_product_id": "1146760259",
                    "ota_product_name": "荣耀开黑双床房",
                    "raw_price": 463,
                    "commission_rate": 0.12,
                    "combined_activity_factor": 0.385124,
                    "estimated_activity_net_price": 156.915,
                },
                {
                    "product_type": "普通全天房",
                    "room_type_id": "py03",
                    "room_type_name": "至臻双床",
                    "ota_product_id": "1146773770",
                    "ota_product_name": "至臻电竞双床房",
                    "raw_price": 437,
                    "commission_rate": 0.12,
                    "combined_activity_factor": 0.385124,
                    "estimated_activity_net_price": 148.103,
                },
            ],
        }
        package = {
            "room_type_transaction_references": [
                {
                    "room_type_id": "py05",
                    "p20": 110,
                    "median": 120,
                    "p80": 159,
                },
                {
                    "room_type_id": "py03",
                    "p20": 100,
                    "median": 120,
                    "p80": 132.3,
                },
            ]
        }
        advisories = build_price_advisories(dynamic, package)
        self.assertEqual(len(advisories), 2)
        decrease = next(
            item
            for item in advisories
            if item["action_type"]
            == "estimated_price_decrease_advisory"
        )
        increase = next(
            item
            for item in advisories
            if item["action_type"]
            == "estimated_price_increase_advisory"
        )
        self.assertEqual(decrease["ota_product_id"], "1146760259")
        self.assertAlmostEqual(
            decrease["current_activity_net_estimate"],
            156.915 * 0.85,
        )
        self.assertLess(decrease["suggested_raw_price"], 463)
        self.assertGreaterEqual(decrease["suggested_change_pct"], -0.05)
        self.assertEqual(increase["ota_product_id"], "1146773770")
        self.assertAlmostEqual(
            increase["current_activity_net_estimate"],
            148.103 * 0.85,
        )
        self.assertEqual(increase["suggested_raw_price"], 450)
        self.assertGreater(increase["suggested_raw_price"], 437)
        self.assertLessEqual(increase["suggested_change_pct"], 0.05)
        for item in advisories:
            self.assertEqual(item["platform"], "meituan")
            self.assertTrue(item["advisory_only"])
            self.assertFalse(item["auto_execution_eligible"])
            self.assertEqual(item["handoff_capability"], "S5")

    def test_public_message_replaces_blind_period_mismatch_with_meituan_trends(self):
        base = (
            "S16 进度偏差诊断｜2026-08-04\n"
            "\n四、原因判断\n"
            "- 大盘：暂不可判断；当前估算 — 单，历史中位 276.9 单。\n"
            "- 份额：暂不可判断；当前估算 —，历史中位 9.6%。\n"
            "- 浏览：当前与历史统计周期不同；当前 297，历史中位 415。\n"
            "- 一转：当前与历史统计周期不同；当前 11.9%，历史中位 8.4%。\n"
            "- 二转：当前与历史统计周期不同；当前 4.0%，历史中位 6.7%。\n"
            "\n五、建议动作\n"
            "- 当前不生成动作候选。"
        )
        dynamic = {
            "meituan_market_proxy": {
                "status": "available",
                "current_estimated_market_orders": 251.9,
                "own_orders_proxy": 22,
                "peer_average_orders": 12.1,
                "peer_hotel_count": 20,
                "baseline_market_orders": 276.9,
                "current_estimated_market_share": 0.0873,
                "baseline_market_share": 0.096,
                "share_delta_pp": -0.87,
                "market_projection": {
                    "projected_full_day": 319,
                    "status": "likely_above_history",
                },
            },
            "meituan_pace_insights": {
                "browse_projection": {
                    "projected_full_day": 376,
                    "status": "likely_below_history",
                },
                "first_conversion_trend": {
                    "status": "currently_above_history"
                },
                "second_conversion_trend": {
                    "status": "currently_below_history",
                    "additional_orders_needed_to_match_history": 14,
                },
            },
            "browse": {"current": 297, "baseline_median": 415},
            "first_conversion": {
                "current": 0.119,
                "baseline_median": 0.084,
            },
            "second_conversion": {
                "current": 0.04,
                "baseline_median": 0.067,
            },
            "estimated_price_advisories": [
                {
                    "action_type": "estimated_price_decrease_advisory",
                    "ota_product_id": "1146760259",
                    "ota_product_name": "荣耀开黑双床房",
                    "current_raw_price": 463,
                    "suggested_raw_price": 440,
                    "suggested_change_pct": -0.05,
                    "current_activity_net_estimate": 133,
                    "pms_transaction_median_reference": 120,
                    "observe_minutes": 90,
                }
            ],
        }
        render = _message_wrapper(lambda report: base)
        text = render({"dynamic_diagnosis": dynamic})
        self.assertNotIn("大盘：暂不可判断", text)
        self.assertIn("美团大盘（估算）", text)
        self.assertIn("美团估算份额", text)
        self.assertIn("美团浏览", text)
        self.assertIn("有望跑赢历史", text)
        self.assertIn("会员预期折扣后预计酒店收入", text)
        self.assertIn("试探降价", text)
        self.assertIn("不自动执行", text)

    def test_public_message_preserves_zero_authoritative_own_orders(self):
        base = "S16\n\n四、原因判断\n- 大盘：旧\n\n五、建议动作"
        dynamic = {
            "meituan_market_proxy": {
                "status": "available",
                "current_estimated_market_orders": 55.1,
                "own_orders": 0,
                "peer_average_orders": 2.9,
                "peer_hotel_count": 20,
                "baseline_market_orders": 278.6,
                "current_estimated_market_share": 0.0,
                "baseline_market_share": 0.086,
                "share_delta_pp": -8.6,
                "market_projection": {
                    "projected_full_day": 112.0,
                    "status": "likely_below_history",
                },
            }
        }
        render = _message_wrapper(lambda report: base)
        text = render({"dynamic_diagnosis": dynamic})
        self.assertIn("本店今日美团订单代理 0单", text)
        self.assertNotIn("本店今日美团订单代理 —单", text)


if __name__ == "__main__":
    unittest.main()

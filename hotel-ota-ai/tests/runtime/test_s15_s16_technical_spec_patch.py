from __future__ import annotations

import unittest

from runtime import s15_platform_reference as platform_reference
from runtime import s15_s16_compact_output_patch as compact_patch
from runtime import s15_s16_technical_spec_patch as technical_patch
from runtime import s15_technical_decision as decision
from runtime import s15_technical_sources as sources


class S15S16TechnicalSpecPatchTest(unittest.TestCase):
    def test_market_estimate_uses_rank_denominator_as_peer_population(
        self,
    ) -> None:
        point = sources._market_point(
            {
                "FLOW_PAY_ORDER_CNT": {
                    "metric_value": 22,
                    "peer_average": 12.1,
                    "competitor_rank": "3/20",
                }
            }
        )
        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point["estimated_market_orders"], 242)
        self.assertAlmostEqual(
            point["estimated_market_share"],
            22 / 242,
        )
        self.assertTrue(point["estimated"])
        self.assertEqual(
            point["estimation_method"],
            "peer_average_times_peer_hotel_count",
        )

    def test_daily_platform_reference_filters_same_weekday(self) -> None:
        rows = []
        for day, browse in (
            ("2026-07-13", 80),
            ("2026-07-20", 100),
            ("2026-07-27", 120),
            ("2026-07-28", 999),
        ):
            rows.append(
                {
                    "business_date": day,
                    "metric_code": "FLOW_INTENTION_UV",
                    "metric_value": browse,
                    "metric_unit": "人",
                }
            )
        result = platform_reference.build_platform_reference(
            rows,
            target_date="2026-08-03",
        )
        self.assertEqual(
            result["selected_tier"],
            "M4_same_weekday_daily",
        )
        self.assertEqual(result["selected_sample_days"], 3)
        self.assertEqual(
            result["baselines"]["browse_uv"]["median"],
            100,
        )
        self.assertFalse(result["hourly_baseline_available"])

    def test_browse_weak_prefers_ad_candidate_before_price(self) -> None:
        diagnosis, actions = decision._diagnose_and_actions(
            {
                "sales": {
                    "status": "slow",
                    "sales_progress_delta_pp": -12,
                },
                "market": {"status": "normal"},
                "market_share": {"delta_pp": -4},
                "browse": {"status": "weak"},
                "first_conversion": {"status": "normal"},
                "second_conversion": {"is_weak": False},
                "price": {"high_room_type_ids": ["py01"]},
                "ad_context": {"ad_running": False},
            }
        )
        self.assertIn("traffic_insufficient", diagnosis)
        self.assertEqual(
            actions[0]["action_type"],
            "suggest_enable_ad_slot",
        )
        self.assertFalse(actions[0]["auto_executable"])

    def test_ad_candidate_requires_at_least_ten_pp_sales_lag(
        self,
    ) -> None:
        _, actions = decision._diagnose_and_actions(
            {
                "sales": {
                    "status": "slow",
                    "sales_progress_delta_pp": -9,
                },
                "market": {"status": "normal"},
                "market_share": {"delta_pp": -4},
                "browse": {"status": "weak"},
                "first_conversion": {"status": "normal"},
                "second_conversion": {"is_weak": False},
                "price": {"high_room_type_ids": []},
                "ad_context": {"ad_running": False},
            }
        )
        self.assertEqual(
            actions[0]["action_type"],
            "investigate_traffic_before_spend",
        )

    def test_market_cold_share_normal_blocks_aggressive_action(
        self,
    ) -> None:
        diagnosis, actions = decision._diagnose_and_actions(
            {
                "sales": {
                    "status": "significant_slow",
                    "sales_progress_delta_pp": -18,
                },
                "market": {"status": "cold"},
                "market_share": {"delta_pp": -1},
                "browse": {"status": "weak"},
                "first_conversion": {"status": "weak"},
                "second_conversion": {"is_weak": True},
                "price": {"high_room_type_ids": ["py01"]},
                "ad_context": {"ad_running": False},
            }
        )
        self.assertIn("market_cold_share_not_weak", diagnosis)
        self.assertEqual(
            actions[0]["action_type"],
            "conservative_inventory_management",
        )
        self.assertFalse(actions[0]["auto_executable"])

    def test_price_candidate_requires_weak_second_conversion(
        self,
    ) -> None:
        diagnosis, actions = decision._diagnose_and_actions(
            {
                "sales": {
                    "status": "significant_slow",
                    "sales_progress_delta_pp": -18,
                },
                "market": {"status": "normal"},
                "market_share": {"delta_pp": -4},
                "browse": {"status": "normal"},
                "first_conversion": {"status": "normal"},
                "second_conversion": {"is_weak": True},
                "price": {"high_room_type_ids": ["py01", "py03"]},
                "ad_context": {"ad_running": False},
            }
        )
        self.assertIn("detail_page_conversion_weak", diagnosis)
        self.assertIn("specific_room_prices_high", diagnosis)
        self.assertEqual(
            actions[0]["action_type"],
            "suggest_room_price_reduction",
        )
        self.assertEqual(
            actions[0]["suggested_change_pct_range"],
            [-8, -5],
        )
        self.assertEqual(actions[0]["observe_minutes"], 90)
        self.assertFalse(actions[0]["auto_executable"])

    def test_s16_boundary_excludes_cross_domain_diagnosis(self) -> None:
        text = decision._strict_s16_boundary(
            "本结果只说明销售节奏和结构，不据此直接推断必然满房，"
            "也不直接生成调价或推广动作。"
        )
        self.assertIn("只判断全店销售进度和房型结构", text)
        self.assertIn("不分析经营根因", text)
        self.assertNotIn("晚间需求", text)

    def test_s15_render_declares_daily_platform_grain(self) -> None:
        text = decision.render_s15_analysis(
            {
                "operating_analysis": {
                    "sales": {
                        "status": "slow",
                        "sales_progress_delta_pp": -12,
                        "committed_sold": 10,
                        "total_rooms": 30,
                    },
                    "market": {
                        "status": "normal",
                        "estimated_market_orders": 200,
                        "baseline_estimated_market_orders": 190,
                        "market_heat_ratio": 1.05,
                    },
                    "market_share": {
                        "current_estimated_market_share": 0.05,
                        "baseline_estimated_market_share": 0.06,
                        "delta_pp": -1,
                    },
                    "browse": {
                        "status": "weak",
                        "current": 80,
                        "baseline_median": 110,
                        "ratio": 0.73,
                    },
                    "first_conversion": {
                        "status": "normal",
                        "current": 0.11,
                        "baseline_median": 0.10,
                    },
                    "second_conversion": {
                        "status": "normal",
                        "current": 0.08,
                        "baseline_p25": 0.06,
                        "conversion_index_vs_market": 0.95,
                        "is_weak": False,
                    },
                    "price": {
                        "high_room_type_ids": [],
                        "low_room_type_ids": [],
                    },
                    "diagnosis": ["traffic_insufficient"],
                    "actions": [
                        {
                            "action_type": "suggest_enable_ad_slot",
                            "observe_minutes": 60,
                        }
                    ],
                }
            }
        )
        self.assertIn(
            "销售进度 → 大盘 → 估算份额 → 浏览 → 一转 → 二转 → "
            "房型价格 → 动作",
            text,
        )
        self.assertIn("日级数据", text)
        self.assertIn("不生成小时浏览/一转/二转基准", text)
        self.assertIn("仅生成建议，不直接执行", text)

    def test_root_cause_and_cross_axis_questions_route_to_s15(self) -> None:
        for message in (
            "今天销售进度为什么落后",
            "大盘是否冷",
            "市场份额是否下降",
            "浏览是否不足",
            "一转是否弱",
            "二转是否弱",
            "价格是否偏高",
            "今天要不要开推广",
            "今天是否应该降价",
        ):
            with self.subTest(message=message):
                self.assertTrue(
                    technical_patch._should_route_to_s15(message)
                )

    def test_progress_only_questions_remain_s16(self) -> None:
        for message in (
            "当前进度",
            "还差几间",
            "各房型进度",
            "今天每小时卖了多少",
        ):
            with self.subTest(message=message):
                self.assertFalse(
                    technical_patch._should_route_to_s15(message)
                )

    def test_execution_requests_are_not_stolen_from_s5_s6_s8(self) -> None:
        for message in (
            "调价 dry-run",
            "确认执行降价",
            "推广执行预览",
            "同步房价",
            "创建调价任务",
        ):
            with self.subTest(message=message):
                self.assertFalse(
                    technical_patch._should_route_to_s15(message)
                )

    def test_compact_result_keeps_only_one_long_body(self) -> None:
        text = "完整S15经营判断"
        compact = compact_patch.remove_duplicate_summary(
            {
                "intent": "sales_baseline_demo",
                "summary": text,
                "send_payload": {"text": text},
            }
        )
        self.assertNotIn("summary", compact)
        self.assertEqual(compact["send_payload"]["text"], text)
        self.assertEqual(
            compact["summary_omitted_reason"],
            "identical_to_send_payload_text",
        )


if __name__ == "__main__":
    unittest.main()

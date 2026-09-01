from __future__ import annotations

import unittest

from runtime.s15_s16_final_convergence_patch import (
    MATURITY_POLICY_VERSION,
    add_s16_platform_order_line,
    business_followup_contract,
    cache_payload_has_policy,
    enhance_s15_message,
    layered_collector_health,
    normalize_s16_text,
    sanitize_s16_result,
)


class S15S16FinalConvergencePatchTests(unittest.TestCase):
    @staticmethod
    def _previous_health(points):
        observed = [
            point["hour"]
            for point in points
            if int(point.get("exact_sample_count") or 0) > 0
        ]
        ratio = len(observed) / 24
        maturity = (
            "trend_only"
            if ratio < 0.40
            else "weak"
            if ratio < 0.75
            else "temporary"
        )
        return {
            "collector_coverage_ratio": ratio,
            "object_maturity": maturity,
            "maturity_source": "full_history",
        }

    def test_recent_six_full_day_remains_second_layer(self) -> None:
        points = [
            {
                "hour": hour,
                "exact_sample_count": 1,
                "recent_exact_sample_count": 6,
                "recent_sample_day_count": 6,
            }
            for hour in range(15)
        ]
        health = layered_collector_health(self._previous_health, points)
        self.assertEqual(health["object_maturity"], "temporary")
        self.assertEqual(health["maturity_source"], "recent_6_samples")
        self.assertTrue(health["recent_full_day_recovered"])
        self.assertFalse(health["recent_business_sample_recovered"])

    def test_business_hours_are_third_layer_only(self) -> None:
        points = [
            {
                "hour": hour,
                "exact_sample_count": 1,
                "recent_exact_sample_count": 6,
                "recent_sample_day_count": 6,
            }
            for hour in range(9, 18)
        ]
        health = layered_collector_health(self._previous_health, points)
        self.assertAlmostEqual(health["recent_sample_coverage_ratio"], 54 / 144)
        self.assertAlmostEqual(
            health["recent_business_sample_coverage_ratio"],
            54 / 90,
        )
        self.assertFalse(health["recent_full_day_recovered"])
        self.assertTrue(health["recent_business_sample_recovered"])
        self.assertEqual(
            health["maturity_source"],
            "recent_6_business_hours",
        )
        self.assertEqual(health["object_maturity"], "temporary")

    def test_fewer_than_six_samples_cannot_recover(self) -> None:
        points = [
            {
                "hour": hour,
                "recent_exact_sample_count": 5,
                "recent_sample_day_count": 5,
            }
            for hour in range(9, 24)
        ]
        health = layered_collector_health(self._previous_health, points)
        self.assertFalse(health["recent_sample_recovered"])
        self.assertEqual(health["maturity_source"], "full_history")

    def test_s15_room_hourly_lines_precede_hotel_lines(self) -> None:
        payload = {
            "status": "ok",
            "target_date": "2026-08-06",
            "as_of_datetime": "2026-08-06T13:00:00+08:00",
            "hotel": {
                "baseline_health": {
                    "maturity_policy_version": MATURITY_POLICY_VERSION,
                    "collector_coverage_ratio": 0.366,
                    "recent_sample_coverage_ratio": 0.292,
                    "recent_business_sample_coverage_ratio": 0.60,
                    "object_maturity": "temporary",
                    "maturity_source": "recent_6_business_hours",
                },
                "hourly_points": [
                    {
                        "hour": 9,
                        "capacity": {"median": 0.20, "sample_count": 6},
                        "target_completion": {
                            "median": 0.25,
                            "sample_count": 6,
                        },
                        "exact_sample_count": 5,
                        "fallback_sample_count": 1,
                    }
                ],
            },
            "room_types": {
                "r1": {
                    "room_type_name": "测试房型",
                    "hourly_points": [
                        {
                            "hour": 9,
                            "capacity": {"median": 0.20, "sample_count": 6},
                            "target_completion": {
                                "median": 0.25,
                                "sample_count": 6,
                            },
                            "exact_sample_count": 5,
                            "fallback_sample_count": 1,
                        }
                    ],
                }
            },
        }
        base = "\n".join(
            [
                "S15 销售基准线｜2026-08-06",
                "",
                "一、最终销售目标",
                "",
                "二、全店小时销售基准",
                "- 09:00：最终目标完成中位 25.0%；容量消化中位 20.0%；样本 6天。",
                "",
                "三、平台历史基准",
                "",
                "四、价格参考",
                "",
                "五、样本与边界",
            ]
        )
        text = enhance_s15_message(lambda _: base, payload)
        self.assertLess(
            text.index("二、全部房型小时销售进度"),
            text.index("三、全店小时销售基准"),
        )
        self.assertIn("精5+回1", text)
        self.assertIn(
            "统计样本 6天，其中精确小时 5天、fallback 1天",
            text,
        )
        self.assertIn("最近6样本营业时段覆盖 60.0%", text)

    def test_s16_proxy_terms_and_aliases_are_removed(self) -> None:
        text = normalize_s16_text(
            "大盘约100单，本店代理13单；使用本店 PMS 订单代理。"
        )
        self.assertIn("本店美团支付订单13单", text)
        self.assertNotIn("PMS 订单代理", text)

        cleaned = sanitize_s16_result(
            {
                "dynamic_diagnosis": {
                    "meituan_market_proxy": {
                        "status": "available",
                        "own_orders": 13,
                        "own_orders_proxy": 13,
                        "own_order_proxy_source": "legacy",
                        "own_order_source": (
                            "meituan_ota_business_metrics.FLOW_PAY_ORDER_CNT"
                        ),
                    },
                    "data_limitations": ["使用本店 PMS 订单代理"],
                }
            }
        )
        proxy = cleaned["dynamic_diagnosis"]["meituan_market_proxy"]
        self.assertNotIn("own_orders_proxy", proxy)
        self.assertNotIn("own_order_proxy_source", proxy)
        self.assertEqual(proxy["own_order_label"], "本店美团支付订单")
        self.assertFalse(proxy["pms_or_jd01_fallback_used"])

    def test_s16_authoritative_text_includes_platform_order_line(self) -> None:
        report = {
            "dynamic_diagnosis": {
                "meituan_market_proxy": {
                    "status": "available",
                    "own_orders": 13,
                    "peer_average_orders": 5.3,
                    "peer_hotel_count": 20,
                    "own_order_snapshot_time": "2026-08-06 13:00:00",
                    "hourly_collection_may_lag": True,
                }
            }
        }
        text = add_s16_platform_order_line(
            "S16\n\n四、原因判断\n- 大盘：正常。",
            report,
        )
        self.assertIn("本店支付订单 13单", text)
        self.assertIn("同行平均 5.3单/店", text)
        self.assertIn("约1小时采集延迟", text)

    def test_followup_contract_blocks_engineering_internals(self) -> None:
        contract = business_followup_contract()
        self.assertEqual(contract["mode"], "business_followup_only")
        rules = " ".join(contract["rules"])
        self.assertIn("代码文件名", rules)
        self.assertIn("提交号", rules)
        self.assertIn("只解释酒店经营结果", rules)

    def test_cache_requires_new_maturity_policy(self) -> None:
        self.assertFalse(
            cache_payload_has_policy(
                {"hotel": {"baseline_health": {}}}
            )
        )
        self.assertTrue(
            cache_payload_has_policy(
                {
                    "hotel": {
                        "baseline_health": {
                            "maturity_policy_version": MATURITY_POLICY_VERSION
                        }
                    }
                }
            )
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from runtime.s15_s16_advisory_boundary_patch import allow_advisory_s16
from runtime.s15_s16_template_advisory_patch import (
    _percent_value,
    advisory_output_contract,
    append_complete_s15_families,
)


class S15S16TemplateAdvisoryPatchTests(unittest.TestCase):
    def test_complete_s15_appends_all_available_families(self) -> None:
        text = append_complete_s15_families(
            "【全店小时节奏】\n...\n\n【房型基准｜当前时点】\n...\n\n【平台流量与转化】\n...\n\n口径说明",
            {
                "peer_demand_proxy": {
                    "points": [
                        {
                            "metric_name": "预订订单量",
                            "metric_unit": "order",
                            "period_start_date": "2026-06-27",
                            "period_end_date": "2026-07-26",
                            "hotel_value": 35,
                            "competitor_avg": 585.87,
                            "competitor_rank": 23,
                            "competition_circle_hotel_count": 24,
                        }
                    ]
                },
                "rolling_30d_context": {
                    "meituan": [
                        {
                            "period_start_date": "2026-07-05",
                            "period_end_date": "2026-08-03",
                            "snapshot_time": "2026-08-03 18:52:35",
                            "exposure_uv": 138490,
                            "browse_uv": 11944,
                            "pay_order_count": 865,
                            "exposure_to_browse_rate_pct": 8.62,
                            "browse_to_pay_rate_pct": 7.24,
                            "peer_exposure_to_browse_rate_pct": 10.22,
                            "peer_browse_to_pay_rate_pct": 8.05,
                            "exposure_peer_rank": "2/20",
                        }
                    ]
                },
                "gross_booking_created_curve_context": {
                    "points": [
                        {
                            "stay_date": "2026-07-20",
                            "booking_hour": 20,
                            "gross_created_rooms": 3,
                        }
                    ]
                },
                "gross_order_hour_distribution_context": {
                    "points": [
                        {"bucket_label": "20-22", "rate_pct": 31.5}
                    ]
                },
                "unavailable_baseline_families": {
                    "market_orders_baseline": "source_semantic_unavailable"
                },
            },
        )
        self.assertIn("【同行需求代理】", text)
        self.assertIn("预订订单量", text)
        self.assertIn("【30日滚动背景】", text)
        self.assertIn("【订单创建曲线背景】", text)
        self.assertIn("【平台订单时段分布】", text)
        self.assertIn("【数据边界】", text)
        self.assertLess(text.index("【同行需求代理】"), text.index("口径说明"))

    def test_contract_allows_advice_but_not_execution(self) -> None:
        contract = advisory_output_contract({"intent": "sales_baseline_demo"})
        self.assertTrue(contract["ai_analysis_allowed"])
        self.assertIn("晚间剩余需求推断", contract["advisory_analysis_allowed"])
        self.assertIn("调价建议", contract["advisory_analysis_allowed"])
        self.assertIn("推广建议", contract["advisory_analysis_allowed"])
        self.assertIn("不得自动创建调价或推广任务", contract["advisory_requirements"])
        self.assertTrue(contract["must_preserve_all_available_sections"])

    def test_s16_boundary_allows_advice(self) -> None:
        source = (
            "边界  只判断销售节奏与房型结构；"
            "不推断晚间剩余需求，不自动生成调价或推广建议。"
        )
        result = allow_advisory_s16(source)
        self.assertIn("可基于当前节奏", result)
        self.assertIn("建议不等于自动执行", result)
        self.assertNotIn("不推断晚间剩余需求", result)

    def test_percent_format_accepts_ratio_and_percent_points(self) -> None:
        self.assertEqual(_percent_value(0.0193), "1.9%")
        self.assertEqual(_percent_value(1.93), "1.9%")
        self.assertEqual(_percent_value(8.62), "8.6%")


if __name__ == "__main__":
    unittest.main()

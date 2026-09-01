from __future__ import annotations

import unittest

from runtime.meituan_activity_net_price_output_patch import (
    append_remaining_products,
    render_product_activity_net_line,
)
from runtime.meituan_activity_net_price_patch import _price_analysis_wrapper


class MeituanActivityNetPriceOutputTests(unittest.TestCase):
    def _product(self, index: int) -> dict[str, object]:
        return {
            "product_type": "普通全天房",
            "ota_product_id": f"P{index}",
            "ota_product_name": f"商品{index}",
            "raw_price": 358,
            "commission_rate": 0.12,
            "commission_net_base_price": 315.04,
            "matched_activity_count": 2,
            "applied_activities": [
                {"activity_name": "天天特价", "discount_factor": 0.8},
                {"activity_name": "首住折扣", "discount_factor": 0.94},
            ],
            "combined_activity_factor": 0.752,
            "estimated_activity_net_price": 236.91008,
        }

    def test_business_output_contains_commission_and_compounded_factors(self) -> None:
        line = render_product_activity_net_line(self._product(1))
        self.assertIn("美团底价 ¥358", line)
        self.assertIn("扣佣金率 12.0% 后底价 ¥315", line)
        self.assertIn("匹配 2 个活动", line)
        self.assertIn("系数 0.80 × 0.94 连续相乘", line)
        self.assertIn("活动后预计酒店收入 ¥237", line)
        self.assertIn("不含用户券", line)

    def test_all_products_after_first_five_are_rendered(self) -> None:
        report = {
            "dynamic_diagnosis": {
                "product_prices": [self._product(index) for index in range(1, 8)]
            }
        }
        text = append_remaining_products(
            "四、原因判断\n前五个已输出\n\n五、建议动作",
            report,
        )
        self.assertIn("其余美团商品", text)
        self.assertIn("商品6", text)
        self.assertIn("商品7", text)
        self.assertLess(text.index("商品7"), text.index("五、建议动作"))

    def test_activity_net_reference_cannot_generate_price_action_evidence(self) -> None:
        def previous(payload: object, rows: object) -> dict[str, object]:
            return {
                "room_results": [
                    {
                        "room_type_id": "py08",
                        "ota_product_id": "P1",
                        "baseline_median": 122,
                        "price_status": "high",
                        "action_eligible": True,
                        "product_results": [
                            {
                                "ota_product_id": "P1",
                                "price_status": "high",
                                "action_eligible": True,
                            }
                        ],
                    }
                ],
                "high_room_type_ids": ["py08"],
                "low_room_type_ids": [],
            }

        analyze = _price_analysis_wrapper(previous)
        result = analyze(
            {},
            [
                {
                    "ota_product_id": "P1",
                    "ota_sale_price": 358,
                    "commission_rate_normalized": 0.12,
                    "commission_net_base_price": 315.04,
                    "matched_activity_count": 2,
                    "combined_activity_factor": 0.752,
                    "estimated_activity_net_price": 236.91008,
                    "applied_activities": [
                        {"activity_name": "天天特价", "discount_factor": 0.8},
                        {"activity_name": "首住折扣", "discount_factor": 0.94},
                    ],
                }
            ],
        )
        self.assertEqual(result["price_evidence_level"], "reference_only")
        self.assertEqual(result["high_room_type_ids"], [])
        self.assertEqual(result["action_eligible_product_ids"], [])
        room = result["room_results"][0]
        self.assertFalse(room["action_eligible"])
        product = room["product_results"][0]
        self.assertFalse(product["comparison_allowed"])
        self.assertFalse(product["action_eligible"])
        self.assertEqual(product["price_status"], "reference_only")


if __name__ == "__main__":
    unittest.main()

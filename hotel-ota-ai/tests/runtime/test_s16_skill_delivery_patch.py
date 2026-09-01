from __future__ import annotations

import unittest

from runtime.s16_skill_delivery_patch import apply_s16_delivery_contract


class S16SkillDeliveryPatchTest(unittest.TestCase):
    def test_s16_allows_one_skill_guided_analysis_with_fallback(self):
        result = {
            "intent": "progress_deviation_demo",
            "dynamic_diagnosis": {
                "room_structure": {
                    "room_type_results": [
                        {"room_type_id": "R1", "sales_status": "slow"},
                        {"room_type_id": "R2", "sales_status": "normal"},
                    ]
                }
            },
        }
        rendered, send = apply_s16_delivery_contract(
            result,
            {"text": "权威正文", "must_send_text_verbatim": True},
            {"text": "权威正文", "must_send_text_verbatim": True},
        )
        self.assertTrue(send["ai_analysis_allowed"])
        self.assertTrue(send["ai_rewrite_allowed"])
        self.assertFalse(send["must_send_text_verbatim"])
        self.assertEqual(send["authoritative_fallback_text"], "权威正文")
        contract = send["assistant_response_contract"]
        self.assertEqual(contract["maximum_runtime_tool_calls"], 1)
        self.assertFalse(contract["second_analysis_pass_allowed"])
        self.assertEqual(contract["all_room_type_ids"], ["R1", "R2"])
        self.assertEqual(contract["room_type_count"], 2)
        self.assertTrue(contract["must_preserve_all_room_types"])
        self.assertEqual(contract["anomalous_room_type_ids"], ["R1"])
        self.assertTrue(rendered["ai_analysis_allowed"])

    def test_s16_market_contract_forbids_cross_day_and_calls_same_batch_a_supplement(self):
        _, send = apply_s16_delivery_contract(
            {
                "intent": "progress_deviation_demo",
                "dynamic_diagnosis": {"room_structure": {"room_type_results": []}},
            },
            {"text": "权威正文"},
            {"text": "权威正文"},
        )

        contract = send["assistant_response_contract"]
        preserve = "\n".join(contract["must_preserve"])
        forbidden = "\n".join(contract["forbidden"])
        allowed = "\n".join(contract["allowed"])

        self.assertIn("PAY_ORDER_CNT全字段优先", preserve)
        self.assertIn("同业务日同snapshot_time", preserve)
        self.assertIn("其它美团指标competitor_rank的共同分母", preserve)
        self.assertIn("绝不跨业务日取数", preserve)
        self.assertIn("同日同批次FLOW/其它指标仅用于补充缺失单元格", allowed)
        self.assertIn("描述成回退、兜底、降级或借用历史数据", forbidden)
        self.assertIn("上一业务日、昨天、历史日", forbidden)
        self.assertIn("当前同批次关键字段不足时静默借用其它日期", forbidden)

    def test_s16_room_structure_contract_keeps_all_nine_rooms(self):
        room_rows = [
            {
                "room_type_id": f"R{index}",
                "room_type_name": f"房型{index}",
                "sales_status": "slow" if index == 6 else "normal",
                "committed_sold": 0 if index in {7, 8, 9} else index,
                "total_rooms": 1,
            }
            for index in range(1, 10)
        ]
        _, send = apply_s16_delivery_contract(
            {
                "intent": "progress_deviation_demo",
                "dynamic_diagnosis": {
                    "room_structure": {"room_type_results": room_rows}
                },
            },
            {"text": "权威正文"},
            {"text": "权威正文"},
        )

        contract = send["assistant_response_contract"]
        self.assertEqual(
            contract["all_room_type_ids"],
            [f"R{index}" for index in range(1, 10)],
        )
        self.assertEqual(contract["room_type_count"], 9)
        self.assertEqual(contract["anomalous_room_type_ids"], ["R6"])
        self.assertTrue(contract["must_preserve_all_room_types"])
        self.assertTrue(
            any(
                "省略正常" in item
                for item in contract["forbidden"]
            )
        )
        self.assertTrue(
            any(
                "全部房型" in item
                for item in contract["must_preserve"]
            )
        )

    def test_s15_delivery_remains_unchanged(self):
        rendered, send = apply_s16_delivery_contract(
            {"intent": "sales_baseline_demo"},
            {"text": "S15", "must_send_text_verbatim": True},
            {"text": "S15", "must_send_text_verbatim": True},
        )
        self.assertTrue(send["must_send_text_verbatim"])
        self.assertNotIn("assistant_response_contract", send)
        self.assertTrue(rendered["must_send_text_verbatim"])


if __name__ == "__main__":
    unittest.main()

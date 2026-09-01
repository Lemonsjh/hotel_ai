from __future__ import annotations

import unittest

from runtime.feishu_command_router import _detect_intent
from runtime.s5_route_restore_patch import is_direct_s5_pricing_request
from runtime.s16_skill_delivery_patch import build_s16_response_contract


class S5RouteRestorePatchTest(unittest.TestCase):
    def test_direct_pricing_questions_route_to_s5(self) -> None:
        for message in (
            "需要调价吗？",
            "今天是否需要调价",
            "现在调价吗",
            "调不调价",
            "要不要涨价",
            "该涨还是该降",
            "哪些房型需要调价",
        ):
            with self.subTest(message=message):
                self.assertTrue(is_direct_s5_pricing_request(message))
                self.assertEqual(_detect_intent(message), "revenue_decision")

    def test_diagnosis_question_stays_in_s16(self) -> None:
        message = "为什么销售落后，是不是价格导致的？"
        self.assertFalse(is_direct_s5_pricing_request(message))
        self.assertEqual(_detect_intent(message), "progress_deviation_demo")

    def test_execution_preview_is_not_intercepted(self) -> None:
        message = "调价 dry-run"
        self.assertFalse(is_direct_s5_pricing_request(message))
        self.assertEqual(_detect_intent(message), "price_execution_dry_run")

    def test_s16_contract_forbids_redirect_only_reply(self) -> None:
        contract = build_s16_response_contract(
            {"intent": "progress_deviation_demo", "dynamic_diagnosis": {}}
        )
        forbidden = "\n".join(contract["forbidden"])
        self.assertIn("请改问S5", forbidden)
        self.assertFalse(contract["routing_boundary"]["redirect_only_reply_allowed"])


if __name__ == "__main__":
    unittest.main()

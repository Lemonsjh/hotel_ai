from __future__ import annotations

import unittest

from runtime.feishu_output_renderer import _context


class TestExposureConversionContext(unittest.TestCase):
    def test_context_surfaces_exposure_unit_and_conversion_basis(self) -> None:
        # R5:曝光单位与支付转化率口径必须能透到渲染上下文,供展示标注(次/人、view_to_payment)。
        result = {
            "exposure": 1085,
            "exposure_unit": "人",
            "exposure_metric_name": "曝光人数",
            "payment_conversion_rate": 0.0012,
            "payment_conversion_rate_basis": "view_to_payment",
        }
        ctx = _context(result)
        self.assertEqual(ctx["exposure"], 1085)
        self.assertEqual(ctx["exposure_unit"], "人")
        self.assertEqual(ctx["payment_conversion_rate_basis"], "view_to_payment")


if __name__ == "__main__":
    unittest.main()

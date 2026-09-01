from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v11 import _manual_card


class ManualCrownInputTest(unittest.TestCase):
    def test_manual_card_contains_input_and_local_storage(self):
        html = _manual_card(
            {
                "hotel_id": "puyue",
                "hotel_name": "璞悦·奢电竞酒店(贵阳花溪公园店)",
                "period_start": "2026-06-15",
                "period_end": "2026-07-14",
            }
        )

        self.assertIn("id='crown-type-input'", html)
        self.assertIn("id='crown-operator-input'", html)
        self.assertIn("id='crown-time-input'", html)
        self.assertIn("保存录入", html)
        self.assertIn("localStorage.setItem", html)
        self.assertIn("已人工录入", html)
        self.assertIn("当前浏览器本地保存", html)
        self.assertNotIn("挂冠类型</small><strong>暂无数据", html)


if __name__ == "__main__":
    unittest.main()

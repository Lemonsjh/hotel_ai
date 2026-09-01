from __future__ import annotations

import unittest

from marketing_diagnosis.reporting_v17 import _compact_overview, _pair_cards


class CompactOverviewAndPairTest(unittest.TestCase):
    def test_overview_only_keeps_period_and_total_score(self) -> None:
        html = _compact_overview(
            {
                "period_start": "2026-06-16",
                "period_end": "2026-07-15",
                "visual_diagnosis": {
                    "normalized_score": 58.8,
                    "raw_score": 39.4,
                    "connected_base_score": 67.0,
                    "rule_version": "internal-version",
                },
            }
        )

        self.assertIn("总得分", html)
        self.assertIn("58.8", html)
        self.assertIn("2026-06-16 至 2026-07-15", html)
        self.assertNotIn("数据库核验", html)
        self.assertNotIn("规则版本", html)
        self.assertNotIn("折算得分", html)
        self.assertNotIn("原始得分", html)
        self.assertNotIn("已接入基础分", html)
        self.assertNotIn("未取到数据", html)

    def test_cards_7_and_8_are_wrapped_in_one_two_column_container(self) -> None:
        source = (
            "<main>"
            "<article class='diagnosis-card' data-status='success' id='rule-7'><div>七</div></article>"
            "<article class='diagnosis-card' data-status='success' id='rule-8'><div>八</div></article>"
            "</main>"
        )
        html = _pair_cards(source)

        self.assertIn("diagnosis-pair-v17", html)
        self.assertEqual(html.count("id='rule-7'"), 1)
        self.assertEqual(html.count("id='rule-8'"), 1)
        self.assertLess(html.index("id='rule-7'"), html.index("id='rule-8'"))


if __name__ == "__main__":
    unittest.main()

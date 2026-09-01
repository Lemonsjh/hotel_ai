import unittest

from marketing_diagnosis.reporting_v3 import build_html


class ReportHtmlTests(unittest.TestCase):
    def setUp(self):
        self.result = {
            "hotel_name": "测试酒店",
            "platform": "multi",
            "period_start": "2026-06-01",
            "period_end": "2026-06-30",
            "final_score": 82,
            "score_before_cap": 86,
            "cap_score": 90,
            "risk_level": "medium",
            "metrics": {},
            "data_quality": {},
            "module_scores": [],
            "rule_hits": [],
            "ai_analysis": {"overview": ["这段内容不应进入 HTML"]},
        }

    def test_uses_green_reference_theme(self):
        report = build_html(self.result)
        self.assertIn("酒店经营与线上运营综合诊断", report)
        self.assertIn("class='hero", report)
        self.assertIn("class='diagnosis-card'", report)
        self.assertIn("23项诊断结果总览", report)

    def test_does_not_render_ai_analysis(self):
        report = build_html(self.result)
        self.assertNotIn("AI", report)
        self.assertNotIn("这段内容不应进入 HTML", report)
        self.assertNotIn("整改动作", report)


if __name__ == "__main__":
    unittest.main()

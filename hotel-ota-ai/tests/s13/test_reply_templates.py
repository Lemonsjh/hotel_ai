from __future__ import annotations

import unittest

from runtime.s13.contracts import ReviewRecord
from runtime.s13.policy import build_candidate


def _record(content: str | None, rating: float, *, source_negative: bool | None = None) -> ReviewRecord:
    return ReviewRecord("hotel-a", "meituan", "review-1", content, rating, False, "2026-08-04T10:00:00+08:00", is_negative_review=source_negative)


class ReplyTemplateTests(unittest.TestCase):
    def test_positive_five_star_uses_warm_positive_template(self) -> None:
        candidate = build_candidate(_record("环境很好，服务热情", 5))
        self.assertEqual(candidate["template_key"], "positive_review")
        self.assertEqual(candidate["tone"], "warm")
        self.assertIn("认可", candidate["draft"])

    def test_five_star_with_complaint_uses_apology_template(self) -> None:
        candidate = build_candidate(_record("五星，但卫生一般，淋浴不舒服", 5))
        self.assertEqual(candidate["template_key"], "high_rating_negative_feedback")
        self.assertEqual(candidate["tone"], "apologetic")
        self.assertIn("抱歉", candidate["draft"])
        self.assertIn("卫生", candidate["draft"])

    def test_source_negative_overrides_high_star_positive_opening(self) -> None:
        candidate = build_candidate(_record("整体尚可", 5, source_negative=True))
        self.assertEqual(candidate["template_key"], "high_rating_negative_feedback")
        self.assertIn("抱歉", candidate["draft"])

    def test_low_score_uses_negative_template(self) -> None:
        candidate = build_candidate(_record("前台响应太慢", 2))
        self.assertEqual(candidate["template_key"], "negative_review")
        self.assertEqual(candidate["tone"], "apologetic")
        self.assertIn("未达到您的预期", candidate["draft"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from runtime.algorithms.s5_decision_context import build_s5_decision_context
from runtime.business_context_resolver import resolve_business_context


class TestS5TimeAwareContext(unittest.TestCase):
    def test_s5_uses_explicit_time_context_without_legacy_progress_trend(self) -> None:
        context = resolve_business_context(mode="demo", as_of_time="16:40")
        decision = build_s5_decision_context(context)

        self.assertEqual(decision["as_of_time"], "16:40")
        self.assertEqual(decision["traffic_timing_context"]["as_of_time"], "16:40")
        self.assertNotIn("progress_trend_status", decision)
        self.assertNotIn("progress_trend", decision["business_pressure_context"])

    def test_s5_without_time_context_is_partial(self) -> None:
        context = resolve_business_context(mode="demo")
        decision = build_s5_decision_context(context)

        self.assertEqual(decision["decision_strength"], "partial")
        self.assertIn("as_of_time", decision["missing_time_context_fields"])
        self.assertIn("cannot_assess_current_pricing_timing_without_as_of_time", decision["not_allowed_conclusions"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from runtime.business_context_resolver import resolve_business_context
from runtime.decisions.progress_diagnosis import build_progress_diagnosis


class TestBusinessContextAsOfTime(unittest.TestCase):
    def test_missing_as_of_time_does_not_select_last_hourly_snapshot(self) -> None:
        context = resolve_business_context(mode="demo")

        self.assertIsNone(context["as_of_time"])
        self.assertTrue(context["time_context_required"])
        self.assertEqual(context["progress"]["status"], "partial")
        self.assertEqual(context["progress"]["missing_fields"], ["as_of_time"])

    def test_s16_without_as_of_time_returns_partial_without_hourly_detail(self) -> None:
        context = resolve_business_context(mode="demo")
        diagnosis = build_progress_diagnosis(context=context)

        self.assertEqual(diagnosis["status"], "partial")
        self.assertIsNone(diagnosis["as_of_time"])
        self.assertEqual(diagnosis["actual_hourly_sales"], [])
        self.assertEqual(diagnosis["actual_vs_target_hourly"], [])
        self.assertIn("as_of_time", diagnosis["missing_fields"])


if __name__ == "__main__":
    unittest.main()

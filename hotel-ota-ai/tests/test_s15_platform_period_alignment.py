from __future__ import annotations

import unittest

from runtime.s15_platform_period_patch import (
    _is_completed_daily_row,
    _period_summary,
    _set_period_mismatch,
)


class S15PlatformPeriodAlignmentTests(unittest.TestCase):
    def test_next_day_snapshot_is_completed_daily_fact(self) -> None:
        row = {
            "business_date": "2026-08-02 00:00:00",
            "snapshot_time": "2026-08-03 18:52:34",
        }
        self.assertTrue(_is_completed_daily_row(row))

    def test_same_day_snapshot_is_partial_daily_cumulative(self) -> None:
        row = {
            "business_date": "2026-08-03 00:00:00",
            "snapshot_time": "2026-08-03 18:52:34",
        }
        self.assertFalse(_is_completed_daily_row(row))

    def test_period_summary_separates_completed_and_partial_dates(self) -> None:
        summary = _period_summary(
            [
                {
                    "business_date": "2026-08-02",
                    "snapshot_time": "2026-08-03 18:52:34",
                    "metric_code": "FLOW_INTENTION_UV",
                },
                {
                    "business_date": "2026-08-03",
                    "snapshot_time": "2026-08-03 18:52:34",
                    "metric_code": "FLOW_INTENTION_UV",
                },
            ]
        )
        self.assertEqual(summary["completed_dates"], ["2026-08-02"])
        self.assertEqual(summary["partial_dates"], ["2026-08-03"])
        self.assertEqual(summary["completed_day_count"], 1)
        self.assertEqual(summary["partial_day_count"], 1)

    def test_partial_day_axis_keeps_facts_but_blocks_comparison(self) -> None:
        axis = _set_period_mismatch(
            {
                "current": 169,
                "baseline_median": 415,
                "ratio": 169 / 415,
                "status": "weak",
            }
        )
        self.assertEqual(axis["current"], 169)
        self.assertEqual(axis["baseline_median"], 415)
        self.assertIsNone(axis["ratio"])
        self.assertEqual(axis["status"], "period_mismatch")
        self.assertFalse(axis["comparison_allowed"])
        self.assertAlmostEqual(axis["reference_ratio"], 169 / 415)


if __name__ == "__main__":
    unittest.main()

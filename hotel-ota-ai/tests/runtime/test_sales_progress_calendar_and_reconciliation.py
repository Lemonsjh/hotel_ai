from __future__ import annotations

import datetime as dt
import unittest

from runtime.sales_progress.baseline_service import _select_dates, build_baseline
from runtime.sales_progress.deviation_service import build_deviation
from tests.runtime.test_sales_progress_real_field import FakeRepository


class SalesProgressCalendarAndReconciliationTests(unittest.TestCase):
    def test_p1_uses_internal_season_holiday_weekday_labels(self) -> None:
        target = dt.date(2026, 8, 8)
        dates = [(target - dt.timedelta(days=7 * index)).isoformat() for index in range(1, 7)]
        contexts = {
            target.isoformat(): {
                "season_tag": "summer",
                "is_holiday": 0,
                "is_weekend": 1,
            },
            **{
                day: {
                    "season_tag": "summer",
                    "is_holiday": 0,
                    "is_weekend": 1,
                }
                for day in dates
            },
        }
        tier, selected = _select_dates(target.isoformat(), dates, contexts)
        self.assertEqual(tier, "P1_season_holiday_weekday")
        self.assertEqual(set(selected), set(dates))

    def test_s16_exposes_bands_remaining_gap_and_reconciliation(self) -> None:
        repo = FakeRepository()
        baseline = build_baseline(
            repo,
            hotel_id="hotel-a",
            target_date=repo.target.isoformat(),
            as_of_datetime=f"{repo.target} 23:59:59",
        )
        report = build_deviation(
            repo,
            hotel_id="hotel-a",
            target_date=repo.target.isoformat(),
            as_of_datetime=f"{repo.target} 16:30:00",
            baseline=baseline,
        )
        target_line = report["hotel_result"]["target_line"]
        self.assertIn("baseline_p25", target_line)
        self.assertIn("baseline_p80", target_line)
        self.assertEqual(
            target_line["remaining_target_gap"],
            report["hotel_result"]["effective_target_room_nights"]
            - report["hotel_result"]["committed_sold"],
        )
        self.assertIn(report["structure_reconciliation"]["status"], {"ok", "conflict"})


if __name__ == "__main__":
    unittest.main()

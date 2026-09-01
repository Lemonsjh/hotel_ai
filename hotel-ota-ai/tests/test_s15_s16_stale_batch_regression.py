from __future__ import annotations

import unittest

from runtime.s15_s16_stale_batch_patch import select_batch


class S15S16StaleBatchRegressionTests(unittest.TestCase):
    def _rows(self, snapshot_time: str) -> list[dict[str, object]]:
        return [
            {
                "room_type_id": "py01",
                "total_rooms": 5,
                "available_rooms": 3,
                "occupied_rooms": 2,
                "overbooking_rooms": 0,
                "snapshot_time": snapshot_time,
            },
            {
                "room_type_id": "py02",
                "total_rooms": 4,
                "available_rooms": 2,
                "occupied_rooms": 2,
                "overbooking_rooms": 0,
                "snapshot_time": snapshot_time,
            },
        ]

    def test_cross_day_forecast_remains_real_but_stale(self) -> None:
        selected = select_batch(
            self._rows("2026-08-03 22:00:00"),
            expected_room_types=["py01", "py02"],
            requested_hour=17,
            as_of_datetime="2026-08-04 17:30:00",
        )
        self.assertEqual(selected.status, "ok")
        self.assertEqual(len(selected.rows), 2)
        self.assertEqual(selected.observed_hour, 17)
        self.assertEqual(selected.reason, "stale_cross_day_forecast_used")
        self.assertGreater(selected.checkpoint_gap_minutes or 0, 120)

    def test_same_day_stale_forecast_uses_capture_hour(self) -> None:
        selected = select_batch(
            self._rows("2026-08-04 10:05:00"),
            expected_room_types=["py01", "py02"],
            requested_hour=17,
            as_of_datetime="2026-08-04 17:30:00",
        )
        self.assertEqual(selected.status, "ok")
        self.assertEqual(selected.observed_hour, 10)
        self.assertEqual(selected.reason, "stale_checkpoint_used")
        self.assertEqual(selected.checkpoint_gap_minutes, 445)

    def test_newest_current_forecast_wins_over_older_cross_day_snapshot(self) -> None:
        old_rows = self._rows("2026-08-03 22:00:00")
        new_rows = self._rows("2026-08-04 10:05:00")
        for row in new_rows:
            row["available_rooms"] = 1
        selected = select_batch(
            old_rows + new_rows,
            expected_room_types=["py01", "py02"],
            requested_hour=17,
            as_of_datetime="2026-08-04 17:30:00",
        )
        self.assertEqual(selected.status, "ok")
        self.assertEqual(selected.snapshot_time, "2026-08-04 10:05:00")
        self.assertEqual(selected.observed_hour, 10)
        self.assertTrue(all(row["available_rooms"] == 1 for row in selected.rows))

    def test_historical_hourly_gap_stays_strict(self) -> None:
        rows = self._rows("2026-07-21 10:05:00")
        for row in rows:
            row["snapshot_hour"] = "2026-07-21 10:00:00"
        selected = select_batch(
            rows,
            expected_room_types=["py01", "py02"],
            requested_hour=17,
            as_of_datetime=None,
        )
        self.assertEqual(selected.status, "data_gap")
        self.assertEqual(selected.reason, "checkpoint_gap_exceeds_limit")
        self.assertEqual(selected.rows, [])


if __name__ == "__main__":
    unittest.main()

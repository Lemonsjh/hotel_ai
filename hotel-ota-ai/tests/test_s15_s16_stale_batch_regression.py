from __future__ import annotations

import unittest

from runtime.s15_s16_spec_followup_patch import strict_hourly_facts
from runtime.s15_s16_stale_batch_patch import select_batch
from runtime.sales_progress.service import _attach_exact_hour_grid


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

    def test_missing_canonical_id_uses_pms_id_for_read_only_batch(self) -> None:
        rows = self._rows("2026-08-04 10:05:00")
        rows.append(
            {
                "room_type_id": None,
                "pms_room_type_id": "QPF",
                "room_type_name": "棋牌房",
                "total_rooms": 3,
                "available_rooms": 2,
                "occupied_rooms": 1,
                "overbooking_rooms": 0,
                "snapshot_time": "2026-08-04 10:05:00",
            }
        )
        selected = select_batch(
            rows,
            expected_room_types=["py01", "py02"],
            requested_hour=10,
            as_of_datetime="2026-08-04 10:06:00",
        )
        inferred = next(row for row in selected.rows if row.get("pms_room_type_id") == "QPF")
        self.assertEqual(selected.status, "ok")
        self.assertEqual(inferred["room_type_id"], "read:pms:QPF")
        self.assertEqual(inferred["room_type_identity_source"], "pms_id_fallback")

    def test_duplicate_name_fallback_remains_partial(self) -> None:
        rows = self._rows("2026-08-04 10:05:00")
        for _ in range(2):
            rows.append(
                {
                    "room_type_id": None,
                    "room_type_name": "棋牌房",
                    "total_rooms": 3,
                    "available_rooms": 2,
                    "overbooking_rooms": 0,
                    "snapshot_time": "2026-08-04 10:05:00",
                }
            )
        selected = select_batch(rows, expected_room_types=["py01", "py02"], requested_hour=10)
        self.assertEqual(selected.status, "partial")
        self.assertEqual(selected.reason, "partial_room_type_scope")

    def test_hourly_baseline_rekeys_duplicate_canonical_ids_by_pms_id(self) -> None:
        rows = [
            {
                "stay_date": "2026-08-04",
                "snapshot_hour": 10,
                "snapshot_time": "2026-08-04 10:05:00",
                "room_type_id": "wyn02",
                "pms_room_type_id": "BZSCF",
                "room_type_name": "标准双床房",
                "total_rooms": 5,
                "available_rooms": 3,
                "overbooking_rooms": 0,
            },
            {
                "stay_date": "2026-08-04",
                "snapshot_hour": 10,
                "snapshot_time": "2026-08-04 10:05:00",
                "room_type_id": "wyn02",
                "pms_room_type_id": "QPF",
                "room_type_name": "棋牌房",
                "total_rooms": 3,
                "available_rooms": 2,
                "overbooking_rooms": 0,
            },
        ]
        for hour in (9, 11):
            rows.extend(
                {
                    **row,
                    "snapshot_hour": hour,
                    "snapshot_time": f"2026-08-04 {hour:02d}:05:00",
                }
                for row in rows[:2]
            )
        facts, expected = strict_hourly_facts(rows, ["2026-08-04"])
        self.assertEqual(expected, ("read:pms:BZSCF", "read:pms:QPF"))
        self.assertIn(("2026-08-04", 10), facts)
        self.assertTrue(
            all(
                fact["room_type_identity_source"] == "canonical_id_conflict_fallback"
                for fact in facts[("2026-08-04", 10)]
            )
        )

    def test_hour_grid_evidence_uses_duplicate_identity_fallback(self) -> None:
        rows = [
            {
                "stay_date": day,
                "snapshot_hour": 10,
                "snapshot_time": f"{day} 10:05:00",
                "room_type_id": "wyn02",
                "pms_room_type_id": pms_id,
                "total_rooms": total,
                "available_rooms": 2,
                "overbooking_rooms": 0,
            }
            for day in ("2026-08-02", "2026-08-03", "2026-08-04")
            for pms_id, total in (("BZSCF", 5), ("QPF", 3))
        ]

        class Repository:
            def hourly_history(self, *_: object) -> list[dict[str, object]]:
                return rows

        result = _attach_exact_hour_grid(
            {
                "selected_dates": ["2026-08-02", "2026-08-03", "2026-08-04"],
                "expected_room_type_ids": ["wyn02"],
                "room_types": {},
            },
            repository=Repository(),
            hotel_id="wyn",
            target_date="2026-08-05",
            as_of_datetime="2026-08-05 10:00:00",
        )
        health = result["hour_grid_health"]
        self.assertEqual(health["expected_room_type_count"], 2)
        self.assertEqual(health["exact_cell_count"], 3)


if __name__ == "__main__":
    unittest.main()

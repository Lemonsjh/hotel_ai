from __future__ import annotations

import unittest

from runtime.s15_s16_prearrival_fact_patch import _wrap_deviation


class _Repository:
    def __init__(self, snapshot_time: str) -> None:
        self.snapshot_time = snapshot_time

    def current_forecast(
        self, hotel_id: str, target_date: str, as_of_datetime: str
    ) -> list[dict[str, object]]:
        return [
            {
                "hotel_id": hotel_id,
                "stay_date": target_date,
                "snapshot_time": self.snapshot_time,
                "room_type_id": "py01",
                "total_rooms": 5,
                "available_rooms": 3,
                "overbooking_rooms": 0,
            }
        ]


class S15S16PrearrivalFactTests(unittest.TestCase):
    def _report(self) -> dict[str, object]:
        line = {
            "actual_progress": 0.4,
            "baseline_median": 0.6,
            "baseline_p25": 0.5,
            "baseline_p80": 0.7,
            "delta_pp": -20,
            "expected_sold": 3,
            "room_gap": -1,
            "remaining_target_gap": 2,
            "status": "significant_slow",
        }
        return {
            "status": "ok",
            "hotel_id": "puyue",
            "target_date": "2026-08-04",
            "as_of_datetime": "2026-08-04 17:30:00",
            "hotel_result": {
                "committed_sold": 2,
                "total_rooms": 5,
                "capacity_line": dict(line),
                "target_line": dict(line),
            },
            "room_type_results": [
                {
                    "room_type_id": "py01",
                    "committed_sold": 2,
                    "total_rooms": 5,
                    "capacity_line": dict(line),
                    "target_line": dict(line),
                }
            ],
            "structure_summary": {
                "slow_room_type_count": 1,
                "fast_room_type_count": 0,
                "labels": ["room_type_structural_lag"],
            },
        }

    def test_prearrival_snapshot_keeps_facts_but_disables_progress_judgment(self) -> None:
        def previous(*args: object, **kwargs: object) -> dict[str, object]:
            return self._report()

        build = _wrap_deviation(previous)
        result = build(
            _Repository("2026-08-03 18:58:24"),
            hotel_id="puyue",
            target_date="2026-08-04",
            as_of_datetime="2026-08-04 17:30:00",
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["freshness_status"], "stale_prearrival_fact")
        self.assertFalse(result["progress_judgment_allowed"])
        hotel = result["hotel_result"]
        self.assertEqual(hotel["committed_sold"], 2)
        self.assertEqual(hotel["target_line"]["status"], "unavailable")
        self.assertIsNone(hotel["target_line"]["delta_pp"])
        self.assertEqual(hotel["target_line"]["remaining_target_gap"], 2)
        self.assertEqual(len(result["room_type_results"]), 1)
        self.assertEqual(result["structure_summary"]["slow_room_type_count"], 0)

    def test_same_day_snapshot_keeps_normal_progress_result(self) -> None:
        expected = self._report()

        def previous(*args: object, **kwargs: object) -> dict[str, object]:
            return expected

        build = _wrap_deviation(previous)
        result = build(
            _Repository("2026-08-04 10:05:00"),
            hotel_id="puyue",
            target_date="2026-08-04",
            as_of_datetime="2026-08-04 17:30:00",
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["hotel_result"]["target_line"]["status"], "significant_slow")
        self.assertNotIn("current_fact_time_semantics", result)


if __name__ == "__main__":
    unittest.main()

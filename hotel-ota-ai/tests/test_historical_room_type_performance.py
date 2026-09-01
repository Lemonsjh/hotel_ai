from __future__ import annotations

import unittest

from runtime.feishu_command_router import _detect_intent
from runtime.historical_room_type_performance import (
    build_historical_room_type_performance,
    render_historical_room_type_performance_reply,
)


class _Repository:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def _query(self, sql, params):
        self.calls.append((sql, params))
        return self.rows

    def close(self):
        pass


class HistoricalRoomTypePerformanceTests(unittest.TestCase):
    def test_detects_explicit_historical_room_type_occupancy_and_price_request(self) -> None:
        self.assertEqual(
            _detect_intent("帮我分析一下各房型最近15天的出租率和成交价格"),
            "historical_room_type_performance",
        )
        self.assertEqual(_detect_intent("今天 ADR 多少"), "run_s02_demo")

    def test_uses_completed_days_and_deduplicates_each_room_day(self) -> None:
        repository = _Repository(
            [
                {"business_date": "2026-08-28", "room_type_id": "a", "room_type_name": "大床房", "room_nights": 1, "room_revenue": 100, "occupancy_rate": 0.5, "adr": 100, "revpar": 50, "snapshot_time": "2026-08-28 20:00:00"},
                {"business_date": "2026-08-28", "room_type_id": "a", "room_type_name": "大床房", "room_nights": 2, "room_revenue": 220, "occupancy_rate": 0.6, "adr": 110, "revpar": 66, "snapshot_time": "2026-08-28 23:00:00"},
                {"business_date": "2026-08-29", "room_type_id": "a", "room_type_name": "大床房", "room_nights": 3, "room_revenue": 330, "occupancy_rate": 70, "adr": 110, "revpar": 77, "snapshot_time": "2026-08-29 23:00:00"},
                {"business_date": "2026-08-30", "room_type_id": "a", "room_type_name": "大床房", "room_nights": 1, "room_revenue": 120, "occupancy_rate": 80, "adr": 120, "revpar": 96, "snapshot_time": "2026-08-30 23:00:00"},
            ]
        )
        result = build_historical_room_type_performance(
            hotel_id="hotel-a",
            days=3,
            as_of_time="2026-08-31 10:00:00",
            repository_factory=lambda _: repository,
        )

        sql, params = repository.calls[0]
        self.assertIn("FROM jl01_room_type_performance_daily", sql)
        self.assertNotIn("jy01_hotel_statistics_daily", sql)
        self.assertEqual(params[1:3], ("2026-08-28", "2026-08-30"))
        self.assertEqual(result["freshness_status"], "historical_complete")
        room = result["room_types"][0]
        self.assertEqual(room["covered_days"], 3)
        self.assertEqual(room["average_occupancy_rate"], 70.0)
        self.assertEqual(room["adr"], 113.33)
        self.assertEqual(room["revpar"], 79.67)
        self.assertIn("成交 ADR", render_historical_room_type_performance_reply(result))
        self.assertIn("RevPAR ¥80", render_historical_room_type_performance_reply(result))

    def test_marks_missing_days_instead_of_filling_them(self) -> None:
        repository = _Repository(
            [{"business_date": "2026-08-30", "room_type_id": "a", "room_type_name": "大床房", "room_nights": 1, "room_revenue": 100, "occupancy_rate": 50, "snapshot_time": "2026-08-30 23:00:00"}]
        )
        result = build_historical_room_type_performance(
            hotel_id="hotel-a",
            days=3,
            as_of_time="2026-08-31 10:00:00",
            repository_factory=lambda _: repository,
        )

        self.assertEqual(result["freshness_status"], "partial")
        self.assertEqual(result["room_types"][0]["missing_days"], ["2026-08-28", "2026-08-29"])


if __name__ == "__main__":
    unittest.main()

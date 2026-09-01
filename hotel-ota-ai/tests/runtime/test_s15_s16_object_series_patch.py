from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from runtime.s15_s16_object_series_patch import (
    rebuild_independent_baseline_series,
)
from runtime.sales_progress.core import calculate_room_fact


class S15S16ObjectSeriesPatchTests(unittest.TestCase):
    def _capture(self) -> SimpleNamespace:
        days = ["2026-07-01", "2026-07-02", "2026-07-03"]
        hourly_rows = []
        for index, day in enumerate(days, start=1):
            hourly_rows.append(
                {
                    "hotel_id": "hotel-puyue",
                    "stay_date": day,
                    "snapshot_hour": 10,
                    "snapshot_time": f"{day} 10:10:00",
                    "room_type_id": "r1",
                    "room_type_name": "房型一",
                    "total_rooms": 10,
                    "available_rooms": 10 - (index + 1),
                    "occupied_rooms": 0,
                    "overbooking_rooms": 0,
                }
            )
        return SimpleNamespace(
            hourly_rows=hourly_rows,
            room_daily_rows=[
                {
                    "business_date": "2026-07-01",
                    "room_type_id": "r1",
                    "room_nights": 4,
                    "room_revenue": 400,
                },
                {
                    "business_date": "2026-07-02",
                    "room_type_id": "r1",
                    "room_nights": 6,
                    "room_revenue": 720,
                },
                {
                    "business_date": "2026-07-03",
                    "room_type_id": "r1",
                    "room_nights": 8,
                    "room_revenue": 1040,
                },
            ],
            hotel_daily_rows=[
                {
                    "business_date": "2026-07-01",
                    "room_nights": 10,
                    "room_revenue": 1200,
                },
                {
                    "business_date": "2026-07-02",
                    "room_nights": 20,
                    "room_revenue": 2400,
                },
                {
                    "business_date": "2026-07-03",
                    "room_nights": 30,
                    "room_revenue": 3600,
                },
            ],
            price_rows=[
                {
                    "business_date": "2026-06-28",
                    "room_type_id": "r1",
                    "room_daily_price": 100,
                    "room_nights": 1,
                    "room_fee": 100,
                },
                {
                    "business_date": "2026-06-29",
                    "room_type_id": "r1",
                    "room_daily_price": 120,
                    "room_nights": 2,
                    "room_fee": 240,
                },
                {
                    "business_date": "2026-06-30",
                    "room_type_id": "r1",
                    "room_daily_price": 140,
                    "room_nights": 3,
                    "room_fee": 420,
                },
                {
                    "business_date": "2026-07-01",
                    "room_type_id": "r1",
                    "room_daily_price": 160,
                    "room_nights": 4,
                    "room_fee": 640,
                },
            ],
        )

    def test_hotel_uses_jy01_and_room_uses_jl01(self) -> None:
        payload = {
            "status": "ok",
            "selected_tier": "capacity-tier",
            "selected_dates": ["2026-07-01"],
            "hotel": {
                "hourly_points": [
                    {"hour": 10, "maturity": "weak", "capacity": {}}
                ]
            },
            "room_types": {
                "r1": {
                    "room_type_id": "r1",
                    "hourly_points": [
                        {"hour": 10, "maturity": "weak", "capacity": {}}
                    ],
                }
            },
        }
        capture = self._capture()

        def select_dates(target_date, available_dates, date_contexts):
            dates = sorted(available_dates)
            return f"tier-{len(dates)}", dates

        def hourly_facts(rows, selected_dates):
            selected = set(selected_dates)
            result = {}
            for row in rows:
                day = str(row["stay_date"])
                if day in selected:
                    result[(day, 10)] = [calculate_room_fact(row)]
            return result, ("r1",)

        with patch(
            "runtime.sales_progress.baseline_service._select_dates",
            side_effect=select_dates,
        ), patch(
            "runtime.sales_progress.baseline_service._hourly_facts",
            side_effect=hourly_facts,
        ):
            result = rebuild_independent_baseline_series(
                payload,
                capture,
                target_date="2026-08-03",
                date_contexts={},
            )

        hotel = result["hotel"]
        room = result["room_types"]["r1"]
        self.assertEqual(
            hotel["target_final_source"],
            "jy01_exact_total_business_metric",
        )
        self.assertEqual(hotel["effective_target_room_nights"], 20)
        self.assertEqual(
            room["target_final_source"],
            "jl01_exact_canonical_room_type",
        )
        self.assertEqual(room["effective_target_room_nights"], 6)
        self.assertEqual(
            hotel["hourly_points"][0]["target_completion"]["sample_count"],
            3,
        )
        self.assertEqual(
            room["hourly_points"][0]["target_completion"]["median"],
            0.5,
        )

    def test_price_series_selects_dates_independently(self) -> None:
        payload = {
            "status": "ok",
            "selected_tier": "capacity-tier",
            "selected_dates": ["2026-07-01"],
            "hotel": {"hourly_points": []},
            "room_types": {"r1": {"room_type_id": "r1", "hourly_points": []}},
        }
        capture = self._capture()

        def select_dates(target_date, available_dates, date_contexts):
            dates = sorted(available_dates)
            return f"tier-{len(dates)}", dates

        with patch(
            "runtime.sales_progress.baseline_service._select_dates",
            side_effect=select_dates,
        ), patch(
            "runtime.sales_progress.baseline_service._hourly_facts",
            return_value=({}, ("r1",)),
        ):
            result = rebuild_independent_baseline_series(
                payload,
                capture,
                target_date="2026-08-03",
                date_contexts={},
            )

        selection = result["baseline_object_selection"]
        self.assertEqual(selection["capacity_series"]["dates"], ["2026-07-01"])
        self.assertEqual(
            len(selection["room_price_series"]["r1"]["dates"]),
            4,
        )
        self.assertEqual(
            result["room_types"]["r1"]["price_series_tier"],
            "tier-4",
        )
        self.assertEqual(result["room_types"]["r1"]["price_baseline"]["median"], 140)


if __name__ == "__main__":
    unittest.main()

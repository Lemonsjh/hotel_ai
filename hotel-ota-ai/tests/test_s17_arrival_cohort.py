from __future__ import annotations

import datetime as dt
import unittest

from runtime.algorithms.customer_arrival import aggregate_arrivals
from runtime.decisions.customer import render_s17_summary


class TestS17ArrivalCohort(unittest.TestCase):
    def test_arrival_structure_excludes_cancelled_orders(self) -> None:
        rows = [
            {
                "hotel_id": "puyue",
                "source_platform": "PMS（别样红）",
                "order_id": "created-before-window",
                "booking_time": "2026-06-20 10:00:00",
                "arrival_time": "2026-07-10 15:00:00",
                "departure_time": "2026-07-12 12:00:00",
                "room_type_id": "py01",
                "room_count": 1,
                "booking_status": "已入住",
                "snapshot_time": "2026-08-03 13:00:00",
            },
            {
                "hotel_id": "puyue",
                "source_platform": "PMS（别样红）",
                "order_id": "cancelled-in-window",
                "booking_time": "2026-07-01 10:00:00",
                "arrival_time": "2026-07-11 15:00:00",
                "departure_time": "2026-07-14 12:00:00",
                "room_type_id": "py01",
                "room_count": 2,
                "booking_status": "已取消",
                "snapshot_time": "2026-08-03 13:00:00",
            },
            {
                "hotel_id": "puyue",
                "source_platform": "PMS（别样红）",
                "order_id": "arrives-after-window",
                "booking_time": "2026-07-20 10:00:00",
                "arrival_time": "2026-08-10 15:00:00",
                "departure_time": "2026-08-11 12:00:00",
                "room_type_id": "py01",
                "room_count": 1,
                "booking_status": "预订",
                "snapshot_time": "2026-08-03 13:00:00",
            },
        ]
        result = aggregate_arrivals(
            rows,
            hotel_id="puyue",
            window_start=dt.datetime(2026, 7, 4),
            window_end=dt.datetime(2026, 8, 3, 14),
            as_of=dt.datetime(2026, 8, 3, 14),
        )
        self.assertEqual(result["arrival_window_order_count"], 2)
        self.assertEqual(result["arrival_order_count"], 1)
        self.assertEqual(result["current_cancelled_orders"], 1)
        self.assertEqual(result["current_cancelled_share"], 0.5)
        self.assertEqual(result["current_non_cancelled_orders"], 1)
        self.assertEqual(result["booked_rooms"], 1)
        self.assertEqual(result["planned_room_nights"], 2)
        buckets = {item["name"]: item["value"] for item in result["stay_duration_buckets"]}
        self.assertEqual(buckets, {"2_nights": 1})

    def test_summary_uses_planned_arrival_wording(self) -> None:
        summary = render_s17_summary(
            {
                "window_start": "2026-07-04 00:00:00",
                "window_end": "2026-08-03 14:00:00",
                "as_of_datetime": "2026-08-03 14:00:00",
                "populations": {
                    "pms_booking_created": {
                        "created_order_count": 10,
                        "booked_rooms": 10,
                        "current_cancelled_orders": 1,
                        "current_non_cancelled_orders": 9,
                        "stay_duration_buckets": [{"name": "1_night", "value": 9, "share": 0.9}],
                    },
                    "pms_arrival_cohort": {
                        "arrival_order_count": 4,
                        "planned_arrival_order_count": 4,
                        "booked_rooms": 4,
                        "planned_room_nights": 8,
                        "current_cancelled_orders": 1,
                        "current_cancelled_share": 0.2,
                        "current_non_cancelled_orders": 4,
                        "stay_duration_buckets": [{"name": "2_nights", "value": 4, "share": 1.0}],
                        "long_stay_share": 1.0,
                    },
                },
            }
        )
        self.assertIn("计划到店订单：4 单，4 间预订房，计划入住 8 间夜", summary)
        self.assertIn("计划到店订单入住时长结构：2晚 4单（100.0%）", summary)
        self.assertNotIn("到店 cohort", summary)
        self.assertNotIn("入住时长结构：1晚 9单", summary)


if __name__ == "__main__":
    unittest.main()

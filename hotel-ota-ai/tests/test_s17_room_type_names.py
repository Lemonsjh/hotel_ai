from __future__ import annotations

import datetime as dt
import unittest

import runtime  # noqa: F401 - installs runtime patches
from runtime.algorithms.customer_order import aggregate_bookings
from runtime.decisions.customer import render_s17_summary


class TestS17RoomTypeNames(unittest.TestCase):
    def test_booking_distribution_uses_room_type_name(self) -> None:
        result = aggregate_bookings(
            [
                {
                    "hotel_id": "puyue",
                    "source_platform": "PMS",
                    "order_id": "o-1",
                    "booking_time": "2026-07-10 10:00:00",
                    "arrival_time": "2026-07-10 15:00:00",
                    "departure_time": "2026-07-11 12:00:00",
                    "room_type_id": "py04",
                    "room_type_name": "尊享电竞大床房",
                    "room_count": 2,
                    "booking_status": "预订",
                    "guest_source": "中介",
                    "member_level": "美团预订",
                    "snapshot_time": "2026-08-03 20:00:00",
                }
            ],
            hotel_id="puyue",
            window_start=dt.datetime(2026, 7, 4),
            window_end=dt.datetime(2026, 8, 3, 21),
            as_of=dt.datetime(2026, 8, 3, 21),
            contact_hmac_secret=None,
        )

        cells = result["room_type_room_distribution"]
        self.assertEqual(cells[0]["name"], "尊享电竞大床房")
        self.assertEqual(cells[0]["room_type_name"], "尊享电竞大床房")
        self.assertEqual(cells[0]["room_type_id"], "py04")

        summary = render_s17_summary(
            {
                "window_start": "2026-07-04",
                "window_end": "2026-08-03",
                "as_of_datetime": "2026-08-03 21:00:00",
                "populations": {"pms_booking_created": result},
            }
        )
        self.assertIn("尊享电竞大床房 2间预订房", summary)
        self.assertNotIn("py04", summary)

    def test_missing_name_never_falls_back_to_internal_code(self) -> None:
        result = aggregate_bookings(
            [
                {
                    "hotel_id": "puyue",
                    "source_platform": "PMS",
                    "order_id": "o-2",
                    "booking_time": "2026-07-10 10:00:00",
                    "arrival_time": "2026-07-10 15:00:00",
                    "departure_time": "2026-07-11 12:00:00",
                    "room_type_id": "py05",
                    "room_type_name": None,
                    "room_count": 1,
                    "booking_status": "预订",
                    "guest_source": "中介",
                    "member_level": "美团预订",
                    "snapshot_time": "2026-08-03 20:00:00",
                }
            ],
            hotel_id="puyue",
            window_start=dt.datetime(2026, 7, 4),
            window_end=dt.datetime(2026, 8, 3, 21),
            as_of=dt.datetime(2026, 8, 3, 21),
            contact_hmac_secret=None,
        )
        self.assertEqual(result["room_type_room_distribution"][0]["name"], "房型名称未映射")
        summary = render_s17_summary(
            {
                "populations": {"pms_booking_created": result},
            }
        )
        self.assertIn("房型名称未映射", summary)
        self.assertNotIn("py05", summary)


if __name__ == "__main__":
    unittest.main()

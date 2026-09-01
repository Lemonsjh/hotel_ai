from __future__ import annotations

import datetime as dt
import os
import unittest
from unittest.mock import patch

from runtime.algorithms.customer_order import aggregate_bookings, aggregate_realized
from runtime.decisions.customer import render_s17_summary


AS_OF = dt.datetime(2026, 8, 3, 14, 0, 0)
START = dt.datetime(2026, 7, 4)
END = dt.datetime(2026, 8, 3, 14, 0, 0)


def booking(order_id: str, *, member_level: str | None, status: str = "预订") -> dict:
    return {
        "hotel_id": "puyue",
        "source_platform": "PMS（别样红）",
        "order_id": order_id,
        "booking_time": "2026-07-20 10:00:00",
        "arrival_time": "2026-07-20 15:00:00",
        "departure_time": "2026-07-21 12:00:00",
        "room_type_id": "py01",
        "room_count": 1,
        "booking_status": status,
        "guest_source": "中介",
        "member_level": member_level,
        "snapshot_time": "2026-08-03 13:00:00",
    }


class TestS17StrictMdAlignment(unittest.TestCase):
    def test_channel_share_uses_all_orders_and_keeps_unknown(self) -> None:
        rows = (
            [booking(f"m{i}", member_level="美团预付") for i in range(569)]
            + [booking(f"c{i}", member_level="携程预付") for i in range(8)]
            + [booking(f"u{i}", member_level=None) for i in range(7)]
        )
        result = aggregate_bookings(
            rows,
            hotel_id="puyue",
            window_start=START,
            window_end=END,
            as_of=AS_OF,
            contact_hmac_secret=None,
        )
        cells = {item["name"]: item for item in result["booking_channel_order_distribution"]}
        self.assertEqual(set(cells), {"meituan", "ctrip", "unknown"})
        self.assertEqual(cells["meituan"]["share"], 0.9743)
        self.assertEqual(cells["ctrip"]["share"], 0.0137)
        self.assertEqual(cells["unknown"]["share"], 0.012)
        self.assertEqual(result["booking_channel_unknown_orders"], 7)
        self.assertEqual(result["booking_channel_share_denominator"], "all_orders_in_booking_window")
        self.assertEqual(result["current_non_cancelled_orders"], 584)

    def test_only_approved_room_charge_subjects_enter_realized_adr(self) -> None:
        rows = [
            {
                "hotel_id": "puyue",
                "source_platform": "pms",
                "order_id": "o1",
                "room_no": "101",
                "charge_subject": "房费",
                "business_date": "2026-07-20",
                "customer_source": "中介",
                "room_type_id": "py01",
                "room_nights": 2,
                "room_fee": 400,
                "snapshot_time": "2026-08-03 13:00:00",
            },
            {
                "hotel_id": "puyue",
                "source_platform": "pms",
                "order_id": "o1",
                "room_no": "101",
                "charge_subject": "早餐",
                "business_date": "2026-07-20",
                "customer_source": "中介",
                "room_type_id": "py01",
                "room_nights": 2,
                "room_fee": 100,
                "snapshot_time": "2026-08-03 13:00:00",
            },
        ]
        with patch.dict(os.environ, {"HOTEL_OTA_S17_APPROVED_ROOM_CHARGE_SUBJECTS": "房费"}, clear=False):
            result = aggregate_realized(
                rows,
                hotel_id="puyue",
                window_start=START,
                window_end=END,
                as_of=AS_OF,
            )
        self.assertEqual(result["realized_room_nights"], 2.0)
        self.assertEqual(result["realized_room_fee"], 400.0)
        self.assertEqual(result["realized_adr"], 200.0)
        self.assertEqual(result["excluded_unapproved_charge_record_count"], 1)
        self.assertEqual(result["excluded_unapproved_charge_amount"], 100.0)

    def test_deterministic_summary_keeps_units_and_hides_retired_kf11(self) -> None:
        payload = {
            "window_start": "2026-07-04 00:00:00",
            "window_end": "2026-08-03 14:00:00",
            "as_of_datetime": "2026-08-03 14:00:00",
            "data_gaps": ["booking_channel_field_mapping_missing"],
            "populations": {
                "pms_booking_created": {
                    "created_order_count": 530,
                    "booked_rooms": 533,
                    "current_cancelled_orders": 157,
                    "current_cancelled_share": 157 / 530,
                    "current_non_cancelled_orders": 373,
                    "guest_source_order_distribution": [
                        {"name": "中介", "value": 523, "share": 523 / 530},
                        {"name": "非会员", "value": 7, "share": 7 / 530},
                    ],
                    "booking_channel_status": "unavailable",
                    "lead_time_buckets": [
                        {"name": "same_day", "value": 469, "share": 469 / 530},
                        {"name": "1_3_days", "value": 48, "share": 48 / 530},
                    ],
                    "average_lead_time_days": 0.27,
                    "stay_duration_buckets": [
                        {"name": "1_night", "value": 463, "share": 463 / 530},
                        {"name": "same_day_or_day_use", "value": 26, "share": 26 / 530},
                    ],
                    "long_stay_share": 0.081,
                },
                "realized_stay": {
                    "realized_room_nights": 801,
                    "realized_room_fee": 122273.36,
                    "realized_adr": 152.65,
                    "source_distribution": [],
                    "room_type_distribution": [{"room_type_id": "py01", "realized_room_nights": 100}],
                },
                "physical_occupancy": {
                    "physical_occupied_rooms": 16,
                    "snapshot_time": "2026-08-03 13:59:00",
                },
                "extension_reconciliation": {
                    "active_extension_records": 2,
                    "extended_hours": 5,
                },
            },
        }
        summary = render_s17_summary(payload)
        self.assertIn("530 单，533 间预订房", summary)
        self.assertNotIn("533 间夜", summary)
        self.assertIn("预订客源分类（仅表示客源类别，不代表预订渠道）", summary)
        self.assertIn("预订渠道：暂不可用", summary)
        self.assertIn("实现间夜 801", summary)
        self.assertNotIn("当前物理在住", summary)
        self.assertNotIn("KF11", summary)
        self.assertIn("当前有效续住记录 2 条", summary)
        self.assertNotIn("典型电竞酒店", summary)
        self.assertNotIn("来自中介渠道", summary)


if __name__ == "__main__":
    unittest.main()

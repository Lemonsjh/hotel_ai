from __future__ import annotations

import datetime as dt
import json
import unittest
from pathlib import Path

from runtime.algorithms.customer_order import (
    aggregate_bookings,
    aggregate_extensions,
    aggregate_physical,
    aggregate_realized,
    suppress_cells,
)


AS_OF = dt.datetime(2026, 7, 31, 12, 0, 0)
START = dt.datetime(2026, 7, 1)
END = dt.datetime(2026, 8, 1)


def booking(order_id: str, snapshot: str, **overrides):
    row = {
        "hotel_id": "hotel-1",
        "source_platform": "PMS（别样红）",
        "order_id": order_id,
        "booking_time": "2026-07-02 10:00:00",
        "arrival_time": "2026-07-03 15:00:00",
        "departure_time": "2026-07-04 12:00:00",
        "room_type_id": "rt-1",
        "room_count": 1,
        "booking_status": "预订",
        "guest_source": "中介",
        "member_level": "美团预付",
        "contact": "138-0000-0001",
        "snapshot_time": snapshot,
    }
    row.update(overrides)
    return row


class TestS17MdAlgorithm(unittest.TestCase):
    def test_latest_order_scope_and_exact_hotel(self) -> None:
        rows = [
            booking("o-1", "2026-07-02 11:00:00", booking_status="预订"),
            booking("o-1", "2026-07-03 11:00:00", booking_status="取消"),
            booking("o-2", "2026-07-03 11:00:00", hotel_id="other-hotel"),
        ]
        result = aggregate_bookings(rows, hotel_id="hotel-1", window_start=START, window_end=END, as_of=AS_OF, contact_hmac_secret="secret")
        self.assertEqual(result["created_order_count"], 1)
        self.assertEqual(result["current_cancelled_orders"], 1)
        self.assertEqual(result["current_cancelled_share"], 1.0)

    def test_same_day_positive_duration_is_not_invalid(self) -> None:
        rows = [booking("o-1", "2026-07-03 11:00:00", arrival_time="2026-07-03 09:00:00", departure_time="2026-07-03 18:00:00")]
        result = aggregate_bookings(rows, hotel_id="hotel-1", window_start=START, window_end=END, as_of=AS_OF, contact_hmac_secret="secret")
        buckets = {item["name"]: item["value"] for item in result["stay_duration_buckets"]}
        self.assertEqual(buckets["same_day_or_day_use"], 1)
        self.assertNotIn("invalid_nonpositive_duration", buckets)

    def test_contact_proxy_never_returns_contact_or_hash(self) -> None:
        rows = [
            booking("o-0", "2026-06-20 11:00:00", booking_time="2026-06-15 10:00:00"),
            booking("o-1", "2026-07-03 11:00:00"),
            booking("o-2", "2026-07-04 11:00:00", booking_time="2026-07-04 10:00:00"),
        ]
        result = aggregate_bookings(
            rows, hotel_id="hotel-1", window_start=START, window_end=END, as_of=AS_OF,
            contact_hmac_secret="secret", contact_lookup_value="13800000001",
        )
        proxy = result["contact_proxy"]
        self.assertEqual(proxy["repeat_booking_contact_share_proxy"], 1.0)
        self.assertEqual(proxy["contact_seen_before_share_proxy"], 1.0)
        self.assertEqual(proxy["exact_lookup"]["all_order_count"], 3)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn("13800000001", serialized)
        self.assertNotIn('"contact_proxy_key":', serialized)

    def test_missing_canonical_room_type_is_unmapped(self) -> None:
        result = aggregate_bookings(
            [booking("o-1", "2026-07-03 11:00:00", room_type_id=None, room_type_name="名称不能补齐")],
            hotel_id="hotel-1", window_start=START, window_end=END, as_of=AS_OF, contact_hmac_secret=None,
        )
        self.assertEqual(result["unmapped_count"], 1)
        self.assertEqual(result["room_type_order_distribution"], [])

    def test_masked_or_semantically_wrong_contacts_fail_closed(self) -> None:
        rows = [
            booking("o-1", "2026-07-03 11:00:00", contact="张三"),
            booking("o-2", "2026-07-04 11:00:00", contact="***"),
        ]
        result = aggregate_bookings(
            rows, hotel_id="hotel-1", window_start=START, window_end=END,
            as_of=AS_OF, contact_hmac_secret="secret", contact_lookup_value="13800000001",
        )
        proxy = result["contact_proxy"]
        self.assertEqual(proxy["status"], "unavailable")
        self.assertEqual(proxy["reason"], "contact_semantic_unavailable_or_masked")
        self.assertEqual(proxy["maturity"], "unavailable")
        self.assertEqual(proxy["invalid_contact_count"], 2)
        self.assertIsNone(proxy["repeat_booking_contact_share_proxy"])
        self.assertIsNone(proxy["exact_lookup"])

    def test_realized_stay_keeps_zero_night_adjustment_out_of_adr(self) -> None:
        rows = [
            {"hotel_id": "hotel-1", "source_platform": "pms", "order_id": "o1", "room_no": "101", "charge_subject": "房费", "business_date": "2026-07-02", "customer_source": "中介", "room_type_id": "rt-1", "room_nights": 2, "room_fee": 400, "snapshot_time": "2026-07-03"},
            {"hotel_id": "hotel-1", "source_platform": "pms", "order_id": "o2", "room_no": "102", "charge_subject": "调整", "business_date": "2026-07-02", "customer_source": "中介", "room_type_id": "rt-1", "room_nights": 0, "room_fee": 50, "snapshot_time": "2026-07-03"},
        ]
        result = aggregate_realized(rows, hotel_id="hotel-1", window_start=START, window_end=END, as_of=AS_OF)
        self.assertEqual(result["realized_adr"], 200.0)
        self.assertEqual(result["reconciliation_amount"], 50.0)

    def test_physical_and_extension_are_separate(self) -> None:
        physical = aggregate_physical(
            [
                {"hotel_id": "hotel-1", "business_date": "2026-07-31", "room_no": "101", "room_status": "住脏", "room_type_id": "rt-1", "snapshot_time": "2026-07-31 10:00:00"},
                {"hotel_id": "hotel-1", "business_date": "2026-07-31", "room_no": "102", "room_status": "住净", "room_type_id": "rt-1", "snapshot_time": "2026-07-31 10:00:00"},
            ],
            hotel_id="hotel-1", business_date=dt.date(2026, 7, 31), as_of=AS_OF,
        )
        extension = aggregate_extensions(
            [
                {"hotel_id": "hotel-1", "source_platform": "pms", "order_id": "o1", "room_no": "101", "room_type_id": "rt-1", "checkin_time": "2026-07-30", "original_checkout_time": "2026-07-31 10:00:00", "checkout_time": "2026-07-31 14:00:00", "snapshot_time": "2026-07-31 11:00:00"},
                {"hotel_id": "hotel-1", "source_platform": "pms", "order_id": "old", "room_no": "102", "room_type_id": "rt-1", "checkin_time": "2026-07-20", "checkout_time": "2026-07-21", "snapshot_time": "2026-07-21"},
            ],
            hotel_id="hotel-1", as_of=AS_OF,
        )
        self.assertEqual(physical["physical_occupied_rooms"], 2)
        self.assertEqual(extension["active_extension_records"], 1)
        self.assertEqual(extension["extended_hours"], 4.0)

    def test_privacy_suppression_precedes_output_limit(self) -> None:
        visible, suppressed = suppress_cells(
            [{"name": "small", "count": 2}, {"name": "safe", "count": 5}, {"name": "large", "count": 9}],
            count_field="count", minimum_cohort_size=3, max_output_cells=10,
        )
        self.assertEqual([item["name"] for item in visible], ["large"])
        self.assertEqual(suppressed, 2)

    def test_machine_contract_removes_customer_profile_outputs(self) -> None:
        root = Path(__file__).resolve().parents[1]
        contract = json.loads((root / "contracts/v27/contract.json").read_text(encoding="utf-8"))
        node = contract["node_io_contract"]["N014"]
        keys = {item["canonical_key"] for item in node["outputs"]}
        self.assertEqual(keys, {"customer_order_populations", "repeat_booking_contact_share_proxy", "provider_loss_proxy", "data_gaps"})
        self.assertNotIn("customer_segments", keys)
        self.assertNotIn("target_guest_tasks", keys)


if __name__ == "__main__":
    unittest.main()

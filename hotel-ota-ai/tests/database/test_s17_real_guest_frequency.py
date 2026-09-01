from __future__ import annotations

import datetime as dt
import json

from runtime.algorithms.guest_frequency import (
    aggregate_real_guest_frequency,
    guest_frequency_level,
    normalize_guest_name,
)


def _realized(
    *,
    hotel_id: str,
    order_id: str,
    guest_name: str,
    checkin: str,
    business_date: str,
    room_no: str,
) -> dict:
    return {
        "hotel_id": hotel_id,
        "source_platform": "pms",
        "order_id": order_id,
        "room_no": room_no,
        "guest_name": guest_name,
        "charge_subject": "房费",
        "business_date": business_date,
        "checkin_time": checkin,
        "checkout_time": f"{business_date} 12:00:00",
        "room_nights": 1,
        "room_fee": 100,
        "snapshot_time": "2026-08-07 10:00:00",
    }


def _booking(order_id: str, contact: str) -> dict:
    return {
        "hotel_id": "h1",
        "source_platform": "pms",
        "order_id": order_id,
        "contact": contact,
        "snapshot_time": "2026-08-07 10:00:00",
    }


def test_guest_name_is_primary_key_and_realized_order_is_one_visit() -> None:
    realized = [
        _realized(
            hotel_id="h1",
            order_id="o1",
            guest_name="张三",
            checkin="2026-07-10 14:00:00",
            business_date="2026-07-10",
            room_no="101",
        ),
        # Same stay/order, second room-fee row. It must not become another visit.
        _realized(
            hotel_id="h1",
            order_id="o1",
            guest_name="张三",
            checkin="2026-07-10 14:00:00",
            business_date="2026-07-11",
            room_no="101",
        ),
        _realized(
            hotel_id="h1",
            order_id="o2",
            guest_name=" 张三 ",
            checkin="2026-07-20 14:00:00",
            business_date="2026-07-20",
            room_no="102",
        ),
        _realized(
            hotel_id="h1",
            order_id="o3",
            guest_name="张三",
            checkin="2026-08-01 14:00:00",
            business_date="2026-08-01",
            room_no="103",
        ),
        # Same name in another hotel must never join this identity.
        _realized(
            hotel_id="h2",
            order_id="other-hotel-order",
            guest_name="张三",
            checkin="2026-08-02 14:00:00",
            business_date="2026-08-02",
            room_no="201",
        ),
    ]
    bookings = [
        _booking("o1", "13800138000"),
        _booking("o2", "13800138000"),
        _booking("o3", "13800138000"),
    ]

    result = aggregate_real_guest_frequency(
        realized,
        bookings,
        hotel_id="h1",
        window_start=dt.datetime(2026, 7, 8),
        window_end=dt.datetime(2026, 8, 8),
        as_of=dt.datetime(2026, 8, 7, 12),
        contact_hmac_secret="test-secret",
        guest_name_lookup="张三",
    )

    lookup = result["exact_lookup"]
    assert result["primary_identity_key"] == "guest_name"
    assert result["identity_scope"] == "hotel_id+normalized_guest_name"
    assert lookup["visit_count"] == 3
    assert lookup["frequency_level"] == "中频"
    assert lookup["first_arrival_date"] == "2026-07-10"
    assert lookup["last_arrival_date"] == "2026-08-01"
    assert lookup["contact_corroboration"] == "single_consistent_contact"
    assert lookup["raw_contact_included"] is False


def test_same_name_multiple_contacts_warns_but_does_not_split_primary_key() -> None:
    realized = [
        _realized(
            hotel_id="h1",
            order_id="o1",
            guest_name="李四",
            checkin="2026-07-15 14:00:00",
            business_date="2026-07-15",
            room_no="101",
        ),
        _realized(
            hotel_id="h1",
            order_id="o2",
            guest_name="李四",
            checkin="2026-08-01 14:00:00",
            business_date="2026-08-01",
            room_no="102",
        ),
    ]
    bookings = [
        _booking("o1", "13800138000"),
        _booking("o2", "13900139000"),
    ]

    result = aggregate_real_guest_frequency(
        realized,
        bookings,
        hotel_id="h1",
        window_start=dt.datetime(2026, 7, 8),
        window_end=dt.datetime(2026, 8, 8),
        as_of=dt.datetime(2026, 8, 7, 12),
        contact_hmac_secret="test-secret",
        guest_name_lookup="李四",
    )

    lookup = result["exact_lookup"]
    assert lookup["visit_count"] == 2
    assert lookup["frequency_level"] == "低频"
    assert lookup["identity_status"] == "needs_check"
    assert lookup["contact_corroboration"] == "multiple_contacts_same_name"
    assert "same_name_multiple_contacts" in lookup["warnings"]
    serialized = json.dumps(result, ensure_ascii=False)
    assert "13800138000" not in serialized
    assert "13900139000" not in serialized


def test_bulk_frequency_contains_no_named_roster() -> None:
    realized = [
        _realized(
            hotel_id="h1",
            order_id="o1",
            guest_name="王五",
            checkin="2026-08-01 14:00:00",
            business_date="2026-08-01",
            room_no="101",
        )
    ]

    result = aggregate_real_guest_frequency(
        realized,
        [],
        hotel_id="h1",
        window_start=dt.datetime(2026, 7, 8),
        window_end=dt.datetime(2026, 8, 8),
        as_of=dt.datetime(2026, 8, 7, 12),
        contact_hmac_secret=None,
        guest_name_lookup=None,
    )

    assert result["bulk_guest_name_list_included"] is False
    assert result["exact_lookup"] is None
    assert "王五" not in json.dumps(result, ensure_ascii=False)


def test_frequency_level_and_name_normalization_contract() -> None:
    assert normalize_guest_name("  张三  ") == "张三"
    assert guest_frequency_level(0) == "未观察到到店"
    assert guest_frequency_level(1) == "首次"
    assert guest_frequency_level(2) == "低频"
    assert guest_frequency_level(3) == "中频"
    assert guest_frequency_level(4) == "中频"
    assert guest_frequency_level(5) == "高频"

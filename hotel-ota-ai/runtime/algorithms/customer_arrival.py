from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any

from runtime.algorithms.customer_order import (
    _datetime,
    _distribution,
    _latest,
    _number,
    _ratio,
    _status,
    _stay_bucket,
    _text,
)


def aggregate_arrivals(
    rows: list[dict[str, Any]],
    *,
    hotel_id: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
    as_of: dt.datetime,
) -> dict[str, Any]:
    scoped = [row for row in rows if _text(row.get("hotel_id")) == hotel_id]
    latest, missing_dedup = _latest(scoped, ("source_platform", "order_id"), as_of)
    in_window: list[dict[str, Any]] = []
    for row in latest:
        arrival = _datetime(row.get("arrival_time"))
        if arrival is not None and window_start <= arrival < window_end:
            in_window.append(row)

    status_counter: Counter[str] = Counter()
    stay_buckets: Counter[str] = Counter()
    room_type_orders: Counter[str] = Counter()
    room_type_rooms: Counter[str] = Counter()
    overnight_values: list[int] = []
    unmapped_count = 0
    booked_rooms = 0

    for row in in_window:
        normalized_status = _status(row.get("booking_status") or row.get("order_status"))
        status_counter[normalized_status] += 1
        rooms = max(int(_number(row.get("room_count")) or 0), 0)
        booked_rooms += rooms

        room_type_id = _text(row.get("room_type_id"))
        if room_type_id:
            room_type_orders[room_type_id] += 1
            room_type_rooms[room_type_id] += rooms
        else:
            unmapped_count += 1

        arrival = _datetime(row.get("arrival_time"))
        departure = _datetime(row.get("departure_time"))
        duration_bucket, nights = _stay_bucket(arrival, departure)
        stay_buckets[duration_bucket] += 1
        if nights and nights > 0:
            overnight_values.append(nights)

    arrival_orders = len(in_window)
    cancelled_orders = status_counter["cancelled"]
    return {
        "population_id": "pms_arrival_cohort",
        "population_definition": "latest JD01 order scope with arrival_time in requested window",
        "window_field": "arrival_time",
        "window_start": window_start.isoformat(sep=" "),
        "window_end": window_end.isoformat(sep=" "),
        "as_of_datetime": as_of.isoformat(sep=" "),
        "source": "jd01_booking_detail",
        "grain": "hotel_id+source_platform+order_id latest as-of",
        "unit": "arrival_orders_booked_rooms_and_stay_duration",
        "arrival_order_count": arrival_orders,
        "booked_rooms": booked_rooms,
        "current_cancelled_orders": cancelled_orders,
        "current_cancelled_share": _ratio(cancelled_orders, arrival_orders),
        "current_non_cancelled_orders": arrival_orders - cancelled_orders,
        "unknown_status_orders": status_counter["other_or_unknown"],
        "stay_duration_buckets": _distribution(stay_buckets, arrival_orders, unit="orders"),
        "long_stay_share": _ratio(
            sum(1 for nights in overnight_values if nights >= 2),
            len(overnight_values),
        ),
        "room_type_order_distribution": _distribution(
            room_type_orders,
            arrival_orders - unmapped_count,
            unit="orders",
        ),
        "room_type_room_distribution": _distribution(
            room_type_rooms,
            booked_rooms,
            unit="rooms",
        ),
        "unmapped_count": unmapped_count,
        "missing_dedup_key_count": missing_dedup,
    }

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import os
import unicodedata
from collections import Counter, defaultdict
from typing import Any, Iterable


CANCELLED = {"取消", "已取消", "取消预订", "cancel", "cancelled", "canceled"}
ACTIVE_OR_STAYED = {
    "预订", "已预订", "入住", "已入住", "在住", "confirmed", "booked", "checked_in", "checkin", "staying"
}
OCCUPIED = {"入住", "已入住", "在住", "住客房", "住脏", "住净", "occupied", "checked_in", "inhouse", "stayover"}
DEFAULT_APPROVED_ROOM_CHARGE_SUBJECTS = frozenset({"房费"})


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    text = _text(value).replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def _ratio(numerator: float, denominator: float) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _latest(rows: Iterable[dict[str, Any]], key_fields: tuple[str, ...], as_of: dt.datetime) -> tuple[list[dict[str, Any]], int]:
    latest: dict[tuple[str, ...], tuple[dt.datetime, dict[str, Any]]] = {}
    missing = 0
    for row in rows:
        key = tuple(_text(row.get(field)) for field in key_fields)
        if any(not item for item in key):
            missing += 1
            continue
        captured = _datetime(row.get("snapshot_time") or row.get("collected_at") or row.get("updated_at"))
        if captured is None or captured > as_of:
            continue
        previous = latest.get(key)
        if previous is None or captured > previous[0]:
            latest[key] = (captured, row)
    return [item[1] for item in latest.values()], missing


def _status(value: Any) -> str:
    raw = _text(value).lower()
    if raw in CANCELLED:
        return "cancelled"
    if raw in ACTIVE_OR_STAYED:
        return "active_or_stayed"
    return "other_or_unknown"


def _booking_channel(product_tag: Any) -> str:
    raw = _text(product_tag).lower()
    if raw.startswith("美团") or raw.startswith("meituan"):
        return "meituan"
    if raw.startswith("飞猪") or raw.startswith("fliggy"):
        return "fliggy"
    return "unknown"


def _lead_bucket(days: int | None) -> str:
    if days is None or days < 0:
        return "invalid_negative_or_missing"
    if days == 0:
        return "same_day"
    if days <= 3:
        return "1_3_days"
    if days <= 7:
        return "4_7_days"
    if days <= 14:
        return "8_14_days"
    if days <= 30:
        return "15_30_days"
    return "31_plus_days"


def _stay_bucket(arrival: dt.datetime | None, departure: dt.datetime | None) -> tuple[str, int | None]:
    if arrival is None or departure is None or departure <= arrival:
        return "invalid_nonpositive_duration", None
    nights = (departure.date() - arrival.date()).days
    if nights == 0:
        return "same_day_or_day_use", 0
    if nights == 1:
        return "1_night", nights
    if nights == 2:
        return "2_nights", nights
    if nights <= 4:
        return "3_4_nights", nights
    if nights <= 7:
        return "5_7_nights", nights
    return "8_plus_nights", nights


def _normalize_contact(value: Any) -> str | None:
    raw = unicodedata.normalize("NFKC", _text(value))
    if not raw or raw.lower() in {"无", "未知", "unknown", "null", "none", "-", "--"}:
        return None
    normalized = "".join(character for character in raw if character not in " -()（）.")
    if normalized.startswith("+86"):
        normalized = normalized[3:]
    elif normalized.startswith("0086"):
        normalized = normalized[4:]
    return normalized if len(normalized) >= 6 else None


def _contact_key(hotel_id: str, value: Any, secret: str) -> str | None:
    normalized = _normalize_contact(value)
    if normalized is None:
        return None
    message = f"{hotel_id}\0{normalized}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _distribution(counter: Counter[str], denominator: int | float, *, unit: str) -> list[dict[str, Any]]:
    return [
        {"name": key, "value": value, "share": _ratio(value, denominator), "unit": unit}
        for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def _approved_room_charge_subjects() -> frozenset[str]:
    configured = os.environ.get("HOTEL_OTA_S17_APPROVED_ROOM_CHARGE_SUBJECTS", "")
    values = {_text(item) for item in configured.split(",") if _text(item)}
    return frozenset(values) if values else DEFAULT_APPROVED_ROOM_CHARGE_SUBJECTS


def aggregate_bookings(
    rows: list[dict[str, Any]], *, hotel_id: str, window_start: dt.datetime, window_end: dt.datetime,
    as_of: dt.datetime, contact_hmac_secret: str | None, contact_lookup_value: str | None = None,
) -> dict[str, Any]:
    scoped = [row for row in rows if _text(row.get("hotel_id")) == hotel_id]
    latest, missing_dedup = _latest(scoped, ("source_platform", "order_id"), as_of)
    in_window: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    for row in latest:
        booking_time = _datetime(row.get("booking_time"))
        if booking_time is None or booking_time >= window_end:
            continue
        history.append(row)
        if booking_time >= window_start:
            in_window.append(row)

    status_counter: Counter[str] = Counter()
    channel_orders: Counter[str] = Counter()
    channel_rooms: Counter[str] = Counter()
    guest_source_orders: Counter[str] = Counter()
    room_type_orders: Counter[str] = Counter()
    room_type_rooms: Counter[str] = Counter()
    lead_buckets: Counter[str] = Counter()
    stay_buckets: Counter[str] = Counter()
    booking_matrix: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: {
        "created_order_count": 0, "active_order_count": 0, "booked_rooms": 0, "active_booked_rooms": 0
    })
    lead_values: list[int] = []
    overnight_values: list[int] = []
    unmapped_count = 0
    contact_counts: dict[str, dict[str, int]] = defaultdict(lambda: {"all": 0, "non_cancelled": 0, "stayed": 0})
    prior_contact_keys: set[str] = set()
    invalid_contact_count = 0

    if contact_hmac_secret:
        for row in history:
            booking_time = _datetime(row.get("booking_time"))
            key = _contact_key(hotel_id, row.get("contact"), contact_hmac_secret)
            if key and booking_time and booking_time < window_start:
                prior_contact_keys.add(key)

    for row in in_window:
        normalized_status = _status(row.get("booking_status") or row.get("order_status"))
        status_counter[normalized_status] += 1
        rooms = max(int(_number(row.get("room_count")) or 0), 0)
        channel = _booking_channel(row.get("member_level") or row.get("booking_product_tag"))
        guest_source = _text(row.get("guest_source")) or "unknown"
        room_type_id = _text(row.get("room_type_id"))
        channel_orders[channel] += 1
        channel_rooms[channel] += rooms
        guest_source_orders[guest_source] += 1
        if room_type_id:
            room_type_orders[room_type_id] += 1
            room_type_rooms[room_type_id] += rooms
            cell = booking_matrix[(channel, guest_source, room_type_id)]
            cell["created_order_count"] += 1
            cell["booked_rooms"] += rooms
            if normalized_status != "cancelled":
                cell["active_order_count"] += 1
                cell["active_booked_rooms"] += rooms
        else:
            unmapped_count += 1

        booking_time = _datetime(row.get("booking_time"))
        arrival = _datetime(row.get("arrival_time"))
        departure = _datetime(row.get("departure_time"))
        lead_days = (arrival.date() - booking_time.date()).days if booking_time and arrival else None
        lead_buckets[_lead_bucket(lead_days)] += 1
        if lead_days is not None and lead_days >= 0:
            lead_values.append(lead_days)
        duration_bucket, nights = _stay_bucket(arrival, departure)
        stay_buckets[duration_bucket] += 1
        if nights and nights > 0:
            overnight_values.append(nights)

        if contact_hmac_secret:
            key = _contact_key(hotel_id, row.get("contact"), contact_hmac_secret)
            if key is None:
                invalid_contact_count += 1
            else:
                contact_counts[key]["all"] += 1
                if normalized_status != "cancelled":
                    contact_counts[key]["non_cancelled"] += 1
                if normalized_status == "active_or_stayed" and _text(row.get("booking_status")).lower() in {
                    "入住", "已入住", "在住", "checked_in", "checkin", "staying"
                }:
                    contact_counts[key]["stayed"] += 1

    created = len(in_window)
    booked_rooms = sum(channel_rooms.values())
    cancelled_orders = status_counter["cancelled"]
    current_non_cancelled_orders = created - cancelled_orders
    known_channel_orders_counter = Counter({key: value for key, value in channel_orders.items() if key != "unknown"})
    known_channel_rooms_counter = Counter({key: value for key, value in channel_rooms.items() if key != "unknown"})
    known_channels = sum(known_channel_orders_counter.values())
    known_channel_rooms = sum(known_channel_rooms_counter.values())
    known_contacts = len(contact_counts)
    seen_before = sum(1 for key in contact_counts if key in prior_contact_keys)
    eligible = sum(1 for counts in contact_counts.values() if counts["non_cancelled"] >= 1)
    repeat_contacts = sum(1 for counts in contact_counts.values() if counts["non_cancelled"] >= 2)
    non_cancelled_orders = sum(counts["non_cancelled"] for counts in contact_counts.values())
    repeat_orders = sum(max(counts["non_cancelled"] - 1, 0) for counts in contact_counts.values())
    stayed_contacts = sum(1 for counts in contact_counts.values() if counts["stayed"] >= 1)
    repeat_stayed_contacts = sum(1 for counts in contact_counts.values() if counts["stayed"] >= 2)
    contact_frequency = Counter(
        "1_order" if counts["all"] == 1 else "2_orders" if counts["all"] == 2 else "3_4_orders" if counts["all"] <= 4 else "5_plus_orders"
        for counts in contact_counts.values()
    )
    contact_proxy_status = "ok" if contact_hmac_secret and known_contacts > 0 else "unavailable"
    contact_proxy_reason = None
    if not contact_hmac_secret:
        contact_proxy_reason = "contact_hmac_secret_missing"
    elif known_contacts == 0:
        contact_proxy_reason = "contact_semantic_unavailable_or_masked"
    lookup_counts = None
    if contact_proxy_status == "ok" and contact_lookup_value:
        lookup_key = _contact_key(hotel_id, contact_lookup_value, contact_hmac_secret)
        if lookup_key:
            counts = {"all": 0, "non_cancelled": 0, "stayed": 0}
            for row in history:
                if _contact_key(hotel_id, row.get("contact"), contact_hmac_secret) != lookup_key:
                    continue
                normalized_status = _status(row.get("booking_status") or row.get("order_status"))
                counts["all"] += 1
                if normalized_status != "cancelled":
                    counts["non_cancelled"] += 1
                if normalized_status == "active_or_stayed" and _text(row.get("booking_status")).lower() in {
                    "入住", "已入住", "在住", "checked_in", "checkin", "staying"
                }:
                    counts["stayed"] += 1
            lookup_counts = {
                "all_order_count": counts["all"],
                "non_cancelled_order_count": counts["non_cancelled"],
                "checked_in_or_stayed_order_count": counts["stayed"],
                "contact_semantics": "booking_contact_value",
            }
    return {
        "population_id": "pms_booking_created",
        "population_definition": "latest JD01 order scope created in requested window",
        "window_field": "booking_time",
        "window_start": window_start.isoformat(sep=" "),
        "window_end": window_end.isoformat(sep=" "),
        "as_of_datetime": as_of.isoformat(sep=" "),
        "source": "jd01_booking_detail",
        "grain": "hotel_id+source_platform+order_id latest as-of",
        "unit": "orders_and_booked_rooms",
        "created_order_count": created,
        "booked_rooms": booked_rooms,
        "current_cancelled_orders": cancelled_orders,
        "current_cancelled_share": _ratio(cancelled_orders, created),
        "current_non_cancelled_orders": current_non_cancelled_orders,
        "active_or_stayed_orders": status_counter["active_or_stayed"],
        "unknown_status_orders": status_counter["other_or_unknown"],
        "unknown_status_share": _ratio(status_counter["other_or_unknown"], created),
        "booking_channel_order_distribution": _distribution(known_channel_orders_counter, known_channels, unit="orders"),
        "booking_channel_room_distribution": _distribution(known_channel_rooms_counter, known_channel_rooms, unit="rooms"),
        "booking_channel_unknown_orders": channel_orders.get("unknown", 0),
        "booking_channel_unknown_rooms": channel_rooms.get("unknown", 0),
        "booking_channel_known_order_coverage": _ratio(known_channels, created),
        "booking_channel_known_room_coverage": _ratio(known_channel_rooms, booked_rooms),
        "guest_source_order_distribution": _distribution(guest_source_orders, created, unit="orders"),
        "room_type_order_distribution": _distribution(room_type_orders, created - unmapped_count, unit="orders"),
        "room_type_room_distribution": _distribution(room_type_rooms, booked_rooms, unit="rooms"),
        "booking_matrix": [
            {"booking_channel": key[0], "guest_source_class": key[1], "room_type_id": key[2], **value}
            for key, value in sorted(booking_matrix.items())
        ],
        "lead_time_buckets": _distribution(lead_buckets, created, unit="orders"),
        "average_lead_time_days": round(sum(lead_values) / len(lead_values), 2) if lead_values else None,
        "stay_duration_buckets": _distribution(stay_buckets, created, unit="orders"),
        "long_stay_share": _ratio(sum(1 for nights in overnight_values if nights >= 2), len(overnight_values)),
        "unmapped_count": unmapped_count,
        "missing_dedup_key_count": missing_dedup,
        "contact_proxy": {
            "status": contact_proxy_status,
            "reason": contact_proxy_reason,
            "contact_semantics": "booking_contact_value",
            "eligible_contact_keys": eligible,
            "repeat_contact_keys": repeat_contacts,
            "contact_seen_before_share_proxy": _ratio(seen_before, known_contacts),
            "repeat_booking_contact_share_proxy": _ratio(repeat_contacts, eligible),
            "repeat_booking_order_share_proxy": _ratio(repeat_orders, non_cancelled_orders),
            "repeat_stayed_contact_share_proxy": _ratio(repeat_stayed_contacts, stayed_contacts),
            "contact_frequency_distribution": _distribution(contact_frequency, known_contacts, unit="contact_proxy_keys"),
            "invalid_contact_count": invalid_contact_count,
            "verified_customer_repeat_rate": None,
            "person_visit_count": None,
            "maturity": "weak_proxy" if contact_proxy_status == "ok" else "unavailable",
            "exact_lookup": lookup_counts,
        },
    }


def aggregate_realized(rows: list[dict[str, Any]], *, hotel_id: str, window_start: dt.datetime, window_end: dt.datetime, as_of: dt.datetime) -> dict[str, Any]:
    scoped = [row for row in rows if _text(row.get("hotel_id")) == hotel_id]
    latest, missing = _latest(scoped, ("business_date", "source_platform", "order_id", "room_no", "charge_subject"), as_of)
    approved_subjects = _approved_room_charge_subjects()
    source_nights: Counter[str] = Counter()
    source_fee: Counter[str] = Counter()
    source_records: Counter[str] = Counter()
    room_nights: Counter[str] = Counter()
    room_fee: Counter[str] = Counter()
    room_records: Counter[str] = Counter()
    reconciliation_amount = 0.0
    excluded_unapproved_charge_amount = 0.0
    excluded_unapproved_charge_record_count = 0
    unmapped = 0
    for row in latest:
        business_time = _datetime(row.get("business_date"))
        if business_time is None or not window_start <= business_time < window_end:
            continue
        nights = max(_number(row.get("room_nights")) or 0, 0)
        fee = _number(row.get("room_fee")) or 0
        charge_subject = _text(row.get("charge_subject"))
        source = _text(row.get("customer_source")) or "unknown"
        room_type_id = _text(row.get("room_type_id"))
        if nights == 0:
            reconciliation_amount += fee
            continue
        if charge_subject not in approved_subjects:
            excluded_unapproved_charge_record_count += 1
            excluded_unapproved_charge_amount += fee
            continue
        source_nights[source] += nights
        source_fee[source] += fee
        source_records[source] += 1
        if room_type_id:
            room_nights[room_type_id] += nights
            room_fee[room_type_id] += fee
            room_records[room_type_id] += 1
        else:
            unmapped += 1
    total_nights = float(sum(source_nights.values()))
    total_fee = float(sum(source_fee.values()))
    return {
        "population_id": "realized_stay",
        "population_definition": "latest approved RS01 room-fee records in business-date window",
        "window_field": "business_date",
        "window_start": window_start.isoformat(sep=" "),
        "window_end": window_end.isoformat(sep=" "),
        "as_of_datetime": as_of.isoformat(sep=" "),
        "source": "rs01_room_revenue_daily",
        "grain": "business_date+source_platform+order_id+room_no+charge_subject latest as-of",
        "unit": "room_nights_currency_and_adr",
        "approved_charge_subjects": sorted(approved_subjects),
        "charge_subject_policy_revision": "s17-room-charge-subjects.v1",
        "realized_room_nights": total_nights,
        "realized_room_fee": round(total_fee, 2),
        "realized_adr": round(total_fee / total_nights, 2) if total_nights else None,
        "source_distribution": [
            {"customer_source": key, "realized_room_nights": nights, "realized_room_fee": round(source_fee[key], 2),
             "record_count": source_records[key], "room_night_share": _ratio(nights, total_nights), "revenue_share": _ratio(source_fee[key], total_fee)}
            for key, nights in source_nights.most_common()
        ],
        "room_type_distribution": [
            {"room_type_id": key, "realized_room_nights": nights, "realized_room_fee": round(room_fee[key], 2),
             "record_count": room_records[key], "realized_adr": round(room_fee[key] / nights, 2) if nights else None}
            for key, nights in room_nights.most_common()
        ],
        "reconciliation_amount": round(reconciliation_amount, 2),
        "excluded_unapproved_charge_record_count": excluded_unapproved_charge_record_count,
        "excluded_unapproved_charge_amount": round(excluded_unapproved_charge_amount, 2),
        "unmapped_count": unmapped,
        "missing_dedup_key_count": missing,
    }


def aggregate_physical(rows: list[dict[str, Any]], *, hotel_id: str, business_date: dt.date, as_of: dt.datetime) -> dict[str, Any]:
    scoped = [row for row in rows if _text(row.get("hotel_id")) == hotel_id and _datetime(row.get("snapshot_time")) and _datetime(row.get("snapshot_time")) <= as_of]
    snapshots = [_datetime(row.get("snapshot_time")) for row in scoped if _datetime(row.get("business_date")) and _datetime(row.get("business_date")).date() == business_date]
    selected = max((value for value in snapshots if value), default=None)
    batch = [row for row in scoped if _datetime(row.get("snapshot_time")) == selected] if selected else []
    latest, missing = _latest(batch, ("room_no",), as_of)
    occupied = Counter()
    unmapped = 0
    for row in latest:
        if _text(row.get("room_status")).lower() not in OCCUPIED:
            continue
        room_type_id = _text(row.get("room_type_id"))
        if room_type_id:
            occupied[room_type_id] += 1
        else:
            unmapped += 1
    return {
        "population_id": "physical_occupancy",
        "population_definition": "occupied rooms in the latest complete KF11 snapshot batch",
        "window_field": "exact_business_date_and_snapshot_time",
        "business_date": business_date.isoformat(),
        "as_of_datetime": as_of.isoformat(sep=" "),
        "source": "kf11_room_status_snapshot",
        "grain": "latest complete snapshot batch then latest room_no",
        "unit": "rooms",
        "snapshot_time": selected.isoformat(sep=" ") if selected else None,
        "physical_occupied_rooms": sum(occupied.values()) + unmapped,
        "room_type_distribution": [{"room_type_id": key, "physical_occupied_rooms": value} for key, value in occupied.most_common()],
        "unmapped_count": unmapped,
        "missing_dedup_key_count": missing,
    }


def aggregate_extensions(rows: list[dict[str, Any]], *, hotel_id: str, as_of: dt.datetime) -> dict[str, Any]:
    scoped = [row for row in rows if _text(row.get("hotel_id")) == hotel_id]
    latest, missing = _latest(scoped, ("source_platform", "order_id", "room_no"), as_of)
    active = Counter()
    extended_hours = 0.0
    unmapped = 0
    for row in latest:
        checkin = _datetime(row.get("checkin_time"))
        checkout = _datetime(row.get("checkout_time"))
        if not checkin or not checkout or not checkin <= as_of < checkout:
            continue
        room_type_id = _text(row.get("room_type_id"))
        if room_type_id:
            active[room_type_id] += 1
        else:
            unmapped += 1
        original = _datetime(row.get("original_checkout_time"))
        if original and checkout > original:
            extended_hours += (checkout - original).total_seconds() / 3600
    return {
        "population_id": "extension_reconciliation",
        "population_definition": "latest JD04 records active at as-of by approved interval rule",
        "window_field": "checkin_time<=as_of_datetime<checkout_time",
        "as_of_datetime": as_of.isoformat(sep=" "),
        "source": "jd04_inhouse_extension",
        "grain": "source_platform+order_id+room_no latest as-of",
        "unit": "records_and_hours",
        "active_extension_records": sum(active.values()) + unmapped,
        "extended_hours": round(extended_hours, 2),
        "room_type_distribution": [{"room_type_id": key, "active_extension_records": value} for key, value in active.most_common()],
        "unmapped_count": unmapped,
        "missing_dedup_key_count": missing,
    }


def suppress_cells(cells: list[dict[str, Any]], *, count_field: str, minimum_cohort_size: int, max_output_cells: int) -> tuple[list[dict[str, Any]], int]:
    visible: list[dict[str, Any]] = []
    primary_suppressed = 0
    for cell in cells:
        cohort = int(_number(cell.get(count_field)) or 0)
        if cohort < minimum_cohort_size:
            primary_suppressed += 1
            continue
        visible.append({**cell, "privacy_cohort_size": cohort, "suppression_status": "visible"})
    complementary_suppressed = 0
    if primary_suppressed == 1 and visible:
        # A single hidden cell can be recovered from a displayed total and all
        # remaining cells. Hide the smallest remaining cell before ordering or paging.
        smallest = min(range(len(visible)), key=lambda index: visible[index]["privacy_cohort_size"])
        visible.pop(smallest)
        complementary_suppressed = 1
    visible.sort(key=lambda cell: (-int(cell["privacy_cohort_size"]), str(cell)))
    truncated = max(len(visible) - max_output_cells, 0)
    return visible[:max_output_cells], primary_suppressed + complementary_suppressed + truncated

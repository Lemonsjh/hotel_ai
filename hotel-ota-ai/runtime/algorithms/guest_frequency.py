from __future__ import annotations

import datetime as dt
import unicodedata
from collections import Counter, defaultdict
from typing import Any

from runtime.algorithms.customer_order import (
    _contact_key,
    _datetime,
    _latest,
    _number,
    _ratio,
    _text,
)


_INVALID_GUEST_NAMES = {
    "无",
    "未知",
    "unknown",
    "null",
    "none",
    "-",
    "--",
    "散客",
    "客人",
    "住客",
}


def normalize_guest_name(value: Any) -> str | None:
    """Normalize a PMS guest name conservatively without fuzzy matching."""
    raw = unicodedata.normalize("NFKC", _text(value))
    raw = " ".join(raw.split()).strip()
    if not raw or raw.casefold() in _INVALID_GUEST_NAMES:
        return None
    return raw.casefold()


def guest_frequency_level(visit_count: int) -> str:
    """Classify realized arrivals only inside the selected S17 window."""
    if visit_count <= 0:
        return "窗口内0次"
    if visit_count == 1:
        return "窗口内1次"
    if visit_count == 2:
        return "窗口内2次"
    if visit_count <= 4:
        return "窗口内3–4次"
    return "窗口内5次及以上"


def _safe_contact_key(hotel_id: str, value: Any, secret: str | None) -> str | None:
    if not secret:
        return None
    raw = _text(value)
    lowered = raw.lower()
    if not raw or "*" in raw or "脱敏" in raw or lowered in {"unknown", "masked", "null", "none"}:
        return None
    return _contact_key(hotel_id, raw, secret)


def _visit_time(row: dict[str, Any]) -> dt.datetime | None:
    return _datetime(row.get("checkin_time")) or _datetime(row.get("business_date"))


def _visit_key(row: dict[str, Any], guest_key: str) -> tuple[str, ...]:
    order_id = _text(row.get("order_id"))
    source_platform = _text(row.get("source_platform")) or "pms"
    if order_id:
        return ("order", source_platform, order_id)
    checkin = _datetime(row.get("checkin_time"))
    checkout = _datetime(row.get("checkout_time"))
    return (
        "fallback",
        guest_key,
        checkin.isoformat(sep=" ") if checkin else "",
        checkout.isoformat(sep=" ") if checkout else "",
    )


def aggregate_real_guest_frequency(
    realized_rows: list[dict[str, Any]],
    booking_rows: list[dict[str, Any]],
    *,
    hotel_id: str,
    window_start: dt.datetime,
    window_end: dt.datetime,
    as_of: dt.datetime,
    contact_hmac_secret: str | None,
    guest_name_lookup: str | None = None,
) -> dict[str, Any]:
    """Count realized PMS visits by guest_name, with contact as corroboration only.

    Valid-name population and realized-frequency population are intentionally
    separate. A valid normalized RS01 guest_name is counted in the window even
    when that row cannot establish a realized stay. Frequency requires positive
    room_nights, but never depends on charge_subject because charge subject is a
    revenue classification rather than stay evidence. Repeated charge rows for
    the same realized order collapse to one visit.
    """
    scoped_realized = [
        row for row in realized_rows if _text(row.get("hotel_id")) == hotel_id
    ]
    latest_realized, missing_dedup = _latest(
        scoped_realized,
        ("business_date", "source_platform", "order_id", "room_no", "charge_subject"),
        as_of,
    )

    scoped_bookings = [
        row for row in booking_rows if _text(row.get("hotel_id")) == hotel_id
    ]
    latest_bookings, _ = _latest(
        scoped_bookings, ("source_platform", "order_id"), as_of
    )

    contacts_by_order: dict[tuple[str, str], set[str]] = defaultdict(set)
    contacts_by_order_id: dict[str, set[str]] = defaultdict(set)
    for row in latest_bookings:
        order_id = _text(row.get("order_id"))
        if not order_id:
            continue
        contact_key = _safe_contact_key(
            hotel_id, row.get("contact"), contact_hmac_secret
        )
        if not contact_key:
            continue
        source_platform = _text(row.get("source_platform")) or "pms"
        contacts_by_order[(source_platform, order_id)].add(contact_key)
        contacts_by_order_id[order_id].add(contact_key)

    valid_guest_names: set[str] = set()
    visits_by_guest: dict[str, dict[tuple[str, ...], dt.datetime]] = defaultdict(dict)
    display_name_by_guest: dict[str, str] = {}
    contacts_by_guest: dict[str, set[str]] = defaultdict(set)
    missing_name_count = 0
    fallback_visit_key_count = 0

    for row in latest_realized:
        visit_time = _visit_time(row)
        if visit_time is None or not window_start <= visit_time < window_end:
            continue

        guest_key = normalize_guest_name(row.get("guest_name"))
        if guest_key:
            valid_guest_names.add(guest_key)
            display_name_by_guest.setdefault(
                guest_key,
                unicodedata.normalize("NFKC", _text(row.get("guest_name"))).strip(),
            )

        nights = max(_number(row.get("room_nights")) or 0, 0)
        if nights <= 0:
            continue
        if not guest_key:
            missing_name_count += 1
            continue

        visit_key = _visit_key(row, guest_key)
        if visit_key[0] == "fallback":
            fallback_visit_key_count += 1
        previous_time = visits_by_guest[guest_key].get(visit_key)
        if previous_time is None or visit_time < previous_time:
            visits_by_guest[guest_key][visit_key] = visit_time

        order_id = _text(row.get("order_id"))
        if order_id:
            source_platform = _text(row.get("source_platform")) or "pms"
            corroborating = contacts_by_order.get((source_platform, order_id))
            if not corroborating:
                corroborating = contacts_by_order_id.get(order_id)
            if corroborating:
                contacts_by_guest[guest_key].update(corroborating)

    frequency_counter: Counter[str] = Counter()
    for guest_key, visits in visits_by_guest.items():
        frequency_counter[guest_frequency_level(len(visits))] += 1

    frequency_guest_count = len(visits_by_guest)
    level_order = {
        "窗口内1次": 0,
        "窗口内2次": 1,
        "窗口内3–4次": 2,
        "窗口内5次及以上": 3,
    }
    frequency_distribution = [
        {
            "name": level,
            "value": count,
            "share": _ratio(count, frequency_guest_count),
            "unit": "guest_name_keys",
        }
        for level, count in sorted(
            frequency_counter.items(), key=lambda item: level_order.get(item[0], 99)
        )
    ]
    guest_name_visit_counts = [
        {
            "guest_name": display_name_by_guest.get(guest_key, guest_key),
            "visit_count": len(visits),
        }
        for guest_key, visits in sorted(
            visits_by_guest.items(),
            key=lambda item: (
                -len(item[1]),
                display_name_by_guest.get(item[0], item[0]).casefold(),
            ),
        )
    ]

    exact_lookup = None
    if guest_name_lookup is not None:
        lookup_key = normalize_guest_name(guest_name_lookup)
        if lookup_key:
            visits = visits_by_guest.get(lookup_key, {})
            ordered_times = sorted(visits.values())
            contact_key_count = len(contacts_by_guest.get(lookup_key, set()))
            warnings: list[str] = []
            if contact_key_count > 1:
                warnings.append("same_name_multiple_contacts")
            if not contact_hmac_secret:
                warnings.append("contact_corroboration_unavailable_hmac_secret_missing")
            elif contact_key_count == 0:
                warnings.append("contact_corroboration_unavailable_or_not_joined")
            exact_lookup = {
                "guest_name": display_name_by_guest.get(
                    lookup_key,
                    unicodedata.normalize("NFKC", _text(guest_name_lookup)).strip(),
                ),
                "visit_count": len(visits),
                "frequency_level": guest_frequency_level(len(visits)),
                "first_arrival_date": ordered_times[0].date().isoformat()
                if ordered_times
                else None,
                "last_arrival_date": ordered_times[-1].date().isoformat()
                if ordered_times
                else None,
                "primary_identity_key": "guest_name",
                "identity_scope": "exact_hotel_id",
                "identity_status": "needs_check"
                if contact_key_count > 1
                else "ok",
                "contact_corroboration": (
                    "multiple_contacts_same_name"
                    if contact_key_count > 1
                    else "single_consistent_contact"
                    if contact_key_count == 1
                    else "unavailable"
                ),
                "warnings": warnings,
                "raw_contact_included": False,
            }

    valid_guest_name_count = len(valid_guest_names)
    return {
        "population_id": "real_guest_frequency",
        "population_definition": (
            "window-valid RS01 guest names plus realized PMS visit frequency from positive room_nights, "
            "grouped by guest_name within exact hotel scope"
        ),
        "status": "ok" if valid_guest_name_count > 0 else "unavailable",
        "reason": None if valid_guest_name_count > 0 else "no_valid_guest_names_in_window",
        "source": "rs01_room_revenue_daily+jd01_booking_detail_contact_corroboration",
        "window_field": "checkin_time_fallback_business_date",
        "window_start": window_start.isoformat(sep=" "),
        "window_end": window_end.isoformat(sep=" "),
        "as_of_datetime": as_of.isoformat(sep=" "),
        "primary_identity_key": "guest_name",
        "identity_scope": "hotel_id+normalized_guest_name",
        "identity_match_policy": "exact_normalized_name_no_fuzzy_matching",
        "contact_role": "auxiliary_corroboration_only_not_primary_key",
        "customer_name_total_rule": "distinct_normalized_valid_guest_name_in_window",
        "frequency_evaluable_name_rule": "valid_guest_name_with_positive_room_nights_realized_stay_evidence",
        "visit_count_rule": "distinct_realized_stay_order_per_guest_name_independent_of_charge_subject",
        "charge_subject_filter_for_frequency": False,
        "frequency_level_rule": {
            "1": "窗口内1次",
            "2": "窗口内2次",
            "3-4": "窗口内3–4次",
            "5+": "窗口内5次及以上",
        },
        "valid_guest_name_count": valid_guest_name_count,
        "realized_frequency_guest_name_count": frequency_guest_count,
        "unique_guest_name_count": frequency_guest_count,
        "unique_guest_name_count_semantics": "realized_frequency_guest_name_count",
        "frequency_distribution": frequency_distribution,
        "guest_name_visit_counts": guest_name_visit_counts,
        "missing_guest_name_record_count": missing_name_count,
        "fallback_visit_key_record_count": fallback_visit_key_count,
        "missing_dedup_key_count": missing_dedup,
        "exact_lookup": exact_lookup,
        "bulk_guest_name_list_included": bool(guest_name_visit_counts),
        "raw_contact_included": False,
        "contact_fingerprint_included": False,
        "direct_action_allowed": False,
    }


__all__ = [
    "aggregate_real_guest_frequency",
    "guest_frequency_level",
    "normalize_guest_name",
]

from __future__ import annotations

import datetime as dt
from typing import Any


FORMULA_VERSION = "jd01_jd04_kf11_realtime_occupancy_v1"
KF11_OCCUPIED_ALIASES = {
    "住脏",
    "住净",
    "住修",
    "在住",
    "occupied",
    "in_house",
    "staying",
}

CHECKED_IN_ALIASES = {"已入住", "入住", "在住", "checked_in", "checkin", "in_house", "staying"}
RESERVED_ALIASES = {"预订", "已预订", "reserved", "booked", "confirmed"}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    text = str(value).strip()
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = dt.datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            continue
    return None


def _date_part(value: Any) -> str | None:
    parsed = _parse_datetime(value)
    if parsed is not None:
        return parsed.date().isoformat()
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else None


def _resolve_as_of(value: Any, business_date: str) -> dt.datetime | None:
    if isinstance(value, str) and len(value.strip()) <= 5 and ":" in value:
        value = f"{business_date} {value.strip()}:00"
    return _parse_datetime(value)


def _status_text(row: dict[str, Any]) -> str:
    return str(
        row.get("booking_status")
        or row.get("booking_Status")
        or row.get("status")
        or row.get("order_status")
        or row.get("room_status")
        or ""
    ).strip().lower()


def _status_matches(status: str, aliases: set[str]) -> bool:
    normalized = status.strip().lower()
    return any(alias.lower() == normalized or alias.lower() in normalized for alias in aliases)


def _dedupe_key(row: dict[str, Any], index: int) -> tuple[str, str]:
    room_no = str(row.get("room_no") or "").strip()
    if room_no and "***" not in room_no:
        return ("room_no", room_no)
    order_id = str(row.get("order_id") or row.get("order_no") or row.get("reservation_id") or "").strip()
    if order_id and "***" not in order_id:
        return ("order_id", order_id)
    return ("row_missing_key", f"row-{index}")


def _row_units(row: dict[str, Any]) -> int:
    value = row.get("room_count") or row.get("rooms") or row.get("room_nights") or 1
    try:
        return max(int(round(float(value))), 1)
    except (TypeError, ValueError):
        return 1


def _kf11_occupied_rooms(payload: dict[str, Any]) -> int | None:
    rows = _rows(payload)
    if not rows:
        value = payload.get("occupied_rooms") or payload.get("inhouse_rooms") or payload.get("checked_in_rooms")
        try:
            return int(round(float(value))) if value is not None else None
        except (TypeError, ValueError):
            return None
    seen: set[tuple[str, str]] = set()
    occupied = 0
    occupied_aliases = {item.lower() for item in KF11_OCCUPIED_ALIASES}
    for index, row in enumerate(rows):
        status = str(row.get("room_status") or row.get("status") or "").strip().lower()
        if status not in occupied_aliases and not status.startswith("住"):
            continue
        key = _dedupe_key(row, index)
        if key in seen:
            continue
        seen.add(key)
        occupied += 1
    return occupied


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("realtime_rows") or payload.get("rows") or payload.get("records") or []
    return [dict(item) for item in rows if isinstance(item, dict)]


def _max_snapshot_time(*payloads: dict[str, Any]) -> str | None:
    values = [
        payload.get("data_snapshot_time") or payload.get("snapshot_time") or payload.get("captured_at")
        for payload in payloads
        if payload
    ]
    values = [str(value) for value in values if value not in (None, "")]
    return max(values) if values else None


def build_realtime_occupancy(
    *,
    operating_payload: dict[str, Any],
    reservation_payload: dict[str, Any],
    stayover_payload: dict[str, Any],
    business_date: str,
    as_of_time: str | None = None,
) -> dict[str, Any]:
    business_date = str(business_date)[:10]
    as_of = _resolve_as_of(as_of_time, business_date)
    total_rooms = int(round(_to_float(operating_payload.get("total_rooms") or operating_payload.get("room_count"), 0)))
    maintenance_rooms = int(round(_to_float(operating_payload.get("maintenance_rooms") or operating_payload.get("maintain_rooms"), 0)))
    dirty_rooms = int(round(_to_float(operating_payload.get("dirty_rooms"), 0)))
    kf11_occupied_rooms = _kf11_occupied_rooms(operating_payload)
    if as_of is None:
        denominator = max(total_rooms - maintenance_rooms, 0)
        return {
            "status": "data_gap",
            "reason": "realtime_occupancy_as_of_time_required",
            "formula_version": FORMULA_VERSION,
            "actual_numerator_rooms": None,
            "denominator_rooms": denominator if denominator > 0 else None,
            "actual_occupancy_rate": None,
            "kf11_occupied_rooms": kf11_occupied_rooms,
            "maintenance_rooms": maintenance_rooms,
            "dirty_rooms": dirty_rooms,
            "total_rooms": total_rooms,
            "duplicate_risk": False,
            "snapshot_time": _max_snapshot_time(operating_payload, reservation_payload, stayover_payload),
        }

    seen: set[tuple[str, str]] = set()
    duplicate_risk = False
    components = {
        "jd01_checked_in_departure_after_as_of": 0,
        "jd01_reserved_arrival_today": 0,
        "jd04_checkout_after_as_of": 0,
    }
    evidence_rows = 0
    component_evidence: set[str] = set()

    reservation_rows = _rows(reservation_payload)
    stayover_rows = _rows(stayover_payload)
    if reservation_rows:
        component_evidence.update(
            {
                "jd01_checked_in_departure_after_as_of",
                "jd01_reserved_arrival_today",
            }
        )
    if stayover_rows:
        component_evidence.add("jd04_checkout_after_as_of")

    explicit_component_fields = {
        "jd01_checked_in_departure_after_as_of": reservation_payload,
        "jd01_reserved_arrival_today": reservation_payload,
        "jd04_checkout_after_as_of": stayover_payload,
    }
    reservation_adjustment_components = {
        key: int(round(_to_float(reservation_payload.get(key), 0)))
        for key in ("jd01_reserved_raw_arrival_today", "jd01_cancelled_arrival_today")
        if key in reservation_payload
    }
    for component, payload in explicit_component_fields.items():
        if component in payload:
            component_evidence.add(component)

    def add(row: dict[str, Any], component: str, index: int) -> None:
        nonlocal duplicate_risk, evidence_rows
        key = _dedupe_key(row, index)
        if key[0] == "row_missing_key":
            duplicate_risk = True
        if key in seen:
            return
        seen.add(key)
        components[component] += _row_units(row)
        evidence_rows += 1

    for index, row in enumerate(reservation_rows):
        status = _status_text(row)
        departure = _parse_datetime(row.get("departure_time") or row.get("checkout_time") or row.get("curr_departure"))
        arrival_date = _date_part(row.get("arrival_time") or row.get("business_date") or row.get("checkin_time"))
        if _status_matches(status, CHECKED_IN_ALIASES) and departure and departure > as_of:
            add(row, "jd01_checked_in_departure_after_as_of", index)
        elif _status_matches(status, RESERVED_ALIASES) and arrival_date == business_date:
            add(row, "jd01_reserved_arrival_today", index)

    stayover_offset = len(reservation_rows)
    for index, row in enumerate(stayover_rows, start=stayover_offset):
        checkout = _parse_datetime(row.get("checkout_time") or row.get("departure_time") or row.get("curr_departure"))
        if checkout and checkout > as_of:
            add(row, "jd04_checkout_after_as_of", index)

    aggregate_fallback = False
    if evidence_rows == 0:
        for component, payload in explicit_component_fields.items():
            if component in payload:
                components[component] = int(round(_to_float(payload.get(component), 0)))

    numerator = sum(components.values())
    denominator = max(total_rooms - maintenance_rooms, 0)
    if denominator <= 0:
        return {
            "status": "data_gap",
            "reason": "realtime_occupancy_denominator_missing",
            "formula_version": FORMULA_VERSION,
            "total_rooms": total_rooms,
            "maintenance_rooms": maintenance_rooms,
            "dirty_rooms": dirty_rooms,
            "duplicate_risk": duplicate_risk,
        }
    missing_components = [component for component in components if component not in component_evidence]
    if missing_components:
        return {
            "status": "data_gap",
            "reason": "realtime_occupancy_formula_evidence_missing",
            "formula_version": FORMULA_VERSION,
            "actual_numerator_rooms": None,
            "denominator_rooms": denominator,
            "kf11_occupied_rooms": kf11_occupied_rooms,
            "kf11_formula_gap_rooms": None,
            "maintenance_rooms": maintenance_rooms,
            "dirty_rooms": dirty_rooms,
            "total_rooms": total_rooms,
            "numerator_components": components,
            "reservation_adjustment_components": reservation_adjustment_components,
            "denominator_components": {
                "total_rooms": total_rooms,
                "maintenance_rooms": maintenance_rooms,
                "dirty_rooms_not_deducted": dirty_rooms,
            },
            "missing_formula_components": missing_components,
            "duplicate_risk": duplicate_risk,
            "aggregate_fallback": aggregate_fallback,
            "as_of_time": as_of.strftime("%Y-%m-%d %H:%M:%S"),
            "snapshot_time": _max_snapshot_time(operating_payload, reservation_payload, stayover_payload),
        }
    occupancy_rate = round(min(max(numerator / denominator, 0.0), 1.0), 4)
    return {
        "status": "ok",
        "formula_version": FORMULA_VERSION,
        "occupancy_rate_source": "jd01_jd04_over_kf11_total_minus_maintenance",
        "actual_numerator_rooms": numerator,
        "denominator_rooms": denominator,
        "actual_occupancy_rate": occupancy_rate,
        "kf11_occupied_rooms": kf11_occupied_rooms,
        "kf11_formula_gap_rooms": (kf11_occupied_rooms - numerator) if kf11_occupied_rooms is not None else None,
        "maintenance_rooms": maintenance_rooms,
        "dirty_rooms": dirty_rooms,
        "total_rooms": total_rooms,
        "numerator_components": components,
        "reservation_adjustment_components": reservation_adjustment_components,
        "denominator_components": {
            "total_rooms": total_rooms,
            "maintenance_rooms": maintenance_rooms,
            "dirty_rooms_not_deducted": dirty_rooms,
        },
        "duplicate_risk": duplicate_risk,
        "aggregate_fallback": aggregate_fallback,
        "as_of_time": as_of.strftime("%Y-%m-%d %H:%M:%S"),
        "snapshot_time": _max_snapshot_time(operating_payload, reservation_payload, stayover_payload),
    }

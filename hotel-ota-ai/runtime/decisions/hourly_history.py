from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
DEFAULT_HOURLY_ANCHORS = [(7, 0.07), (10, 0.2), (12, 0.34), (15, 0.54), (16, 0.62), (18, 0.74), (20, 0.86), (22, 1.0)]
DEFAULT_PROGRESS_CHECKPOINTS = [(12, "midday"), (16, "afternoon"), (20, "evening_peak")]


def _safe_identifier(name: str, label: str = "identifier") -> str:
    if not name or not SAFE_IDENTIFIER.match(str(name)):
        raise ValueError(f"unsafe {label}: {name}")
    return f"`{name}`"


def _load_mapping_config(path: str | None = None) -> dict[str, Any] | None:
    config_path = path or os.environ.get("HOTEL_OTA_DB_MAPPING_CONFIG")
    if not config_path:
        return None
    with open(config_path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _profile(config: dict[str, Any] | None, profile_name: str | None = None) -> dict[str, Any] | None:
    if not config:
        return None
    profiles = config.get("profiles") or {}
    selected = profile_name or os.environ.get("HOTEL_OTA_DB_PROFILE") or config.get("default_profile")
    if not selected:
        return None
    profile = profiles.get(selected)
    if not isinstance(profile, dict):
        return None
    result = dict(profile)
    result["_profile_name"] = selected
    return result


def _dsn_from_profile(profile: dict[str, Any]) -> str:
    dsn_env = profile.get("dsn_env")
    return (os.environ.get(str(dsn_env)) if dsn_env else None) or os.environ.get("HOTEL_OTA_DB_DSN") or str(profile.get("dsn") or "")


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise ValueError("mysql DSN must start with mysql:// or mysql+pymysql://")
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/"),
        "charset": query.get("charset", ["utf8mb4"])[0],
        "connect_timeout": int(query.get("connect_timeout", ["10"])[0]),
    }


def _connect_mysql(profile: dict[str, Any]):
    import pymysql

    params = _parse_mysql_dsn(_dsn_from_profile(profile))
    return pymysql.connect(
        host=params["host"],
        port=params["port"],
        user=params["user"],
        password=params["password"],
        database=params["database"],
        charset=params["charset"],
        connect_timeout=params["connect_timeout"],
        read_timeout=20,
        write_timeout=20,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _hotel_name(profile: dict[str, Any], hotel_id: str) -> str:
    hotel = (profile.get("hotel_ids") or {}).get(hotel_id)
    if isinstance(hotel, dict):
        return str(hotel.get("hotel_name") or hotel.get("name") or hotel_id)
    if isinstance(hotel, str):
        return hotel
    return hotel_id


def _date_part(value: Any) -> dt.date | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    text = str(value).strip()[:10]
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def _datetime_value(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value
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


def _to_units(value: Any) -> int:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 1.0
    return max(int(round(number or 1)), 1)


def _target_from_ratio(target_room_nights: int, ratio: float, last: int) -> int:
    return max(last, int(round(target_room_nights * max(0.0, min(1.0, ratio)))))


def curve_from_history_rows(rows: list[dict[str, Any]], *, target_date: str, target_room_nights: int, min_history_days: int = 3) -> dict[str, Any]:
    target = dt.date.fromisoformat(str(target_date)[:10])
    per_day: dict[str, list[tuple[dt.date, int, int]]] = {}
    for row in rows:
        stay_date = _date_part(row.get("stay_date") or row.get("arrival_date") or row.get("business_date"))
        booking_time = _datetime_value(row.get("booking_time"))
        if not stay_date or not booking_time or stay_date >= target:
            continue
        if stay_date.weekday() != target.weekday():
            continue
        booking_date = booking_time.date()
        if booking_date > stay_date:
            continue
        units = _to_units(row.get("room_count") or row.get("room_nights") or row.get("orders") or 1)
        per_day.setdefault(stay_date.isoformat(), []).append((booking_date, booking_time.hour, units))
    usable_days = {day: items for day, items in per_day.items() if sum(item[2] for item in items) > 0}
    if len(usable_days) < min_history_days:
        return {
            "status": "data_gap",
            "reason": "insufficient_historical_same_weekday_booking_days",
            "basis_days": len(usable_days),
            "min_history_days": min_history_days,
        }
    ratios_by_hour: dict[int, list[float]] = {hour: [] for hour, _ in DEFAULT_HOURLY_ANCHORS}
    basis_room_nights = 0
    for day, items in usable_days.items():
        stay_date = dt.date.fromisoformat(day)
        total = sum(units for _, _, units in items)
        basis_room_nights += total
        for hour, _ in DEFAULT_HOURLY_ANCHORS:
            cumulative = 0
            for booking_date, booking_hour, units in items:
                if booking_date < stay_date or booking_hour <= hour:
                    cumulative += units
            ratios_by_hour[hour].append(min(cumulative / total, 1.0))
    curve = []
    last_target = 0
    last_ratio = 0.0
    curve_ratios: dict[int, float] = {}
    for hour, fallback_ratio in DEFAULT_HOURLY_ANCHORS:
        values = ratios_by_hour.get(hour) or []
        ratio = sum(values) / len(values) if values else fallback_ratio
        ratio = max(last_ratio, min(ratio, 1.0))
        if hour == DEFAULT_HOURLY_ANCHORS[-1][0]:
            ratio = 1.0
        target_value = target_room_nights if ratio >= 1.0 else _target_from_ratio(target_room_nights, ratio, last_target)
        curve.append({"hour": hour, "target_room_nights": target_value, "target_orders": target_value})
        curve_ratios[hour] = round(ratio, 4)
        last_target = target_value
        last_ratio = ratio
    checkpoints = []
    for hour, name in DEFAULT_PROGRESS_CHECKPOINTS:
        target_value = next((item["target_room_nights"] for item in curve if item["hour"] == hour), None)
        if target_value is not None:
            checkpoints.append({"hour": hour, "checkpoint": name, "checkpoint_target_room_nights": target_value, "target_room_nights": target_value, "target_orders": target_value, "checkpoint_target_orders": target_value})
    return {
        "status": "ok",
        "hourly_target_curve": curve,
        "progress_checkpoints": checkpoints,
        "hourly_curve_source": "historical_same_weekday_booking_curve",
        "basis_days": len(usable_days),
        "basis_room_nights": basis_room_nights,
        "curve_ratios": {str(hour): ratio for hour, ratio in curve_ratios.items()},
        "source_confidence": "high" if len(usable_days) >= 4 and basis_room_nights >= 20 else "medium",
        "direct_price_trigger_allowed": False,
        "pricing_usage": "progress_and_confidence_only",
    }


def build_historical_hourly_curve(*, hotel_id: str, target_date: str, target_room_nights: int, mapping_config: str | None = None, profile_name: str | None = None, lookback_weeks: int = 8, min_history_days: int = 3) -> dict[str, Any]:
    if os.environ.get("HOTEL_OTA_DB_SOURCE_ENABLE", "0") != "1":
        return {"status": "data_gap", "reason": "database_source_disabled"}
    try:
        config = _load_mapping_config(mapping_config)
        profile = _profile(config, profile_name)
        if not profile:
            return {"status": "data_gap", "reason": "database_mapping_required"}
        tables = profile.get("tables") or {}
        columns_by_table = profile.get("columns") or {}
        table = tables.get("reservation_snapshot")
        columns = columns_by_table.get("reservation_snapshot") or {}
        if not table or not columns:
            return {"status": "data_gap", "reason": "reservation_snapshot_mapping_required"}
        hotel_col = columns.get("hotel_name")
        booking_col = columns.get("booking_time")
        arrival_col = columns.get("arrival_time") or columns.get("business_date") or columns.get("checkin_date")
        room_count_col = columns.get("room_count")
        status_col = columns.get("booking_status") or columns.get("status") or columns.get("order_status")
        if not all([hotel_col, booking_col, arrival_col]):
            return {"status": "data_gap", "reason": "booking_time_or_arrival_time_mapping_required"}
        target = dt.date.fromisoformat(str(target_date)[:10])
        start = target - dt.timedelta(days=max(1, int(lookback_weeks)) * 7)
        safe_table = _safe_identifier(str(table), "table")
        safe_hotel = _safe_identifier(str(hotel_col), "column")
        safe_booking = _safe_identifier(str(booking_col), "column")
        safe_arrival = _safe_identifier(str(arrival_col), "column")
        select_parts = [f"DATE({safe_arrival}) AS stay_date", f"{safe_booking} AS booking_time"]
        if room_count_col:
            select_parts.append(f"{_safe_identifier(str(room_count_col), 'column')} AS room_count")
        else:
            select_parts.append("1 AS room_count")
        where_parts = [f"{safe_hotel} = %s", f"DATE({safe_arrival}) >= %s", f"DATE({safe_arrival}) < %s", f"WEEKDAY(DATE({safe_arrival})) = WEEKDAY(%s)"]
        params: list[Any] = [_hotel_name(profile, hotel_id), start.isoformat(), target.isoformat(), target.isoformat()]
        if status_col:
            aliases = profile.get("reservation_status_active_aliases") or ["预订", "已预订", "confirmed", "booked", "reserved"]
            placeholders = ", ".join(["%s"] * len(aliases))
            where_parts.append(f"TRIM({_safe_identifier(str(status_col), 'column')}) IN ({placeholders})")
            params.extend(aliases)
        sql = f"SELECT {', '.join(select_parts)} FROM {safe_table} WHERE {' AND '.join(where_parts)} LIMIT 2000"
        with _connect_mysql(profile) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = [dict(row) for row in cursor.fetchall()]
        result = curve_from_history_rows(rows, target_date=target.isoformat(), target_room_nights=target_room_nights, min_history_days=min_history_days)
        result.update({
            "method": "reservation_booking_time_same_weekday_curve_v1",
            "source_table": str(table),
            "lookback_weeks": lookback_weeks,
            "raw_row_count": len(rows),
            "hotel_id": hotel_id,
        })
        return result
    except Exception as exc:
        return {"status": "data_gap", "reason": f"historical_hourly_curve_error:{exc.__class__.__name__}"}

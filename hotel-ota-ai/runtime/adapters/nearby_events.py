from __future__ import annotations

import datetime as dt
import json
import os
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
DEFAULT_COLUMNS = {
    "snapshot_time": "snapshot_time",
    "channel_source": "channel_source",
    "hotel_name": "hotel_name",
    "poi_id": "poi_id",
    "event_id": "event_id",
    "event_class_id": "event_class_id",
    "event_name": "event_name",
    "event_start_date": "event_start_date",
    "event_end_date": "event_end_date",
    "event_address": "event_address",
    "distance_km": "distance_km",
    "countdown_days": "countdown_days",
}


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
    profile = profiles.get(selected or "")
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


def _to_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else None


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    if number is None:
        return None
    return int(round(number))


def _event_heat(distance_km: float | None, countdown_days: int | None) -> tuple[str, float]:
    distance = 99.0 if distance_km is None else distance_km
    countdown = 99 if countdown_days is None else countdown_days
    if countdown < 0:
        return "low", 0.45
    if distance <= 5 and countdown <= 3:
        return "high", 0.9
    if distance <= 10 and countdown <= 7:
        return "medium", 0.8
    if distance <= 15 and countdown <= 14:
        return "medium", 0.7
    return "low", 0.6


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    distance = _to_float(row.get("distance_km"))
    countdown = _to_int(row.get("countdown_days"))
    heat, confidence = _event_heat(distance, countdown)
    start_date = _to_date(row.get("event_start_date"))
    end_date = _to_date(row.get("event_end_date"))
    return {
        "event_id": str(row.get("event_id") or ""),
        "date": start_date,
        "event_start_date": start_date,
        "event_end_date": end_date,
        "event_name": row.get("event_name") or "unknown_event",
        "event_type": "meituan_nearby_event",
        "event_class_id": row.get("event_class_id"),
        "location": row.get("event_address"),
        "distance_km": distance,
        "countdown_days": countdown,
        "poi_id": row.get("poi_id"),
        "source_platform": row.get("channel_source") or "meituan",
        "confidence": confidence,
        "expected_heat": heat,
        "status": "active_or_upcoming" if countdown is None or countdown >= 0 else "expired",
        "field_quality": "confirmed_exact",
        "source_quality": "platform_nearby_event_table",
        "direct_price_trigger_allowed": False,
    }


def load_database_nearby_events(config: dict[str, Any], *, hotel_id: str, business_date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if os.environ.get("HOTEL_OTA_DB_SOURCE_ENABLE", "0") != "1":
        return [], {"status": "data_gap", "source": "database_nearby_event", "reason": "database_source_disabled", "field_quality": "missing"}
    tenant = config
    events_config = tenant.get("events") or {}
    if not events_config.get("enabled", True):
        return [], {"status": "data_gap", "source": "database_nearby_event", "reason": "event_discovery_provider_disabled", "field_quality": "missing"}
    try:
        mapping = _load_mapping_config(events_config.get("mapping_config"))
        profile = _profile(mapping, events_config.get("profile"))
        if not profile:
            return [], {"status": "data_gap", "source": "database_nearby_event", "reason": "database_mapping_required", "field_quality": "missing"}
        tables = profile.get("tables") or {}
        columns_by_table = profile.get("columns") or {}
        table_key = str(events_config.get("table_key") or "meituan_nearby_event")
        table = tables.get(table_key) or events_config.get("table") or "meituan_ota_nearby_event"
        columns = dict(DEFAULT_COLUMNS)
        columns.update(columns_by_table.get(table_key) or {})
        hotel_id_col = columns.get("hotel_id")
        hotel_name_col = columns.get("hotel_name")
        hotel_col = hotel_id_col or hotel_name_col
        tenant_filter_mode = "hotel_id" if hotel_id_col else "hotel_name_legacy"
        risk_flags = [] if tenant_filter_mode == "hotel_id" else ["hotel_id_missing_in_event_table"]
        start_col = columns["event_start_date"]
        end_col = columns["event_end_date"]
        snapshot_col = columns.get("snapshot_time")
        lookahead_days = int(events_config.get("lookahead_days") or 14)
        target = dt.date.fromisoformat(str(business_date)[:10])
        window_end = target + dt.timedelta(days=max(0, lookahead_days))
        projection_keys = [
            "snapshot_time",
            "channel_source",
            "hotel_name",
            "poi_id",
            "event_id",
            "event_class_id",
            "event_name",
            "event_start_date",
            "event_end_date",
            "event_address",
            "distance_km",
            "countdown_days",
        ]
        projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in projection_keys if columns.get(key)]
        safe_table = _safe_identifier(str(table), "table")
        where_parts = [
            f"{_safe_identifier(hotel_col, 'column')} = %s",
            f"DATE({_safe_identifier(start_col, 'column')}) <= %s",
            f"(DATE({_safe_identifier(end_col, 'column')}) >= %s OR {_safe_identifier(end_col, 'column')} IS NULL)",
        ]
        tenant_value = hotel_id if tenant_filter_mode == "hotel_id" else _hotel_name(profile, hotel_id)
        params: list[Any] = [tenant_value, window_end.isoformat(), target.isoformat()]
        if snapshot_col:
            safe_snapshot = _safe_identifier(snapshot_col, "column")
            where_parts.append(f"{safe_snapshot} = (SELECT MAX({safe_snapshot}) FROM {safe_table} WHERE {_safe_identifier(hotel_col, 'column')} = %s)")
            params.append(tenant_value)
        sql = f"SELECT {', '.join(projection)} FROM {safe_table} WHERE {' AND '.join(where_parts)} ORDER BY {_safe_identifier(start_col, 'column')} ASC, COALESCE({_safe_identifier(columns['distance_km'], 'column')}, 999) ASC LIMIT %s"
        params.append(int(events_config.get("limit") or 20))
        with _connect_mysql(profile) as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = [dict(row) for row in cursor.fetchall()]
        events = [_normalize_row(row) for row in rows]
        events = [event for event in events if event.get("event_id")]
        latest_snapshot = str(rows[0].get("snapshot_time")) if rows and rows[0].get("snapshot_time") is not None else None
        return events, {
            "status": "ok" if events else "data_gap",
            "source": "database_nearby_event",
            "event_source": "meituan_ota_nearby_event",
            "reason": None if events else "database_nearby_event_no_rows",
            "field_quality": "confirmed_exact" if events else "missing",
            "source_quality": "platform_nearby_event_table" if events else "missing",
            "direct_price_trigger_allowed": False,
            "tenant_filter_mode": tenant_filter_mode,
            "risk_flags": risk_flags,
            "data_status": "partial" if events and tenant_filter_mode == "hotel_name_legacy" else "ok" if events else "data_gap",
            "raw_row_count": len(rows),
            "filtered_row_count": len(events),
            "source_table": str(table),
            "data_snapshot_time": latest_snapshot,
        }
    except Exception as exc:
        return [], {"status": "data_gap", "source": "database_nearby_event", "reason": f"database_nearby_event_error:{exc.__class__.__name__}", "field_quality": "missing"}

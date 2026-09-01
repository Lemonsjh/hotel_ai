from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.parse
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import Any

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit, json_dumps, now_local, today
from runtime.derived_contexts import build_progress_context, build_sales_baseline_context
from runtime.market_sources import (
    build_event_context,
    build_regional_heat_context,
    event_bridge_status,
    load_verified_http_events,
    load_openclaw_bridge_events,
    load_manual_events,
    load_market_source_config,
    market_config_for_hotel,
    resolve_weather_payload,
    unavailable_weather,
)
from runtime.storage import connect


BUILTIN_SPECIAL_DAYS: dict[int, list[dict[str, Any]]] = {
    2026: [
        {"date": "2026-01-01", "holiday_name": "元旦", "holiday_group": "元旦", "is_off_day": True},
        {"date": "2026-02-14", "holiday_name": "春节调休上班", "holiday_group": "春节", "is_off_day": False, "is_adjusted_workday": True},
        {"date": "2026-02-17", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-18", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-19", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-20", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-21", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-22", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-02-23", "holiday_name": "春节", "holiday_group": "春节", "is_off_day": True},
        {"date": "2026-04-05", "holiday_name": "清明节", "holiday_group": "清明", "is_off_day": True},
        {"date": "2026-05-01", "holiday_name": "劳动节", "holiday_group": "劳动节", "is_off_day": True},
        {"date": "2026-05-02", "holiday_name": "劳动节", "holiday_group": "劳动节", "is_off_day": True},
        {"date": "2026-06-19", "holiday_name": "端午节", "holiday_group": "端午", "is_off_day": True},
        {"date": "2026-09-25", "holiday_name": "中秋节", "holiday_group": "中秋", "is_off_day": True},
        {"date": "2026-10-01", "holiday_name": "国庆节", "holiday_group": "国庆", "is_off_day": True},
        {"date": "2026-10-02", "holiday_name": "国庆节", "holiday_group": "国庆", "is_off_day": True},
        {"date": "2026-10-03", "holiday_name": "国庆节", "holiday_group": "国庆", "is_off_day": True},
    ]
}


def _date(value: str | None) -> dt.date:
    return dt.date.fromisoformat(value or today())


def _daterange(start: dt.date, end: dt.date):
    current = start
    while current <= end:
        yield current
        current += dt.timedelta(days=1)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是"}
    return False


def _normalize_seed_item(item: dict[str, Any], source: str) -> dict[str, Any]:
    date_value = item.get("date") or item.get("day") or item.get("dt")
    if not date_value:
        raise ValueError("holiday seed item requires date")
    is_off_day = item.get("is_off_day")
    if is_off_day is None:
        is_off_day = item.get("isOffDay")
    if is_off_day is None:
        is_off_day = item.get("is_holiday")
    if is_off_day is None:
        is_off_day = item.get("isHoliday")
    is_adjusted = item.get("is_adjusted_workday")
    if is_adjusted is None:
        is_adjusted = item.get("isAdjustedWorkday")
    normalized_off = _bool(is_off_day)
    holiday_flag = item.get("is_holiday")
    if holiday_flag is None:
        holiday_flag = item.get("isHoliday")
    normalized_holiday = _bool(holiday_flag) if holiday_flag is not None else normalized_off
    normalized_adjusted = _bool(is_adjusted) or not normalized_off
    holiday_name = item.get("holiday_name") or item.get("name") or item.get("localName") or item.get("note")
    return {
        "date": str(date_value)[:10],
        "holiday_name": holiday_name,
        "holiday_group": item.get("holiday_group") or holiday_name,
        "is_off_day": normalized_off,
        "is_holiday": normalized_holiday,
        "is_adjusted_workday": normalized_adjusted and not normalized_off,
        "source": item.get("source") or source,
    }


def load_holiday_seed(year: int, seed_file: str | None = None) -> dict[str, dict[str, Any]]:
    source = "builtin_project_seed"
    raw: Any = {"days": BUILTIN_SPECIAL_DAYS.get(year, [])}
    default_seed_file = Path(__file__).resolve().parents[2] / "data" / "holiday-seeds" / f"holiday-seed-{year}.json"
    selected_seed_file = Path(seed_file) if seed_file else default_seed_file if default_seed_file.exists() else None
    if selected_seed_file:
        source = f"seed_file:{selected_seed_file.name}"
        with open(selected_seed_file, "r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("days") or raw.get("holidays") or raw.get("data") or []
    else:
        items = []
    seed: dict[str, dict[str, Any]] = {}
    for item in items:
        normalized = _normalize_seed_item(dict(item), source)
        if dt.date.fromisoformat(normalized["date"]).year == year:
            seed[normalized["date"]] = normalized
    return seed


def _tags_for(date_value: dt.date, special: dict[str, Any] | None, next_delta: int | None, prev_delta: int | None) -> dict[str, Any]:
    weekday = date_value.weekday()
    is_weekend = weekday >= 5
    is_adjusted = bool((special or {}).get("is_adjusted_workday"))
    is_holiday = bool((special or {}).get("is_holiday"))
    is_off_day = bool((special or {}).get("is_off_day")) or (is_weekend and not is_adjusted)
    is_workday = is_adjusted or not is_off_day
    month = date_value.month
    if is_adjusted:
        demand_level = "low_or_normal"
        price_advice = "调休上班日，不按普通周末高价。"
    elif is_holiday:
        demand_level = "high_candidate"
        price_advice = "法定假期需求候选，仍需结合今日经营和进度。"
    elif is_weekend:
        demand_level = "medium_candidate"
        price_advice = "周末需求候选，不能单独触发涨价。"
    else:
        demand_level = "normal"
        price_advice = "普通工作日，按实时经营数据判断。"
    if is_holiday:
        season_tag = "holiday_peak"
    elif next_delta is not None and 0 < next_delta <= 3:
        season_tag = "holiday_warmup"
    elif prev_delta is not None and 0 < prev_delta <= 2:
        season_tag = "holiday_cooldown"
    elif month in {7, 8}:
        season_tag = "summer_vacation"
    elif month in {1, 2}:
        season_tag = "winter_vacation"
    else:
        season_tag = "normal"
    school_vacation_tag = "summer_vacation" if month in {7, 8} else "winter_vacation" if month in {1, 2} else "none"
    return {
        "weekday": weekday + 1,
        "is_weekend": is_weekend,
        "is_workday": is_workday,
        "is_holiday": is_holiday,
        "is_adjusted_workday": is_adjusted,
        "is_off_day": is_off_day,
        "season_tag": season_tag,
        "school_vacation_tag": school_vacation_tag,
        "demand_level": demand_level,
        "price_advice": price_advice,
    }


def build_calendar_days(year: int, seed_file: str | None = None) -> list[dict[str, Any]]:
    seed = load_holiday_seed(year, seed_file)
    start = dt.date(year, 1, 1)
    end = dt.date(year, 12, 31)
    holiday_dates = sorted(dt.date.fromisoformat(day) for day, item in seed.items() if item.get("is_holiday"))
    rows: list[dict[str, Any]] = []
    for date_value in _daterange(start, end):
        next_holiday = min((holiday for holiday in holiday_dates if holiday >= date_value), default=None)
        prev_holiday = max((holiday for holiday in holiday_dates if holiday <= date_value), default=None)
        next_delta = (next_holiday - date_value).days if next_holiday else None
        prev_delta = (date_value - prev_holiday).days if prev_holiday else None
        special = seed.get(date_value.isoformat())
        tags = _tags_for(date_value, special, next_delta, prev_delta)
        rows.append(
            {
                "date": date_value.isoformat(),
                "year": date_value.year,
                "month": date_value.month,
                "day": date_value.day,
                "days_to_holiday": next_delta,
                "days_after_holiday": prev_delta,
                "holiday_name": (special or {}).get("holiday_name"),
                "holiday_group": (special or {}).get("holiday_group"),
                "source_quality": "confirmed" if special else "computed",
                "source": (special or {}).get("source") or "runtime_date_algorithm",
                "updated_at": now_local(),
                **tags,
            }
        )
    return rows


def _ensure_calendar_tables(db_path: str) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS calendar_days (
                  date TEXT PRIMARY KEY,
                  year INTEGER NOT NULL,
                  month INTEGER NOT NULL,
                  day INTEGER NOT NULL,
                  weekday INTEGER NOT NULL,
                  is_weekend INTEGER NOT NULL,
                  is_workday INTEGER NOT NULL,
                  is_holiday INTEGER NOT NULL,
                  is_adjusted_workday INTEGER NOT NULL,
                  is_off_day INTEGER NOT NULL,
                  holiday_name TEXT,
                  holiday_group TEXT,
                  days_to_holiday INTEGER,
                  days_after_holiday INTEGER,
                  season_tag TEXT NOT NULL,
                  school_vacation_tag TEXT NOT NULL,
                  local_event_count INTEGER NOT NULL DEFAULT 0,
                  event_heat_level TEXT NOT NULL DEFAULT 'none',
                  demand_level TEXT NOT NULL,
                  price_advice TEXT NOT NULL,
                  source_quality TEXT NOT NULL,
                  source TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS event_candidates (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  hotel_id TEXT NOT NULL,
                  date TEXT NOT NULL,
                  event_name TEXT NOT NULL,
                  event_type TEXT,
                  location TEXT,
                  distance_km REAL,
                  source_url TEXT,
                  confidence REAL NOT NULL DEFAULT 0,
                  expected_heat TEXT NOT NULL DEFAULT 'unknown',
                  status TEXT NOT NULL DEFAULT 'candidate',
                  created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS holiday_calendar_cache (
                  date TEXT PRIMARY KEY,
                  year INTEGER NOT NULL,
                  provider TEXT NOT NULL,
                  holiday_name TEXT,
                  holiday_group TEXT,
                  is_off_day INTEGER NOT NULL,
                  is_holiday INTEGER NOT NULL,
                  is_adjusted_workday INTEGER NOT NULL,
                  source_quality TEXT NOT NULL,
                  fetched_at TEXT NOT NULL,
                  raw_source TEXT
                );
                """
            )


def sync_calendar_year(db_path: str, year: int, seed_file: str | None = None) -> dict[str, Any]:
    _ensure_calendar_tables(db_path)
    rows = build_calendar_days(year, seed_file)
    with closing(connect(db_path)) as conn:
        with conn:
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO calendar_days (
                      date, year, month, day, weekday, is_weekend, is_workday, is_holiday,
                      is_adjusted_workday, is_off_day, holiday_name, holiday_group,
                      days_to_holiday, days_after_holiday, season_tag, school_vacation_tag,
                      local_event_count, event_heat_level, demand_level, price_advice,
                      source_quality, source, updated_at
                    )
                    VALUES (
                      :date, :year, :month, :day, :weekday, :is_weekend, :is_workday, :is_holiday,
                      :is_adjusted_workday, :is_off_day, :holiday_name, :holiday_group,
                      :days_to_holiday, :days_after_holiday, :season_tag, :school_vacation_tag,
                      0, 'none', :demand_level, :price_advice,
                      :source_quality, :source, :updated_at
                    )
                    ON CONFLICT(date) DO UPDATE SET
                      year=excluded.year,
                      month=excluded.month,
                      day=excluded.day,
                      weekday=excluded.weekday,
                      is_weekend=excluded.is_weekend,
                      is_workday=excluded.is_workday,
                      is_holiday=excluded.is_holiday,
                      is_adjusted_workday=excluded.is_adjusted_workday,
                      is_off_day=excluded.is_off_day,
                      holiday_name=excluded.holiday_name,
                      holiday_group=excluded.holiday_group,
                      days_to_holiday=excluded.days_to_holiday,
                      days_after_holiday=excluded.days_after_holiday,
                      season_tag=excluded.season_tag,
                      school_vacation_tag=excluded.school_vacation_tag,
                      demand_level=excluded.demand_level,
                      price_advice=excluded.price_advice,
                      source_quality=excluded.source_quality,
                      source=excluded.source,
                      updated_at=excluded.updated_at
                    """,
                    {key: int(value) if isinstance(value, bool) else value for key, value in row.items()},
                )
    return {"status": "ok", "year": year, "rows": len(rows), "seed_file": seed_file, "updated_at": now_local()}


def _remote_holiday_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if any(key in payload for key in ("holidays", "weekends", "workdays")):
            normalized: list[dict[str, Any]] = []
            for item in payload.get("holidays") or []:
                if isinstance(item, dict):
                    normalized.append({**item, "is_holiday": True, "is_off_day": True})
            for item in payload.get("weekends") or []:
                if isinstance(item, dict):
                    normalized.append({**item, "is_holiday": False, "is_off_day": True})
            for item in payload.get("workdays") or []:
                if isinstance(item, dict):
                    normalized.append({**item, "is_holiday": False, "is_off_day": False, "is_adjusted_workday": True})
            return normalized
        items = payload.get("days") or payload.get("data") or payload.get("results")
        if isinstance(items, list):
            normalized = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                day_type = str(item.get("type") or item.get("day_type") or "").lower()
                row = dict(item)
                if day_type == "holiday":
                    row["is_holiday"] = True
                    row["is_off_day"] = True
                elif day_type in {"workday", "adjusted_workday"}:
                    row["is_holiday"] = False
                    row["is_off_day"] = False
                    row["is_adjusted_workday"] = True
                elif day_type == "weekend":
                    row["is_holiday"] = False
                    row["is_off_day"] = True
                normalized.append(row)
            return normalized
    return []


def _holiday_provider_candidates(provider_config: dict[str, Any]) -> list[dict[str, Any]]:
    providers = provider_config.get("providers")
    if not isinstance(providers, dict):
        return [dict(provider_config)]
    ordered: list[str] = []
    primary = str(provider_config.get("provider") or "").strip()
    if primary:
        ordered.append(primary)
    for item in provider_config.get("fallback_providers") or []:
        key = str(item or "").strip()
        if key and key not in ordered:
            ordered.append(key)
    candidates: list[dict[str, Any]] = []
    for key in ordered:
        value = providers.get(key)
        if not isinstance(value, dict):
            continue
        merged = dict(value)
        merged.setdefault("provider", key)
        merged.setdefault("commercial_use_confirmed", provider_config.get("commercial_use_confirmed"))
        candidates.append(merged)
    return candidates or [dict(provider_config)]


def _endpoint_for_provider(provider_config: dict[str, Any], year: int) -> str:
    endpoint = str(provider_config.get("endpoint") or "")
    endpoint_template = provider_config.get("endpoint_template")
    if not endpoint and endpoint_template:
        endpoint = str(endpoint_template).format(year=year)
    return endpoint


def _provider_diagnostic(
    provider: str,
    *,
    year: int,
    endpoint: str,
    reason: str,
    error_type: str | None = None,
    http_status: Any | None = None,
    fallback_attempted: bool = False,
    fallback_provider: str | None = None,
) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(endpoint)
    return {
        "provider": provider,
        "year": year,
        "reason": reason,
        "error_type": error_type,
        "http_status": http_status,
        "endpoint_host": parsed.hostname,
        "retry_count": 0,
        "fallback_attempted": fallback_attempted,
        "fallback_provider": fallback_provider,
    }


def sync_holiday_provider_cache(
    db_path: str,
    year: int,
    provider_config: dict[str, Any],
    *,
    http_get: Any | None = None,
) -> dict[str, Any]:
    """Cache a confirmed external holiday provider without replacing the builtin fallback."""
    diagnostics: list[dict[str, Any]] = []
    candidates = _holiday_provider_candidates(provider_config)
    fallback_provider_names = [str(item.get("provider") or "holiday_provider") for item in candidates[1:]]
    for index, candidate in enumerate(candidates):
        provider = str(candidate.get("provider") or "holiday_provider")
        endpoint = _endpoint_for_provider(candidate, year)
        fallback_attempted = index > 0
        fallback_provider = provider if fallback_attempted else (fallback_provider_names[0] if fallback_provider_names else None)
        api_key_env = candidate.get("api_key_env")
        api_key = os.environ.get(str(api_key_env)) if api_key_env else None
        allow_anonymous = bool(candidate.get("allow_anonymous"))
        if api_key:
            auth_mode = "api_key"
        elif allow_anonymous:
            auth_mode = "anonymous"
        else:
            auth_mode = "none"
        commercial_confirmed = bool(candidate.get("commercial_use_confirmed"))
        if auth_mode == "none" and candidate.get("api_key_env"):
            diagnostics.append(
                _provider_diagnostic(
                    provider,
                    year=year,
                    endpoint=endpoint,
                    reason="holiday_provider_api_key_required",
                    fallback_attempted=fallback_attempted,
                    fallback_provider=fallback_provider,
                )
            )
            continue
        if not commercial_confirmed and auth_mode != "anonymous":
            diagnostics.append(
                _provider_diagnostic(
                    provider,
                    year=year,
                    endpoint=endpoint,
                    reason="holiday_provider_commercial_use_not_confirmed",
                    fallback_attempted=fallback_attempted,
                    fallback_provider=fallback_provider,
                )
            )
            continue
        if not endpoint.startswith("https://"):
            diagnostics.append(
                _provider_diagnostic(
                    provider,
                    year=year,
                    endpoint=endpoint,
                    reason="holiday_provider_https_required",
                    fallback_attempted=fallback_attempted,
                    fallback_provider=fallback_provider,
                )
            )
            continue
        timeout = float(candidate.get("timeout_seconds") or 5)
        headers = {"Accept": "application/json", "User-Agent": "hotel-ota-ai/1.0"}
        header_name = candidate.get("api_key_header")
        if api_key and header_name:
            headers[str(header_name)] = api_key
        request_endpoint = endpoint
        query_name = candidate.get("api_key_query_param")
        if api_key and query_name:
            separator = "&" if "?" in request_endpoint else "?"
            request_endpoint = f"{request_endpoint}{separator}{urllib.parse.urlencode({str(query_name): api_key})}"
        try:
            if http_get:
                try:
                    payload = http_get(request_endpoint, timeout, headers=headers)
                except TypeError:
                    payload = http_get(request_endpoint, timeout)
            else:
                request = urllib.request.Request(request_endpoint, headers=headers)
                with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 - configured public holiday API.
                    payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            diagnostics.append(
                _provider_diagnostic(
                    provider,
                    year=year,
                    endpoint=endpoint,
                    reason=f"holiday_provider_error:{exc.__class__.__name__}",
                    error_type=exc.__class__.__name__,
                    http_status=getattr(exc, "code", None) or getattr(exc, "status", None),
                    fallback_attempted=fallback_attempted,
                    fallback_provider=fallback_provider,
                )
            )
            continue
        items = []
        source_quality = "confirmed_external" if commercial_confirmed and auth_mode != "anonymous" else "anonymous_free_test"
        commercial_output_allowed = source_quality == "confirmed_external"
        for item in _remote_holiday_items(payload):
            normalized = _normalize_seed_item(item, f"remote_holiday_provider:{provider}")
            if dt.date.fromisoformat(normalized["date"]).year == year:
                items.append(normalized)
        if not items:
            diagnostics.append(
                _provider_diagnostic(
                    provider,
                    year=year,
                    endpoint=endpoint,
                    reason="holiday_provider_no_rows",
                    fallback_attempted=fallback_attempted,
                    fallback_provider=fallback_provider,
                )
            )
            continue
        _ensure_calendar_tables(db_path)
        sync_calendar_year(db_path, year)
        fetched_at = now_local()
        with closing(connect(db_path)) as conn:
            with conn:
                for item in items:
                    date_value = dt.date.fromisoformat(item["date"])
                    tags = _tags_for(date_value, item, None, None)
                    row = {
                        "date": item["date"],
                        "year": year,
                        "provider": provider,
                        "holiday_name": item.get("holiday_name"),
                        "holiday_group": item.get("holiday_group") or item.get("holiday_name"),
                        "is_off_day": int(bool(tags["is_off_day"])),
                        "is_holiday": int(bool(tags["is_holiday"])),
                        "is_adjusted_workday": int(bool(tags["is_adjusted_workday"])),
                        "source_quality": source_quality,
                        "fetched_at": fetched_at,
                        "raw_source": f"remote_holiday_provider:{provider}",
                    }
                    conn.execute(
                        """
                        INSERT INTO holiday_calendar_cache (
                          date, year, provider, holiday_name, holiday_group, is_off_day,
                          is_holiday, is_adjusted_workday, source_quality, fetched_at, raw_source
                        )
                        VALUES (
                          :date, :year, :provider, :holiday_name, :holiday_group, :is_off_day,
                          :is_holiday, :is_adjusted_workday, :source_quality, :fetched_at, :raw_source
                        )
                        ON CONFLICT(date) DO UPDATE SET
                          year=excluded.year,
                          provider=excluded.provider,
                          holiday_name=excluded.holiday_name,
                          holiday_group=excluded.holiday_group,
                          is_off_day=excluded.is_off_day,
                          is_holiday=excluded.is_holiday,
                          is_adjusted_workday=excluded.is_adjusted_workday,
                          source_quality=excluded.source_quality,
                          fetched_at=excluded.fetched_at,
                          raw_source=excluded.raw_source
                        """,
                        row,
                    )
                    conn.execute(
                        """
                        UPDATE calendar_days
                        SET is_workday=?,
                            is_holiday=?,
                            is_adjusted_workday=?,
                            is_off_day=?,
                            holiday_name=?,
                            holiday_group=?,
                            season_tag=?,
                            demand_level=?,
                            price_advice=?,
                            source_quality=?,
                            source=?,
                            updated_at=?
                        WHERE date=?
                        """,
                        (
                            int(bool(tags["is_workday"])),
                            int(bool(tags["is_holiday"])),
                            int(bool(tags["is_adjusted_workday"])),
                            int(bool(tags["is_off_day"])),
                            row["holiday_name"],
                            row["holiday_group"],
                            tags["season_tag"],
                            tags["demand_level"],
                            tags["price_advice"],
                            row["source_quality"],
                            row["raw_source"],
                            fetched_at,
                            row["date"],
                        ),
                    )
        return {
            "status": "ok",
            "provider": provider,
            "year": year,
            "rows": len(items),
            "source": f"remote_holiday_provider:{provider}",
            "source_quality": source_quality,
            "commercial_output_allowed": commercial_output_allowed,
            "auth_mode": auth_mode,
            "updated_at": fetched_at,
            "fallback_attempted": fallback_attempted,
            "fallback_provider": provider if fallback_attempted else None,
            "provider_diagnostics": diagnostics,
        }
    if len(candidates) == 1 and diagnostics:
        first = diagnostics[0]
        return {
            "status": "data_gap",
            "provider": first.get("provider"),
            "year": year,
            "reason": first.get("reason"),
            "error_type": first.get("error_type"),
            "http_status": first.get("http_status"),
            "endpoint_host": first.get("endpoint_host"),
            "fallback_attempted": False,
            "fallback_provider": None,
            "provider_diagnostics": diagnostics,
        }
    seed_sync = sync_calendar_year(db_path, year)
    return {
        "status": "data_gap",
        "year": year,
        "reason": "holiday_provider_all_failed",
        "source_quality": "project_seed_fallback",
        "seed_fallback_used": True,
        "fallback_attempted": len(candidates) > 1,
        "fallback_provider": fallback_provider_names[0] if fallback_provider_names else None,
        "provider_diagnostics": diagnostics,
        "seed_sync": seed_sync,
    }


def _row_to_calendar_context(row: Any) -> dict[str, Any]:
    result = dict(row)
    for key in ("is_weekend", "is_workday", "is_holiday", "is_adjusted_workday", "is_off_day"):
        result[key] = bool(result.get(key))
    return result


def get_calendar_day(db_path: str, date_text: str) -> dict[str, Any]:
    date_value = _date(date_text)
    _ensure_calendar_tables(db_path)
    with closing(connect(db_path)) as conn:
        row = conn.execute("SELECT * FROM calendar_days WHERE date=?", (date_value.isoformat(),)).fetchone()
    if row is None:
        sync_calendar_year(db_path, date_value.year)
        with closing(connect(db_path)) as conn:
            row = conn.execute("SELECT * FROM calendar_days WHERE date=?", (date_value.isoformat(),)).fetchone()
    if row is None:
        raise ValueError(f"calendar row not found: {date_value.isoformat()}")
    return _row_to_calendar_context(row)


def _holiday_provider_from_market_source(args: argparse.Namespace) -> dict[str, Any] | None:
    config_path = getattr(args, "market_source_config", None)
    if not config_path:
        return None
    config = load_market_source_config(config_path)
    tenant = market_config_for_hotel(config, getattr(args, "hotel_id", None))
    if tenant.get("status") != "ok":
        return {"status": "data_gap", "reason": tenant.get("reason") or "tenant_market_config_not_found"}
    holiday = dict(tenant.get("holiday") or {})
    providers = holiday.get("providers")
    if isinstance(providers, dict):
        selected = getattr(args, "holiday_provider", None) or holiday.get("provider")
        if str(selected or "") not in providers:
            return {"status": "data_gap", "reason": "holiday_provider_config_not_found", "provider": selected}
        holiday["provider"] = selected
        holiday.setdefault("commercial_use_confirmed", holiday.get("commercial_use_confirmed"))
        return holiday
    return holiday


def calendar_sync(args: argparse.Namespace) -> None:
    seed_sync = sync_calendar_year(args.db, args.year, args.seed_file)
    if getattr(args, "sync_remote_holidays", False):
        provider_config = _holiday_provider_from_market_source(args)
        if not provider_config:
            emit({"status": "data_gap", "year": args.year, "reason": "holiday_provider_config_not_found", "seed_sync": seed_sync})
            return
        if provider_config.get("status") == "data_gap":
            emit({"status": "data_gap", "year": args.year, "reason": provider_config.get("reason"), "seed_sync": seed_sync})
            return
        remote = sync_holiday_provider_cache(args.db, args.year, provider_config)
        remote["seed_sync"] = seed_sync
        emit(remote)
        return
    emit(seed_sync)


def calendar_query(args: argparse.Namespace) -> None:
    context = get_calendar_day(args.db, args.date)
    emit({"status": "ok", **context, "approval_allowed": False})


def _load_json_file(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _canonical_weather_provider(provider: str) -> str:
    aliases = {
        "wttr_mcp": "wttr_http",
        "sample": "weather_fixture",
        "manual": "manual_weather",
    }
    return aliases.get(provider or "weather_mcp", provider or "weather_mcp")


def _weather_source_quality(provider: str) -> str:
    if provider == "weather_mcp":
        return "confirmed"
    if provider in {"wttr_http", "amap_api", "qweather_api", "open_meteo", "open_meteo_failed_fallback_wttr_http"}:
        return "secondary"
    if provider == "weather_fixture":
        return "fixture"
    if provider == "manual_weather":
        return "manual"
    return "secondary"


def _open_meteo_weather_text(code: Any) -> str:
    try:
        numeric = int(code)
    except (TypeError, ValueError):
        return "unknown"
    if numeric == 0:
        return "clear"
    if numeric == 1:
        return "mainly_clear"
    if numeric == 2:
        return "partly_cloudy"
    if numeric == 3:
        return "overcast"
    if numeric in {45, 48}:
        return "fog"
    if numeric in {51, 53, 55, 56, 57}:
        return "drizzle"
    if numeric in {61, 63, 65, 66, 67}:
        return "rain"
    if numeric in {71, 73, 75, 77}:
        return "snow"
    if numeric in {80, 81, 82}:
        return "rain_showers"
    if numeric in {85, 86}:
        return "snow_showers"
    if numeric in {95, 96, 99}:
        return "thunderstorm"
    return "unknown"


def normalize_weather(payload: dict[str, Any] | None, provider: str = "weather_mcp") -> dict[str, Any]:
    provider = _canonical_weather_provider(provider)
    if not payload:
        summary = "天气 MCP 未配置或未返回。" if provider == "weather_mcp" else f"{provider} 天气源未配置或未返回。"
        return {
            "status": "unavailable",
            "source": provider,
            "weather_summary": summary,
            "weather_risk_level": "unknown",
            "source_quality": "unavailable",
            "field_quality": "missing",
        }
    if payload.get("status") in {"timeout", "error", "unavailable"}:
        return {
            "status": "unavailable",
            "source": provider,
            "weather_summary": payload.get("message") or f"{provider} 天气源超时或不可用。",
            "weather_risk_level": "unknown",
            "source_quality": "unavailable",
            "field_quality": "missing",
        }
    if provider == "open_meteo" and isinstance(payload.get("current"), dict):
        current = payload["current"]
        weather_code = current.get("weather_code")
        weather_text = _open_meteo_weather_text(weather_code)
        precip = current.get("precipitation")
        rain = current.get("rain")
        showers = current.get("showers")
        try:
            precip_value = float(precip or 0) + float(rain or 0) + float(showers or 0)
        except (TypeError, ValueError):
            precip_value = 0.0
        risk = "low"
        if weather_text in {"thunderstorm", "snow", "rain_showers"} or precip_value >= 10:
            risk = "high"
        elif weather_text in {"rain", "drizzle", "fog", "snow_showers"} or precip_value > 0:
            risk = "medium"
        signal = "cautious" if risk in {"medium", "high"} else "neutral"
        return {
            "status": "ok",
            "source": provider,
            "provider": provider,
            "display_location": payload.get("display_location"),
            "latitude": payload.get("latitude"),
            "longitude": payload.get("longitude"),
            "timezone": payload.get("timezone"),
            "weather_code": weather_code,
            "weather_text": weather_text,
            "weather_summary": weather_text,
            "weather_context": weather_text,
            "temperature_c": current.get("temperature_2m"),
            "apparent_temperature_c": current.get("apparent_temperature"),
            "precipitation_mm": precip,
            "rain_mm": rain,
            "showers_mm": showers,
            "cloud_cover_pct": current.get("cloud_cover"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
            "captured_at": current.get("time") or payload.get("generationtime_ms"),
            "weather_signal": signal,
            "weather_risk_level": risk,
            "source_quality": _weather_source_quality(provider),
            "field_quality": "confirmed",
            "data_snapshot_time": now_local(),
        }
    current = (payload.get("current_condition") or [{}])[0] if isinstance(payload.get("current_condition"), list) else payload
    if isinstance(payload.get("now"), dict):
        current = payload["now"]
    desc = payload.get("weather_summary") or payload.get("description")
    if not desc:
        desc = current.get("text")
    if not desc:
        weather_desc = current.get("weatherDesc") or []
        if weather_desc and isinstance(weather_desc, list):
            desc = (weather_desc[0] or {}).get("value")
    temp = current.get("temp_C") or current.get("temperature") or current.get("temp")
    precip = current.get("precipMM") or current.get("precipitation") or current.get("precip")
    summary_parts = [str(desc or "天气已返回")]
    if temp not in (None, ""):
        summary_parts.append(f"{temp}C")
    weather_text = " ".join(summary_parts)
    risk = "low"
    text = weather_text.lower()
    try:
        precip_value = float(precip or 0)
    except (TypeError, ValueError):
        precip_value = 0.0
    if any(word in text for word in ("storm", "暴雨", "大雨", "snow", "雪", "雷")) or precip_value >= 10:
        risk = "high"
    elif any(word in text for word in ("rain", "雨", "fog", "雾", "阴")) or precip_value > 0:
        risk = "medium"
    signal = "cautious" if risk in {"medium", "high"} else "neutral"
    return {
        "status": "ok",
        "source": provider,
        "weather_summary": weather_text,
        "weather_context": weather_text,
        "weather_signal": signal,
        "weather_risk_level": risk,
        "source_quality": _weather_source_quality(provider),
        "field_quality": "confirmed" if desc else "inferred",
        "data_snapshot_time": now_local(),
    }


def _fresh_operating_context(payload: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
    if not payload:
        return False, {"status": "missing", "freshness_status": "missing_date"}
    context = {
        "status": payload.get("status") or "ok",
        "freshness_status": payload.get("freshness_status"),
        "business_status": payload.get("business_status"),
        "data_business_date": payload.get("data_business_date"),
        "data_snapshot_time": payload.get("data_snapshot_time"),
    }
    fresh = context["freshness_status"] == "fresh" and context["business_status"] == "current"
    return fresh, context


def _fresh_progress_context(payload: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
    if not payload:
        return False, {"status": "missing", "freshness_status": "missing_date", "downstream_allowed": False}
    context = {
        "status": payload.get("status") or "ok",
        "freshness_status": payload.get("freshness_status"),
        "business_status": payload.get("business_status"),
        "downstream_allowed": bool(payload.get("downstream_allowed")),
        "actual_source": payload.get("actual_source"),
        "target_source": payload.get("target_source"),
        "current_facts": payload.get("current_facts"),
        "progress_granularity": payload.get("progress_granularity"),
    }
    return context["freshness_status"] == "fresh" and context["downstream_allowed"], context


def _database_progress_context(hotel_id: str, business_date: str, operating_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not database_source_enabled():
        return None
    try:
        db_result = database_template_result("daily_metrics", hotel_id, date=business_date)
    except Exception as exc:  # pragma: no cover - diagnostics must degrade, not break S4.
        return {
            "status": "data_gap",
            "freshness_status": "missing_date",
            "business_status": "unknown",
            "downstream_allowed": False,
            "actual_source": "mysql_runtime",
            "target_source": "unavailable",
            "internal_missing_fields": [f"progress_database_error:{exc.__class__.__name__}"],
        }
    source_payload: dict[str, Any] | None = None
    baseline_context: dict[str, Any] | None = None
    if isinstance(db_result, dict) and db_result.get("status") == "ok":
        source_payload = db_result
    elif operating_payload:
        source_payload = operating_payload
    if not source_payload:
        return {
            "status": "data_gap",
            "freshness_status": "missing_date",
            "business_status": "unknown",
            "downstream_allowed": False,
            "actual_source": "mysql_runtime",
            "target_source": "unavailable",
        }
    try:
        monthly_result = database_template_result("monthly_metrics", hotel_id)
        if isinstance(monthly_result, dict) and monthly_result.get("status") == "ok":
            revenue_result = None
            try:
                candidate_revenue = database_template_result("room_fee_daily", hotel_id, date=business_date)
                if isinstance(candidate_revenue, dict) and candidate_revenue.get("status") == "ok":
                    revenue_result = candidate_revenue
            except Exception:
                revenue_result = None
            baseline_context = build_sales_baseline_context(source_payload, monthly_result=monthly_result, revenue_result=revenue_result)
    except Exception:
        baseline_context = None
    order_result = None
    try:
        candidate_orders = database_template_result("order_snapshot", hotel_id, date=business_date)
        if isinstance(candidate_orders, dict) and candidate_orders.get("status") == "ok":
            order_result = candidate_orders
    except Exception:
        order_result = None
    context = build_progress_context(source_payload, baseline_context=baseline_context, order_result=order_result)
    context["actual_source"] = "mysql_runtime"
    estimated = bool(baseline_context and "monthly_average_room_nights" in (baseline_context.get("derived_fields") or []))
    if context.get("target_room_nights") is not None:
        context["target_source"] = "baseline_estimated" if estimated else "sales_baseline"
    else:
        context["target_source"] = "baseline_target_missing"
    if estimated:
        context["baseline_estimated"] = True
        context["commercial_label"] = "reference_baseline"
        context.setdefault("risk_flags", []).append("baseline_estimated_not_formal_target")
    context["downstream_allowed"] = bool(
        context.get("status") == "ok"
        and context.get("freshness_status") == "fresh"
        and context.get("business_status") == "current"
        and context.get("target_room_nights") is not None
        and not estimated
    )
    return context


def market_context(args: argparse.Namespace) -> None:
    business_date = args.date or today()
    calendar_context = _load_json_file(getattr(args, "calendar_fixture", None)) or get_calendar_day(args.db, business_date)
    calendar_context.setdefault("business_date", calendar_context.get("date") or business_date)
    market_source_config = load_market_source_config(getattr(args, "market_source_config", None))
    weather_provider = args.weather_provider
    if args.weather_fixture and weather_provider == "weather_mcp":
        weather_provider = "weather_fixture"
    if args.weather_fixture:
        weather_context = normalize_weather(_load_json_file(args.weather_fixture), weather_provider)
    else:
        weather_payload, resolved_provider, weather_error = resolve_weather_payload(market_source_config, hotel_id=args.hotel_id)
        weather_context = (
            normalize_weather(weather_payload, resolved_provider)
            if weather_payload
            else unavailable_weather(resolved_provider, weather_error)
        )
    operating_payload = _load_json_file(args.operating_fixture)
    if operating_payload is None and database_source_enabled():
        db_result = database_template_result("operating_snapshot", args.hotel_id, date=business_date)
        operating_payload = (db_result.get("payload") or {}) if db_result.get("status") == "ok" else None
    operating_fresh, operating_context = _fresh_operating_context(operating_payload)
    progress_payload = _load_json_file(args.progress_fixture)
    if progress_payload is None:
        progress_payload = _database_progress_context(args.hotel_id, business_date, operating_payload)
    progress_fresh, progress_context = _fresh_progress_context(progress_payload)
    event_context = build_event_context(market_source_config, business_date=business_date, hotel_id=args.hotel_id)
    regional_heat_context = build_regional_heat_context(
        market_source_config,
        hotel_id=args.hotel_id,
        event_context=event_context,
        operating_context=operating_payload or operating_context,
        progress_context=progress_context,
        competitor_context=None,
    )
    weather_available = weather_context.get("status") == "ok"
    events_available = event_context.get("status") in {"ok", "partial"}
    regional_heat_available = regional_heat_context.get("status") == "ok"
    calendar_available = calendar_context.get("source_quality") in {"confirmed", "computed", "confirmed_external"}
    operating_available = operating_context.get("status") in {"ok", "partial"} or bool(operating_payload)
    context_generation_allowed = bool(calendar_available and weather_available and operating_available)
    downstream_allowed = bool(
        context_generation_allowed
        and operating_fresh
        and progress_fresh
    )
    omitted_modules = []
    if not events_available:
        omitted_modules.append("events")
    if not regional_heat_available:
        omitted_modules.append("regional_heat")
    used_modules = ["calendar", "weather", "operating"]
    if events_available:
        used_modules.append("events")
    if regional_heat_available:
        used_modules.append("regional_heat")
    progress_available = progress_context.get("status") in {"ok", "partial"} and bool(progress_context.get("current_facts"))
    if progress_available:
        used_modules.append("progress")
    if downstream_allowed:
        status = "ok"
        market_context_level = "revenue_context_ready"
    elif context_generation_allowed:
        status = "partial"
        market_context_level = "basic_environment"
    else:
        status = "data_gap"
        market_context_level = "unavailable"
    blocked_reason = None
    if not weather_available:
        blocked_reason = "weather_context_unavailable"
    if not operating_fresh or not progress_fresh:
        blocked_reason = "missing_fresh_operating_progress"
    elif not events_available:
        blocked_reason = event_context.get("reason") or "event_context_unavailable"
    elif not regional_heat_available:
        blocked_reason = "regional_heat_context_unavailable"
    if calendar_context.get("is_adjusted_workday"):
        demand_signal = "neutral"
    elif calendar_context.get("is_holiday") and downstream_allowed:
        demand_signal = "strong"
    elif weather_context.get("weather_risk_level") in {"medium", "high"}:
        demand_signal = "cautious"
    else:
        demand_signal = "neutral"
    emit(
        {
            "status": status,
            "hotel_id": args.hotel_id,
            "business_date": business_date,
            "market_context_level": market_context_level,
            "context_generation_allowed": context_generation_allowed,
            "downstream_revenue_allowed": downstream_allowed,
            "used_modules": used_modules,
            "omitted_modules": omitted_modules,
            "calendar_context": calendar_context,
            "weather_context": weather_context,
            "event_context": event_context,
            "regional_heat_context": regional_heat_context,
            "competitor_context": {"status": "s7_aggregate_pending"},
            "operating_context": operating_context,
            "progress_context": progress_context,
            "holiday_source": calendar_context.get("source") or "builtin_project_seed",
            "event_source": event_context.get("event_source") or event_context.get("source"),
            "weather_source": weather_context.get("source"),
            "regional_heat_source": regional_heat_context.get("regional_heat_source") or regional_heat_context.get("source"),
            "demand_signal": demand_signal,
            "source_quality": "confirmed" if downstream_allowed else "partial",
            "freshness_status": "fresh" if downstream_allowed else "missing_date",
            "data_snapshot_time": now_local(),
            "downstream_allowed": downstream_allowed,
            "downstream_blocked_reason": None if downstream_allowed else blocked_reason,
            "approval_allowed": False,
            "live_allowed": False,
            "next_skill": "S5" if downstream_allowed else "S14",
        }
    )


def event_discover(args: argparse.Namespace) -> None:
    _ensure_calendar_tables(args.db)
    fixture = _load_json_file(args.fixture_file)
    if not fixture:
        market_source_config = load_market_source_config(getattr(args, "market_source_config", None))
        tenant = market_config_for_hotel(market_source_config, args.hotel_id)
        provider = (tenant.get("events") or {}).get("provider") if tenant.get("status") == "ok" else None
        if tenant.get("status") != "ok":
            events = []
            meta = {
                "status": "data_gap",
                "source": "unconfigured",
                "reason": tenant.get("reason") or "tenant_market_config_not_found",
            }
        elif provider == "verified_http_json":
            events, meta = load_verified_http_events(
                market_source_config,
                hotel_id=args.hotel_id,
                date_range=args.date_range,
            )
        elif provider == "openclaw_bridge_http_search":
            business_date = str(args.date_range).split("..", 1)[0]
            events, meta = load_openclaw_bridge_events(
                tenant,
                hotel_id=args.hotel_id,
                business_date=business_date,
            )
        else:
            events, meta = load_manual_events(tenant, date_range=args.date_range)
        if meta.get("status") not in {"ok", "partial"}:
            emit(
                {
                    "status": "data_gap",
                    "hotel_id": args.hotel_id,
                    "date_range": args.date_range,
                    "reason": meta.get("reason") or "event_discovery_provider_not_configured",
                    "source": meta.get("source") or "manual_json",
                    "event_source": meta.get("source") or "manual_json",
                    "source_capability": "manual_json_or_future_mcp",
                    "events_imported": 0,
                }
            )
            return
        output_source = meta.get("source") or provider or "manual_json"
    else:
        events = fixture.get("events") if isinstance(fixture, dict) else fixture
        if not isinstance(events, list):
            events = []
        output_source = "fixture_file"
    with closing(connect(args.db)) as conn:
        with conn:
            for item in events:
                conn.execute(
                    """
                    INSERT INTO event_candidates (
                      hotel_id, date, event_name, event_type, location, distance_km,
                      source_url, confidence, expected_heat, status, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        args.hotel_id,
                        item.get("date"),
                        item.get("event_name") or item.get("name") or "unknown_event",
                        item.get("event_type"),
                        item.get("location"),
                        item.get("distance_km"),
                        item.get("source_url"),
                        float(item.get("confidence") or 0),
                        item.get("expected_heat") or "unknown",
                        item.get("status") or "candidate",
                        now_local(),
                    ),
                )
    emit(
        {
            "status": meta.get("status") if not fixture else "ok",
            "hotel_id": args.hotel_id,
            "date_range": args.date_range,
            "source": output_source,
            "event_source": output_source,
            "cache_status": meta.get("cache_status") if not fixture else None,
            "stale": bool(meta.get("stale")) if not fixture else False,
            "events_imported": len(events),
        }
    )


def event_bridge_check(args: argparse.Namespace) -> None:
    market_source_config = load_market_source_config(getattr(args, "market_source_config", None))
    tenant = market_config_for_hotel(market_source_config, args.hotel_id)
    status = event_bridge_status(market_source_config, hotel_id=args.hotel_id)
    events: list[dict[str, Any]] = []
    meta: dict[str, Any] = {"status": "data_gap", "reason": status.get("reason")}
    if (
        tenant.get("status") == "ok"
        and status.get("bridge_configured")
        and status.get("enabled")
        and status.get("endpoint_localhost")
        and status.get("token_status") == "set"
    ):
        events, meta = load_openclaw_bridge_events(tenant, hotel_id=args.hotel_id, business_date=args.date)
    bridge_verified = meta.get("status") in {"ok", "partial"}
    emit(
        {
            "status": "ok" if bridge_verified else "data_gap",
            "hotel_id": args.hotel_id,
            "business_date": args.date,
            "bridge_configured": bool(status.get("bridge_configured")),
            "bridge_enabled": bool(status.get("enabled")),
            "endpoint_localhost": bool(status.get("endpoint_localhost")),
            "token_status": status.get("token_status"),
            "service_id_verified": bridge_verified or meta.get("reason") == "market_bridge_no_events",
            "source_type_verified": bridge_verified or meta.get("reason") == "market_bridge_no_events",
            "event_count": len(events),
            "commercial_output_allowed": bridge_verified and bool(events),
            "reason": None if bridge_verified else meta.get("reason") or status.get("reason"),
            "source": meta.get("source") or "openclaw_bridge_http_search",
        }
    )

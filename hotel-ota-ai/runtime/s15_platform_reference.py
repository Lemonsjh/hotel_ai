from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

from runtime.sales_progress.metrics import build_metric_baselines
from runtime.sales_progress.repository import MEITUAN_METRICS


def _date(value: Any) -> str:
    return str(value or "")[:10]


def _derived_context(day: str) -> dict[str, Any]:
    parsed = dt.date.fromisoformat(day)
    return {
        "weekday": parsed.weekday(),
        "week_type": "weekend" if parsed.weekday() >= 5 else "weekday",
        "season_type": None,
        "holiday_type": None,
    }


def _context(
    day: str,
    date_contexts: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    derived = _derived_context(day)
    source = dict((date_contexts or {}).get(day) or {})
    weekday = source.get("weekday")
    if isinstance(weekday, str):
        aliases = {
            "mon": 0,
            "monday": 0,
            "tue": 1,
            "tuesday": 1,
            "wed": 2,
            "wednesday": 2,
            "thu": 3,
            "thursday": 3,
            "fri": 4,
            "friday": 4,
            "sat": 5,
            "saturday": 5,
            "sun": 6,
            "sunday": 6,
        }
        weekday = aliases.get(weekday.strip().lower(), derived["weekday"])
    elif weekday is None:
        weekday = derived["weekday"]
    week_type = source.get("week_type") or derived["week_type"]
    return {
        "weekday": int(weekday),
        "week_type": str(week_type),
        "season_type": source.get("season_type"),
        "holiday_type": source.get("holiday_type"),
    }


def _matches(
    candidate: Mapping[str, Any],
    target: Mapping[str, Any],
    fields: Sequence[str],
) -> bool:
    for field in fields:
        expected = target.get(field)
        actual = candidate.get(field)
        if expected in (None, "") or actual in (None, ""):
            return False
        if str(actual) != str(expected):
            return False
    return True


def _confidence(history_day_count: int) -> tuple[str, bool]:
    if history_day_count <= 7:
        return "TREND_ONLY", False
    if history_day_count <= 29:
        return "WEAK_REFERENCE", False
    if history_day_count <= 55:
        return "TEMPORARY", False
    if history_day_count <= 89:
        return "STABLE", True
    return "STRONG", True


def build_platform_reference(
    rows: Sequence[Mapping[str, Any]],
    *,
    target_date: str,
    date_contexts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    target_date = _date(target_date)
    history_days = sorted(
        {
            _date(row.get("business_date"))
            for row in rows
            if _date(row.get("business_date"))
            and _date(row.get("business_date")) != target_date
        }
    )
    target = _context(target_date, date_contexts)
    contexts = {
        day: _context(day, date_contexts)
        for day in history_days
    }
    tiers: tuple[tuple[str, tuple[str, ...]], ...] = (
        (
            "M1_same_season_holiday_weekday_daily",
            ("season_type", "holiday_type", "weekday"),
        ),
        (
            "M2_same_season_holiday_weektype_daily",
            ("season_type", "holiday_type", "week_type"),
        ),
        (
            "M3_same_season_holiday_daily",
            ("season_type", "holiday_type"),
        ),
        ("M4_same_weekday_daily", ("weekday",)),
        ("M5_same_weektype_daily", ("week_type",)),
    )
    selected_tier = "M6_all_daily_trend"
    selected_dates = history_days
    for tier, fields in tiers:
        matched = [
            day
            for day in history_days
            if _matches(contexts[day], target, fields)
        ]
        if matched:
            selected_tier = tier
            selected_dates = matched
            break
    selected_set = set(selected_dates)
    selected_rows = [
        dict(row)
        for row in rows
        if _date(row.get("business_date")) in selected_set
    ]
    metric_result = build_metric_baselines(
        selected_rows,
        MEITUAN_METRICS,
        "meituan",
    )
    confidence, auto_action_allowed = _confidence(len(history_days))
    return {
        "status": "available" if selected_dates else "unavailable",
        "platform": "meituan",
        "grain": "daily",
        "hourly_baseline_available": False,
        "selected_tier": selected_tier,
        "selected_dates": selected_dates,
        "selected_sample_days": len(selected_dates),
        "history_day_count": len(history_days),
        "baseline_confidence_level": confidence,
        "auto_action_allowed": auto_action_allowed,
        "target_context": target,
        "baselines": metric_result.get("baselines") or {},
        "daily_points": metric_result.get("daily_points") or [],
        "conflicts": metric_result.get("conflicts") or [],
        "date_tag_filter_applied": True,
    }

from __future__ import annotations

import datetime as dt
from typing import Any


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _minute_of_day(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.hour * 60 + value.minute
    text = str(value).strip()
    if text.isdigit():
        hour = int(text)
        return hour * 60 if 0 <= hour <= 23 else None
    if "T" in text:
        text = text.replace("T", " ")
    if " " in text:
        text = text.split(" ", 1)[1]
    text = text[:5]
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _time_label(value: Any) -> str | None:
    minute = _minute_of_day(value)
    if minute is None:
        return None
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _actual_rows(actual_snapshots: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in actual_snapshots or []:
        minute = _minute_of_day(item.get("snapshot_at") or item.get("as_of_time") or item.get("hour"))
        sold = _number(item.get("sold_rooms") or item.get("current_sold_rooms") or item.get("orders_cumulative"))
        if minute is None or sold is None:
            continue
        rows.append(
            {
                **dict(item),
                "_minute": minute,
                "_sold_rooms": sold,
                "_orders_cumulative": _number(item.get("orders_cumulative")) or sold,
                "_occupancy_rate": _number(item.get("occupancy_rate")),
            }
        )
    return sorted(rows, key=lambda row: row["_minute"])


def _target_rows(target_curve: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in target_curve or []:
        minute = _minute_of_day(item.get("snapshot_at") or item.get("as_of_time") or item.get("hour"))
        target = _number(
            item.get("target_sold_rooms")
            or item.get("target_room_nights")
            or item.get("checkpoint_target_room_nights")
            or item.get("target_orders")
            or item.get("target")
        )
        if minute is None or target is None:
            continue
        rows.append({**dict(item), "_minute": minute, "_target_sold_rooms": target})
    return sorted(rows, key=lambda row: row["_minute"])


def _pickup_speed(rows: list[dict[str, Any]]) -> str | None:
    if len(rows) < 3:
        return None
    recent = rows[-3:]
    first_delta = recent[1]["_sold_rooms"] - recent[0]["_sold_rooms"]
    second_delta = recent[2]["_sold_rooms"] - recent[1]["_sold_rooms"]
    if second_delta > first_delta:
        return "accelerating"
    if second_delta < first_delta:
        return "slowing"
    return "steady"


def _status(gap: float, daily_remaining_gap: float) -> str:
    if daily_remaining_gap <= 0:
        return "daily_target_met"
    if gap > 0:
        return "ahead_of_checkpoint_but_daily_not_complete"
    if gap < 0:
        return "behind_checkpoint"
    return "on_checkpoint"


def resolve_progress_at_time(
    actual_snapshots: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    target_curve: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    as_of_time: str | None,
    *,
    daily_target_room_nights: int | float | None = None,
    target_strategy: str = "latest_checkpoint_at_or_before_as_of_time",
) -> dict[str, Any]:
    as_of_minute = _minute_of_day(as_of_time)
    if as_of_minute is None:
        return {
            "status": "partial",
            "algorithm": "time_aware_progress_v1",
            "as_of_time": as_of_time,
            "time_grain": "as_of_time",
            "target_strategy": target_strategy,
            "missing_fields": ["as_of_time"],
            "as_of_actual_sold_rooms": None,
            "as_of_target_sold_rooms": None,
            "as_of_checkpoint_gap": None,
            "daily_remaining_gap": None,
        }

    actual_rows = _actual_rows(actual_snapshots)
    targets = _target_rows(target_curve)
    past_actuals = [row for row in actual_rows if row["_minute"] <= as_of_minute]
    future_actuals = [row for row in actual_rows if row["_minute"] > as_of_minute]
    past_targets = [row for row in targets if row["_minute"] <= as_of_minute]
    future_targets = [row for row in targets if row["_minute"] > as_of_minute]
    if not past_actuals:
        return {
            "status": "future_data_leak_blocked" if future_actuals else "partial",
            "algorithm": "time_aware_progress_v1",
            "as_of_time": _time_label(as_of_time),
            "time_grain": "as_of_time",
            "target_strategy": target_strategy,
            "missing_fields": ["future_snapshot_after_as_of_time"] if future_actuals else ["actual_snapshots"],
            "future_rows_ignored": len(future_actuals),
            "as_of_actual_sold_rooms": None,
            "as_of_target_sold_rooms": None,
            "as_of_checkpoint_gap": None,
            "daily_remaining_gap": None,
        }
    if not past_targets:
        return {
            "status": "partial",
            "algorithm": "time_aware_progress_v1",
            "as_of_time": _time_label(as_of_time),
            "time_grain": "as_of_time",
            "target_strategy": target_strategy,
            "missing_fields": ["target_curve_at_or_before_as_of_time"],
            "future_rows_ignored": len(future_actuals),
            "as_of_actual_sold_rooms": past_actuals[-1]["_sold_rooms"],
            "as_of_target_sold_rooms": None,
            "as_of_checkpoint_gap": None,
            "daily_remaining_gap": None,
        }

    actual = past_actuals[-1]
    target = past_targets[-1]
    actual_sold = actual["_sold_rooms"]
    target_sold = target["_target_sold_rooms"]
    daily_target = _number(daily_target_room_nights)
    if daily_target is None:
        daily_target = targets[-1]["_target_sold_rooms"] if targets else target_sold
    gap = actual_sold - target_sold
    daily_remaining = max(0.0, daily_target - actual_sold)
    next_target = future_targets[0] if future_targets else None
    pickup_speed = _pickup_speed(past_actuals)
    result = {
        "status": "ok",
        "algorithm": "time_aware_progress_v1",
        "as_of_time": _time_label(as_of_time),
        "time_grain": "as_of_time",
        "target_strategy": target_strategy,
        "actual_snapshot_at": actual.get("snapshot_at") or _time_label(actual.get("hour")),
        "target_checkpoint_time": _time_label(target.get("hour") or target.get("snapshot_at") or target.get("as_of_time")),
        "as_of_actual_sold_rooms": int(round(actual_sold)),
        "as_of_target_sold_rooms": int(round(target_sold)),
        "as_of_checkpoint_gap": int(round(gap)),
        "daily_target_room_nights": int(round(daily_target)),
        "daily_remaining_gap": int(round(daily_remaining)),
        "next_checkpoint_time": _time_label(next_target.get("hour")) if next_target else None,
        "next_checkpoint_target": int(round(next_target["_target_sold_rooms"])) if next_target else None,
        "projected_next_gap": None,
        "pickup_speed": pickup_speed,
        "progress_status": _status(gap, daily_remaining),
        "future_rows_ignored": len(future_actuals),
        "missing_fields": [] if pickup_speed is not None else ["pickup_speed_requires_three_past_snapshots"],
    }
    if next_target and pickup_speed is not None:
        recent_delta = past_actuals[-1]["_sold_rooms"] - past_actuals[-2]["_sold_rooms"] if len(past_actuals) >= 2 else 0
        projected = actual_sold + max(0, recent_delta)
        result["projected_next_gap"] = int(round(projected - next_target["_target_sold_rooms"]))
    return result

from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _hour(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value)
    try:
        return int(text[:2])
    except ValueError:
        return None


def calculate_progress_trend(hourly_snapshots: list[dict[str, Any]] | tuple[dict[str, Any], ...]) -> dict[str, Any]:
    rows = []
    for item in hourly_snapshots or []:
        sold = _number(item.get("sold_rooms") or item.get("current_sold_rooms") or item.get("orders_cumulative"))
        target = _number(item.get("target_sold_rooms") or item.get("target_room_nights") or item.get("target_orders"))
        hour = _hour(item.get("hour") or item.get("snapshot_at"))
        if sold is None or target is None or hour is None:
            continue
        rows.append({"hour": hour, "sold_rooms": sold, "target_sold_rooms": target, "gap": sold - target})
    rows = sorted(rows, key=lambda row: row["hour"])
    if len(rows) < 2:
        return {
            "status": "partial",
            "algorithm": "hourly_progress_trend_v1",
            "missing_fields": ["hourly_business_snapshots"],
            "pickup_speed": None,
            "trend_gap": None,
            "remaining_sales_window": None,
            "risk_level": "medium",
        }

    recent = rows[-3:]
    pickups = [recent[index]["sold_rooms"] - recent[index - 1]["sold_rooms"] for index in range(1, len(recent))]
    if len(pickups) >= 2 and pickups[-1] > pickups[0]:
        pickup_speed = "accelerating"
    elif len(pickups) >= 2 and pickups[-1] < pickups[0]:
        pickup_speed = "slowing"
    else:
        pickup_speed = "steady"
    latest = rows[-1]
    previous = rows[-2]
    trend_gap = round(latest["gap"] - previous["gap"], 4)
    remaining_sales_window = max(0, 24 - int(latest["hour"]))
    if latest["gap"] < -4 and pickup_speed != "accelerating" and remaining_sales_window <= 4:
        risk_level = "high"
    elif latest["gap"] < 0:
        risk_level = "medium"
    else:
        risk_level = "low"
    return {
        "status": "ok",
        "algorithm": "hourly_progress_trend_v1",
        "pickup_speed": pickup_speed,
        "trend_gap": trend_gap,
        "latest_gap": round(latest["gap"], 4),
        "remaining_sales_window": remaining_sales_window,
        "risk_level": risk_level,
        "hourly_points": rows,
        "missing_fields": [],
    }

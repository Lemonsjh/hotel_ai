from __future__ import annotations

from typing import Any

from runtime.business_context_resolver import resolve_business_context
from runtime.common import DEFAULT_DB, today


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _minute(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if "T" in text:
        text = text.replace("T", " ")
    if " " in text:
        text = text.split(" ", 1)[1]
    text = text[:5]
    parts = text.split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (IndexError, TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _time_label(value: Any) -> str | None:
    minute = _minute(value)
    if minute is None:
        return None
    return f"{minute // 60:02d}:{minute % 60:02d}"


def _safe_flags(context: dict[str, Any] | None = None) -> dict[str, Any]:
    context = context or {}
    return {
        "business_status": "demo_or_historical",
        "today_label_allowed": False,
        "approval_data_allowed": False,
        "approval_preview_allowed": True,
        "formal_approval_allowed": False,
        "formal_approval_created": False,
        "live_allowed": False,
        "live_execution_count": 0,
        "data_source_type": context.get("data_source_type", "unavailable"),
        "freshness_status": context.get("freshness_status", "missing_date"),
    }


def _actual_hourly_sales(progress: dict[str, Any], orders: dict[str, Any], as_of_time: str | None) -> list[dict[str, Any]]:
    rows = progress.get("hourly_business_snapshots") or []
    if not rows:
        cumulative = 0
        rows = []
        for item in orders.get("hourly_order_progress") or []:
            increment = _number(item.get("synthetic_room_nights") or item.get("room_nights") or item.get("orders_increment")) or 0
            cumulative += increment
            rows.append(
                {
                    "hour": item.get("hour"),
                    "as_of_time": item.get("hour"),
                    "snapshot_at": item.get("snapshot_at") or item.get("hour"),
                    "sold_rooms": cumulative,
                    "orders_cumulative": cumulative,
                    "orders_increment": increment,
                    "data_source_type": orders.get("data_source_type"),
                    "freshness_status": orders.get("freshness_status"),
                }
            )
    cutoff = _minute(as_of_time)
    normalized = []
    for item in rows:
        label = _time_label(item.get("as_of_time") or item.get("snapshot_at") or item.get("hour"))
        minute = _minute(label)
        if minute is None:
            continue
        if cutoff is not None and minute > cutoff:
            continue
        normalized.append(
            {
                "hour": label,
                "as_of_time": label,
                "snapshot_at": item.get("snapshot_at") or label,
                "sold_rooms": int(round(_number(item.get("sold_rooms") or item.get("current_sold_rooms") or item.get("orders_cumulative")) or 0)),
                "orders_cumulative": int(round(_number(item.get("orders_cumulative") or item.get("sold_rooms")) or 0)),
                "orders_increment": int(round(_number(item.get("orders_increment")) or 0)),
                "occupancy_rate": item.get("occupancy_rate"),
                "target_sold_rooms": item.get("target_sold_rooms") or item.get("target_room_nights"),
                "data_source_type": item.get("data_source_type") or orders.get("data_source_type"),
                "freshness_status": item.get("freshness_status") or orders.get("freshness_status"),
            }
        )
    return normalized


def _target_curve(baseline: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for item in baseline.get("hourly_target_curve") or baseline.get("checkpoint_targets") or []:
        label = _time_label(item.get("as_of_time") or item.get("hour") or item.get("snapshot_at"))
        if label is None:
            continue
        target = _number(
            item.get("target_sold_rooms")
            or item.get("target_room_nights")
            or item.get("checkpoint_target_room_nights")
            or item.get("target_orders")
            or item.get("target")
        )
        rows.append(
            {
                "hour": label,
                "as_of_time": label,
                "target_sold_rooms": int(round(target or 0)),
                "target_room_nights": int(round(target or 0)),
                "data_source_type": item.get("data_source_type") or baseline.get("data_source_type"),
                "freshness_status": item.get("freshness_status") or baseline.get("freshness_status"),
            }
        )
    return rows


def _completion(actual: Any, target: Any) -> float | None:
    actual_number = _number(actual)
    target_number = _number(target)
    if actual_number is None or target_number in (None, 0):
        return None
    return round(actual_number / target_number, 4)


def build_progress_diagnosis(
    *,
    db_path: str | None = None,
    hotel_id: str = "puyue-demo",
    business_date: str | None = None,
    as_of_time: str | None = None,
    use_generated_today: bool = False,
    strict_generated_today: bool = False,
    demo_data_dir: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = context or resolve_business_context(
        db_path=db_path or DEFAULT_DB,
        hotel_id=hotel_id,
        business_date=business_date,
        as_of_time=as_of_time,
        mode="demo" if use_generated_today else "auto",
        use_generated_today=use_generated_today,
        strict_generated_today=strict_generated_today,
        demo_data_dir=demo_data_dir,
    )
    if resolved.get("status") == "data_gap":
        return {
            "status": "data_gap",
            "node_id": "N011",
            "skill_id": "S16",
            "hotel_id": hotel_id,
            "business_date": business_date or today(),
            "context_source": resolved.get("context_source"),
            "blocked_reason": resolved.get("blocked_reason") or "strict_generated_today_no_static_fallback",
            "missing_fields": resolved.get("missing_fields") or resolved.get("data_gaps") or ["synthetic_today_demo"],
            **_safe_flags(resolved),
        }

    facts = resolved.get("facts") or {}
    progress = dict(facts.get("progress_deviation") or resolved.get("progress") or {})
    baseline = dict(facts.get("sales_baseline") or {})
    orders = dict(facts.get("orders_aggregate") or {})
    selected_as_of = as_of_time or resolved.get("as_of_time") or progress.get("as_of_time")
    if selected_as_of is None:
        return {
            "status": "partial",
            "node_id": "N011",
            "skill_id": "S16",
            "hotel_id": hotel_id,
            "business_date": business_date or resolved.get("business_date"),
            "data_business_date": business_date or resolved.get("business_date"),
            "as_of_time": None,
            "as_of_time_source": resolved.get("as_of_time_source") or "not_provided",
            "context_source": resolved.get("context_source"),
            "data_source_type": resolved.get("data_source_type"),
            "freshness_status": resolved.get("freshness_status"),
            "actual_hourly_sales": [],
            "target_hourly_curve": [],
            "actual_vs_target_hourly": [],
            "as_of_actual_sold_rooms": None,
            "as_of_target_sold_rooms": None,
            "as_of_checkpoint_gap": None,
            "daily_remaining_gap": None,
            "pickup_speed": None,
            "progress_status": "time_context_required",
            "deviation_reasons": ["as_of_time_required"],
            "missing_fields": ["as_of_time"],
            "summary": "S16 requires an explicit current time before comparing actual sales with the matching checkpoint target.",
            "not_allowed_conclusions": [
                "cannot_use_last_hourly_snapshot_as_current_progress",
                "synthetic_or_demo_data_cannot_create_formal_approval_or_live_execution",
            ],
            "formal_approval_created": False,
            "live_allowed": False,
            "live_execution_count": 0,
            **_safe_flags(resolved),
        }
    actual_rows = _actual_hourly_sales(progress, orders, selected_as_of)
    target_rows = _target_curve(baseline)
    actual = progress.get("as_of_actual_sold_rooms")
    target = progress.get("as_of_target_sold_rooms")
    daily_target = progress.get("daily_target_room_nights") or baseline.get("daily_target_room_nights") or baseline.get("target_room_nights")
    data_source_type = resolved.get("data_source_type") or progress.get("data_source_type")
    synthetic_or_demo = data_source_type in {"synthetic_today_demo", "demo_data"}
    status = "preview_only" if synthetic_or_demo else ("ok" if progress.get("status") == "ok" else "partial")
    if progress.get("status") in {"partial", "future_data_leak_blocked"}:
        status = "partial"
    comparison = []
    targets_by_hour = {item["hour"]: item for item in target_rows}
    for row in actual_rows:
        target_row = targets_by_hour.get(row["hour"]) or {}
        target_sold = target_row.get("target_sold_rooms")
        comparison.append(
            {
                "hour": row["hour"],
                "actual_sold_rooms": row["sold_rooms"],
                "target_sold_rooms": target_sold,
                "gap": row["sold_rooms"] - target_sold if isinstance(target_sold, int) else None,
            }
        )
    return {
        "status": status,
        "node_id": "N011",
        "skill_id": "S16",
        "hotel_id": hotel_id,
        "business_date": business_date or resolved.get("business_date"),
        "data_business_date": business_date or resolved.get("business_date"),
        "as_of_time": selected_as_of,
        "as_of_time_source": resolved.get("as_of_time_source") or "explicit_argument",
        "context_source": resolved.get("context_source"),
        "data_source_type": data_source_type,
        "freshness_status": resolved.get("freshness_status") or progress.get("freshness_status"),
        "actual_hourly_sales": actual_rows,
        "target_hourly_curve": target_rows,
        "actual_vs_target_hourly": comparison,
        "as_of_actual_sold_rooms": actual,
        "as_of_target_sold_rooms": target,
        "as_of_checkpoint_gap": progress.get("as_of_checkpoint_gap"),
        "daily_remaining_gap": progress.get("daily_remaining_gap"),
        "pickup_speed": progress.get("pickup_speed"),
        "progress_status": progress.get("progress_status"),
        "deviation_reasons": progress.get("deviation_reason_candidates") or progress.get("deviation_reasons") or [],
        "daily_target_room_nights": daily_target,
        "target_room_nights": daily_target,
        "actual_room_nights": actual,
        "checkpoint_target_room_nights": target,
        "room_night_gap": progress.get("as_of_checkpoint_gap"),
        "completion_rate": _completion(actual, target),
        "daily_completion_rate": _completion(actual, daily_target),
        "future_rows_ignored": progress.get("future_rows_ignored"),
        "missing_fields": progress.get("missing_fields") or [],
        "summary": "S16 progress diagnosis uses runtime business context and time-aware synthetic/current data.",
        "not_allowed_conclusions": [
            "synthetic_or_demo_data_cannot_be_used_as_real_today_business_result",
            "synthetic_or_demo_data_cannot_create_formal_approval_or_live_execution",
        ],
        "run_context": {
            "context_source": resolved.get("context_source"),
            "business_date": resolved.get("business_date"),
            "data_source_type": resolved.get("data_source_type"),
            "freshness_status": resolved.get("freshness_status"),
            "fallback_used": bool(resolved.get("fallback_used")),
            "generated_demo_run_id": resolved.get("generated_demo_run_id"),
            "generated_at": resolved.get("generated_at"),
        },
        "coverage_report": resolved.get("coverage_report"),
        "formal_approval_created": False,
        "live_allowed": False,
        "live_execution_count": 0,
        **_safe_flags(resolved),
    }

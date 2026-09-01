from __future__ import annotations

from typing import Any

from runtime.algorithms.run_context import build_run_context
from runtime.algorithms.time_aware_progress import resolve_progress_at_time
from runtime.common import DEFAULT_DB
from runtime.time_context import normalize_as_of_time


def _coverage_report(facts: dict[str, Any], progress: dict[str, Any]) -> dict[str, Any]:
    coverage_by_skill: dict[str, dict[str, list[str]]] = {}
    skill_fields = {
        "S15": ["daily_target_room_nights", "hourly_target_curve", "active_target_source"],
        "S16": ["as_of_actual_sold_rooms", "as_of_target_sold_rooms", "as_of_checkpoint_gap", "daily_remaining_gap"],
        "S5": ["as_of_checkpoint_gap", "daily_remaining_gap", "pickup_speed", "current_window_type", "conversion_problem"],
    }
    available = set()
    for payload in facts.values():
        if isinstance(payload, dict):
            available.update(str(key) for key, value in payload.items() if value not in (None, "", [], {}))
    available.update(str(key) for key, value in progress.items() if value not in (None, "", [], {}))
    for skill_id, fields in skill_fields.items():
        used = [field for field in fields if field in available]
        missing = [field for field in fields if field not in available]
        coverage_by_skill[skill_id] = {
            "available_fields": sorted(used),
            "used_by_algorithm": sorted(used),
            "display_only": [],
            "missing_fields": sorted(missing),
            "disabled_by_time_context": sorted(progress.get("missing_fields") or []),
        }
    return {"coverage_by_skill": coverage_by_skill}


def _normalize_baseline(baseline: dict[str, Any], context_source: str | None) -> dict[str, Any]:
    result = dict(baseline)
    target = result.get("target_room_nights") or result.get("target_sold_rooms") or result.get("sales_baseline")
    result["daily_target_room_nights"] = target
    result["synthetic_today_target_room_nights"] = target if context_source == "sqlite_synthetic_today_demo" else None
    result["sample_target_room_nights"] = 15
    result["real_business_target_room_nights"] = target if result.get("data_source_type") == "real_data" else None
    result["active_target_source"] = "synthetic_today_demo" if context_source == "sqlite_synthetic_today_demo" else "static_demo_fixture"
    result["sample_target_active"] = False
    result["checkpoint_targets"] = result.get("checkpoint_targets") or result.get("hourly_target_curve") or []
    return result


def resolve_business_context(
    *,
    db_path: str = DEFAULT_DB,
    hotel_id: str | None = None,
    business_date: str | None = None,
    as_of_time: str | None = None,
    as_of_time_source: str | None = None,
    mode: str = "auto",
    use_generated_today: bool = False,
    demo_data_dir: str | None = None,
    strict_generated_today: bool = False,
) -> dict[str, Any]:
    requested_generated = bool(use_generated_today or mode in {"demo", "synthetic_today_demo"})
    context = build_run_context(
        db_path=db_path,
        hotel_id=hotel_id,
        use_generated_today=requested_generated,
        demo_data_dir=demo_data_dir,
        strict_generated_today=strict_generated_today,
    )
    if context.get("status") == "data_gap":
        return context
    if hotel_id and context.get("hotel_id") not in {None, hotel_id}:
        return {
            "status": "data_gap",
            "reason": "tenant_context_not_found",
            "hotel_id": hotel_id,
            "requested_hotel_id": hotel_id,
            "context_source": context.get("context_source"),
            "data_source_type": context.get("data_source_type"),
            "freshness_status": context.get("freshness_status"),
            "business_date": business_date or context.get("business_date"),
            "context_warnings": ["tenant_context_not_found"],
        }
    facts = {key: dict(value) if isinstance(value, dict) else value for key, value in (context.get("facts") or {}).items()}
    baseline = _normalize_baseline(dict(facts.get("sales_baseline") or {}), context.get("context_source"))
    progress = dict(facts.get("progress_deviation") or {})
    hourly = progress.get("hourly_business_snapshots") or []
    selected_as_of = normalize_as_of_time(as_of_time)
    time_progress = resolve_progress_at_time(
        hourly,
        baseline.get("hourly_target_curve") or baseline.get("checkpoint_targets") or [],
        selected_as_of,
        daily_target_room_nights=baseline.get("daily_target_room_nights"),
    )
    progress.update(time_progress)
    progress["current_sold_rooms"] = time_progress.get("as_of_actual_sold_rooms", progress.get("current_sold_rooms"))
    progress["target_sold_rooms"] = time_progress.get("daily_target_room_nights", progress.get("target_sold_rooms"))
    progress["room_night_gap"] = time_progress.get("as_of_checkpoint_gap", progress.get("room_night_gap"))
    facts["sales_baseline"] = baseline
    facts["progress_deviation"] = progress
    business = dict(facts.get("business_snapshot") or {})
    coverage = _coverage_report(facts, progress)
    resolved = dict(context)
    resolved.update(
        {
            "status": "partial" if selected_as_of is None else "ok",
            "facts": facts,
            "business_date": business_date or context.get("business_date"),
            "as_of_time": time_progress.get("as_of_time"),
            "as_of_time_source": as_of_time_source or ("not_provided" if selected_as_of is None else "explicit_argument"),
            "time_context_required": selected_as_of is None,
            "time_context_status": time_progress.get("status"),
            "snapshot_at": time_progress.get("actual_snapshot_at") or business.get("data_snapshot_time") or context.get("generated_at"),
            "storage_source": "sqlite" if context.get("context_source") == "sqlite_synthetic_today_demo" else "fixture",
            "_db_path": db_path,
            "context_source": context.get("context_source"),
            "data_source_type": context.get("data_source_type"),
            "freshness_status": context.get("freshness_status"),
            "time_grain": "as_of_time",
            "sold_rooms_cumulative": time_progress.get("as_of_actual_sold_rooms"),
            "orders_cumulative": time_progress.get("as_of_actual_sold_rooms"),
            "occupancy_rate": business.get("occupancy_rate"),
            "daily_target_room_nights": baseline.get("daily_target_room_nights"),
            "active_target_source": baseline.get("active_target_source"),
            "hourly_target_curve": baseline.get("hourly_target_curve") or [],
            "coverage_report": coverage,
            "progress": progress,
        }
    )
    return resolved

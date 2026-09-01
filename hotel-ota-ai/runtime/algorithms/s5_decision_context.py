from __future__ import annotations

from typing import Any

from runtime.algorithms.competitor_alert import calculate_competitor_alert
from runtime.algorithms.demand_index import calculate_demand_index
from runtime.algorithms.ota_health_score import calculate_ota_health_score
from runtime.field_trigger_policy import evaluate_field_triggers
from runtime.time_context import minute_of_day, normalize_as_of_time


RUNTIME_REQUIRED_FIELDS = [
    "current_price",
    "floor_price",
    "ceiling_price",
    "expected_occupancy_tonight",
    "baseline_price_by_room_type",
]

ALGORITHM_USED_FIELDS = [
    "current_price",
    "floor_price",
    "ceiling_price",
    "demand_pressure",
    "as_of_checkpoint_gap",
    "daily_remaining_gap",
    "pickup_speed",
    "inventory_pressure",
    "conversion_problem",
    "competitor_context",
    "traffic_timing_context",
    "diagnosis_status",
]

CONTEXT_DISCLOSURE_FIELDS = [
    "expected_occupancy_tonight",
    "baseline_price_by_room_type",
    "reservation_details",
    "hourly_target_curve",
    "weather_signal",
    "event_signal",
    "ota_health_score",
    "payment_conversion_rate",
]


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def _rate(present: int, total: int) -> float:
    if total <= 0:
        return 1.0
    return round(present / total, 4)


def _first_room(context: dict[str, Any]) -> dict[str, Any]:
    rooms = (((context.get("facts") or {}).get("room_types") or {}).get("room_types") or [])
    return dict(rooms[0] if rooms else {})


def _available_fields(context: dict[str, Any], derived: dict[str, Any]) -> set[str]:
    facts = context.get("facts") or {}
    fields: set[str] = set()
    for payload in list(facts.values()) + [derived]:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if _present(value):
                    fields.add(str(key))
    room = _first_room(context)
    for key, value in room.items():
        if _present(value):
            fields.add(str(key))
    return fields


def _field_usage_states(available: set[str], derived: dict[str, Any], used_fields: list[str]) -> dict[str, str]:
    states: dict[str, str] = {}
    for field in sorted(set(RUNTIME_REQUIRED_FIELDS + ALGORITHM_USED_FIELDS + CONTEXT_DISCLOSURE_FIELDS)):
        if field in used_fields:
            states[field] = "used_by_algorithm"
        elif _present(derived.get(field)) or field in available:
            states[field] = "available_context"
        else:
            states[field] = "missing"
    return states


def _traffic_timing_context(context: dict[str, Any], progress: dict[str, Any]) -> dict[str, Any]:
    market = ((context.get("facts") or {}).get("market_context") or {})
    peak = market.get("traffic_peak_window") or "19:00-22:00"
    as_of_time = normalize_as_of_time(context.get("as_of_time"))
    as_of_minute = minute_of_day(as_of_time)
    bounds = [minute_of_day(value) for value in str(peak).split("-", 1)]
    if as_of_minute is None or len(bounds) != 2 or None in bounds:
        current_window_type = "unknown"
        remaining_minutes = None
    elif as_of_minute < bounds[0]:
        current_window_type = "pre_peak"
        remaining_minutes = bounds[0] - as_of_minute
    elif as_of_minute <= bounds[1]:
        current_window_type = "in_or_near_peak"
        remaining_minutes = bounds[1] - as_of_minute
    else:
        current_window_type = "post_peak"
        remaining_minutes = 0
    return {
        "next_peak_window": peak,
        "as_of_time": as_of_time,
        "current_window_type": current_window_type,
        "remaining_high_traffic_minutes": remaining_minutes,
        "booking_curve_stage": progress.get("pickup_speed") or "unknown",
        "trend_gap": progress.get("as_of_checkpoint_gap"),
        "risk_level": progress.get("progress_status") or "unknown",
    }


def build_s5_decision_context(
    context: dict[str, Any],
    *,
    scenario_id: str = "SC03",
    active_optional_edges: set[str] | None = None,
) -> dict[str, Any]:
    facts = context.get("facts") or {}
    room = _first_room(context)
    orders = facts.get("orders_aggregate") or {}
    baseline = facts.get("sales_baseline") or {}
    progress = facts.get("progress_deviation") or {}
    demand = calculate_demand_index(context)
    competitor = calculate_competitor_alert(context)
    health = calculate_ota_health_score(context)
    traffic_timing = _traffic_timing_context(context, progress)
    competitor_context = dict(competitor.get("competitor_context") or {})
    diagnosis_status = health.get("diagnosis_status") or health.get("status")
    conversion = health.get("conversion_funnel") or {}
    conversion_rates = conversion.get("rates") if isinstance(conversion, dict) else {}

    derived = {
        "price_floor": room.get("floor_price"),
        "price_ceiling": room.get("ceiling_price"),
        "approval_policy": "demo_preview_only",
        "live_switch": False,
        "source_capability": "read_only",
        "skill_switch": True,
        "execution_boundary": "preview_only_no_live",
        "current_price": room.get("current_price"),
        "floor_price": room.get("floor_price"),
        "ceiling_price": room.get("ceiling_price"),
        "expected_occupancy_tonight": orders.get("expected_occupancy_tonight"),
        "baseline_price_by_room_type": baseline.get("baseline_price_by_room_type"),
        "demand_pressure": float(demand.get("demand_index") or 0) / 100.0,
        "as_of_checkpoint_gap": progress.get("as_of_checkpoint_gap"),
        "daily_remaining_gap": progress.get("daily_remaining_gap"),
        "pickup_speed": progress.get("pickup_speed"),
        "as_of_actual_sold_rooms": progress.get("as_of_actual_sold_rooms"),
        "as_of_target_sold_rooms": progress.get("as_of_target_sold_rooms"),
        "time_grain": progress.get("time_grain"),
        "inventory_pressure": (demand.get("inventory_diagnosis") or {}).get("inventory_pressure"),
        "conversion_problem": (conversion.get("conversion_problem") if isinstance(conversion, dict) else None),
        "ota_health_score": health.get("ota_health_score"),
        "payment_conversion_rate": (conversion_rates or {}).get("payment_conversion_rate"),
        "weather_signal": (facts.get("market_context") or {}).get("weather_signal"),
        "event_signal": (facts.get("market_context") or {}).get("event_signal"),
        "reservation_details": orders.get("reservation_details"),
        "hourly_target_curve": baseline.get("hourly_target_curve"),
        "competitor_context": competitor_context,
        "traffic_timing_context": traffic_timing,
        "diagnosis_status": diagnosis_status,
    }
    available = _available_fields(context, derived)
    trigger_report = evaluate_field_triggers(
        scenario_id,
        skill_id="S5",
        available_fields=available,
        active_optional_edges=active_optional_edges,
    )
    runtime_missing = [field for field in RUNTIME_REQUIRED_FIELDS if not _present(derived.get(field))]
    algorithm_present = sum(1 for field in ALGORITHM_USED_FIELDS if _present(derived.get(field)))
    contract_triggered = trigger_report.get("triggered_required_fields") or []
    contract_missing = trigger_report.get("missing_triggered_fields") or []
    contract_coverage = _rate(len(contract_triggered) - len(contract_missing), len(contract_triggered))
    runtime_coverage = _rate(len(RUNTIME_REQUIRED_FIELDS) - len(runtime_missing), len(RUNTIME_REQUIRED_FIELDS))
    algorithm_coverage = _rate(algorithm_present, len(ALGORITHM_USED_FIELDS))
    algorithm_used_inputs = [field for field in ALGORITHM_USED_FIELDS if _present(derived.get(field))]
    algorithm_unused_available_inputs = [
        field
        for field in CONTEXT_DISCLOSURE_FIELDS
        if field in available and field not in algorithm_used_inputs
    ]
    field_usage_states = _field_usage_states(available, derived, algorithm_used_inputs)

    is_static_demo_fallback = (
        context.get("context_source") == "static_demo_fixtures"
        or context.get("data_source_type") == "demo_data"
    )
    missing_time_context_fields = [] if normalize_as_of_time(context.get("as_of_time")) else ["as_of_time"]
    not_allowed: list[str] = []
    if is_static_demo_fallback or runtime_missing or diagnosis_status in {"partial", "data_gap"}:
        not_allowed.append("cannot_confirm_price_is_primary_issue")
    if missing_time_context_fields:
        not_allowed.append("cannot_assess_current_pricing_timing_without_as_of_time")
    if trigger_report["missing_by_policy"].get("hard_required"):
        decision_strength = "data_gap"
    elif is_static_demo_fallback:
        decision_strength = "partial"
    elif missing_time_context_fields or runtime_missing or diagnosis_status in {"partial", "data_gap"} or algorithm_coverage < 0.9:
        decision_strength = "partial"
    else:
        decision_strength = "full"

    return {
        "context_source": context.get("context_source"),
        "as_of_time": normalize_as_of_time(context.get("as_of_time")),
        "as_of_time_source": context.get("as_of_time_source") or "not_provided",
        "missing_time_context_fields": missing_time_context_fields,
        "scenario_id": scenario_id,
        "active_edges": trigger_report.get("active_edges") or [],
        "inactive_optional_edges": trigger_report.get("inactive_optional_edges") or [],
        "triggered_required_fields": contract_triggered,
        "missing_triggered_fields": contract_missing,
        "untriggered_optional_fields": trigger_report.get("untriggered_optional_fields") or [],
        "contract_input_coverage": contract_coverage,
        "runtime_feed_coverage": runtime_coverage,
        "algorithm_usage_coverage": algorithm_coverage,
        "algorithm_used_inputs": algorithm_used_inputs,
        "algorithm_unused_available_inputs": algorithm_unused_available_inputs,
        "field_usage_states": field_usage_states,
        "decision_strength": decision_strength,
        "not_allowed_conclusions": not_allowed,
        "conversion_problem": derived["conversion_problem"],
        "ota_health_score": derived["ota_health_score"],
        "payment_conversion_rate": derived["payment_conversion_rate"],
        "our_price_index": competitor_context.get("our_price_index"),
        "current_window_type": traffic_timing.get("current_window_type"),
        "pickup_speed": derived.get("pickup_speed"),
        "pricing_guard_context": {
            "current_price": room.get("current_price"),
            "floor_price": room.get("floor_price"),
            "ceiling_price": room.get("ceiling_price"),
            "max_single_change_pct": room.get("max_single_change_pct"),
            "max_increase_pct": room.get("max_increase_pct", room.get("max_single_change_pct")),
            "max_decrease_pct": room.get("max_decrease_pct", room.get("max_single_change_pct")),
            "min_increase_pct": room.get("min_increase_pct", 0.0),
            "min_decrease_pct": room.get("min_decrease_pct", 0.0),
        },
        "business_pressure_context": {
            "expected_occupancy_tonight": orders.get("expected_occupancy_tonight"),
            "as_of_checkpoint_gap": progress.get("as_of_checkpoint_gap"),
            "daily_remaining_gap": progress.get("daily_remaining_gap"),
            "as_of_actual_sold_rooms": progress.get("as_of_actual_sold_rooms"),
            "as_of_target_sold_rooms": progress.get("as_of_target_sold_rooms"),
            "progress_status": progress.get("progress_status"),
        },
        "market_context": {
            "demand_index": demand.get("demand_index"),
            "demand_level": demand.get("demand_level"),
            "demand_formula_version": demand.get("formula_version"),
            "demand_sub_scores": demand.get("sub_scores") or {},
            "demand_calibration_applied": demand.get("calibration_applied") or [],
            "weather_signal": derived["weather_signal"],
            "event_signal": derived["event_signal"],
        },
        "competitor_context": competitor_context,
        "traffic_timing_context": traffic_timing,
        "conversion_health_context": {
            "ota_health_score": health.get("ota_health_score"),
            "conversion_problem": derived["conversion_problem"],
            "conversion_funnel": conversion,
        },
        "diagnosis_constraint_context": {
            "diagnosis_status": diagnosis_status,
            "usable_findings": health.get("usable_findings") or [],
            "not_allowed_conclusions": health.get("not_allowed_conclusions") or [],
        },
        "data_gap_context": {
            "missing_runtime_fields": runtime_missing,
            "missing_contract_fields": contract_missing,
            "missing_by_policy": trigger_report.get("missing_by_policy") or {},
        },
        "direct_price_trigger_allowed": False,
    }

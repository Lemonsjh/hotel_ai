from __future__ import annotations

import re
from typing import Any

from runtime.algorithm_rule_loader import find_algorithm_rule
from runtime.algorithms.revenue_decision_engine import build_s5_decision_ref, calculate_revenue_recommendation
from runtime.control_plane import resolve_price_guard_policy


HARD_REQUIRED = [
    "hotel_id",
    "data_business_date",
    "current_price",
    "floor_price",
    "ceiling_price",
    "freshness_status",
    "data_source_type",
]
DEMO_METADATA = {
    "data_source_type": "demo_data",
    "freshness_status": "demo_data",
    "business_status": "demo_or_historical",
    "today_label_allowed": False,
    "approval_data_allowed": False,
    "live_allowed": False,
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _merge_payload(payload: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    merged.update(payload.get("demo_input") or {})
    merged.update(payload.get("demo_meta") or {})
    merged.update({key: value for key, value in payload.items() if not isinstance(value, (dict, list))})
    return merged


def _is_demo_payload(payload: dict[str, Any]) -> bool:
    return payload.get("data_source_type") in {"demo_data", "synthetic_today_demo"} or payload.get("freshness_status") in {"demo_data", "synthetic_current_day"}


def _mark_demo_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    if data.get("data_source_type") == "synthetic_today_demo":
        data.update(
            {
                "data_source_type": "synthetic_today_demo",
                "freshness_status": "synthetic_current_day",
                "business_status": "demo_or_historical",
                "today_label_allowed": False,
                "approval_data_allowed": False,
                "live_allowed": False,
            }
        )
    else:
        data.update(DEMO_METADATA)
    risk_flags = set(data.get("risk_flags") or [])
    risk_flags.add("demo_data")
    data["risk_flags"] = sorted(risk_flags)
    return data


def _progress_gap(data: dict[str, Any]) -> float:
    if "progress_gap" in data:
        return _to_float(data.get("progress_gap"))
    completion_rate = data.get("completion_rate")
    if completion_rate is not None:
        return _to_float(completion_rate) - 1.0
    status = str(data.get("progress_status") or "").lower()
    if status in {"behind", "lagging", "under_target"}:
        return -0.08
    if status in {"ahead", "over_target"}:
        return 0.06
    return 0.0


def _bounded_candidate(current_price: float, floor_price: float, ceiling_price: float, change_pct: float, max_change_pct: float) -> float:
    bounded_change = max(-max_change_pct, min(max_change_pct, change_pct))
    candidate = current_price * (1.0 + bounded_change)
    candidate = max(floor_price, min(ceiling_price, candidate))
    return round(candidate, 2)


def _calculate_recommendation(data: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, Any]:
    current_price = _to_float(data["current_price"])
    floor_price = _to_float(data["floor_price"])
    ceiling_price = _to_float(data["ceiling_price"], current_price)
    max_change_pct = _to_float(data.get("max_single_change_pct"), _to_float(thresholds.get("max_single_change_pct"), 0.15))
    max_change_pct = max(0.01, min(max_change_pct, 0.30))

    demand_pressure = _to_float(data.get("demand_pressure"), _to_float(data.get("demand_index"), 50.0) / 100.0)
    progress_gap = _progress_gap(data)
    inventory_pressure = _to_float(data.get("inventory_pressure"), 0.5)
    conversion_problem = bool(data.get("conversion_problem"))

    change_pct = 0.0
    if demand_pressure >= 0.72:
        change_pct += 0.08
    elif demand_pressure <= 0.40:
        change_pct -= 0.05
    if progress_gap < -0.05:
        change_pct -= 0.02
    elif progress_gap > 0.05:
        change_pct += 0.03
    if inventory_pressure >= 0.70:
        change_pct += 0.04
    elif inventory_pressure <= 0.30:
        change_pct -= 0.03
    if conversion_problem:
        change_pct -= 0.03

    candidate_price = _bounded_candidate(current_price, floor_price, ceiling_price, change_pct, max_change_pct)
    actual_change_pct = 0.0 if current_price == 0 else round((candidate_price - current_price) / current_price, 4)
    if candidate_price > current_price:
        price_action = "increase"
    elif candidate_price < current_price:
        price_action = "decrease"
    else:
        price_action = "hold"
    risk_level = "medium" if abs(actual_change_pct) >= 0.08 else "low"
    raw_conservative_price = _to_float(data.get("conservative_price"), candidate_price)
    if price_action == "decrease":
        conservative_price = min(current_price, max(candidate_price, raw_conservative_price))
    elif price_action == "increase":
        conservative_price = max(current_price, min(candidate_price, raw_conservative_price))
    else:
        conservative_price = current_price
    conservative_price = round(max(floor_price, min(ceiling_price, conservative_price)), 2)
    return {
        "room_type_id": data.get("room_type_id"),
        "room_type_name": data.get("room_type_name"),
        "channel": data.get("channel"),
        "adapter": data.get("adapter"),
        "method": data.get("method"),
        "price_action": price_action,
        "candidate_price": candidate_price,
        "conservative_price": conservative_price,
        "execution_price": conservative_price,
        "current_price": current_price,
        "floor_price": floor_price,
        "ceiling_price": ceiling_price,
        "max_single_change_pct": max_change_pct,
        "actual_change_pct": actual_change_pct,
        "progress_gap": round(progress_gap, 4),
        "demand_pressure": round(demand_pressure, 4),
        "inventory_pressure": round(inventory_pressure, 4),
        "risk_level": risk_level,
    }


def run_revenue_decision_demo(payload: dict[str, Any], *, db_path: str | None = None) -> dict[str, Any]:
    data = _merge_payload(payload)
    missing = [field for field in HARD_REQUIRED if data.get(field) in (None, "")]
    if missing:
        return {
            "skill_id": "S5",
            "node_id": "N015",
            "status": "blocked",
            **DEMO_METADATA,
            "reason": "missing_hard_required_fields",
            "missing_fields": missing,
            "approval_data_allowed": False,
            "live_allowed": False,
            "blocked_for_live": True,
            "formal_approval_created": False,
            "live_execution_count": 0,
        }

    rule = find_algorithm_rule(skill_id="S5")
    thresholds = ((rule.get("algorithm") or {}).get("thresholds") or {})
    time_context_missing = bool(data.get("missing_time_context_fields")) or not data.get("as_of_time")
    selected = calculate_revenue_recommendation(data, thresholds)
    room_type_recommendations: list[dict[str, Any]] = []
    policy_time = str(data.get("as_of_time") or data.get("data_business_date") or data.get("business_date") or "")
    business_date = str(data.get("data_business_date") or data.get("business_date") or "")
    if re.fullmatch(r"\d{2}:\d{2}", policy_time) and business_date:
        policy_time = f"{business_date}T{policy_time}:00"
    for room in data.get("room_type_candidates") or []:
        room_data = dict(data)
        room_data.update(room)
        room_type_id = str(room_data.get("room_type_id") or "")
        policy = None
        if db_path and room_type_id and data.get("hotel_id"):
            policy = resolve_price_guard_policy(
                db_path,
                hotel_id=str(data["hotel_id"]),
                room_type_id=room_type_id,
                at_time=policy_time,
            )
            if policy.get("floor_price") is not None:
                room_data["floor_price"] = policy["floor_price"]
            if policy.get("ceiling_price") is not None:
                room_data["ceiling_price"] = policy["ceiling_price"]
            for field in ("max_increase_pct", "max_decrease_pct", "min_increase_pct", "min_decrease_pct"):
                room_data[field] = policy.get(field)
        room_data["inventory_pressure"] = _to_float(room.get("sold_rooms")) / max(_to_float(room.get("inventory"), 1.0), 1.0)
        recommendation = calculate_revenue_recommendation(room_data, thresholds)
        if policy:
            recommendation.update(
                {
                    "price_guard_source": policy.get("source"),
                    "price_guard_policy_id": policy.get("policy_id"),
                    "price_guard_policy_version": policy.get("version"),
                    "price_guard_policy_state": policy.get("policy_state"),
                }
            )
        else:
            recommendation["price_guard_source"] = "algorithm_default"
        recommendation["rank"] = len(room_type_recommendations) + 1
        room_type_recommendations.append(recommendation)
    if not room_type_recommendations:
        selected_with_rank = dict(selected)
        selected_with_rank["rank"] = 1
        room_type_recommendations = [selected_with_rank]
    selected_recommendation = room_type_recommendations[0]
    if time_context_missing:
        selected_recommendation = dict(selected_recommendation)
        selected_recommendation["action_timing"] = "time_context_required"
        selected_recommendation["reason_codes"] = list(selected_recommendation.get("reason_codes") or []) + ["as_of_time_required"]

    demo_payload = _mark_demo_payload(data) if _is_demo_payload(data) else {**data, "approval_data_allowed": False, "live_allowed": False}
    decision_ref = build_s5_decision_ref(
        selected_recommendation,
        freshness_status=demo_payload.get("freshness_status"),
        business_date=demo_payload.get("data_business_date") or demo_payload.get("business_date") or demo_payload.get("demo_business_date"),
        hotel_id=demo_payload.get("hotel_id"),
        guard_version=str(selected_recommendation.get("price_guard_policy_version") or "room-price-guard-v1"),
        price_guard_policy_id=selected_recommendation.get("price_guard_policy_id"),
    )
    return {
        "skill_id": "S5",
        "node_id": "N015",
        "status": "preview_only" if _is_demo_payload(demo_payload) else "dry_run",
        "data_source_type": demo_payload.get("data_source_type"),
        "as_of_time": data.get("as_of_time"),
        "as_of_time_source": data.get("as_of_time_source") or "not_provided",
        "missing_time_context_fields": data.get("missing_time_context_fields") or [],
        "freshness_status": demo_payload.get("freshness_status"),
        "business_status": demo_payload.get("business_status", "demo_or_historical"),
        "approval_data_allowed": False,
        "live_allowed": False,
        "approval_preview_allowed": True,
        "demo_approval_preview_id": f"demo-approval-preview-{decision_ref['decision_id']}",
        "formal_approval_allowed": False,
        "price_action": selected_recommendation["price_action"],
        "candidate_price": selected_recommendation["candidate_price"],
        "conservative_price": selected_recommendation["conservative_price"],
        "execution_price": selected_recommendation["execution_price"],
        "current_price": selected_recommendation["current_price"],
        "floor_price": selected_recommendation["floor_price"],
        "ceiling_price": selected_recommendation["ceiling_price"],
        "max_single_change_pct": selected_recommendation["max_single_change_pct"],
        "max_increase_pct": selected_recommendation.get("max_increase_pct"),
        "max_decrease_pct": selected_recommendation.get("max_decrease_pct"),
        "min_increase_pct": selected_recommendation.get("min_increase_pct"),
        "min_decrease_pct": selected_recommendation.get("min_decrease_pct"),
        "price_guard_source": selected_recommendation.get("price_guard_source"),
        "price_guard_policy_source": selected_recommendation.get("price_guard_source"),
        "price_guard_policy_id": selected_recommendation.get("price_guard_policy_id"),
        "price_guard_policy_version": selected_recommendation.get("price_guard_policy_version"),
        "actual_change_pct": selected_recommendation["actual_change_pct"],
        "progress_gap": selected_recommendation["progress_gap"],
        "as_of_checkpoint_gap": selected_recommendation.get("as_of_checkpoint_gap"),
        "daily_remaining_gap": selected_recommendation.get("daily_remaining_gap"),
        "pickup_speed": selected_recommendation.get("pickup_speed"),
        "demand_pressure": selected_recommendation["demand_pressure"],
        "demand_formula_version": data.get("demand_formula_version"),
        "demand_sub_scores": data.get("demand_sub_scores") or {},
        "demand_calibration_applied": data.get("demand_calibration_applied") or [],
        "inventory_pressure": selected_recommendation["inventory_pressure"],
        "risk_level": selected_recommendation["risk_level"],
        "action_timing": selected_recommendation.get("action_timing"),
        "reason_codes": selected_recommendation.get("reason_codes") or [],
        "direct_price_trigger_allowed": selected_recommendation.get("direct_price_trigger_allowed", False),
        "calculation_trace": selected_recommendation.get("calculation_trace"),
        "trace_consistent": bool((selected_recommendation.get("calculation_trace") or {}).get("explain_consistent")),
        "room_type_id": selected_recommendation.get("room_type_id"),
        "room_type_name": selected_recommendation.get("room_type_name"),
        "s5_decision_id": decision_ref["decision_id"],
        "s5_output_hash": decision_ref["output_hash"],
        "decision_ref": decision_ref,
        "selected_recommendation": selected_recommendation,
        "room_type_recommendations": room_type_recommendations[:3],
        "price_recommendations": room_type_recommendations[:3],
        "expected_occupancy_tonight": data.get("expected_occupancy_tonight"),
        "expected_sold_rooms_tonight": data.get("expected_sold_rooms_tonight"),
        "stayover_rooms": data.get("stayover_rooms"),
        "departure_rooms": data.get("departure_rooms"),
        "reservation_summary": data.get("reservation_summary"),
        "baseline_price": data.get("baseline_price"),
        "baseline_price_by_room_type": data.get("baseline_price_by_room_type") or [],
        "sales_baseline": data.get("sales_baseline"),
        "target_room_nights": data.get("target_room_nights"),
        "hourly_target_curve": data.get("hourly_target_curve") or [],
        "baseline_confidence": data.get("baseline_confidence"),
        "demo_required_inputs_covered": bool(data.get("demo_required_inputs_covered")),
        "contract_input_coverage": data.get("contract_input_coverage"),
        "runtime_feed_coverage": data.get("runtime_feed_coverage"),
        "algorithm_usage_coverage": data.get("algorithm_usage_coverage"),
        "algorithm_used_inputs": data.get("algorithm_used_inputs") or [],
        "algorithm_unused_available_inputs": data.get("algorithm_unused_available_inputs") or [],
        "field_usage_states": data.get("field_usage_states") or {},
        "decision_strength": "partial" if time_context_missing else data.get("decision_strength"),
        "not_allowed_conclusions": list(data.get("not_allowed_conclusions") or []) + (
            ["cannot_assess_current_pricing_timing_without_as_of_time"] if time_context_missing else []
        ),
        "conversion_problem": data.get("conversion_problem"),
        "ota_health_score": data.get("ota_health_score"),
        "payment_conversion_rate": data.get("payment_conversion_rate"),
        "our_price_index": data.get("our_price_index"),
        "current_window_type": data.get("current_window_type"),
        "pickup_speed": data.get("pickup_speed"),
        "pricing_guard_context": data.get("pricing_guard_context") or {},
        "business_pressure_context": data.get("business_pressure_context") or {},
        "market_context": data.get("market_context") or {},
        "competitor_context": data.get("competitor_context") or {},
        "traffic_timing_context": data.get("traffic_timing_context") or {},
        "conversion_health_context": data.get("conversion_health_context") or {},
        "diagnosis_constraint_context": data.get("diagnosis_constraint_context") or {},
        "data_gap_context": data.get("data_gap_context") or {},
        "handoff_to": "S6",
        "blocked_for_live": True,
        "reason": "demo_data_never_live" if _is_demo_payload(demo_payload) else "dry_run_only",
        "formal_approval_created": False,
        "live_execution_count": 0,
        "algorithm_rule_ref": "runtime/algorithm_rules/revenue_rules.yaml",
        "algorithm_engine_ref": "runtime/algorithms/revenue_decision_engine.py",
        "executed_by_runtime": "runtime/decisions/revenue_decision.py",
    }

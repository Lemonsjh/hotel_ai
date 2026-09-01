from __future__ import annotations

from typing import Any

from runtime.safety.payload_hash import price_execution_payload, price_execution_payload_hash


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def progress_gap(data: dict[str, Any]) -> float:
    if "as_of_checkpoint_gap" in data:
        return to_float(data.get("as_of_checkpoint_gap"))
    if "progress_gap" in data:
        return to_float(data.get("progress_gap"))
    completion_rate = data.get("completion_rate")
    if completion_rate is not None:
        return to_float(completion_rate) - 1.0
    status = str(data.get("progress_status") or "").lower()
    if status in {"behind", "lagging", "under_target"}:
        return -0.08
    if status in {"ahead", "over_target"}:
        return 0.06
    return 0.0


def bounded_candidate(
    current_price: float,
    floor_price: float,
    ceiling_price: float,
    change_pct: float,
    max_increase_pct: float,
    max_decrease_pct: float,
) -> float:
    bounded_change = max(-max_decrease_pct, min(max_increase_pct, change_pct))
    candidate = current_price * (1.0 + bounded_change)
    candidate = max(floor_price, min(ceiling_price, candidate))
    return round(candidate, 2)


def calculate_revenue_recommendation(data: dict[str, Any], thresholds: dict[str, Any] | None = None) -> dict[str, Any]:
    thresholds = thresholds or {}
    current_price = to_float(data["current_price"])
    floor_price = to_float(data["floor_price"])
    ceiling_price = to_float(data["ceiling_price"], current_price)
    legacy_max = to_float(data.get("max_single_change_pct"), to_float(thresholds.get("max_single_change_pct"), 0.15))
    max_increase_pct = to_float(data.get("max_increase_pct"), to_float(thresholds.get("max_increase_pct"), legacy_max))
    max_decrease_pct = to_float(data.get("max_decrease_pct"), to_float(thresholds.get("max_decrease_pct"), legacy_max))
    min_increase_pct = to_float(data.get("min_increase_pct"), to_float(thresholds.get("min_increase_pct"), 0.0))
    min_decrease_pct = to_float(data.get("min_decrease_pct"), to_float(thresholds.get("min_decrease_pct"), 0.0))
    max_increase_pct = max(0.0, min(max_increase_pct, 0.30))
    max_decrease_pct = max(0.0, min(max_decrease_pct, 0.30))
    min_increase_pct = max(0.0, min(min_increase_pct, max_increase_pct))
    min_decrease_pct = max(0.0, min(min_decrease_pct, max_decrease_pct))

    demand_pressure = to_float(data.get("demand_pressure"), to_float(data.get("demand_index"), 50.0) / 100.0)
    checkpoint_gap = progress_gap(data)
    daily_remaining_gap = to_float(data.get("daily_remaining_gap"), 0.0)
    pickup_speed = str(data.get("pickup_speed") or "")
    inventory_pressure = to_float(data.get("inventory_pressure"), 0.5)
    conversion_problem = bool(data.get("conversion_problem"))
    competitor_context = data.get("competitor_context") or {}
    traffic_timing_context = data.get("traffic_timing_context") or {}
    diagnosis_constraint_context = data.get("diagnosis_constraint_context") or {}
    reason_codes: list[str] = []
    factor_adjustments: list[dict[str, Any]] = []

    def add_factor(name: str, delta: float, reason_code: str) -> None:
        nonlocal change_pct
        change_pct += delta
        factor_adjustments.append({"name": name, "delta": round(delta, 4), "reason_code": reason_code})
        reason_codes.append(reason_code)

    change_pct = 0.0
    if demand_pressure >= 0.72:
        add_factor("demand_pressure", 0.08, "strong_demand_pressure")
    elif demand_pressure <= 0.40:
        add_factor("demand_pressure", -0.05, "weak_demand_pressure")
    if checkpoint_gap < -1:
        add_factor("as_of_checkpoint_gap", -0.02, "checkpoint_gap_behind")
    elif checkpoint_gap > 1 and daily_remaining_gap <= 4:
        add_factor("as_of_checkpoint_gap", 0.02, "checkpoint_ahead_daily_gap_small")
    elif checkpoint_gap > 1:
        reason_codes.append("checkpoint_ahead_but_daily_not_complete")
    if daily_remaining_gap > 8 and pickup_speed == "slowing":
        add_factor("daily_remaining_gap", -0.02, "daily_gap_large_pickup_slowing")
    if inventory_pressure >= 0.70:
        add_factor("inventory_pressure", 0.04, "inventory_pressure_high")
    elif inventory_pressure <= 0.30:
        add_factor("inventory_pressure", -0.03, "inventory_pressure_low")
    if conversion_problem:
        add_factor("conversion_problem", -0.03, "conversion_problem")
    price_index = to_float(competitor_context.get("our_price_index"), 0.0) if isinstance(competitor_context, dict) else 0.0
    if price_index >= 1.12:
        add_factor("competitor_price_risk", -0.03, "competitor_price_risk")
    elif 0 < price_index <= 0.92:
        reason_codes.append("below_competitor_median_check_margin")
    current_window_type = traffic_timing_context.get("current_window_type") if isinstance(traffic_timing_context, dict) else None
    raw_adjustment = round(change_pct, 4)
    rule_adjustments: list[dict[str, Any]] = []
    if current_window_type == "pre_peak" and abs(checkpoint_gap) <= 1:
        before = change_pct
        change_pct *= 0.5
        rule_adjustments.append(
            {
                "name": "pre_peak_observation_window_multiplier",
                "before_adjustment": round(before, 4),
                "after_adjustment": round(change_pct, 4),
            }
        )
        reason_codes.append("pre_peak_observation_window")
    diagnosis_status = diagnosis_constraint_context.get("diagnosis_status") if isinstance(diagnosis_constraint_context, dict) else None
    if diagnosis_status in {"partial", "data_gap"}:
        reason_codes.append("diagnosis_partial_no_strong_price_claim")

    final_adjustment = round(max(-max_decrease_pct, min(max_increase_pct, change_pct)), 4)
    unclamped_candidate = round(current_price * (1.0 + final_adjustment), 2)
    candidate_price = round(max(floor_price, min(ceiling_price, unclamped_candidate)), 2)
    actual_change_pct = 0.0 if current_price == 0 else round((candidate_price - current_price) / current_price, 4)
    if candidate_price > current_price:
        price_action = "increase"
    elif candidate_price < current_price:
        price_action = "decrease"
    else:
        price_action = "hold"
    risk_level = "medium" if abs(actual_change_pct) >= 0.08 else "low"
    if "competitor_price_risk" in reason_codes or diagnosis_status in {"partial", "data_gap"}:
        risk_level = "medium" if risk_level == "low" else risk_level
    if current_window_type == "pre_peak" and abs(checkpoint_gap) <= 1:
        action_timing = "observe_peak_window"
    elif current_window_type == "post_peak" and checkpoint_gap < -1:
        action_timing = "tail_room_action_window"
    else:
        action_timing = "normal_pricing_window"
    raw_conservative_price = to_float(data.get("conservative_price"), candidate_price)
    if price_action == "decrease":
        conservative_price = min(current_price, max(candidate_price, raw_conservative_price))
    elif price_action == "increase":
        conservative_price = max(current_price, min(candidate_price, raw_conservative_price))
    else:
        conservative_price = current_price
    conservative_price = round(max(floor_price, min(ceiling_price, conservative_price)), 2)
    calculation_trace = {
        "base_price": current_price,
        "factor_adjustments": factor_adjustments,
        "raw_adjustment": raw_adjustment,
        "rule_adjustments": rule_adjustments,
        "final_adjustment": final_adjustment,
        "max_increase_pct": max_increase_pct,
        "max_decrease_pct": max_decrease_pct,
        "min_increase_pct": min_increase_pct,
        "min_decrease_pct": min_decrease_pct,
        "unclamped_candidate_price": unclamped_candidate,
        "candidate_price": candidate_price,
        "price_bound_adjusted": candidate_price != unclamped_candidate,
        "clamped_execution_price": conservative_price,
        "explain_consistent": True,
    }
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
        "max_single_change_pct": max(max_increase_pct, max_decrease_pct),
        "max_increase_pct": max_increase_pct,
        "max_decrease_pct": max_decrease_pct,
        "min_increase_pct": min_increase_pct,
        "min_decrease_pct": min_decrease_pct,
        "actual_change_pct": actual_change_pct,
        "progress_gap": round(checkpoint_gap, 4),
        "as_of_checkpoint_gap": round(checkpoint_gap, 4),
        "daily_remaining_gap": round(daily_remaining_gap, 4),
        "pickup_speed": pickup_speed or None,
        "demand_pressure": round(demand_pressure, 4),
        "inventory_pressure": round(inventory_pressure, 4),
        "risk_level": risk_level,
        "action_timing": action_timing,
        "reason_codes": reason_codes or ["balanced_pricing_signal"],
        "direct_price_trigger_allowed": False,
        "calculation_trace": calculation_trace,
    }


def build_s5_decision_ref(
    recommendation: dict[str, Any],
    *,
    freshness_status: str | None = None,
    business_date: str | None = None,
    hotel_id: str | None = None,
    guard_version: str | None = "room-price-guard-v1",
    price_guard_policy_id: str | None = None,
) -> dict[str, Any]:
    payload = price_execution_payload(
        hotel_id=hotel_id,
        room_type_id=recommendation.get("room_type_id"),
        channel=recommendation.get("channel"),
        normal_price=recommendation.get("execution_price"),
        ota_product_id=recommendation.get("ota_product_id"),
        old_price=recommendation.get("current_price"),
        price_guard_policy_id=price_guard_policy_id or recommendation.get("price_guard_policy_id"),
        begin_date=business_date,
        end_date=business_date,
        floor_price=recommendation.get("floor_price"),
        ceiling_price=recommendation.get("ceiling_price"),
        max_increase_pct=recommendation.get("max_increase_pct"),
        max_decrease_pct=recommendation.get("max_decrease_pct"),
        min_increase_pct=recommendation.get("min_increase_pct"),
        min_decrease_pct=recommendation.get("min_decrease_pct"),
        freshness_status=freshness_status,
        guard_version=guard_version,
    )
    payload["candidate_price"] = recommendation.get("candidate_price")
    output_hash = price_execution_payload_hash(payload)
    decision_id = f"s5-{str(recommendation.get('room_type_id') or 'room').lower()}-{output_hash[:12]}"
    return {
        "decision_id": decision_id,
        "output_hash": output_hash,
        "candidate_price": recommendation.get("candidate_price"),
        "execution_price": recommendation.get("execution_price"),
        "floor_price": recommendation.get("floor_price"),
        "ceiling_price": recommendation.get("ceiling_price"),
        "max_increase_pct": recommendation.get("max_increase_pct"),
        "max_decrease_pct": recommendation.get("max_decrease_pct"),
        "min_increase_pct": recommendation.get("min_increase_pct"),
        "min_decrease_pct": recommendation.get("min_decrease_pct"),
        "room_type_id": recommendation.get("room_type_id"),
        "room_type_name": recommendation.get("room_type_name"),
        "channel": recommendation.get("channel"),
        "ota_product_id": recommendation.get("ota_product_id"),
        "freshness_status": freshness_status,
        "business_date": business_date,
        "payload": payload,
    }

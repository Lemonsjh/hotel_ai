from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_activity_decision(context: dict[str, Any]) -> dict[str, Any]:
    facts = context.get("facts") or {}
    promotion = facts.get("promotion") or {}
    room = ((facts.get("room_types") or {}).get("room_types") or [{}])[0]
    base_price = _number(room.get("ota_base_price") or room.get("conservative_price") or room.get("current_price"))
    discount = _number(room.get("activity_discount_factor"))
    final_price = round(base_price * discount, 2) if base_price is not None and discount is not None else None
    floor = _number(room.get("floor_price"))
    expected_roi = _number(promotion.get("expected_roi"))
    expected_orders = _number(promotion.get("expected_orders"))
    budget = _number(promotion.get("promotion_budget"))
    missing = []
    if final_price is None:
        missing.append("activity_final_price")
    if floor is None:
        missing.append("floor_price")
    if expected_roi is None:
        missing.append("expected_roi")
    if final_price is not None and floor is not None and final_price < floor:
        decision = "block"
        reason = "activity_final_price_below_floor"
    elif missing:
        decision = "block"
        reason = "missing_required_activity_fields"
    elif expected_roi is not None and expected_roi >= 1.25 and (expected_orders or 0) >= 4:
        decision = "join"
        reason = "roi_and_order_lift_positive"
    elif expected_roi is not None and expected_roi < 1.0:
        decision = "cancel"
        reason = "roi_negative"
    else:
        decision = "adjust"
        reason = "roi_watch"
    return {
        "status": "ok" if not missing else "data_gap",
        "algorithm": "activity_decision_v1",
        "activity_final_price": final_price,
        "floor_price": floor,
        "conversion_lift_expected": expected_roi,
        "order_lift_expected": expected_orders,
        "promotion_budget": budget,
        "cross_platform_price_gap_rate": 0.0,
        "decision": decision,
        "decision_reason": reason,
        "missing_fields": missing,
        "dry_run_only": True,
        "approval_data_allowed": False,
        "live_allowed": False,
    }

from __future__ import annotations

from typing import Any


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_roi_decision(context: dict[str, Any]) -> dict[str, Any]:
    promotion = (context.get("facts") or {}).get("promotion") or {}
    cost = _number(promotion.get("promotion_cost") or promotion.get("promotion_budget"))
    revenue = _number(promotion.get("promotion_revenue"))
    orders = _number(promotion.get("promotion_orders") or promotion.get("expected_orders"))
    if revenue is None and orders is not None:
        revenue = orders * _number(((context.get("facts") or {}).get("business_snapshot") or {}).get("adr"), 0)
    missing = []
    if cost is None:
        missing.append("promotion_cost")
    if revenue is None:
        missing.append("promotion_revenue")
    if orders is None:
        missing.append("promotion_orders")
    roi = round(revenue / cost, 4) if revenue is not None and cost not in (None, 0) else None
    if missing:
        decision = "data_gap"
    elif roi is not None and roi >= 1.25:
        decision = "keep_or_scale_dry_run"
    elif roi is not None and roi >= 1.0:
        decision = "observe"
    else:
        decision = "pause_or_adjust"
    return {
        "status": "ok" if not missing else "data_gap",
        "algorithm": "promotion_roi_v1",
        "promotion_cost": cost,
        "promotion_revenue": revenue,
        "promotion_orders": orders,
        "roi": roi,
        "decision": decision,
        "missing_fields": missing,
        "approval_data_allowed": False,
        "live_allowed": False,
    }

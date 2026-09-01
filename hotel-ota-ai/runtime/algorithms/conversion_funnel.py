from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator, 4)


def calculate_conversion_funnel(payload: dict[str, Any]) -> dict[str, Any]:
    funnel = payload.get("ota_funnel") or payload
    exposure = _number(funnel.get("exposure") or funnel.get("exposure_count") or funnel.get("impressions"))
    views = _number(funnel.get("views") or funnel.get("view_count"))
    clicks = _number(funnel.get("clicks") or funnel.get("click_count"))
    submitted = _number(funnel.get("submitted_orders") or funnel.get("submit_orders"))
    paid = _number(funnel.get("paid_orders") or funnel.get("orders_today"))
    payment_rate_alias = _number(funnel.get("payment_conversion_rate") or funnel.get("conversion_rate"))
    missing: list[str] = []
    partial: list[str] = []
    for field, value in (("exposure", exposure), ("views", views), ("clicks", clicks), ("paid_orders", paid)):
        if value is None:
            missing.append(field)
    if submitted is None:
        partial.append("submitted_orders")
    rates = {
        "exposure_to_view_rate": _rate(views, exposure),
        "view_to_click_rate": _rate(clicks, views),
        "click_to_submit_rate": _rate(submitted, clicks),
        "submit_to_pay_rate": _rate(paid, submitted),
        "payment_conversion_rate": _rate(paid, views),
    }
    if rates["payment_conversion_rate"] is None and payment_rate_alias is not None:
        rates["payment_conversion_rate"] = round(payment_rate_alias, 4)
        partial.append("payment_conversion_rate_from_v27_alias")
    if rates["click_to_submit_rate"] is None and clicks not in (None, 0) and paid is not None:
        rates["click_to_paid_order_rate"] = _rate(paid, clicks)
        partial.append("click_to_submit_rate_fallback_to_click_to_paid_order")
    traffic_problem = bool((exposure is not None and exposure < 1000) or (views is not None and views < 100))
    conversion_problem = False
    pay_rate = rates["payment_conversion_rate"]
    if pay_rate is not None:
        conversion_problem = pay_rate < 0.04
    elif rates.get("click_to_paid_order_rate") is not None:
        conversion_problem = rates["click_to_paid_order_rate"] < 0.08
    confidence = 1.0 - 0.12 * len(missing) - 0.08 * len(set(partial))
    return {
        "status": "ok" if not missing else "data_gap",
        "algorithm": "conversion_funnel_v1",
        "raw_counts": {
            "exposure": exposure,
            "views": views,
            "clicks": clicks,
            "submitted_orders": submitted,
            "paid_orders": paid,
        },
        "rates": rates,
        "traffic_problem": traffic_problem,
        "conversion_problem": conversion_problem,
        "missing_fields": sorted(set(missing)),
        "partial_fields": sorted(set(partial)),
        "confidence_score": round(max(confidence, 0.0), 2),
    }

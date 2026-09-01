from __future__ import annotations

import statistics
from typing import Any


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_competitor_alert(context: dict[str, Any]) -> dict[str, Any]:
    facts = context.get("facts") or {}
    competitors = list((facts.get("competitors") or {}).get("competitors") or [])
    rooms = (facts.get("room_types") or {}).get("room_types") or []
    our_price = _number((rooms[0] if rooms else {}).get("current_price"))
    prices = [_number(item.get("competitor_price") or item.get("price")) for item in competitors]
    prices = [value for value in prices if value is not None]
    missing = []
    if our_price is None:
        missing.append("current_price")
    if not prices:
        missing.append("competitor_price")
    median = statistics.median(prices) if prices else None
    minimum = min(prices) if prices else None
    maximum = max(prices) if prices else None
    price_index = round(our_price / median, 4) if our_price and median else None
    delta = round(our_price - median, 2) if our_price and median else None
    if len(prices) < 3:
        alert_level = 1
        alert_reason = "competitor_sample_too_small_watch_only"
    elif price_index is not None and price_index >= 1.12:
        alert_level = 4
        alert_reason = "our_price_materially_above_peer_median"
    elif price_index is not None and price_index >= 1.06:
        alert_level = 3
        alert_reason = "our_price_above_peer_median"
    elif price_index is not None and price_index <= 0.92:
        alert_level = 2
        alert_reason = "our_price_below_peer_median_check_margin"
    else:
        alert_level = 1
        alert_reason = "watch"
    risk_level = "high" if alert_level >= 4 else "medium" if alert_level >= 3 else "low"
    competitor_context = {
        "median_competitor_price": median,
        "min_competitor_price": minimum,
        "max_competitor_price": maximum,
        "our_price_index": price_index,
        "price_delta_to_median": delta,
        "competitor_count": len(prices),
        "competitor_promo_detected": any(str(item.get("competitor_activity_label") or "").lower() not in {"", "no_activity"} for item in competitors),
        "direct_price_trigger_allowed": False,
        "risk_level": risk_level,
    }
    return {
        "status": "ok" if not missing else "data_gap",
        "algorithm": "competitor_alert_v1",
        "competitor_count": len(prices),
        "our_price": our_price,
        "peer_price_median": median,
        "peer_price_min": minimum,
        "peer_price_max": maximum,
        "our_price_index": price_index,
        "price_delta_to_median": delta,
        "alert_level": alert_level,
        "alert_reason": alert_reason,
        "competitor_context": competitor_context,
        "risk_level": risk_level,
        "direct_price_trigger_allowed": False,
        "handoff_to": "S5" if alert_level >= 3 else "S14",
        "missing_fields": missing,
        "data_source_type": context.get("data_source_type"),
        "freshness_status": context.get("freshness_status"),
        "today_label_allowed": False,
        "approval_data_allowed": False,
        "live_allowed": False,
    }

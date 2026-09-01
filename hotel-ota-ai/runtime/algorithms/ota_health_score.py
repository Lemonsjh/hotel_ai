from __future__ import annotations

from typing import Any

from runtime.algorithms.conversion_funnel import calculate_conversion_funnel
from runtime.algorithms.inventory import calculate_room_type_inventory


WEIGHTS = {
    "traffic": 0.20,
    "conversion": 0.25,
    "price": 0.15,
    "inventory": 0.15,
    "reputation": 0.15,
    "stability": 0.10,
}


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp(value: float | None, default: float = 65.0) -> float:
    if value is None:
        return default
    return max(0.0, min(100.0, value))


def calculate_ota_health_score(context: dict[str, Any]) -> dict[str, Any]:
    facts = context.get("facts") or {}
    external = facts.get("external_ota_report_fields") or {}
    reputation = facts.get("reputation") or {}
    room_types = facts.get("room_types") or {}
    price_history = facts.get("price_history") or {}
    funnel = calculate_conversion_funnel(external)
    counts = funnel.get("raw_counts") or {}
    exposure = _number(counts.get("exposure"))
    views = _number(counts.get("views"))
    traffic_score = _clamp((views or 0) / max(exposure or 1, 1) * 300)
    pay_rate = (funnel.get("rates") or {}).get("payment_conversion_rate")
    conversion_score = _clamp((pay_rate or 0.03) / 0.06 * 100)
    price_rows = price_history.get("price_history") or []
    price_score = 72.0
    if price_rows:
        baselines = [_number(item.get("baseline_price")) for item in price_rows]
        actuals = [_number(item.get("median_deal_price") or item.get("adr")) for item in price_rows]
        gaps = [abs((actual or base) - base) / base for actual, base in zip(actuals, baselines) if base]
        if gaps:
            price_score = _clamp(100 - min(sum(gaps) / len(gaps), 0.35) * 200)
    inventory = calculate_room_type_inventory(room_types)
    inventory_score = _clamp((inventory.get("inventory_pressure") or 0.5) * 100)
    rating = _number(reputation.get("rating_total") or reputation.get("rating"))
    bad_rate = _number(reputation.get("bad_review_rate") or reputation.get("negative_review_rate")) or 0
    reputation_score = _clamp((rating or 4.2) / 5 * 100 - bad_rate * 40)
    missing_count = len(set((funnel.get("missing_fields") or []) + (inventory.get("missing_fields") or [])))
    stability_score = _clamp(100 - missing_count * 8)
    sub_scores = {
        "traffic": round(traffic_score, 2),
        "conversion": round(conversion_score, 2),
        "price": round(price_score, 2),
        "inventory": round(inventory_score, 2),
        "reputation": round(reputation_score, 2),
        "stability": round(stability_score, 2),
    }
    score = round(sum(sub_scores[key] * weight for key, weight in WEIGHTS.items()), 2)
    level = "healthy" if score >= 80 else "watch" if score >= 65 else "risk"
    status = "ok" if missing_count == 0 else "partial"
    usable_findings = []
    if funnel.get("conversion_problem"):
        usable_findings.append("conversion_rate_low")
    if score < 80:
        usable_findings.append("ota_health_score_watch")
    if inventory.get("inventory_pressure") is not None:
        usable_findings.append("inventory_pressure_available")
    not_allowed_conclusions = []
    if status != "ok":
        not_allowed_conclusions.append("cannot_confirm_price_is_primary_issue")
        not_allowed_conclusions.append("cannot_claim_complete_ota_diagnosis")
    return {
        "status": status,
        "diagnosis_status": "full" if status == "ok" else status,
        "algorithm": "ota_health_score_v1",
        "weights": WEIGHTS,
        "sub_scores": sub_scores,
        "ota_health_score": score,
        "ota_health_level": level,
        "conversion_funnel": funnel,
        "inventory_diagnosis": inventory,
        "missing_fields": sorted(set((funnel.get("missing_fields") or []) + (inventory.get("missing_fields") or []))),
        "usable_findings": usable_findings or ["balanced_ota_health_signal"],
        "not_allowed_conclusions": not_allowed_conclusions,
        "field_coverage_rate": round(max(0.0, 1.0 - missing_count / 12), 4),
        "data_source_type": context.get("data_source_type"),
        "freshness_status": context.get("freshness_status"),
        "today_label_allowed": False,
        "approval_data_allowed": False,
        "live_allowed": False,
    }

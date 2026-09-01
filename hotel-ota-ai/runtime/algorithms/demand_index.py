from __future__ import annotations

from typing import Any

from runtime.algorithms.conversion_funnel import calculate_conversion_funnel
from runtime.algorithms.inventory import calculate_room_type_inventory


FORMULA_VERSION = "revised_first_formula_v27"
FORMULA_OR_RULE = (
    "需求指数=日期环境分20%+区域热度分15%+历史同期分15%+当前预订进度分20%+"
    "当前流量分10%+当前转化分10%+房型库存压力分10%"
)
DEPRECATED_LEGACY_FORMULA = "需求指数=历史需求分20%+当前进度25%+流量15%+转化15%+库存压力15%+日期属性10%"

WEIGHTS = {
    "date_environment": 0.20,
    "regional_heat": 0.15,
    "historical_same_period": 0.15,
    "booking_progress": 0.20,
    "current_traffic": 0.10,
    "current_conversion": 0.10,
    "room_type_inventory_pressure": 0.10,
}
CALIBRATION_RULES = {
    "platform_valley_cap": "traffic_state=valley caps demand_index at 50 unless booking_progress is materially above historical_same_period",
    "platform_peak_floor": "traffic_state=peak floors demand_index at 50 unless both booking_progress and current_conversion are materially weak",
}


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_score(value: float | None, default: float = 60.0) -> float:
    if value is None:
        return default
    return max(0.0, min(100.0, value))


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _number(value)
        if number is not None:
            return number
    return None


def _score_from_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    if 0 <= value <= 1:
        return value * 100
    return value


def _historical_same_period_score(
    price_history: dict[str, Any],
    market: dict[str, Any],
    orders: dict[str, Any],
) -> tuple[float, list[str]]:
    explicit = _first_number(
        market.get("historical_same_period_score"),
        market.get("historical_same_period"),
        orders.get("historical_same_weekday_orders"),
    )
    if explicit is not None:
        return _clamp_score(_score_from_ratio(explicit)), []
    values = [_number(item.get("occupancy")) for item in price_history.get("price_history") or []]
    values = [value for value in values if value is not None]
    if not values:
        return 60.0, ["historical_same_period", "price_history.occupancy"]
    return _clamp_score((sum(values) / len(values)) * 100), []


def _booking_progress_score(snapshot: dict[str, Any], baseline: dict[str, Any], progress: dict[str, Any]) -> tuple[float, list[str]]:
    sold = _first_number(
        progress.get("as_of_actual_sold_rooms"),
        snapshot.get("sold_rooms"),
        progress.get("current_sold_rooms"),
    )
    target = _first_number(
        progress.get("as_of_target_sold_rooms"),
        baseline.get("target_sold_rooms"),
        progress.get("target_sold_rooms"),
        baseline.get("target_room_nights"),
    )
    if sold is None or not target:
        return 55.0, ["as_of_actual_sold_rooms", "as_of_target_sold_rooms"]
    return _clamp_score((sold / target) * 100), []


def _current_traffic_score(market: dict[str, Any], orders: dict[str, Any]) -> tuple[float, list[str]]:
    explicit = _first_number(
        market.get("current_traffic_score"),
        market.get("hourly_demand_index"),
        market.get("traffic_index"),
    )
    if explicit is not None:
        return _clamp_score(_score_from_ratio(explicit)), []
    current = _number(orders.get("today_order_count"))
    last_week = _number(orders.get("last_week_same_day_order_count"))
    if current is None or not last_week:
        return 55.0, ["hourly_demand_index", "today_order_count", "last_week_same_day_order_count"]
    return _clamp_score((current / last_week) * 70), []


def _date_environment_score(market: dict[str, Any]) -> tuple[float, list[str]]:
    explicit = _first_number(market.get("date_environment_score"))
    if explicit is not None:
        return _clamp_score(_score_from_ratio(explicit)), []
    if market.get("holiday_flag") is True:
        return 88.0, []
    if market.get("event_signal"):
        return 78.0, []
    if market.get("weather") or market.get("weather_signal"):
        return 64.0, []
    return 55.0, ["holiday_flag", "event_signal", "weather_signal"]


def _regional_heat_score(market: dict[str, Any]) -> tuple[float, list[str]]:
    explicit = _first_number(
        market.get("regional_heat_index"),
        market.get("regional_heat_score"),
        market.get("industry_heat_index"),
        market.get("area_heat_index"),
    )
    if explicit is not None:
        return _clamp_score(_score_from_ratio(explicit)), []
    if market.get("event_signal"):
        return 70.0, []
    return 55.0, ["regional_heat_index", "industry_heat_index"]


def _traffic_state(market: dict[str, Any]) -> str:
    raw = str(
        market.get("traffic_state")
        or market.get("traffic_peak_valley_window")
        or market.get("traffic_peak_window")
        or ""
    ).lower()
    if any(token in raw for token in ("valley", "low", "低谷")):
        return "valley"
    if any(token in raw for token in ("peak", "high", "高峰", "旺")):
        return "peak"
    return "unknown"


def _apply_peak_valley_calibration(score: float, sub_scores: dict[str, float], market: dict[str, Any]) -> tuple[float, list[str]]:
    state = _traffic_state(market)
    applied: list[str] = []
    booking = sub_scores["booking_progress"]
    historical = sub_scores["historical_same_period"]
    conversion = sub_scores["current_conversion"]
    if state == "valley" and score > 50 and booking < historical + 15:
        score = 50.0
        applied.append("platform_valley_cap")
    if state == "peak" and score < 50 and not (booking + 15 < historical and conversion < 40):
        score = 50.0
        applied.append("platform_peak_floor")
    return score, applied


def calculate_demand_index(context: dict[str, Any]) -> dict[str, Any]:
    facts = context.get("facts") or {}
    snapshot = facts.get("business_snapshot") or {}
    room_types = facts.get("room_types") or {}
    orders = facts.get("orders_aggregate") or {}
    price_history = facts.get("price_history") or {}
    baseline = facts.get("sales_baseline") or {}
    progress = facts.get("progress_deviation") or {}
    market = facts.get("market_context") or {}
    external = facts.get("external_ota_report_fields") or {}
    missing: list[str] = []
    date_environment, date_missing = _date_environment_score(market)
    regional_heat, regional_missing = _regional_heat_score(market)
    historical, history_missing = _historical_same_period_score(price_history, market, orders)
    booking_progress, progress_missing = _booking_progress_score(snapshot, baseline, progress)
    traffic, traffic_missing = _current_traffic_score(market, orders)
    funnel = calculate_conversion_funnel(external)
    conversion_rate = funnel.get("rates", {}).get("payment_conversion_rate")
    conversion = _clamp_score((conversion_rate or 0.03) / 0.06 * 100)
    inventory = calculate_room_type_inventory(room_types)
    inv_pressure = inventory.get("inventory_pressure")
    inventory_score = _clamp_score((inv_pressure or 0.5) * 100)
    missing.extend(
        date_missing
        + regional_missing
        + history_missing
        + progress_missing
        + traffic_missing
        + list(funnel.get("missing_fields") or [])
    )
    sub_scores = {
        "date_environment": round(date_environment, 2),
        "regional_heat": round(regional_heat, 2),
        "historical_same_period": round(historical, 2),
        "booking_progress": round(booking_progress, 2),
        "current_traffic": round(traffic, 2),
        "current_conversion": round(conversion, 2),
        "room_type_inventory_pressure": round(inventory_score, 2),
    }
    weighted = sum(sub_scores[key] * weight for key, weight in WEIGHTS.items())
    score, calibration_applied = _apply_peak_valley_calibration(round(weighted, 2), sub_scores, market)
    score = round(score, 2)
    if score >= 80:
        level = "strong"
    elif score >= 60:
        level = "normal"
    else:
        level = "weak"
    return {
        "status": "ok" if not missing else "partial",
        "algorithm": "weighted_demand_index_revised_first_v27",
        "formula_version": FORMULA_VERSION,
        "formula_or_rule": FORMULA_OR_RULE,
        "deprecated_legacy_formula": DEPRECATED_LEGACY_FORMULA,
        "calibration_rules": CALIBRATION_RULES,
        "calibration_applied": calibration_applied,
        "weights": WEIGHTS,
        "sub_scores": sub_scores,
        "weighted_score": score,
        "demand_index": score,
        "demand_level": level,
        "inventory_diagnosis": inventory,
        "conversion_funnel": funnel,
        "missing_fields": sorted(set(missing)),
        "partial_fields": funnel.get("partial_fields") or [],
        "confidence_score": round(max(1.0 - 0.05 * len(set(missing)), 0.2), 2),
        "reason_codes": [key for key, value in sub_scores.items() if value >= 75] or ["balanced_demo_signal"],
        "data_source_type": context.get("data_source_type"),
        "freshness_status": context.get("freshness_status"),
        "today_label_allowed": False,
        "approval_data_allowed": False,
        "live_allowed": False,
    }

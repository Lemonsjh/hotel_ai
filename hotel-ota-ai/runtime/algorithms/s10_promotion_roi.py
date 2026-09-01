from __future__ import annotations

from collections import defaultdict
from typing import Any


METRIC_FIELDS = (
    "exposure_count", "click_count", "booking_order_count", "room_night_count",
    "booking_order_amount", "spend_amount", "cash_spend_amount", "bonus_spend_amount",
)


def _payload(result: dict[str, Any] | None) -> dict[str, Any]:
    return result.get("payload") if isinstance(result, dict) and isinstance(result.get("payload"), dict) else (result or {})


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _platform(row: dict[str, Any]) -> str:
    source = str(row.get("channel") or row.get("channel_source") or row.get("table_key") or row.get("source_table_key") or row.get("platform_scope") or row.get("source_platform") or "").lower()
    if "meituan" in source or "美团" in source:
        return "meituan"
    if "ctrip" in source or "携程" in source:
        return "ctrip"
    return "unknown"


def _sum(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [_number(row.get(key)) for row in rows]
    usable = [value for value in values if value is not None]
    return round(sum(usable), 2) if usable else None


def _ratio(numerator: float | None, denominator: float | None) -> float | str | None:
    if numerator is None or denominator is None:
        return None
    return "not_computable" if denominator == 0 else round(numerator / denominator, 4)


def _latest(rows: list[dict[str, Any]], key: str) -> str | None:
    values = [str(row.get(key)) for row in rows if row.get(key) not in (None, "")]
    return max(values) if values else None


def _source_state(result: dict[str, Any] | None) -> tuple[str, str | None]:
    payload = _payload(result)
    if not isinstance(result, dict) or result.get("status") != "ok":
        return "data_gap", str((result or {}).get("reason") or "query_unavailable")
    if payload.get("source_status") in {"no_rows", "empty"}:
        return "no_records", None
    if payload.get("source_status") not in {None, "ok"}:
        return "data_gap", str(payload.get("reason") or payload.get("source_status"))
    return "ok", None


def _source_ratio(value: Any) -> float | None:
    number = _number(value)
    return number / 100 if number is not None and number > 1 else number


def _conflicts(rows: list[dict[str, Any]], metrics: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    exposure, clicks = metrics["exposure_count"], metrics["click_count"]
    orders, nights, revenue, spend = (metrics[key] for key in ("booking_order_count", "room_night_count", "booking_order_amount", "spend_amount"))
    if clicks is not None and exposure is not None and clicks > exposure:
        flags.append("metric_conflict:clicks_exceed_exposure")
    if spend is not None and spend > 0 and clicks is None:
        flags.append("metric_conflict:spend_without_clicks")
    if revenue is not None and revenue > 0 and (orders in (None, 0) or nights in (None, 0)):
        flags.append("metric_conflict:revenue_without_orders_or_room_nights")
    checks = (("cost_per_click", metrics["cpc"]), ("click_rate_pct", metrics["ctr"]), ("return_on_ad_spend", metrics["observed_roas"]))
    for field, derived in checks:
        sources = [_source_ratio(row.get(field)) if field == "click_rate_pct" else _number(row.get(field)) for row in rows]
        sources = [value for value in sources if value is not None]
        if sources and isinstance(derived, float) and abs(sources[-1] - derived) > (0.01 if field != "cost_per_click" else 0.05):
            flags.append(f"source_derived_conflict:{field}")
    if metrics["cash_spend_amount"] is not None and metrics["bonus_spend_amount"] is not None and spend is not None:
        if abs(metrics["cash_spend_amount"] + metrics["bonus_spend_amount"] - spend) > 0.05:
            flags.append("spend_breakdown_conflict")
    return flags


def _item(platform: str, rows: list[dict[str, Any]], *, portfolio: bool = False) -> dict[str, Any]:
    metrics = {key: _sum(rows, key) for key in METRIC_FIELDS}
    metrics.update({
        "ctr": _ratio(metrics["click_count"], metrics["exposure_count"]),
        "cpc": _ratio(metrics["spend_amount"], metrics["click_count"]),
        "click_to_order_rate": _ratio(metrics["booking_order_count"], metrics["click_count"]),
        "cpa": _ratio(metrics["spend_amount"], metrics["booking_order_count"]),
        "cost_per_room_night": _ratio(metrics["spend_amount"], metrics["room_night_count"]),
        "attributed_order_value": _ratio(metrics["booking_order_amount"], metrics["booking_order_count"]),
        "attributed_adr": _ratio(metrics["booking_order_amount"], metrics["room_night_count"]),
        "observed_roas": _ratio(metrics["booking_order_amount"], metrics["spend_amount"]),
        "cash_roas": _ratio(metrics["booking_order_amount"], metrics["cash_spend_amount"]),
    })
    metrics["observed_media_net_revenue"] = round(metrics["booking_order_amount"] - metrics["spend_amount"], 2) if metrics["booking_order_amount"] is not None and metrics["spend_amount"] is not None else None
    metrics["observed_media_return_ratio"] = _ratio(metrics["observed_media_net_revenue"], metrics["spend_amount"])
    flags = [] if portfolio else _conflicts(rows, metrics)
    delayed = any(_truthy(row.get("data_delayed")) for row in rows)
    zero_fields = ("exposure_count", "click_count", "spend_amount", "booking_order_count", "booking_order_amount")
    zero_delivery = not delayed and all(metrics[key] == 0 for key in zero_fields)
    if delayed:
        flags.append("source_delayed")
    if zero_delivery:
        flags.append("observed_zero_delivery")
    required = ("spend_amount", "booking_order_amount")
    missing = [key for key in required if any(_number(row.get(key)) is None for row in rows)]
    status = "data_gap" if missing else ("partial" if flags else "ok")
    scope = {
        "scope_type": "hotel_channel_plan_launch_rolling_30d" if platform == "meituan" and not portfolio else "hotel_channel_rolling_30d",
        "period_start_date": _latest(rows, "period_start_date"), "period_end_date": _latest(rows, "period_end_date"),
        "snapshot_time": _latest(rows, "snapshot_time"), "status": status, "quality_flags": sorted(set(flags)), "data_gaps": missing,
        **metrics,
    }
    if platform == "meituan" and not portfolio:
        sample = rows[0]
        scope.update({key: sample.get(key) for key in ("plan_id", "plan_name", "launch_id", "launch_name", "promotion_name", "promotion_status")})
    elif platform == "ctrip":
        scope["platform_scope"] = rows[0].get("platform_scope")
    return scope


def _groups(platform: str, rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        window = (row.get("period_start_date"), row.get("period_end_date"), row.get("snapshot_time"))
        key = (row.get("plan_id"), row.get("launch_id"), *window) if platform == "meituan" else window
        grouped[key].append(row)
    return list(grouped.values())


def _platform_result(platform: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "no_records", "items": [], "portfolios": [], "quality_flags": ["exact_hotel_source_no_records"], "data_gaps": [f"platform_missing:{platform}:ota_promotion_performance_30d"]}
    items = [_item(platform, group) for group in _groups(platform, rows)]
    portfolio_groups: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        portfolio_groups[(row.get("period_start_date"), row.get("period_end_date"), row.get("snapshot_time"))].append(row)
    portfolios = [_item(platform, group, portfolio=True) for group in portfolio_groups.values()]
    flags = sorted({flag for item in items for flag in item["quality_flags"]})
    gaps = sorted({gap for item in items for gap in item["data_gaps"]})
    return {"status": "data_gap" if gaps else ("partial" if flags else "ok"), "items": items, "portfolios": portfolios, "quality_flags": flags, "data_gaps": gaps}


def build_s10_promotion_roi(*, performance_result: dict[str, Any], as_of_time: str | None) -> dict[str, Any]:
    """Read-only source-attributed promotion evidence; never imply profit or incrementality."""
    payload = _payload(performance_result)
    state, reason = _source_state(performance_result)
    rows = [dict(row) for row in payload.get("rows") or [] if isinstance(row, dict)]
    source_gaps = [str(item) for item in payload.get("source_gaps") or []]
    if not rows:
        gaps = source_gaps or [f"promotion_performance:{reason}" if reason else "promotion_performance:no_records"]
        return {"status": "data_gap" if source_gaps else state, "skill_id": "S10", "platforms": {}, "data_gaps": gaps, "roi_decision": "data_gap", "approval_data_allowed": False, "live_allowed": False}
    platforms = {platform: _platform_result(platform, [row for row in rows if _platform(row) == platform]) for platform in ("meituan", "ctrip")}
    observed_roas = {platform: [item["observed_roas"] for item in detail["portfolios"]] for platform, detail in platforms.items()}
    data_gaps = sorted({*source_gaps, *(gap for detail in platforms.values() for gap in detail["data_gaps"])})
    flags = sorted({flag for detail in platforms.values() for flag in detail["quality_flags"]})
    return {
        "status": "partial" if data_gaps or flags else "ok", "skill_id": "S10", "algorithm": "promotion_source_attributed_roi_v2", "as_of_time": as_of_time,
        "platforms": platforms, "observed_roas": observed_roas,
        "promotion_roi": {"metric": "observed_roas", "legacy_field": True, "by_platform": observed_roas},
        "contribution_estimate": {"status": "unavailable", "data_gaps": ["cost_policy_missing", "commission_not_exactly_attributable", "refund_cancel_basis_unknown"]},
        "incremental_roi": {"status": "unavailable", "reason": "approved_control_or_comparable_baseline_missing"},
        "profit_simulation": {"status": "unavailable", "reason": "cost_policy_missing"}, "roi_decision": "observe_only_no_execution",
        "data_gaps": data_gaps, "quality_flags": flags, "approval_data_allowed": False, "live_allowed": False,
    }

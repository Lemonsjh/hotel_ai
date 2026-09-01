from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

from runtime.s15_technical_sources import (
    _ad_context,
    _current_room_prices,
    _group_metric_rows,
    _market_point,
    _metric_current,
    _n,
    _row_for,
    _safe_ratio,
    _sales_status,
)

VERSION = "s16-dynamic-diagnosis.v1"


def _day(value: Any) -> str:
    return str(value or "")[:10]


def _as_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        result = value
    elif value in (None, ""):
        return None
    else:
        try:
            result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return result.replace(tzinfo=None) if result.tzinfo else result


def _current_period_is_complete(rows: Sequence[Mapping[str, Any]]) -> bool:
    dated = [row for row in rows if _day(row.get("business_date"))]
    if not dated:
        return False
    for row in dated:
        business = _day(row.get("business_date"))
        snapshot = _as_datetime(row.get("snapshot_time"))
        if snapshot is None:
            return False
        try:
            business_date = dt.date.fromisoformat(business)
        except ValueError:
            return False
        if snapshot.date() <= business_date:
            return False
    return True


def _baseline_axis(package: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    axes = package.get("platform_baselines") or {}
    axis = axes.get(name) if isinstance(axes, Mapping) else None
    return axis if isinstance(axis, Mapping) else {}


def _axis_status(
    current: float | None,
    baseline: Mapping[str, Any],
    *,
    low: float,
    high: float,
) -> tuple[str, float | None]:
    ratio = _safe_ratio(current, baseline.get("median"))
    if ratio is None:
        return "unavailable", None
    if ratio < low:
        return "weak", ratio
    if ratio > high:
        return "strong", ratio
    return "normal", ratio


def _sales_context(report: Mapping[str, Any]) -> dict[str, Any]:
    hotel = report.get("hotel_result") or {}
    target = hotel.get("target_line") or {}
    capacity = hotel.get("capacity_line") or {}
    delta = _n(target.get("delta_pp"))
    return {
        "status": _sales_status(delta),
        "sales_progress_delta_pp": delta,
        "committed_sold": _n(hotel.get("committed_sold")),
        "total_rooms": _n(hotel.get("total_rooms")),
        "available_rooms": _n(hotel.get("available_rooms")),
        "current_expected_sold": _n(target.get("expected_sold")),
        "checkpoint_room_gap": _n(target.get("room_gap")),
        "remaining_target_gap": _n(target.get("remaining_target_gap")),
        "capacity_progress_delta_pp": _n(capacity.get("delta_pp")),
        "freshness_status": report.get("freshness_status"),
        "checkpoint_gap_minutes": report.get("checkpoint_gap_minutes"),
        "judgment_allowed": report.get("progress_judgment_allowed", True) is not False,
    }


def _room_structure(report: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for source in report.get("room_type_results") or []:
        row = dict(source)
        target = row.get("target_line") or {}
        row["sales_status"] = _sales_status(_n(target.get("delta_pp")))
        row["sales_progress_delta_pp"] = _n(target.get("delta_pp"))
        row["checkpoint_room_gap"] = _n(target.get("room_gap"))
        row["current_expected_sold"] = _n(target.get("expected_sold"))
        rows.append(row)
    summary = dict(report.get("structure_summary") or {})
    summary["room_type_results"] = rows
    return summary


def _product_facts(
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> list[dict[str, Any]]:
    try:
        rows = _current_room_prices(
            repository,
            hotel_id,
            target_date,
            as_of_datetime,
        )
    except Exception:
        rows = []
    facts: list[dict[str, Any]] = []
    for row in rows:
        current = _n(row.get("ota_sale_price") or row.get("current_price"))
        if current is None:
            continue
        facts.append(
            {
                "platform": str(
                    row.get("source_platform")
                    or row.get("channel")
                    or "meituan"
                ).lower(),
                "ota_product_id": row.get("ota_product_id"),
                "ota_product_name": row.get("ota_product_name"),
                "room_type_id": row.get("room_type_id"),
                "room_type_name": row.get("room_type_name"),
                "product_type": (
                    "钟点房"
                    if str(row.get("is_hour_room") or "").lower()
                    in {"1", "true", "yes"}
                    else "超级团购"
                    if str(row.get("is_super_deal") or "").lower()
                    in {"1", "true", "yes"}
                    else "普通全天房"
                ),
                "current_price": current,
                "history_status": "unavailable",
                "price_status": "unavailable",
                "comparison_allowed": False,
                "action_eligible": False,
                "comparison_reason": "exact_product_history_unavailable",
            }
        )
    return facts


def _diagnose(
    *,
    sales: Mapping[str, Any],
    market: Mapping[str, Any],
    share: Mapping[str, Any],
    browse: Mapping[str, Any],
    first: Mapping[str, Any],
    second: Mapping[str, Any],
    products: Sequence[Mapping[str, Any]],
    ad_context: Mapping[str, Any],
    structure: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    sales_status = str(sales.get("status") or "unavailable")
    sales_slow = sales_status in {
        "slow",
        "significant_slow",
        "severe_slow",
    }
    sales_fast = sales_status in {"fast", "significant_fast"}
    market_status = str(market.get("status") or "unavailable")
    share_status = str(share.get("status") or "unavailable")
    browse_status = str(browse.get("status") or "unavailable")
    first_status = str(first.get("status") or "unavailable")
    second_weak = bool(second.get("is_weak"))

    structure_labels = set(
        structure.get("labels")
        or structure.get("structure_labels")
        or []
    )
    if "room_type_structural_lag" in structure_labels:
        issues.append({"code": "ROOM_TYPE_SLOW_ONLY", "priority": 35})
    if "mix_offset_detected" in structure_labels:
        issues.append({"code": "ROOM_TYPE_MIX_OFFSET", "priority": 34})

    if sales_status == "unavailable" or sales.get("judgment_allowed") is False:
        issues.append({"code": "DATA_INSUFFICIENT", "priority": 100})
        return issues, []
    if not sales_slow:
        issues.append(
            {
                "code": "SALES_FAST" if sales_fast else "SALES_NORMAL",
                "priority": 10,
            }
        )
        if sales_fast and bool(ad_context.get("ad_running")):
            actions.append(
                {
                    "action_type": "review_promotion_stop",
                    "target_scope": "hotel",
                    "reason_codes": [
                        "sales_on_track_or_ahead",
                        "promotion_running",
                    ],
                    "observe_minutes": 60,
                    "requires_manual_confirmation": True,
                    "auto_execution_eligible": False,
                    "handoff_capability": "S8",
                }
            )
        return issues, actions[:1]

    if market_status == "cold" and share_status not in {
        "weak",
        "significant_weak",
    }:
        issues.append({"code": "MARKET_COLD", "priority": 80})
        actions.append(
            {
                "action_type": "continue_observation",
                "target_scope": "hotel",
                "reason_codes": ["market_cold_share_not_weak"],
                "observe_minutes": 60,
                "requires_manual_confirmation": False,
                "auto_execution_eligible": False,
                "handoff_capability": None,
            }
        )
        return issues, actions
    if market_status == "cold" and share_status in {
        "weak",
        "significant_weak",
    }:
        issues.append(
            {"code": "MARKET_COLD_WITH_SHARE_LOSS", "priority": 90}
        )
    elif share_status in {"weak", "significant_weak"}:
        issues.append({"code": "SHARE_LOSS", "priority": 85})

    if browse_status == "weak":
        issues.append({"code": "TRAFFIC_WEAK", "priority": 75})
        if not second_weak and market_status not in {"cold", "unavailable"}:
            actions.append(
                {
                    "action_type": "review_promotion_enable",
                    "target_scope": "hotel",
                    "reason_codes": [
                        "sales_slow",
                        "browse_weak",
                        "conversion_not_weak",
                    ],
                    "observe_minutes": 60,
                    "requires_manual_confirmation": True,
                    "auto_execution_eligible": False,
                    "handoff_capability": "S8",
                }
            )
        return issues, actions[:1]

    if first_status == "weak":
        issues.append({"code": "CLICK_CONVERSION_WEAK", "priority": 70})
        actions.append(
            {
                "action_type": "optimize_entry_display",
                "target_scope": "hotel",
                "reason_codes": ["first_conversion_weak"],
                "observe_minutes": 60,
                "requires_manual_confirmation": True,
                "auto_execution_eligible": False,
                "handoff_capability": "S8",
            }
        )
        return issues, actions

    if second_weak:
        comparable_high = [
            row
            for row in products
            if row.get("comparison_allowed")
            and row.get("price_status") == "high"
        ]
        if comparable_high:
            issues.append(
                {
                    "code": "SECOND_CONVERSION_WEAK_PRICE_HIGH",
                    "priority": 95,
                }
            )
            actions.append(
                {
                    "action_type": "review_product_price",
                    "target_scope": "ota_product",
                    "target_ota_product_ids": [
                        row.get("ota_product_id")
                        for row in comparable_high
                        if row.get("ota_product_id")
                    ],
                    "reason_codes": [
                        "sales_slow",
                        "second_conversion_weak",
                        "comparable_product_price_high",
                    ],
                    "observe_minutes": 90,
                    "requires_manual_confirmation": True,
                    "auto_execution_eligible": False,
                    "handoff_capability": "S5",
                }
            )
        else:
            issues.append(
                {
                    "code": "SECOND_CONVERSION_WEAK_NON_PRICE",
                    "priority": 88,
                }
            )
            actions.append(
                {
                    "action_type": "investigate_detail_conversion",
                    "target_scope": "hotel",
                    "reason_codes": [
                        "second_conversion_weak",
                        "product_price_not_comparable_or_not_high",
                    ],
                    "observe_minutes": 60,
                    "requires_manual_confirmation": False,
                    "auto_execution_eligible": False,
                    "handoff_capability": None,
                }
            )
        return issues, actions[:1]

    issues.append({"code": "DATA_NOT_COMPARABLE", "priority": 40})
    return issues, []


def build_s16_dynamic_diagnosis(
    repository: Any,
    *,
    baseline: Mapping[str, Any],
    progress_report: Mapping[str, Any],
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> dict[str, Any]:
    package = baseline.get("baseline_package") or {}
    sales = _sales_context(progress_report)
    structure = _room_structure(progress_report)
    try:
        current_rows = list(
            repository.ota_business_metrics(
                "meituan",
                hotel_id,
                target_date,
                target_date,
                as_of_datetime,
            )
        )
    except Exception:
        current_rows = []
    period_comparable = _current_period_is_complete(current_rows)
    grouped = _group_metric_rows(current_rows)
    current_codes = grouped.get(target_date) or {}
    current_market = _market_point(current_codes) or {}

    market_baseline = package.get("market_orders_baseline") or {}
    current_market_orders = _n(current_market.get("estimated_market_orders"))
    market_ratio = (
        _safe_ratio(current_market_orders, market_baseline.get("median"))
        if period_comparable
        else None
    )
    market_status = (
        "cold"
        if market_ratio is not None and market_ratio <= 0.90
        else "hot"
        if market_ratio is not None and market_ratio >= 1.10
        else "normal"
        if market_ratio is not None
        else "period_not_comparable"
        if current_market_orders is not None
        else "unavailable"
    )
    market = {
        **current_market,
        "baseline_median": _n(market_baseline.get("median")),
        "market_heat_ratio": market_ratio,
        "status": market_status,
        "comparison_allowed": period_comparable,
    }

    share_baseline = package.get("market_share_baseline") or {}
    current_share = _n(current_market.get("estimated_market_share"))
    baseline_share = _n(share_baseline.get("median"))
    share_delta = (
        (current_share - baseline_share) * 100
        if period_comparable
        and current_share is not None
        and baseline_share is not None
        else None
    )
    share_status = (
        "significant_weak"
        if share_delta is not None and share_delta <= -5
        else "weak"
        if share_delta is not None and share_delta <= -3
        else "normal"
        if share_delta is not None
        else "period_not_comparable"
        if current_share is not None
        else "unavailable"
    )
    share = {
        "current_estimated_market_share": current_share,
        "baseline_median": baseline_share,
        "delta_pp": share_delta,
        "status": share_status,
        "comparison_allowed": period_comparable,
    }

    metrics = _metric_current(current_rows)
    exposure = _n(metrics.get("exposure_uv"))
    browse_value = _n(metrics.get("browse_uv"))
    pay_orders = _n(metrics.get("paid_orders"))
    first_value = _safe_ratio(browse_value, exposure)
    second_value = _safe_ratio(pay_orders, browse_value)

    browse_baseline = _baseline_axis(package, "browse")
    browse_status, browse_ratio = (
        _axis_status(
            browse_value,
            browse_baseline,
            low=0.90,
            high=1.10,
        )
        if period_comparable
        else (
            "period_not_comparable" if browse_value is not None else "unavailable",
            None,
        )
    )
    browse = {
        "current": browse_value,
        "baseline_median": _n(browse_baseline.get("median")),
        "ratio": browse_ratio,
        "status": browse_status,
        "comparison_allowed": period_comparable,
    }

    first_baseline = _baseline_axis(package, "first_conversion")
    first_sample_ok = (
        exposure is not None
        and exposure >= 300
        and browse_value is not None
        and browse_value >= 30
    )
    first_status, first_ratio = (
        _axis_status(
            first_value,
            first_baseline,
            low=0.80,
            high=1.10,
        )
        if period_comparable and first_sample_ok
        else (
            "sample_insufficient"
            if period_comparable and first_value is not None
            else "period_not_comparable"
            if first_value is not None
            else "unavailable",
            None,
        )
    )
    first = {
        "current": first_value,
        "baseline_median": _n(first_baseline.get("median")),
        "ratio": first_ratio,
        "status": first_status,
        "sample_sufficient": first_sample_ok,
        "exposure_users": exposure,
        "browse_users": browse_value,
        "comparison_allowed": period_comparable,
    }

    second_baseline = _baseline_axis(package, "second_conversion")
    second_strong_sample = (
        browse_value is not None
        and browse_value >= 50
        and pay_orders is not None
        and pay_orders >= 3
    )
    second_weak_sample = (
        not second_strong_sample
        and browse_value is not None
        and browse_value >= 30
        and pay_orders is not None
        and pay_orders >= 2
    )
    second_status, second_ratio = (
        _axis_status(
            second_value,
            second_baseline,
            low=0.80,
            high=1.10,
        )
        if period_comparable
        and (second_strong_sample or second_weak_sample)
        else (
            "sample_insufficient"
            if period_comparable and second_value is not None
            else "period_not_comparable"
            if second_value is not None
            else "unavailable",
            None,
        )
    )
    peer_second = _n(
        (package.get("peer_second_conversion_reference") or {}).get("median")
    )
    peer_index = _safe_ratio(second_value, peer_second)
    own_p25 = _n(second_baseline.get("p25"))
    second_is_weak = bool(
        period_comparable
        and second_strong_sample
        and _n(sales.get("sales_progress_delta_pp")) is not None
        and float(sales["sales_progress_delta_pp"]) <= -8
        and browse_ratio is not None
        and browse_ratio >= 0.90
        and second_value is not None
        and own_p25 is not None
        and second_value < own_p25
        and peer_index is not None
        and peer_index < 0.85
    )
    second = {
        "current": second_value,
        "baseline_median": _n(second_baseline.get("median")),
        "baseline_p25": own_p25,
        "ratio": second_ratio,
        "status": second_status,
        "sample_level": (
            "strong"
            if second_strong_sample
            else "weak_reminder"
            if second_weak_sample
            else "insufficient"
        ),
        "browse_users": browse_value,
        "pay_orders": pay_orders,
        "conversion_index_vs_market": peer_index,
        "is_weak": second_is_weak,
        "comparison_allowed": period_comparable,
    }

    products = _product_facts(
        repository,
        hotel_id,
        target_date,
        as_of_datetime,
    )
    try:
        ad_context = _ad_context(repository, hotel_id, as_of_datetime)
    except Exception:
        ad_context = {}
    lead_row = _row_for(current_codes, "DAY_ROOM_LOWEST_PRICE_AVG")
    lead = {
        "current": _n((lead_row or {}).get("metric_value")),
        "baseline_median": _n(
            (package.get("lead_price_baseline") or {}).get("median")
        ),
        "peer_average": _n((lead_row or {}).get("peer_average")),
        "rank": (lead_row or {}).get("competitor_rank"),
        "comparison_allowed": period_comparable,
    }

    issues, actions = _diagnose(
        sales=sales,
        market=market,
        share=share,
        browse=browse,
        first=first,
        second=second,
        products=products,
        ad_context=ad_context,
        structure=structure,
    )
    issues.sort(
        key=lambda item: (
            -int(item.get("priority") or 0),
            str(item.get("code") or ""),
        )
    )
    return {
        "status": "ok" if sales.get("status") != "unavailable" else "partial",
        "version": VERSION,
        "hotel_id": hotel_id,
        "target_date": target_date,
        "as_of_datetime": as_of_datetime,
        "baseline_revision": baseline.get("baseline_revision"),
        "baseline_cache_status": baseline.get("cache_status"),
        "sales": sales,
        "room_structure": structure,
        "market": market,
        "market_share": share,
        "browse": browse,
        "first_conversion": first,
        "second_conversion": second,
        "product_prices": products,
        "lead_price": lead,
        "promotion_state": ad_context,
        "issues": issues,
        "primary_issue": issues[0] if issues else None,
        "secondary_issues": issues[1:3],
        "action_candidates": actions[:1],
        "action_history_status": "unavailable",
        "observation_state": {
            "status": "not_started" if actions else "not_applicable"
        },
        "cooldown_state": {
            "status": "not_evaluated",
            "reason": "action_history_not_connected",
        },
        "auto_execution_eligible": False,
        "period_comparable": period_comparable,
        "data_limitations": [
            *(
                []
                if period_comparable
                else [
                    "当前平台数据为日内累计，与历史完整日统计周期不同，暂不直接判断强弱。"
                ]
            ),
            *(
                [
                    "当前商品缺少同一商品的可比历史价格，暂不判断价格高低。"
                ]
                if products
                else []
            ),
        ],
    }

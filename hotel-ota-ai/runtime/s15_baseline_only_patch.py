from __future__ import annotations

import datetime as dt
from typing import Any, Mapping

_INSTALLED = False
VERSION = "s15-baseline-only-build.v1"
BASELINE_PACKAGE_VERSION = "s15-baseline-package.v2"


def build_s15_baseline_only_analysis(
    repository: Any,
    payload: Mapping[str, Any],
    *,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
    date_contexts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    from runtime.s15_platform_reference import build_platform_reference
    from runtime.s15_technical_sources import (
        _group_metric_rows,
        _market_point,
        _rolling_peer_second,
        _summarize,
    )

    result: dict[str, Any] = {
        "status": "partial",
        "analysis_version": VERSION,
        "analysis_scope": "historical_baseline_package_only",
        "authority": "Digital-Employee-Algorithm-Technical-Spec-2026-07-08",
        "dynamic_current_facts_included": False,
        "dynamic_diagnosis_included": False,
        "diagnosis": [],
        "actions": [],
        "rules": {
            "platform_metric_grain": "daily",
            "platform_hourly_baseline_available": False,
            "platform_date_tag_filter_required": True,
            "estimated_market_and_share_must_be_labeled": True,
            "exact_product_history_required_for_price_judgment": True,
        },
    }
    if payload.get("status") != "ok":
        result["reason"] = "s15_baseline_unavailable"
        return result

    target = dt.date.fromisoformat(str(target_date)[:10])
    history_start = (target - dt.timedelta(days=365)).isoformat()
    history_end = (target - dt.timedelta(days=1)).isoformat()
    try:
        historical_rows = list(
            repository.ota_business_metrics(
                "meituan",
                hotel_id,
                history_start,
                history_end,
                as_of_datetime,
            )
        )
    except Exception:
        historical_rows = []

    platform_reference = build_platform_reference(
        historical_rows,
        target_date=str(target_date)[:10],
        date_contexts=date_contexts,
    )
    result["platform_reference"] = {
        key: value
        for key, value in platform_reference.items()
        if key != "daily_points"
    }

    grouped = _group_metric_rows(historical_rows)
    selected = set(platform_reference.get("selected_dates") or [])
    market_points = [
        point
        for day, codes in grouped.items()
        if not selected or day in selected
        for point in [_market_point(codes)]
        if point
    ]
    market_distribution = _summarize(
        [float(point["estimated_market_orders"]) for point in market_points]
    )
    share_distribution = _summarize(
        [
            float(point["estimated_market_share"])
            for point in market_points
            if point.get("estimated_market_share") is not None
        ]
    )
    maturity = platform_reference.get("baseline_confidence_level")
    tier = platform_reference.get("selected_tier")
    result["market"] = {
        "baseline_estimated_market_orders": market_distribution.get("median"),
        "sample_count": int(market_distribution.get("sample_count") or 0),
        "baseline_tier": tier,
        "baseline_confidence_level": maturity,
        "grain": "daily_estimate",
        "estimated": True,
    }
    result["market_share"] = {
        "baseline_estimated_market_share": share_distribution.get("median"),
        "sample_count": int(share_distribution.get("sample_count") or 0),
        "baseline_tier": tier,
        "baseline_confidence_level": maturity,
        "grain": "daily_estimate",
        "estimated": True,
    }
    baselines = platform_reference.get("baselines") or {}
    result["browse"] = {
        **dict(baselines.get("browse_uv") or {}),
        "current": None,
        "status": "baseline_only",
    }
    result["first_conversion"] = {
        **dict(baselines.get("first_conversion") or {}),
        "current": None,
        "status": "baseline_only",
    }
    result["second_conversion"] = {
        **dict(baselines.get("second_conversion") or {}),
        "current": None,
        "status": "baseline_only",
        "rolling_30d_peer": _rolling_peer_second(payload),
    }
    result["lead_price"] = {
        **dict(baselines.get("lead_price_metric") or {}),
        "current": None,
        "status": "baseline_only",
    }
    result["price"] = {
        "status": "baseline_only",
        "room_type_transaction_reference_source": "rs01_room_revenue_daily",
        "ota_product_price_history_status": "unavailable",
        "current_product_prices_included": False,
        "price_judgment_allowed": False,
    }
    result["ad_context"] = {
        "status": "not_loaded_in_s15",
        "dynamic_promotion_state_included": False,
    }
    result["status"] = "ok"
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # The historical technical-spec wrapper resolves this module global at
    # call time. Replacing only that production hook keeps compatibility
    # helpers/tests available while preventing S15 rebuilds from querying
    # current sales, current funnel, current prices or action state.
    from runtime import (
        s15_s16_responsibility_patch,
        s15_s16_technical_spec_patch,
    )

    s15_s16_responsibility_patch.BASELINE_PACKAGE_VERSION = (
        BASELINE_PACKAGE_VERSION
    )
    s15_s16_technical_spec_patch.build_s15_operating_analysis = (
        build_s15_baseline_only_analysis
    )

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping

from runtime.s15_platform_reference import build_platform_reference
from runtime.s15_technical_decision import _diagnose_and_actions
from runtime.s15_technical_sources import (
    MARKET_COLD_RATIO,
    MARKET_HOT_RATIO,
    SALES_SLOW_PP,
    SHARE_SIGNIFICANT_WEAK_PP,
    SHARE_WEAK_PP,
    _ad_context,
    _current_room_prices,
    _group_metric_rows,
    _market_point,
    _metric_axis,
    _metric_current,
    _n,
    _parse_rank,
    _price_analysis,
    _rolling_peer_second,
    _row_for,
    _safe_ratio,
    _sales_status,
    _summarize,
)

VERSION = "s15-s16-digital-employee-technical-spec.v2"


def build_s15_operating_analysis(
    repository: Any,
    payload: Mapping[str, Any],
    *,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
    date_contexts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "partial",
        "analysis_version": VERSION,
        "authority": (
            "Digital-Employee-Algorithm-Technical-Spec-2026-07-08"
        ),
        "decision_order": [
            "sales_progress",
            "market_orders",
            "market_share",
            "browse",
            "first_conversion",
            "second_conversion",
            "room_type_price",
            "action",
        ],
        "rules": {
            "platform_metric_grain": "daily",
            "platform_hourly_baseline_available": False,
            "platform_date_tag_filter_required": True,
            "estimated_market_and_share_must_be_labeled": True,
            "weak_reference_cannot_independently_trigger_automatic_action": (
                True
            ),
        },
    }
    if payload.get("status") != "ok":
        result["reason"] = "s15_baseline_unavailable"
        result["diagnosis"] = ["s15_baseline_unavailable"]
        result["actions"] = []
        return result

    try:
        from runtime.sales_progress.deviation_service import build_deviation

        deviation = build_deviation(
            repository,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_datetime=as_of_datetime,
            baseline=payload,
        )
    except Exception as exc:
        deviation = {
            "status": "data_gap",
            "reason": f"deviation_failed:{type(exc).__name__}",
        }

    hotel_result = deviation.get("hotel_result") or {}
    target_line = hotel_result.get("target_line") or {}
    capacity_line = hotel_result.get("capacity_line") or {}
    sales_delta = _n(target_line.get("delta_pp"))
    total_rooms = _n(hotel_result.get("total_rooms"))
    available_rooms = _n(hotel_result.get("available_rooms"))
    result["sales"] = {
        "status": _sales_status(sales_delta),
        "sales_progress_delta_pp": sales_delta,
        "capacity_progress_delta_pp": _n(capacity_line.get("delta_pp")),
        "combined_diagnosis": hotel_result.get("combined_diagnosis"),
        "committed_sold": _n(hotel_result.get("committed_sold")),
        "total_rooms": total_rooms,
        "available_rooms": available_rooms,
        "remaining_inventory_ratio": _safe_ratio(
            available_rooms,
            total_rooms,
        ),
        "effective_target_room_nights": _n(
            hotel_result.get("effective_target_room_nights")
        ),
        "checkpoint_room_gap": _n(target_line.get("room_gap")),
        "remaining_target_gap": _n(
            target_line.get("remaining_target_gap")
        ),
        "maturity": (
            (payload.get("hotel") or {})
            .get("baseline_health", {})
            .get("object_maturity")
        ),
        "room_structure": deviation.get("structure_summary") or {},
        "room_type_results": deviation.get("room_type_results") or [],
        "source": "S16_deterministic_sales_progress",
    }

    target = dt.date.fromisoformat(target_date)
    start_date = (target - dt.timedelta(days=365)).isoformat()
    history_end = (target - dt.timedelta(days=1)).isoformat()
    try:
        historical_rows = list(
            repository.ota_business_metrics(
                "meituan",
                hotel_id,
                start_date,
                history_end,
                as_of_datetime,
            )
        )
    except Exception:
        historical_rows = []
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

    platform_reference = build_platform_reference(
        historical_rows,
        target_date=target_date,
        date_contexts=date_contexts,
    )
    result["platform_reference"] = {
        key: value
        for key, value in platform_reference.items()
        if key != "daily_points"
    }
    grouped_history = _group_metric_rows(historical_rows)
    grouped_current = _group_metric_rows(current_rows)
    current_codes = grouped_current.get(target_date) or {}
    current_market = _market_point(current_codes)
    selected_dates = set(platform_reference.get("selected_dates") or [])
    market_history = [
        point
        for day, codes in grouped_history.items()
        if not selected_dates or day in selected_dates
        for point in [_market_point(codes)]
        if point
    ]
    market_distribution = _summarize(
        [float(row["estimated_market_orders"]) for row in market_history]
    )
    share_distribution = _summarize(
        [
            float(row["estimated_market_share"])
            for row in market_history
            if row.get("estimated_market_share") is not None
        ]
    )
    current_market_orders = _n(
        (current_market or {}).get("estimated_market_orders")
    )
    baseline_market_orders = _n(market_distribution.get("median"))
    market_ratio = _safe_ratio(
        current_market_orders,
        baseline_market_orders,
    )
    market_status = "unavailable"
    if market_ratio is not None:
        market_status = (
            "cold"
            if market_ratio <= MARKET_COLD_RATIO
            else "hot"
            if market_ratio >= MARKET_HOT_RATIO
            else "normal"
        )
    result["market"] = {
        **(current_market or {}),
        "baseline_estimated_market_orders": baseline_market_orders,
        "market_heat_ratio": market_ratio,
        "status": market_status,
        "sample_count": int(market_distribution.get("sample_count") or 0),
        "baseline_tier": platform_reference.get("selected_tier"),
        "baseline_confidence_level": platform_reference.get(
            "baseline_confidence_level"
        ),
        "grain": "daily_estimate",
        "estimated": True,
    }

    current_share = _n(
        (current_market or {}).get("estimated_market_share")
    )
    baseline_share = _n(share_distribution.get("median"))
    share_delta_pp = (
        (current_share - baseline_share) * 100
        if current_share is not None and baseline_share is not None
        else None
    )
    share_status = "unavailable"
    if share_delta_pp is not None:
        share_status = (
            "significant_weak"
            if share_delta_pp <= SHARE_SIGNIFICANT_WEAK_PP
            else "weak"
            if share_delta_pp <= SHARE_WEAK_PP
            else "normal"
        )
    result["market_share"] = {
        "current_estimated_market_share": current_share,
        "baseline_estimated_market_share": baseline_share,
        "delta_pp": share_delta_pp,
        "status": share_status,
        "sample_count": int(share_distribution.get("sample_count") or 0),
        "baseline_tier": platform_reference.get("selected_tier"),
        "baseline_confidence_level": platform_reference.get(
            "baseline_confidence_level"
        ),
        "grain": "daily_estimate",
        "estimated": True,
    }

    current_metrics = _metric_current(current_rows)
    baselines = platform_reference.get("baselines") or {}
    exposure = _n(current_metrics.get("exposure_uv"))
    browse_value = _n(current_metrics.get("browse_uv"))
    orders = _n(current_metrics.get("paid_orders"))
    first_value = _safe_ratio(browse_value, exposure)
    second_value = _safe_ratio(orders, browse_value)
    result["browse"] = _metric_axis(
        browse_value,
        baselines.get("browse_uv") or {},
    )
    first_sample_ok = bool(
        exposure is not None
        and exposure >= 300
        and browse_value is not None
        and browse_value >= 30
    )
    result["first_conversion"] = _metric_axis(
        first_value,
        baselines.get("first_conversion") or {},
        sample_sufficient=first_sample_ok,
    )
    result["first_conversion"].update(
        {
            "exposure_users": exposure,
            "browse_users": browse_value,
        }
    )

    second_sample_strong = bool(
        browse_value is not None
        and browse_value >= 50
        and orders is not None
        and orders >= 3
    )
    second_sample_weak = bool(
        not second_sample_strong
        and browse_value is not None
        and browse_value >= 30
        and orders is not None
        and orders >= 2
    )
    second_axis = _metric_axis(
        second_value,
        baselines.get("second_conversion") or {},
        sample_sufficient=second_sample_strong or second_sample_weak,
    )
    rolling_peer = _rolling_peer_second(payload)
    own_p25 = _n(second_axis.get("baseline_p25"))
    peer_index = _safe_ratio(
        second_value,
        rolling_peer.get("peer_second_conversion"),
    )
    browse_ratio = _n((result.get("browse") or {}).get("ratio"))
    is_second_weak = bool(
        second_sample_strong
        and second_value is not None
        and own_p25 is not None
        and second_value < own_p25
        and peer_index is not None
        and peer_index < 0.85
        and browse_ratio is not None
        and browse_ratio >= 0.90
        and sales_delta is not None
        and sales_delta <= SALES_SLOW_PP
    )
    second_axis.update(
        {
            "browse_users": browse_value,
            "pay_orders": orders,
            "sample_level": (
                "strong"
                if second_sample_strong
                else "weak_reminder"
                if second_sample_weak
                else "insufficient"
            ),
            "strong_judgment_allowed": second_sample_strong,
            "weak_reminder_allowed": second_sample_weak,
            "rolling_30d_peer": rolling_peer,
            "conversion_index_vs_market": peer_index,
            "is_weak": is_second_weak,
        }
    )
    result["second_conversion"] = second_axis

    try:
        price_rows = _current_room_prices(
            repository,
            hotel_id,
            target_date,
            as_of_datetime,
        )
    except Exception:
        price_rows = []
    result["price"] = _price_analysis(payload, price_rows)
    result["ad_context"] = _ad_context(
        repository,
        hotel_id,
        as_of_datetime,
    )

    lead_row = _row_for(current_codes, "DAY_ROOM_LOWEST_PRICE_AVG")
    lead_current = _n((lead_row or {}).get("metric_value"))
    lead_baseline = baselines.get("lead_price_metric") or {}
    lead_rank, lead_rank_total = _parse_rank(
        (lead_row or {}).get("competitor_rank")
    )
    result["lead_price"] = {
        "current": lead_current,
        "baseline_median": _n(lead_baseline.get("median")),
        "ratio": _safe_ratio(
            lead_current,
            lead_baseline.get("median"),
        ),
        "peer_average": _n((lead_row or {}).get("peer_average")),
        "rank": lead_rank,
        "rank_total": lead_rank_total,
        "sample_count": int(lead_baseline.get("sample_count") or 0),
        "baseline_tier": platform_reference.get("selected_tier"),
        "baseline_confidence_level": platform_reference.get(
            "baseline_confidence_level"
        ),
        "grain": "daily",
        "hourly_baseline_available": False,
    }

    diagnosis, actions = _diagnose_and_actions(result)
    result["diagnosis"] = diagnosis
    result["actions"] = actions
    result["status"] = (
        "ok"
        if (result.get("sales") or {}).get("status") != "unavailable"
        else "partial"
    )
    result["action_execution_boundary"] = {
        "advice_only": True,
        "direct_task_creation_allowed": False,
        "direct_price_write_allowed": False,
        "direct_ad_write_allowed": False,
        "price_actions_require": [
            "S5",
            "price_guard",
            "manual_confirmation",
        ],
        "ad_actions_require": ["S8", "manual_confirmation"],
    }
    return result

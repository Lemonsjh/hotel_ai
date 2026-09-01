from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

_INSTALLED = False
VERSION = "s16-platform-pay-order-primary.v4"


def _share_status(delta_pp: float | None) -> str:
    if delta_pp is None:
        return "unavailable"
    if delta_pp <= -5:
        return "significant_weak"
    if delta_pp <= -3:
        return "weak"
    if delta_pp >= 3:
        return "strong"
    return "normal"


def _latest_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Return only metric rows from the latest PAY_ORDER_CNT snapshot batch."""

    ordered = sorted(
        rows,
        key=lambda item: (
            str(item.get("snapshot_time") or ""),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    pay_row = next(
        (
            row
            for row in ordered
            if str(row.get("metric_code") or "") == "PAY_ORDER_CNT"
        ),
        None,
    )
    if pay_row is None:
        return {}

    pay_date = str(pay_row.get("business_date") or "").strip()
    pay_snapshot = str(pay_row.get("snapshot_time") or "").strip()
    if not pay_date or not pay_snapshot:
        return {"PAY_ORDER_CNT": pay_row}

    latest: dict[str, Mapping[str, Any]] = {}
    for row in ordered:
        if str(row.get("business_date") or "").strip() != pay_date:
            continue
        if str(row.get("snapshot_time") or "").strip() != pay_snapshot:
            continue
        code = str(row.get("metric_code") or "").strip()
        if code and code not in latest:
            latest[code] = row
    latest.setdefault("PAY_ORDER_CNT", pay_row)
    return latest


def _peer_rank(value: Any) -> tuple[int | None, int | None]:
    text = str(value or "").strip()
    if "/" not in text:
        return None, None
    left, right = text.split("/", 1)
    try:
        return int(float(left.strip())), int(float(right.strip()))
    except (TypeError, ValueError):
        return None, None


def _current_platform_context(
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> dict[str, Any]:
    from runtime import s15_market_metric_patch as canonical

    try:
        rows = list(
            repository.ota_business_metrics(
                "meituan",
                hotel_id,
                target_date,
                target_date,
                as_of_datetime,
            )
        )
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason": f"meituan_metrics_query_failed:{type(exc).__name__}",
        }

    point = canonical.market_point(_latest_rows(rows))
    if point is None:
        return {
            "status": "unavailable",
            "reason": "meituan_current_market_context_unavailable",
        }
    return {
        "status": "available",
        **point,
    }


def _platform_primary_proxy(
    previous: Callable[..., dict[str, Any]],
    repository: Any,
    *,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
    baseline_market_orders: Any,
    baseline_market_share: Any,
) -> dict[str, Any]:
    del previous  # Platform facts are authoritative; PMS/JD01 fallback is forbidden.
    from runtime import s16_meituan_projection_advisory_patch as source

    context = _current_platform_context(
        repository,
        hotel_id,
        target_date,
        as_of_datetime,
    )
    own_code = str(
        context.get("own_order_metric_code") or "PAY_ORDER_CNT"
    )
    own_source = f"meituan_ota_business_metrics.{own_code}"
    hotel_count_codes = tuple(context.get("peer_hotel_count_metric_codes") or ())
    peer_source = "meituan_ota_business_metrics.PAY_ORDER_CNT"
    borrowed_count_codes = tuple(
        code for code in hotel_count_codes if code != "PAY_ORDER_CNT"
    )
    if borrowed_count_codes:
        peer_source += "+same_batch_peer_hotel_count(" + ",".join(borrowed_count_codes) + ")"
    if context.get("status") != "available":
        return {
            "status": "unavailable",
            "platform": "meituan",
            "reason": context.get("reason") or "meituan_current_market_context_unavailable",
            "own_order_source": own_source,
            "peer_context_source": peer_source,
            "peer_context_previous_day_fallback_used": False,
        }

    own_orders = float(context["own_orders"])
    peer_average = float(context["peer_average_orders"])
    hotel_count = int(context["peer_hotel_count"])
    estimated_market_orders = float(context["estimated_market_orders"])
    estimated_share = context.get("estimated_market_share")
    elapsed = source._elapsed_day_fraction(target_date, as_of_datetime)
    completion_ratios = source._historical_completion_ratios(
        repository,
        hotel_id=hotel_id,
        target_date=target_date,
        as_of_datetime=as_of_datetime,
        metric_code="PAY_ORDER_CNT",
        value_fields=("metric_value", "peer_average"),
    )
    projection = source._market_projection(
        own_orders,
        peer_average,
        hotel_count,
        baseline_market_orders,
        elapsed,
        own_completion_ratio=(
            completion_ratios.get("metric_value")
            if own_code == "PAY_ORDER_CNT"
            else None
        ),
        peer_completion_ratio=completion_ratios.get("peer_average"),
    )
    baseline_share = source._n(baseline_market_share)
    share_delta_pp = (
        (float(estimated_share) - baseline_share) * 100
        if estimated_share is not None and baseline_share is not None
        else None
    )

    return {
        "status": "available",
        "platform": "meituan",
        "current_estimated_market_orders": estimated_market_orders,
        "current_estimated_market_share": estimated_share,
        "baseline_market_orders": source._n(baseline_market_orders),
        "baseline_market_share": baseline_share,
        "share_delta_pp": share_delta_pp,
        "share_status": _share_status(share_delta_pp),
        "own_orders": own_orders,
        "own_orders_proxy": own_orders,  # Compatibility alias for existing renderer only.
        "peer_average_orders": peer_average,
        "peer_rank": context.get("peer_rank"),
        "peer_hotel_count": hotel_count,
        "platform_reported_own_orders": own_orders,
        "own_order_metric_code": own_code,
        "own_order_fallback_used": bool(
            context.get("own_order_fallback_used")
        ),
        "peer_context_metric_code": "PAY_ORDER_CNT",
        "peer_average_metric_code": context.get(
            "peer_average_metric_code"
        ) or "PAY_ORDER_CNT",
        "competitor_rank_metric_code": context.get(
            "competitor_rank_metric_code"
        ),
        "peer_hotel_count_metric_code": context.get(
            "peer_hotel_count_metric_code"
        ),
        "peer_hotel_count_metric_codes": hotel_count_codes,
        "peer_context_business_date": context.get(
            "peer_context_business_date"
        ) or target_date,
        "peer_context_previous_day_fallback_used": False,
        "flow_peer_fields_ignored": bool(
            context.get("flow_peer_fields_ignored", True)
        ),
        "same_batch_fallback_fields": context.get(
            "same_batch_fallback_fields"
        ) or (),
        "same_batch_flow_fallback_fields": context.get(
            "same_batch_flow_fallback_fields"
        ) or (),
        "own_order_snapshot_time": context.get("own_order_snapshot_time"),
        "peer_context_snapshot_time": context.get("peer_context_snapshot_time"),
        "market_projection": projection,
        "elapsed_day_fraction": elapsed,
        "estimation_method": context.get("estimation_method"),
        "market_metric_contract_version": context.get(
            "market_metric_contract_version"
        ),
        "own_order_source": own_source,
        "own_order_proxy_source": own_source,
        "peer_context_source": peer_source,
        "hourly_collection_may_lag": True,
        "gross_orders_not_net_of_cancellation": False,
    }


def _rewrite_user_text(text: str) -> str:
    replacements = {
        "本店今日美团订单代理": "本店今日美团支付订单",
        "本店美团订单代理值": "本店美团支付订单",
        "JD01美团订单代理": "美团小时支付订单",
        "JD01 订单代理": "美团小时支付订单",
        "PMS订单代理": "美团小时支付订单",
        "订单代理口径": "美团小时采集口径",
    }
    result = text
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s16_meituan_projection_advisory_patch as target
    from runtime.sales_progress import presentation

    previous = target.build_meituan_market_proxy
    if getattr(previous, "_S16_PLATFORM_PAY_ORDER_PRIMARY_V4", False):
        return

    def build_meituan_market_proxy(
        repository: Any,
        *,
        hotel_id: str,
        target_date: str,
        as_of_datetime: str,
        baseline_market_orders: Any,
        baseline_market_share: Any,
    ) -> dict[str, Any]:
        return _platform_primary_proxy(
            previous,
            repository,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_datetime=as_of_datetime,
            baseline_market_orders=baseline_market_orders,
            baseline_market_share=baseline_market_share,
        )

    build_meituan_market_proxy._S16_PLATFORM_PAY_ORDER_PRIMARY_V4 = True  # type: ignore[attr-defined]
    target.build_meituan_market_proxy = build_meituan_market_proxy

    previous_message = presentation.build_s16_user_message
    if not getattr(previous_message, "_S16_PLATFORM_ORDER_TERMS_V4", False):

        def build_s16_user_message(report: Mapping[str, Any]) -> str:
            return _rewrite_user_text(previous_message(report))

        build_s16_user_message._S16_PLATFORM_ORDER_TERMS_V4 = True  # type: ignore[attr-defined]
        presentation.build_s16_user_message = build_s16_user_message

    from runtime.s16_pay_order_price_sample_followup_patch import (
        install as install_followup,
    )

    install_followup()

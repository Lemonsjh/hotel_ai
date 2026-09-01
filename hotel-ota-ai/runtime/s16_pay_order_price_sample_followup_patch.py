from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Callable, Mapping, Sequence

_INSTALLED = False
VERSION = "s16-pay-order-price-sample-followup.v3"
BASELINE_PACKAGE_VERSION = "s15-baseline-package.v2"


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _previous_business_date(target_date: str) -> str | None:
    try:
        return (date.fromisoformat(str(target_date)) - timedelta(days=1)).isoformat()
    except ValueError:
        return None


def current_platform_context(
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> dict[str, Any]:
    from runtime import s15_market_metric_patch as canonical
    from runtime import s16_platform_pay_order_primary_patch as platform

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

    latest = platform._latest_rows(rows)
    point = canonical.market_point(latest)
    peer_context_business_date = target_date
    peer_context_previous_day_fallback_used = False

    if point is None:
        flow_row = latest.get("FLOW_PAY_ORDER_CNT") or {}
        pay_row = latest.get("PAY_ORDER_CNT") or {}
        own_orders_available = (
            _n(flow_row.get("metric_value")) is not None
            or _n(pay_row.get("metric_value")) is not None
        )
        _, current_hotel_count = platform._peer_rank(
            pay_row.get("competitor_rank")
        )
        current_peer_context_available = (
            _n(pay_row.get("peer_average")) is not None
            and current_hotel_count is not None
            and current_hotel_count > 0
        )

        previous_date = _previous_business_date(target_date)
        if (
            own_orders_available
            and not current_peer_context_available
            and previous_date is not None
        ):
            try:
                previous_rows = list(
                    repository.ota_business_metrics(
                        "meituan",
                        hotel_id,
                        previous_date,
                        previous_date,
                        as_of_datetime,
                    )
                )
            except Exception:
                previous_rows = []

            previous_pay_row = (
                platform._latest_rows(previous_rows).get("PAY_ORDER_CNT") or {}
            )
            previous_peer_average = _n(
                previous_pay_row.get("peer_average")
            )
            _, previous_hotel_count = platform._peer_rank(
                previous_pay_row.get("competitor_rank")
            )
            if (
                previous_peer_average is not None
                and previous_hotel_count is not None
                and previous_hotel_count > 0
            ):
                fallback_pay_row = dict(pay_row)
                fallback_pay_row["peer_average"] = previous_pay_row.get(
                    "peer_average"
                )
                fallback_pay_row["competitor_rank"] = previous_pay_row.get(
                    "competitor_rank"
                )
                fallback_latest = dict(latest)
                fallback_latest["PAY_ORDER_CNT"] = fallback_pay_row
                point = canonical.market_point(fallback_latest)
                if point is not None:
                    point = dict(point)
                    point["peer_context_snapshot_time"] = previous_pay_row.get(
                        "snapshot_time"
                    )
                    peer_context_business_date = previous_date
                    peer_context_previous_day_fallback_used = True

    if point is None:
        flow_row = latest.get("FLOW_PAY_ORDER_CNT") or {}
        pay_row = latest.get("PAY_ORDER_CNT") or {}
        if (
            _n(flow_row.get("metric_value")) is None
            and _n(pay_row.get("metric_value")) is None
        ):
            reason = "meituan_current_pay_order_unavailable"
        elif _n(pay_row.get("peer_average")) is None:
            reason = "meituan_pay_order_peer_average_unavailable"
        else:
            _, hotel_count = platform._peer_rank(
                pay_row.get("competitor_rank")
            )
            reason = (
                "meituan_pay_order_peer_hotel_count_unavailable"
                if hotel_count is None or hotel_count <= 0
                else "meituan_current_market_context_unavailable"
            )
        return {"status": "unavailable", "reason": reason}

    return {
        "status": "available",
        "own_orders": point.get("own_orders"),
        "peer_average_orders": point.get("peer_average_orders"),
        "peer_rank": point.get("peer_rank"),
        "peer_hotel_count": point.get("peer_hotel_count"),
        "estimated_market_orders": point.get("estimated_market_orders"),
        "estimated_market_share": point.get("estimated_market_share"),
        "estimation_method": point.get("estimation_method"),
        "own_order_metric_code": point.get("own_order_metric_code"),
        "own_order_fallback_used": bool(
            point.get("own_order_fallback_used")
        ),
        "peer_context_metric_code": "PAY_ORDER_CNT",
        "peer_context_business_date": peer_context_business_date,
        "peer_context_previous_day_fallback_used": (
            peer_context_previous_day_fallback_used
        ),
        "flow_peer_fields_ignored": True,
        "own_order_snapshot_time": point.get("own_order_snapshot_time"),
        "peer_context_snapshot_time": point.get(
            "peer_context_snapshot_time"
        ),
        "market_metric_contract_version": canonical.VERSION,
    }


def metric_current_wrapper(
    previous: Callable[[Sequence[Mapping[str, Any]]], dict[str, Any]],
) -> Callable[[Sequence[Mapping[str, Any]]], dict[str, Any]]:
    def metric_current(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        result = dict(previous(rows))
        flow_orders = _n(result.get("paid_orders"))
        pay_orders = _n(result.get("paid_orders_duplicate"))
        if flow_orders is None and pay_orders is not None:
            result["paid_orders"] = pay_orders
            browse = _n(result.get("browse_uv"))
            result["second_conversion"] = (
                pay_orders / browse if browse not in (None, 0) else None
            )
            result["paid_orders_source"] = "PAY_ORDER_CNT"
            result["paid_orders_fallback_used"] = True
        elif flow_orders is not None:
            result["paid_orders_source"] = "FLOW_PAY_ORDER_CNT"
            result["paid_orders_fallback_used"] = False
        return result

    metric_current._S16_PAY_ORDER_PRICE_SAMPLE_FOLLOWUP_V2 = True  # type: ignore[attr-defined]
    return metric_current


def baseline_package_wrapper(
    previous: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def build(payload: Mapping[str, Any]) -> dict[str, Any]:
        package = dict(previous(payload))
        rooms = {
            str(room_id): room if isinstance(room, Mapping) else {}
            for room_id, room in (payload.get("room_types") or {}).items()
        }
        references: list[dict[str, Any]] = []
        for source in package.get("room_type_transaction_references") or []:
            reference = dict(source)
            room = rooms.get(str(reference.get("room_type_id") or ""), {})
            price = room.get("price_baseline") or {}
            source_rows = int(price.get("source_row_count") or 0)
            samples = int(price.get("sample_count") or source_rows or 0)
            reference.update(
                {
                    "sample_count": samples,
                    "source_row_count": source_rows,
                    "weighted_room_nights": _n(price.get("weighted_room_nights")),
                    "comparison_ready": bool(
                        samples > 0
                        and any(
                            _n(reference.get(key)) is not None
                            for key in ("p20", "median", "p80")
                        )
                    ),
                }
            )
            references.append(reference)
        package["room_type_transaction_references"] = references
        package["version"] = BASELINE_PACKAGE_VERSION
        return package

    build._S16_PAY_ORDER_PRICE_SAMPLE_FOLLOWUP_V2 = True  # type: ignore[attr-defined]
    return build


def contract_wrapper(
    previous: Callable[[Mapping[str, Any]], dict[str, Any]],
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    def build(result: Mapping[str, Any]) -> dict[str, Any]:
        contract = dict(previous(result))
        must_preserve = [
            item
            for item in contract.get("must_preserve") or []
            if "FLOW_PAY_ORDER_CNT本店订单与PAY_ORDER_CNT同行口径"
            not in str(item)
        ]
        must_preserve.append(
            "美团本店支付订单优先使用FLOW_PAY_ORDER_CNT，空值时回退PAY_ORDER_CNT；同行均值和同行范围始终只使用PAY_ORDER_CNT"
        )
        forbidden = [
            item
            for item in contract.get("forbidden") or []
            if "PAY_ORDER_CNT.metric_value误当成本店支付订单" not in str(item)
            and "没有同一OTA商品历史时输出确定的价格偏高或偏低"
            not in str(item)
        ]
        forbidden.extend(
            [
                "经营口径支付订单有值时仍声称没有订单、无法估算大盘或二转缺失",
                "使用FLOW_PAY_ORDER_CNT的peer_average或competitor_rank估算同行大盘",
                "同一批数据因模块预绑定旧_market_point而走不同大盘估算路径",
                "房型成交分位数和source_row_count有效时仍把样本数写成0或拒绝净价比较",
                "普通员工对话输出字段名、代码路径、补丁、提交或技术排查过程",
            ]
        )
        allowed = list(contract.get("allowed") or [])
        allowed.append(
            "普通全天房可用活动后预计酒店到手价与对应房型历史成交P20、中位、P80比较，只作为原因证据"
        )
        contract.update(
            {
                "must_preserve": list(dict.fromkeys(must_preserve)),
                "forbidden": list(dict.fromkeys(forbidden)),
                "allowed": list(dict.fromkeys(allowed)),
                "contract_version": VERSION,
            }
        )
        return contract

    build._S16_PAY_ORDER_PRICE_SAMPLE_FOLLOWUP_V2 = True  # type: ignore[attr-defined]
    return build


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s15_market_metric_patch as canonical
    from runtime import s15_s16_responsibility_patch as responsibility
    from runtime import s15_technical_sources
    from runtime import s16_dynamic_diagnosis
    from runtime import s16_platform_pay_order_primary_patch as platform
    from runtime import s16_skill_delivery_patch as skill

    platform._current_platform_context = current_platform_context
    s16_dynamic_diagnosis._market_point = canonical.market_point

    previous_metric = s15_technical_sources._metric_current
    if not getattr(
        previous_metric,
        "_S16_PAY_ORDER_PRICE_SAMPLE_FOLLOWUP_V2",
        False,
    ):
        wrapped_metric = metric_current_wrapper(previous_metric)
        s15_technical_sources._metric_current = wrapped_metric
        s16_dynamic_diagnosis._metric_current = wrapped_metric

    responsibility.BASELINE_PACKAGE_VERSION = BASELINE_PACKAGE_VERSION
    previous_package = responsibility._build_baseline_package
    if not getattr(
        previous_package,
        "_S16_PAY_ORDER_PRICE_SAMPLE_FOLLOWUP_V2",
        False,
    ):
        responsibility._build_baseline_package = baseline_package_wrapper(
            previous_package
        )

    previous_contract = skill.build_s16_response_contract
    if not getattr(
        previous_contract,
        "_S16_PAY_ORDER_PRICE_SAMPLE_FOLLOWUP_V2",
        False,
    ):
        skill.build_s16_response_contract = contract_wrapper(previous_contract)

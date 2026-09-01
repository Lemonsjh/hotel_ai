from __future__ import annotations

import datetime as dt
import math
import statistics
from typing import Any, Callable, Mapping, Sequence

VERSION = "s16-meituan-projection-advisory.v1"
_INSTALLED = False
_SLOW = {"slow", "significant_slow", "severe_slow"}
_FAST = {"fast", "significant_fast"}
_HOURLY_LOOKBACK_DAYS = 60
_HOURLY_VALUE_FIELDS = {"metric_value", "peer_average"}


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _parse_rank(value: Any) -> tuple[int | None, int | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    if "/" in text:
        left, right = text.split("/", 1)
        try:
            return int(float(left.strip())), int(float(right.strip()))
        except (TypeError, ValueError):
            return None, None
    try:
        return int(float(text)), None
    except (TypeError, ValueError):
        return None, None


def _elapsed_day_fraction(target_date: str, as_of_datetime: str) -> float | None:
    as_of = _as_datetime(as_of_datetime)
    if as_of is None or as_of.date().isoformat() != str(target_date)[:10]:
        return None
    minutes = as_of.hour * 60 + as_of.minute + as_of.second / 60.0
    fraction = minutes / 1440.0
    if fraction < 0.35 or fraction >= 1:
        return None
    return fraction


def _snapshot_hour(value: Any) -> int | None:
    parsed = _as_datetime(value)
    if parsed is not None:
        return parsed.hour
    number = _n(value)
    if number is None:
        return None
    hour = int(number)
    return hour if 0 <= hour <= 23 and hour == number else None


def _historical_completion_ratios(
    repository: Any,
    *,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
    metric_code: str,
    value_fields: Sequence[str] = ("metric_value",),
) -> dict[str, float]:
    query = getattr(repository, "_query", None)
    if not callable(query):
        return {}
    as_of = _as_datetime(as_of_datetime)
    try:
        target = dt.date.fromisoformat(str(target_date)[:10])
    except ValueError:
        return {}
    if as_of is None or as_of.date() != target:
        return {}
    fields = tuple(field for field in value_fields if field in _HOURLY_VALUE_FIELDS)
    if not fields:
        return {}
    start_date = target - dt.timedelta(days=_HOURLY_LOOKBACK_DAYS)
    try:
        rows = query(
            """
            SELECT id, business_date, snapshot_time, snapshot_hour,
                   metric_code, metric_value, peer_average
            FROM meituan_ota_business_metrics_hourly
            WHERE hotel_id=%s
              AND business_date >= %s
              AND business_date < %s
              AND metric_code=%s
            ORDER BY business_date ASC, snapshot_hour ASC,
                     snapshot_time ASC, id ASC
            """,
            (
                hotel_id,
                start_date.isoformat(),
                target.isoformat(),
                metric_code,
            ),
        )
    except Exception:
        return {}

    per_field: dict[str, dict[str, dict[str, float | None]]] = {
        field: {} for field in fields
    }
    for source in rows:
        row = dict(source)
        day = str(row.get("business_date") or "")[:10]
        hour = _snapshot_hour(row.get("snapshot_hour"))
        if not day or hour is None:
            continue
        for field in fields:
            value = _n(row.get(field))
            if value is None or value <= 0:
                continue
            state = per_field[field].setdefault(
                day,
                {"same_hour": None, "final": None},
            )
            state["final"] = value
            if hour == as_of.hour:
                state["same_hour"] = value

    from runtime.common import DEFAULT_DB
    from runtime.s15_s16_spec_alignment_patch import select_platform_dates
    from runtime.sales_progress.calendar import load_calendar_contexts

    date_contexts = load_calendar_contexts(
        DEFAULT_DB,
        start_date.isoformat(),
        target.isoformat(),
        target.isoformat(),
    )
    result: dict[str, float] = {}
    for field, days in per_field.items():
        ratios_by_day = {
            day: float(state["same_hour"]) / float(state["final"])
            for day, state in days.items()
            if state.get("same_hour") is not None
            and state.get("final") not in (None, 0)
        }
        if not ratios_by_day:
            continue
        _, selected_dates = select_platform_dates(
            target.isoformat(),
            sorted(ratios_by_day),
            date_contexts,
        )
        selected = [
            ratios_by_day[day]
            for day in selected_dates
            if day in ratios_by_day
        ]
        if selected:
            result[field] = float(statistics.median(selected))
    return result


def _projected_value(
    current: Any,
    elapsed: float | None,
    completion_ratio: Any = None,
) -> tuple[float | None, bool]:
    current_value = _n(current)
    if current_value is None:
        return None, True
    completion = _n(completion_ratio)
    if completion is not None and completion > 0:
        return current_value / completion, False
    if elapsed is None or elapsed <= 0:
        return None, True
    return current_value / elapsed, True


def _projection_result(
    projected: Any,
    baseline: Any,
    *,
    linear_projection_only: bool,
) -> dict[str, Any]:
    projected_value = _n(projected)
    baseline_value = _n(baseline)
    if projected_value is None or baseline_value in (None, 0):
        return {
            "status": "unavailable",
            "projected_full_day": None,
            "projected_ratio_vs_history": None,
            "linear_projection_only": linear_projection_only,
        }
    ratio = projected_value / baseline_value
    status = (
        "likely_above_history"
        if ratio >= 1.05
        else "near_history"
        if ratio >= 0.95
        else "likely_below_history"
    )
    return {
        "status": status,
        "projected_full_day": projected_value,
        "projected_ratio_vs_history": ratio,
        "linear_projection_only": linear_projection_only,
    }


def _projection(
    current: Any,
    baseline: Any,
    elapsed: float | None,
    *,
    completion_ratio: Any = None,
) -> dict[str, Any]:
    projected, linear_only = _projected_value(
        current,
        elapsed,
        completion_ratio,
    )
    return _projection_result(
        projected,
        baseline,
        linear_projection_only=linear_only,
    )


def _market_projection(
    own_orders: Any,
    peer_average: Any,
    peer_hotel_count: int,
    baseline_market_orders: Any,
    elapsed: float | None,
    *,
    own_completion_ratio: Any = None,
    peer_completion_ratio: Any = None,
) -> dict[str, Any]:
    own_value = _n(own_orders)
    peer_value = _n(peer_average)
    projected_own, own_linear = _projected_value(
        own_orders,
        elapsed,
        own_completion_ratio,
    )
    projected_peer, peer_linear = _projected_value(
        peer_average,
        elapsed,
        peer_completion_ratio,
    )
    projected_market = (
        int(math.floor(projected_peer * int(peer_hotel_count) + 0.5))
        if projected_peer is not None
        else None
    )
    current_market = (
        int(math.floor(peer_value * int(peer_hotel_count) + 0.5))
        if peer_value is not None
        else None
    )
    result = _projection_result(
        projected_market,
        baseline_market_orders,
        linear_projection_only=peer_linear,
    )
    result.update(
        {
            "own_hourly_completion_ratio": _n(own_completion_ratio),
            "peer_hourly_completion_ratio": _n(peer_completion_ratio),
            "market_hourly_completion_ratio": (
                current_market / projected_market
                if current_market is not None
                and projected_market not in (None, 0)
                else None
            ),
            "own_projection_method": (
                "historical_hourly_completion_ratio"
                if not own_linear
                else "linear_elapsed_day_fraction"
            ),
            "peer_projection_method": (
                "historical_hourly_completion_ratio"
                if not peer_linear
                else "linear_elapsed_day_fraction"
            ),
            "market_projection_method": (
                "historical_hourly_completion_ratio"
                if not peer_linear
                else "linear_elapsed_day_fraction"
            ),
        }
    )
    return result


def _rate_trend(
    current: Any,
    baseline: Any,
    *,
    sample_sufficient: bool,
) -> dict[str, Any]:
    current_value = _n(current)
    baseline_value = _n(baseline)
    if current_value is None or baseline_value in (None, 0):
        return {"status": "unavailable", "ratio_vs_history": None}
    ratio = current_value / baseline_value
    if not sample_sufficient:
        status = "sample_insufficient"
    elif ratio >= 1.10:
        status = "currently_above_history"
    elif ratio <= 0.90:
        status = "currently_below_history"
    else:
        status = "currently_near_history"
    return {"status": status, "ratio_vs_history": ratio}


def _current_meituan_orders(
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> dict[str, Any]:
    query = getattr(repository, "_query", None)
    if not callable(query):
        return {"status": "unavailable"}
    try:
        rows = query(
            """
            SELECT COUNT(DISTINCT order_id) AS own_orders,
                   MAX(snapshot_time) AS latest_snapshot_time
            FROM jd01_booking_detail
            WHERE hotel_id=%s
              AND DATE(booking_time)=%s
              AND booking_time<=%s
              AND snapshot_time<=%s
              AND (
                    COALESCE(member_level, '') LIKE '%%美团%%'
                 OR COALESCE(operator_name, '') LIKE '%%美团%%'
                 OR COALESCE(guest_source, '') LIKE '%%美团%%'
                 OR COALESCE(remarks, '') LIKE '%%美团%%'
              )
            """,
            (hotel_id, target_date, as_of_datetime, as_of_datetime),
        )
    except Exception:
        return {"status": "unavailable"}
    if not rows:
        return {"status": "unavailable"}
    own_orders = _n(dict(rows[0]).get("own_orders"))
    if own_orders is None:
        return {"status": "unavailable"}
    return {
        "status": "available",
        "own_orders": own_orders,
        "latest_snapshot_time": dict(rows[0]).get("latest_snapshot_time"),
        "source": "jd01_booking_detail_meituan_gross_booking_proxy",
        "deduplication": "distinct_order_id",
        "cancelled_orders_subtracted": False,
    }


def _current_meituan_peer_context(
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> dict[str, Any]:
    query = getattr(repository, "_query", None)
    if not callable(query):
        return {"status": "unavailable"}
    try:
        rows = query(
            """
            SELECT metric_value, peer_average, competitor_rank, snapshot_time
            FROM meituan_ota_business_metrics
            WHERE hotel_id=%s
              AND DATE(business_date)=%s
              AND metric_code='PAY_ORDER_CNT'
              AND snapshot_time<=%s
            ORDER BY snapshot_time DESC, id DESC
            LIMIT 1
            """,
            (hotel_id, target_date, as_of_datetime),
        )
    except Exception:
        return {"status": "unavailable"}
    if not rows:
        return {"status": "unavailable"}
    row = dict(rows[0])
    rank, hotel_count = _parse_rank(row.get("competitor_rank"))
    peer_average = _n(row.get("peer_average"))
    if peer_average is None or hotel_count in (None, 0):
        return {"status": "unavailable"}
    return {
        "status": "available",
        "platform_reported_own_orders": _n(row.get("metric_value")),
        "peer_average_orders": peer_average,
        "peer_rank": rank,
        "peer_hotel_count": hotel_count,
        "snapshot_time": row.get("snapshot_time"),
        "source": "meituan_pay_order_comparison_metric",
    }


def build_meituan_market_proxy(
    repository: Any,
    *,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
    baseline_market_orders: Any,
    baseline_market_share: Any,
) -> dict[str, Any]:
    own = _current_meituan_orders(
        repository, hotel_id, target_date, as_of_datetime
    )
    peers = _current_meituan_peer_context(
        repository, hotel_id, target_date, as_of_datetime
    )
    if own.get("status") != "available" or peers.get("status") != "available":
        return {
            "status": "unavailable",
            "platform": "meituan",
            "own_order_proxy": own,
            "peer_context": peers,
        }
    own_orders = float(own["own_orders"])
    peer_average = float(peers["peer_average_orders"])
    hotel_count = int(peers["peer_hotel_count"])
    estimated_market_orders = int(math.floor(peer_average * hotel_count + 0.5))
    estimated_share = (
        own_orders / estimated_market_orders
        if estimated_market_orders > 0
        else None
    )
    elapsed = _elapsed_day_fraction(target_date, as_of_datetime)
    projection = _projection(
        estimated_market_orders,
        baseline_market_orders,
        elapsed,
    )
    baseline_share = _n(baseline_market_share)
    share_delta_pp = (
        (estimated_share - baseline_share) * 100
        if estimated_share is not None and baseline_share is not None
        else None
    )
    share_status = (
        "significant_weak"
        if share_delta_pp is not None and share_delta_pp <= -5
        else "weak"
        if share_delta_pp is not None and share_delta_pp <= -3
        else "strong"
        if share_delta_pp is not None and share_delta_pp >= 3
        else "normal"
        if share_delta_pp is not None
        else "unavailable"
    )
    platform_own = _n(peers.get("platform_reported_own_orders"))
    source_difference = (
        own_orders - platform_own if platform_own is not None else None
    )
    return {
        "status": "available",
        "platform": "meituan",
        "current_estimated_market_orders": estimated_market_orders,
        "current_estimated_market_share": estimated_share,
        "baseline_market_orders": _n(baseline_market_orders),
        "baseline_market_share": baseline_share,
        "share_delta_pp": share_delta_pp,
        "share_status": share_status,
        "own_orders_proxy": own_orders,
        "peer_average_orders": peer_average,
        "peer_rank": peers.get("peer_rank"),
        "peer_hotel_count": hotel_count,
        "platform_reported_own_orders": platform_own,
        "own_order_source_difference": source_difference,
        "market_projection": projection,
        "elapsed_day_fraction": elapsed,
        "estimation_method": (
            "peer_average_times_peer_hotel_count"
        ),
        "own_order_proxy_source": own.get("source"),
        "peer_context_source": peers.get("source"),
        "gross_orders_not_net_of_cancellation": True,
    }


def build_platform_pace_insights(
    dynamic: Mapping[str, Any],
    *,
    target_date: str,
    as_of_datetime: str,
    repository: Any | None = None,
    hotel_id: str | None = None,
) -> dict[str, Any]:
    elapsed = _elapsed_day_fraction(target_date, as_of_datetime)
    browse = dynamic.get("browse") or {}
    first = dynamic.get("first_conversion") or {}
    second = dynamic.get("second_conversion") or {}
    browse_completion_ratio = None
    if repository is not None and hotel_id:
        browse_completion_ratio = _historical_completion_ratios(
            repository,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_datetime=as_of_datetime,
            metric_code="INTENTION_UV",
        ).get("metric_value")
    browse_projection = _projection(
        browse.get("current"),
        browse.get("baseline_median"),
        elapsed,
        completion_ratio=browse_completion_ratio,
    )
    first_sample = bool(
        _n(first.get("exposure_users")) is not None
        and float(first.get("exposure_users")) >= 300
        and _n(first.get("browse_users")) is not None
        and float(first.get("browse_users")) >= 30
    )
    second_sample = bool(
        _n(second.get("browse_users")) is not None
        and float(second.get("browse_users")) >= 50
        and _n(second.get("pay_orders")) is not None
        and float(second.get("pay_orders")) >= 3
    )
    first_trend = _rate_trend(
        first.get("current"),
        first.get("baseline_median"),
        sample_sufficient=first_sample,
    )
    second_trend = _rate_trend(
        second.get("current"),
        second.get("baseline_median"),
        sample_sufficient=second_sample,
    )
    projected_browse = _n(browse_projection.get("projected_full_day"))
    second_baseline = _n(second.get("baseline_median"))
    current_pay_orders = _n(second.get("pay_orders"))
    required_pay_orders = (
        math.ceil(projected_browse * second_baseline)
        if projected_browse is not None and second_baseline is not None
        else None
    )
    additional_orders_needed = (
        max(required_pay_orders - int(current_pay_orders), 0)
        if required_pay_orders is not None and current_pay_orders is not None
        else None
    )
    return {
        "platform": "meituan",
        "elapsed_day_fraction": elapsed,
        "browse_projection": browse_projection,
        "first_conversion_trend": first_trend,
        "second_conversion_trend": {
            **second_trend,
            "required_pay_orders_at_projected_browse": required_pay_orders,
            "additional_orders_needed_to_match_history": additional_orders_needed,
        },
        "projection_method": (
            "linear_day_pace_reference"
            if browse_projection.get("linear_projection_only")
            else "hourly_completion_ratio_with_linear_fallback"
        ),
        "not_hourly_baseline": True,
        "automatic_action_eligible": False,
    }


def _room_references(package: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for source in package.get("room_type_transaction_references") or []:
        row = dict(source)
        room_id = str(row.get("room_type_id") or "")
        if room_id:
            result[room_id] = row
    return result


def _room_sales(dynamic: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    structure = dynamic.get("room_structure") or {}
    result: dict[str, dict[str, Any]] = {}
    for source in structure.get("room_type_results") or []:
        row = dict(source)
        room_id = str(row.get("room_type_id") or "")
        if room_id:
            result[room_id] = row
    return result


def _change_cap(status: str) -> float:
    return {
        "slow": 0.03,
        "significant_slow": 0.05,
        "severe_slow": 0.08,
        "fast": 0.03,
        "significant_fast": 0.05,
    }.get(status, 0.0)


def build_price_advisories(
    dynamic: Mapping[str, Any],
    package: Mapping[str, Any],
) -> list[dict[str, Any]]:
    from runtime.s5_product_net_revenue_patch import MEMBER_EXPECTED_FACTOR

    member_expected_factor = float(MEMBER_EXPECTED_FACTOR)
    refs = _room_references(package)
    sales = _room_sales(dynamic)
    decreases: list[dict[str, Any]] = []
    increases: list[dict[str, Any]] = []
    for source in dynamic.get("product_prices") or []:
        product = dict(source)
        if product.get("product_type") != "普通全天房":
            continue
        room_id = str(product.get("room_type_id") or "")
        room = sales.get(room_id) or {}
        reference = refs.get(room_id) or {}
        status = str(room.get("sales_status") or "normal")
        total_rooms = _n(room.get("total_rooms"))
        committed = _n(room.get("committed_sold"))
        raw_price = _n(product.get("raw_price") or product.get("current_price"))
        estimated_net = _n(product.get("estimated_activity_net_price"))
        commission_rate = _n(product.get("commission_rate"))
        combined_factor = _n(product.get("combined_activity_factor"))
        median = _n(reference.get("median"))
        p20 = _n(reference.get("p20"))
        p80 = _n(reference.get("p80"))
        if (
            not room_id
            or total_rooms is None
            or total_rooms < 2
            or raw_price in (None, 0)
            or estimated_net is None
            or commission_rate is None
            or combined_factor in (None, 0)
            or median in (None, 0)
        ):
            continue
        estimated_net *= member_expected_factor
        net_factor = (1.0 - commission_rate) * combined_factor * member_expected_factor
        if net_factor <= 0:
            continue
        cap = _change_cap(status)
        if status in _SLOW and estimated_net > median * 1.05:
            target_net = max(median, p20 or median)
            uncapped_change = target_net / net_factor / raw_price - 1.0
            change = max(uncapped_change, -cap)
            if change <= -0.01:
                decreases.append(
                    {
                        "action_type": "estimated_price_decrease_advisory",
                        "platform": "meituan",
                        "target_scope": "ota_product",
                        "ota_product_id": product.get("ota_product_id"),
                        "ota_product_name": product.get("ota_product_name"),
                        "room_type_id": room_id,
                        "room_type_name": product.get("room_type_name")
                        or room.get("room_type_name"),
                        "current_raw_price": raw_price,
                        "suggested_raw_price": round(raw_price * (1.0 + change)),
                        "suggested_change_pct": change,
                        "current_activity_net_estimate": estimated_net,
                        "pms_transaction_median_reference": median,
                        "pms_transaction_p20_reference": p20,
                        "pms_transaction_p80_reference": p80,
                        "room_sales_status": status,
                        "reason_codes": [
                            "room_sales_slow",
                            "activity_net_above_pms_room_transaction_reference",
                        ],
                        "confidence": "low_reference",
                        "advisory_only": True,
                        "requires_manual_confirmation": True,
                        "auto_execution_eligible": False,
                        "handoff_capability": "S5",
                        "observe_minutes": 90,
                    }
                )
        elif (
            status in _FAST
            and committed is not None
            and committed < total_rooms
            and p80 not in (None, 0)
            and estimated_net < float(p80) * 0.98
        ):
            target_net = float(p80) * 0.98
            uncapped_change = target_net / net_factor / raw_price - 1.0
            change = min(uncapped_change, cap)
            if change >= 0.01:
                increases.append(
                    {
                        "action_type": "estimated_price_increase_advisory",
                        "platform": "meituan",
                        "target_scope": "ota_product",
                        "ota_product_id": product.get("ota_product_id"),
                        "ota_product_name": product.get("ota_product_name"),
                        "room_type_id": room_id,
                        "room_type_name": product.get("room_type_name")
                        or room.get("room_type_name"),
                        "current_raw_price": raw_price,
                        "suggested_raw_price": round(raw_price * (1.0 + change)),
                        "suggested_change_pct": change,
                        "current_activity_net_estimate": estimated_net,
                        "pms_transaction_median_reference": median,
                        "pms_transaction_p20_reference": p20,
                        "pms_transaction_p80_reference": p80,
                        "room_sales_status": status,
                        "reason_codes": [
                            "room_sales_fast",
                            "activity_net_below_pms_room_p80_reference",
                        ],
                        "confidence": "low_reference",
                        "advisory_only": True,
                        "requires_manual_confirmation": True,
                        "auto_execution_eligible": False,
                        "handoff_capability": "S5",
                        "observe_minutes": 60,
                    }
                )
    decreases.sort(
        key=lambda item: (
            float(item.get("suggested_change_pct") or 0),
            str(item.get("ota_product_id") or ""),
        )
    )
    increases.sort(
        key=lambda item: (
            -float(item.get("suggested_change_pct") or 0),
            str(item.get("ota_product_id") or ""),
        )
    )
    return decreases[:2] + increases[:2]


def enhance_s16_dynamic_diagnosis(
    dynamic: Mapping[str, Any],
    repository: Any,
    *,
    baseline: Mapping[str, Any],
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> dict[str, Any]:
    result = dict(dynamic)
    package = baseline.get("baseline_package") or {}
    market_baseline = package.get("market_orders_baseline") or {}
    share_baseline = package.get("market_share_baseline") or {}
    market_proxy = build_meituan_market_proxy(
        repository,
        hotel_id=hotel_id,
        target_date=target_date,
        as_of_datetime=as_of_datetime,
        baseline_market_orders=market_baseline.get("median"),
        baseline_market_share=share_baseline.get("median"),
    )
    result["meituan_market_proxy"] = market_proxy
    if market_proxy.get("status") == "available":
        result["market"] = {
            **dict(result.get("market") or {}),
            "platform": "meituan",
            "estimated_market_orders": market_proxy.get(
                "current_estimated_market_orders"
            ),
            "baseline_median": market_proxy.get("baseline_market_orders"),
            "status": (
                market_proxy.get("market_projection") or {}
            ).get("status"),
            "comparison_allowed": False,
            "current_estimate_available": True,
            "projection_reference_only": True,
        }
        result["market_share"] = {
            **dict(result.get("market_share") or {}),
            "platform": "meituan",
            "current_estimated_market_share": market_proxy.get(
                "current_estimated_market_share"
            ),
            "baseline_median": market_proxy.get("baseline_market_share"),
            "delta_pp": market_proxy.get("share_delta_pp"),
            "status": market_proxy.get("share_status"),
            "comparison_allowed": True,
            "estimated": True,
        }
    pace = build_platform_pace_insights(
        result,
        target_date=target_date,
        as_of_datetime=as_of_datetime,
        repository=repository,
        hotel_id=hotel_id,
    )
    result["meituan_pace_insights"] = pace
    result["estimated_price_advisories"] = build_price_advisories(
        result, package
    )
    result["auto_execution_eligible"] = False
    limitations = list(result.get("data_limitations") or [])
    additions = [
        "美团大盘和份额使用本店 PMS 订单明细中的美团订单代理值，结合美团同行平均订单估算，并非平台直接提供的市场总量。",
        "美团浏览和大盘的收盘值优先按近 60 天可比历史的同小时至日终完成率估算；对应历史不可用时才回退日内线性节奏。一转和二转只比较当前累计率与历史完整日中位，均仅作趋势参考。",
        "预估涨降价仅依据房型销售进度、扣佣后活动连乘及预期会员折扣后的预计收入和 PMS 房型成交参考，不等于同一商品历史价格结论。",
    ]
    for item in additions:
        if item not in limitations:
            limitations.append(item)
    result["data_limitations"] = limitations
    return result


def _build_wrapper(previous: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def build(
        repository: Any,
        *,
        baseline: Mapping[str, Any],
        progress_report: Mapping[str, Any],
        hotel_id: str,
        target_date: str,
        as_of_datetime: str,
    ) -> dict[str, Any]:
        dynamic = previous(
            repository,
            baseline=baseline,
            progress_report=progress_report,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_datetime=as_of_datetime,
        )
        return enhance_s16_dynamic_diagnosis(
            dynamic,
            repository,
            baseline=baseline,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_datetime=as_of_datetime,
        )

    build._S16_MEITUAN_PROJECTION_ADVISORY_V1 = True  # type: ignore[attr-defined]
    return build


def _num(value: Any, digits: int = 1) -> str:
    number = _n(value)
    if number is None:
        return "—"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _pct(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.1f}%"


def _pp(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"{number:+.1f}个百分点"


def _money(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"¥{number:,.0f}"


def _projection_text(status: Any) -> str:
    return {
        "likely_above_history": "预计收盘有望跑赢历史",
        "near_history": "预计收盘大致接近历史",
        "likely_below_history": "预计收盘较难跑赢历史",
    }.get(str(status or ""), "当前时点还不适合做收盘趋势估算")


def _rate_text(status: Any) -> str:
    return {
        "currently_above_history": "当前累计高于历史中位，若后续流量结构稳定，有望保持领先",
        "currently_near_history": "当前累计与历史中位接近",
        "currently_below_history": "当前累计低于历史中位，后续需要改善",
        "sample_insufficient": "当前样本仍少，只作方向提示",
    }.get(str(status or ""), "当前暂缺可解释趋势")


def _message_wrapper(previous: Callable[[Mapping[str, Any]], str]) -> Callable[[Mapping[str, Any]], str]:
    def render(report: Mapping[str, Any]) -> str:
        text = previous(report)
        dynamic = report.get("dynamic_diagnosis") or {}
        proxy = dynamic.get("meituan_market_proxy") or {}
        pace = dynamic.get("meituan_pace_insights") or {}
        browse = dynamic.get("browse") or {}
        first = dynamic.get("first_conversion") or {}
        second = dynamic.get("second_conversion") or {}
        market_projection = proxy.get("market_projection") or {}
        browse_projection = pace.get("browse_projection") or {}
        first_trend = pace.get("first_conversion_trend") or {}
        second_trend = pace.get("second_conversion_trend") or {}
        replacement_lines: list[str] = []
        if proxy.get("status") == "available":
            market_completion = _pct(
                market_projection.get("market_hourly_completion_ratio")
            )
            own_completion = _pct(
                market_projection.get("own_hourly_completion_ratio")
            )
            peer_completion = _pct(
                market_projection.get("peer_hourly_completion_ratio")
            )
            projection_method = market_projection.get("market_projection_method")
            if projection_method == "historical_hourly_completion_ratio":
                completion_line = (
                    f"当前时点历史完成率约 {market_completion}"
                    f"（本店 {own_completion}、同行 {peer_completion}）"
                )
            elif projection_method == "hybrid_hourly_completion_ratio":
                completion_line = "本店或同行缺少部分历史完成率，结合日内节奏推算"
            else:
                completion_line = "当前缺少可比历史完成率，按日内节奏推算"
            replacement_lines.extend(
                [
                    "- 美团大盘（估算）：当前约 "
                    f"{_num(proxy.get('current_estimated_market_orders'))}单；"
                    f"本店今日美团订单代理 {_num(proxy.get('own_orders') if proxy.get('own_orders') is not None else proxy.get('own_orders_proxy'))}单，"
                    f"同行平均 {_num(proxy.get('peer_average_orders'))}单/店，"
                    f"范围 {proxy.get('peer_hotel_count') or '—'}家。"
                    f"预计收盘约 "
                    f"{_num(market_projection.get('projected_full_day'))}单，"
                    f"历史同类日中位 {_num(proxy.get('baseline_market_orders'))}单；"
                    f"{completion_line}；"
                    f"{_projection_text(market_projection.get('status'))}。",
                    "- 美团估算份额：当前约 "
                    f"{_pct(proxy.get('current_estimated_market_share'))}，"
                    f"历史中位 {_pct(proxy.get('baseline_market_share'))}，"
                    f"相差 {_pp(proxy.get('share_delta_pp'))}。",
                ]
            )
        else:
            replacement_lines.extend(
                [
                    "- 美团大盘（估算）：当前缺少可同时对齐的本店美团订单代理值或同行订单范围，暂不估算。",
                    "- 美团估算份额：当前缺少估算分母，暂不判断。",
                ]
            )
        replacement_lines.extend(
            [
                "- 美团浏览：当前 "
                f"{_num(browse.get('current'))}；预计收盘 "
                f"{_num(browse_projection.get('projected_full_day'))}，"
                f"历史中位 {_num(browse.get('baseline_median'))}；"
                f"{_projection_text(browse_projection.get('status'))}。",
                "- 美团一转：当前累计 "
                f"{_pct(first.get('current'))}，历史中位 "
                f"{_pct(first.get('baseline_median'))}；"
                f"{_rate_text(first_trend.get('status'))}。",
                "- 美团二转：当前累计 "
                f"{_pct(second.get('current'))}，历史中位 "
                f"{_pct(second.get('baseline_median'))}；"
                f"{_rate_text(second_trend.get('status'))}。"
                f"按当前预计浏览量，若要达到历史中位，预计还需约 "
                f"{_num(second_trend.get('additional_orders_needed_to_match_history'))}单。",
                "- 趋势口径：以上均为美团；浏览和大盘优先使用近 60 天可比历史的同小时至日终完成率，"
                "缺失项回退日内线性节奏；一转、二转是当前累计率方向参考，不冒充小时基准。",
            ]
        )
        lines = text.splitlines()
        result_lines: list[str] = []
        inserted = False
        skip_prefixes = (
            "- 大盘：",
            "- 份额：",
            "- 浏览：",
            "- 一转：",
            "- 二转：",
        )
        for line in lines:
            if line.startswith(skip_prefixes):
                if not inserted:
                    result_lines.extend(replacement_lines)
                    inserted = True
                continue
            result_lines.append(line)
        if not inserted:
            marker = "五、建议动作"
            try:
                index = result_lines.index(marker)
            except ValueError:
                index = len(result_lines)
            result_lines[index:index] = replacement_lines + [""]

        advisories = dynamic.get("estimated_price_advisories") or []
        advisory_lines = ["", "预估调价建议（美团，只读）："]
        if advisories:
            for item in advisories:
                direction = (
                    "试探降价"
                    if item.get("action_type")
                    == "estimated_price_decrease_advisory"
                    else "试探涨价"
                )
                current_raw_price = _n(item.get("current_raw_price"))
                suggested_raw_price = _n(item.get("suggested_raw_price"))
                current_net_estimate = _n(item.get("current_activity_net_estimate"))
                suggested_net_estimate = (
                    current_net_estimate * suggested_raw_price / current_raw_price
                    if current_net_estimate is not None
                    and current_raw_price not in (None, 0)
                    and suggested_raw_price is not None
                    else None
                )
                advisory_lines.append(
                    f"- {direction}｜"
                    f"{item.get('ota_product_name') or item.get('ota_product_id') or '未命名商品'}："
                    f"预估到手价 {_money(current_net_estimate)} → "
                    f"建议约 {_money(suggested_net_estimate)} "
                    f"({_pct(item.get('suggested_change_pct'))})；"
                    f"PMS 房型成交中位参考 "
                    f"{_money(item.get('pms_transaction_median_reference'))}；"
                    f"观察 {item.get('observe_minutes') or 0} 分钟后再判断。"
                )
            advisory_lines.append(
                "- 以上是低置信试探建议，不代表商品历史价格结论；"
                "不自动执行，交由 S5/S6 按具体商品重新核验。"
            )
        else:
            advisory_lines.append(
                "- 当前没有同时满足房型进度和活动及会员预期折扣后收入参考条件的涨降价建议。"
            )
        try:
            action_index = result_lines.index("五、建议动作") + 1
        except ValueError:
            action_index = len(result_lines)
        result_lines[action_index:action_index] = advisory_lines
        return "\n".join(result_lines)

    render._S16_MEITUAN_PROJECTION_ADVISORY_V1 = True  # type: ignore[attr-defined]
    return render


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import (
        s15_s16_complete_output_patch,
        s15_s16_responsibility_patch,
        s16_dynamic_diagnosis,
    )
    from runtime.sales_progress import presentation

    previous_build = s16_dynamic_diagnosis.build_s16_dynamic_diagnosis
    if not getattr(previous_build, "_S16_MEITUAN_PROJECTION_ADVISORY_V1", False):
        wrapped_build = _build_wrapper(previous_build)
        s16_dynamic_diagnosis.build_s16_dynamic_diagnosis = wrapped_build
        s15_s16_responsibility_patch.build_s16_dynamic_diagnosis = wrapped_build

    previous_message = s15_s16_responsibility_patch._dynamic_message
    if not getattr(previous_message, "_S16_MEITUAN_PROJECTION_ADVISORY_V1", False):
        wrapped_message = _message_wrapper(previous_message)
        s15_s16_responsibility_patch._dynamic_message = wrapped_message
        presentation.build_s16_user_message = wrapped_message
        s15_s16_complete_output_patch.s16_message = wrapped_message

from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

SALES_SLOW_PP = -8.0
SALES_SIGNIFICANT_SLOW_PP = -15.0
SALES_SEVERE_SLOW_PP = -25.0
SALES_FAST_PP = 8.0
SALES_SIGNIFICANT_FAST_PP = 15.0
MARKET_COLD_RATIO = 0.90
MARKET_HOT_RATIO = 1.10
SHARE_WEAK_PP = -3.0
SHARE_SIGNIFICANT_WEAK_PP = -5.0
BROWSE_WEAK_RATIO = 0.80
BROWSE_SOFT_RATIO = 0.90
PRICE_HIGH_RATIO = 1.08
PRICE_LOW_RATIO = 0.95
PRICE_P20_FLOOR_FACTOR = 1.02
PRICE_P80_CEILING_FACTOR = 0.98
AD_OPEN_SALES_SLOW_PP = -10.0


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _day(value: Any) -> str:
    return str(value or "")[:10]


def _safe_ratio(numerator: Any, denominator: Any) -> float | None:
    left = _n(numerator)
    right = _n(denominator)
    if left is None or right in (None, 0):
        return None
    return left / right


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


def _status_from_ratio(
    value: float | None,
    *,
    weak: float = 0.80,
    soft: float = 0.90,
) -> str:
    if value is None:
        return "unavailable"
    if value < weak:
        return "weak"
    if value < soft:
        return "soft"
    if value <= 1.10:
        return "normal"
    return "strong"


def _sales_status(delta_pp: Any) -> str:
    value = _n(delta_pp)
    if value is None:
        return "unavailable"
    if value <= SALES_SEVERE_SLOW_PP:
        return "severe_slow"
    if value <= SALES_SIGNIFICANT_SLOW_PP:
        return "significant_slow"
    if value <= SALES_SLOW_PP:
        return "slow"
    if value < SALES_FAST_PP:
        return "normal"
    if value < SALES_SIGNIFICANT_FAST_PP:
        return "fast"
    return "significant_fast"


def _latest_daily(
    rows: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if not rows:
        return None
    return max(
        rows,
        key=lambda row: (
            str(row.get("business_date") or ""),
            str(row.get("snapshot_time") or ""),
        ),
    )


def _group_metric_rows(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Mapping[str, Any]]]:
    grouped: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        day = _day(row.get("business_date"))
        code = str(row.get("metric_code") or "")
        if not day or not code:
            continue
        current = grouped[day].get(code)
        if current is None or str(row.get("snapshot_time") or "") > str(
            current.get("snapshot_time") or ""
        ):
            grouped[day][code] = row
    return grouped


def _row_for(
    codes: Mapping[str, Mapping[str, Any]],
    *names: str,
) -> Mapping[str, Any] | None:
    for name in names:
        row = codes.get(name)
        if row:
            return row
    return None


def _market_point(
    codes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    order_row = _row_for(codes, "FLOW_PAY_ORDER_CNT", "PAY_ORDER_CNT")
    if not order_row:
        return None
    own_orders = _n(order_row.get("metric_value"))
    peer_average = _n(order_row.get("peer_average"))
    rank, hotel_count = _parse_rank(order_row.get("competitor_rank"))
    if hotel_count is None:
        for row in codes.values():
            _, candidate_count = _parse_rank(row.get("competitor_rank"))
            if candidate_count:
                hotel_count = candidate_count
                break
    if (
        own_orders is None
        or peer_average is None
        or hotel_count is None
        or hotel_count <= 0
    ):
        return None
    estimated_market_orders = int(peer_average * hotel_count + 0.5)
    return {
        "own_orders": own_orders,
        "peer_average_orders": peer_average,
        "peer_rank": rank,
        "peer_hotel_count": hotel_count,
        "estimated_market_orders": estimated_market_orders,
        "estimated_market_share": _safe_ratio(
            own_orders,
            estimated_market_orders,
        ),
        "estimation_method": "peer_average_times_peer_hotel_count",
        "peer_average_includes_self": True,
        "estimated": True,
    }


def _summarize(values: Sequence[float]) -> dict[str, Any]:
    from runtime.sales_progress.core import summarize

    return dict(summarize(list(values)))


def _metric_current(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    from runtime.sales_progress.metrics import build_metric_baselines
    from runtime.sales_progress.repository import MEITUAN_METRICS

    result = build_metric_baselines(rows, MEITUAN_METRICS, "meituan")
    daily = list(result.get("daily_points") or [])
    return dict(_latest_daily(daily) or {})


def _rolling_peer_second(payload: Mapping[str, Any]) -> dict[str, Any]:
    rows = list(
        ((payload.get("rolling_30d_context") or {}).get("meituan")) or []
    )
    row = (
        max(rows, key=lambda item: str(item.get("snapshot_time") or ""))
        if rows
        else None
    )
    if not row:
        return {"status": "unavailable"}
    own = _n(row.get("browse_to_pay_rate_pct"))
    peer = _n(row.get("peer_browse_to_pay_rate_pct"))
    if own is not None and abs(own) > 1:
        own /= 100.0
    if peer is not None and abs(peer) > 1:
        peer /= 100.0
    return {
        "status": "available" if peer is not None else "unavailable",
        "period_start_date": _day(row.get("period_start_date")),
        "period_end_date": _day(row.get("period_end_date")),
        "own_second_conversion": own,
        "peer_second_conversion": peer,
        "conversion_index_vs_market": _safe_ratio(own, peer),
        "grain": "rolling_30d_single_window",
        "historical_daily_baseline": False,
    }


def _current_room_prices(
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> list[dict[str, Any]]:
    query = getattr(repository, "_query", None)
    if not callable(query):
        return []
    try:
        rows = query(
            """
            SELECT g.hotel_id, g.business_date, g.snapshot_time,
                   g.ota_product_id, g.ota_product_name, g.rate_plan_name,
                   g.is_super_deal, g.ota_sale_price,
                   g.room_type_id, g.room_type_name,
                   m.mapping_status, m.is_active AS mapping_active,
                   m.is_hour_room, m.price_editable_flag
            FROM meituan_ota_goods_price_mapping g
            INNER JOIN hotel_room_type_mapping m
              ON m.hotel_id=g.hotel_id
             AND m.source_product_id=g.ota_product_id
             AND m.source_platform IN ('美团','meituan')
             AND m.mapping_status='AUTO'
             AND m.is_active=1
            WHERE g.hotel_id=%s AND g.business_date=%s
              AND g.snapshot_time<=%s
              AND g.room_type_id IS NOT NULL AND g.room_type_id<>''
            ORDER BY g.snapshot_time DESC, g.ota_sale_price ASC
            """,
            (hotel_id, target_date, as_of_datetime),
        )
    except Exception:
        return []
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in rows:
        row = dict(source)
        room_id = str(row.get("room_type_id") or "")
        product_id = str(row.get("ota_product_id") or "")
        if (
            not room_id
            or not product_id
            or (room_id, product_id) in seen
        ):
            continue
        seen.add((room_id, product_id))
        result.append(row)
    return result


def _ad_context(
    repository: Any,
    hotel_id: str,
    as_of_datetime: str,
) -> dict[str, Any]:
    query = getattr(repository, "_query", None)
    if not callable(query):
        return {"status": "unavailable"}
    try:
        rows = query(
            """
            SELECT hotel_id, period_start_date, period_end_date, snapshot_time,
                   promotion_status, plan_id, plan_name, promotion_name,
                   exposure_count, click_count, booking_order_count,
                   booking_order_amount, spend_amount
            FROM meituan_ota_promotion_performance_30d
            WHERE hotel_id=%s AND snapshot_time<=%s
            ORDER BY snapshot_time DESC
            LIMIT 1
            """,
            (hotel_id, as_of_datetime),
        )
    except Exception:
        return {"status": "unavailable"}
    if not rows:
        return {"status": "unavailable"}
    row = dict(rows[0])
    status = str(row.get("promotion_status") or "").upper()
    return {
        "status": "available",
        "promotion_status": status,
        "ad_running": status
        in {"RUNNING", "OPEN", "ENABLED", "ACTIVE"},
        "period_start_date": _day(row.get("period_start_date")),
        "period_end_date": _day(row.get("period_end_date")),
        "spend_amount": _n(row.get("spend_amount")),
        "booking_order_count": _n(row.get("booking_order_count")),
        "booking_order_amount": _n(row.get("booking_order_amount")),
    }


def _price_analysis(
    payload: Mapping[str, Any],
    current_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_room: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in current_rows:
        if str(row.get("is_hour_room") or "").strip().lower() in {
            "1",
            "true",
            "yes",
        }:
            continue
        room_id = str(row.get("room_type_id") or "")
        price = _n(row.get("ota_sale_price"))
        if room_id and price is not None and price > 0:
            by_room[room_id].append(row)
    results: list[dict[str, Any]] = []
    rooms = payload.get("room_types") or {}
    for room_id, rows in sorted(by_room.items()):
        current = min(
            rows,
            key=lambda row: float(row.get("ota_sale_price") or 0),
        )
        price = float(current.get("ota_sale_price") or 0)
        room = rooms.get(room_id) or {}
        baseline = room.get("price_baseline") or {}
        avg = _n(baseline.get("weighted_avg"))
        median_value = _n(baseline.get("median"))
        p20 = _n(baseline.get("p20"))
        p80 = _n(baseline.get("p80"))
        ratio_avg = _safe_ratio(price, avg)
        status = "unavailable"
        if ratio_avg is not None:
            status = (
                "high"
                if ratio_avg >= PRICE_HIGH_RATIO
                else "low"
                if ratio_avg <= PRICE_LOW_RATIO
                else "normal"
            )
        results.append(
            {
                "room_type_id": room_id,
                "room_type_name": room.get("room_type_name")
                or current.get("room_type_name")
                or room_id,
                "ota_product_id": current.get("ota_product_id"),
                "ota_product_name": current.get("ota_product_name"),
                "current_price": price,
                "baseline_avg": avg,
                "baseline_median": median_value,
                "baseline_p20": p20,
                "baseline_p80": p80,
                "price_ratio_vs_avg": ratio_avg,
                "price_status": status,
                "near_p20_floor": bool(
                    p20 is not None
                    and price <= p20 * PRICE_P20_FLOOR_FACTOR
                ),
                "near_p80_ceiling": bool(
                    p80 is not None
                    and price >= p80 * PRICE_P80_CEILING_FACTOR
                ),
                "mapping_status": current.get("mapping_status"),
                "mapping_active": bool(current.get("mapping_active")),
            }
        )
    return {
        "status": "available" if results else "unavailable",
        "grain": "current_exact_meituan_product_to_pms_room_type",
        "room_results": results,
        "high_room_type_ids": [
            row["room_type_id"]
            for row in results
            if row["price_status"] == "high"
            and not row["near_p20_floor"]
        ],
        "low_room_type_ids": [
            row["room_type_id"]
            for row in results
            if row["price_status"] == "low"
        ],
    }


def _metric_axis(
    current: Any,
    baseline: Mapping[str, Any],
    *,
    sample_sufficient: bool = True,
) -> dict[str, Any]:
    current_value = _n(current)
    median_value = _n(baseline.get("median"))
    ratio = _safe_ratio(current_value, median_value)
    status = _status_from_ratio(ratio)
    if not sample_sufficient and current_value is not None:
        status = "sample_insufficient"
    return {
        "current": current_value,
        "baseline_median": median_value,
        "baseline_p25": _n(baseline.get("p25")),
        "baseline_p80": _n(baseline.get("p80")),
        "ratio": ratio,
        "status": status,
        "sample_count": int(baseline.get("sample_count") or 0),
        "sample_sufficient": sample_sufficient,
        "grain": "daily",
        "hourly_baseline_available": False,
    }

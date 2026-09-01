from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .core import as_float, date_part, summarize, weighted_quantile


def build_price_baselines(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[tuple[float, float, float | None]]] = defaultdict(list)
    for row in rows:
        room_id = row.get("room_type_id")
        price = as_float(row.get("room_daily_price"))
        nights = as_float(row.get("room_nights"))
        fee = as_float(row.get("room_fee"))
        if (
            room_id
            and price is not None
            and price > 0
            and nights is not None
            and nights > 0
        ):
            grouped[str(room_id)].append((price, nights, fee))
    result: dict[str, Any] = {}
    for room_id, values in grouped.items():
        total_weight = sum(weight for _, weight, _ in values)
        result[room_id] = {
            "weighted_avg": sum(
                price * weight for price, weight, _ in values
            )
            / total_weight,
            "p20": weighted_quantile(
                ((price, weight) for price, weight, _ in values), 0.20
            ),
            "median": weighted_quantile(
                ((price, weight) for price, weight, _ in values), 0.50
            ),
            "p80": weighted_quantile(
                ((price, weight) for price, weight, _ in values), 0.80
            ),
            "min": min(price for price, _, _ in values),
            "max": max(price for price, _, _ in values),
            "weighted_room_nights": total_weight,
            "source_row_count": len(values),
            "room_fee_sum": sum(
                fee for _, _, fee in values if fee is not None
            ),
        }
    return result


def build_metric_baselines(
    rows: Sequence[Mapping[str, Any]],
    registry: Mapping[str, tuple[str, set[Any]]],
    platform: str,
) -> dict[str, Any]:
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    conflicts: list[dict[str, Any]] = []
    for row in rows:
        code = str(row.get("metric_code") or "")
        binding = registry.get(code)
        if not binding:
            continue
        canonical, units = binding
        unit = row.get("metric_unit") or None
        if unit not in units:
            conflicts.append(
                {
                    "metric_code": code,
                    "reason": "unit_mismatch",
                    "unit": unit,
                }
            )
            continue
        day = date_part(row.get("business_date"))
        value = as_float(row.get("metric_value"))
        if day and value is not None:
            by_date[day][canonical] = value
    daily: list[dict[str, Any]] = []
    for day, metrics in sorted(by_date.items()):
        item: dict[str, Any] = {"business_date": day, **metrics}
        if platform == "meituan":
            exposure = metrics.get("exposure_uv")
            browse = metrics.get("browse_uv")
            orders = metrics.get("paid_orders")
            item["first_conversion"] = (
                browse / exposure
                if exposure not in (None, 0) and browse is not None
                else None
            )
            item["second_conversion"] = (
                orders / browse
                if browse not in (None, 0) and orders is not None
                else None
            )
            if (
                "browse_uv_duplicate" in metrics
                and browse is not None
                and metrics["browse_uv_duplicate"] != browse
            ):
                conflicts.append(
                    {
                        "business_date": day,
                        "metric_code": "INTENTION_UV",
                        "reason": "duplicate_metric_conflict",
                    }
                )
            if (
                "paid_orders_duplicate" in metrics
                and orders is not None
                and metrics["paid_orders_duplicate"] != orders
            ):
                conflicts.append(
                    {
                        "business_date": day,
                        "metric_code": "PAY_ORDER_CNT",
                        "reason": "duplicate_metric_conflict",
                    }
                )
        else:
            exposure = metrics.get("list_exposure_count")
            detail = metrics.get("detail_visitor_count")
            orders = metrics.get("submitted_orders")
            item["list_to_detail_ratio"] = (
                detail / exposure
                if exposure not in (None, 0) and detail is not None
                else None
            )
            item["detail_to_submit_ratio"] = (
                orders / detail
                if detail not in (None, 0) and orders is not None
                else None
            )
        daily.append(item)
    keys = sorted(
        {key for row in daily for key in row if key != "business_date"}
    )
    return {
        "platform": platform,
        "daily_points": daily,
        "baselines": {
            key: summarize(
                [
                    row[key]
                    for row in daily
                    if as_float(row.get(key)) is not None
                ]
            )
            for key in keys
        },
        "conflicts": conflicts,
    }


def build_gross_booking_context(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    points = []
    for row in rows:
        day = date_part(row.get("stay_date"))
        hour = as_float(row.get("booking_hour"))
        if day and hour is not None:
            points.append(
                {
                    "stay_date": day,
                    "booking_hour": int(hour),
                    "gross_created_rooms": as_float(
                        row.get("gross_created_rooms")
                    ),
                    "booking_rows": as_float(row.get("booking_rows")),
                }
            )
    return {
        "status": "available" if points else "unavailable",
        "usage": "diagnostic_only_not_committed_sold",
        "points": points,
        "cancellation_timeline_validated": False,
    }


def build_hour_distribution_context(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    points = []
    total_rate = 0.0
    for row in rows:
        label = str(row.get("bucket_label") or "").strip()
        rate = as_float(row.get("rate_pct"))
        value = as_float(row.get("metric_value"))
        if not label or (rate is None and value is None):
            continue
        points.append(
            {
                "bucket_label": label,
                "rate_pct": rate,
                "metric_value": value,
            }
        )
        if rate is not None:
            total_rate += rate
    return {
        "status": "available" if points else "unavailable",
        "usage": "platform_distribution_context_only",
        "points": points,
        "rate_total": total_rate if points else None,
        "rate_total_valid": bool(points) and 99.0 <= total_rate <= 101.0,
        "not_valid_for": [
            "committed_sold",
            "stay_date_hourly_progress",
        ],
    }


def build_peer_demand_context(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    points = [
        {
            "metric_code": row.get("metric_code"),
            "metric_name": row.get("metric_name"),
            "metric_unit": row.get("metric_unit"),
            "period_start_date": date_part(row.get("period_start_date")),
            "period_end_date": date_part(row.get("period_end_date")),
            "hotel_value": as_float(row.get("hotel_value")),
            "competitor_avg": as_float(row.get("competitor_avg")),
            "competitor_rank": as_float(row.get("competitor_rank")),
            "competition_circle_hotel_count": as_float(
                row.get("competition_circle_hotel_count")
            ),
        }
        for row in rows
    ]
    return {
        "status": "available" if points else "unavailable",
        "usage": "peer_demand_proxy_only",
        "points": points,
        "market_total_inference_allowed": False,
    }

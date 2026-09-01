from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

from .core import (
    FORMULA_VERSION,
    S15_POLICY_VERSION,
    aggregate_hotel,
    as_float,
    calculate_room_fact,
    date_part,
    expected_room_type_set,
    maturity,
    select_complete_batch,
    stable_hash,
    summarize,
)
from .metrics import (
    build_gross_booking_context,
    build_hour_distribution_context,
    build_metric_baselines,
    build_peer_demand_context,
    build_price_baselines,
)
from .repository import CTRIP_METRICS, MEITUAN_METRICS, RepositoryError


def _date_window(target_date: str, days: int = 365) -> tuple[str, str]:
    target = dt.date.fromisoformat(target_date)
    return (
        (target - dt.timedelta(days=days)).isoformat(),
        (target - dt.timedelta(days=1)).isoformat(),
    )


def _select_dates(
    target_date: str,
    available_dates: Sequence[str],
    date_contexts: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[str, list[str]]:
    target = dt.date.fromisoformat(target_date)
    unique = sorted(
        {
            dt.date.fromisoformat(item)
            for item in available_dates
            if item and item < target_date
        },
        reverse=True,
    )
    contexts = date_contexts or {}
    target_context = contexts.get(target_date) or {}

    def context(day: dt.date) -> Mapping[str, Any]:
        return contexts.get(day.isoformat()) or {}

    def week_type(day: dt.date) -> bool:
        value = context(day)
        if value.get("is_adjusted_workday"):
            return False
        if value.get("is_workday") is not None:
            return not bool(value.get("is_workday"))
        return bool(value.get("is_weekend", day.weekday() >= 5))

    def same_holiday(
        left: Mapping[str, Any], right: Mapping[str, Any]
    ) -> bool:
        left_flag = bool(left.get("is_holiday"))
        right_flag = bool(right.get("is_holiday"))
        if left_flag != right_flag:
            return False
        if not left_flag:
            return True
        left_group = str(
            left.get("holiday_group") or left.get("holiday_name") or ""
        )
        right_group = str(
            right.get("holiday_group") or right.get("holiday_name") or ""
        )
        return bool(left_group) and left_group == right_group

    if target_context and target_context.get("season_tag"):
        window_start = target_context.get("previous_year_window_start")
        window_end = target_context.get("previous_year_window_end")
        if window_start and window_end:
            p0 = [
                day
                for day in unique
                if str(window_start) <= day.isoformat() <= str(window_end)
                and context(day).get("season_tag")
                == target_context.get("season_tag")
                and same_holiday(context(day), target_context)
                and day.weekday() == target.weekday()
            ]
            if len(p0) >= 3:
                return "P0_previous_year_approved_window", [
                    item.isoformat() for item in p0
                ]
        p1 = [
            day
            for day in unique
            if context(day).get("season_tag") == target_context.get("season_tag")
            and same_holiday(context(day), target_context)
            and day.weekday() == target.weekday()
        ]
        if len(p1) >= 6:
            return "P1_season_holiday_weekday", [
                item.isoformat() for item in p1
            ]
        target_weekend = week_type(target)
        p2 = [
            day
            for day in unique
            if context(day).get("season_tag") == target_context.get("season_tag")
            and same_holiday(context(day), target_context)
            and week_type(day) == target_weekend
        ]
        if len(p2) >= 8:
            return "P2_season_holiday_week_type", [
                item.isoformat() for item in p2
            ]
        p3 = [
            day
            for day in unique
            if context(day).get("season_tag") == target_context.get("season_tag")
            and same_holiday(context(day), target_context)
        ]
        if len(p3) >= 10:
            return "P3_season_holiday", [item.isoformat() for item in p3]

    same_weekday = [
        item for item in unique if item.weekday() == target.weekday()
    ]
    if len(same_weekday) >= 6:
        return "P4_same_weekday", [item.isoformat() for item in same_weekday]
    target_weekend = target.weekday() >= 5
    same_week_type = [
        item
        for item in unique
        if (item.weekday() >= 5) == target_weekend
    ]
    if len(same_week_type) >= 4:
        return "P5_same_week_type", [
            item.isoformat() for item in same_week_type
        ]
    return "P5_cold_start", [item.isoformat() for item in unique[:8]]


def _group_latest(
    rows: Sequence[Mapping[str, Any]], keys: tuple[str, ...]
) -> dict[tuple[str, ...], dict[str, Any]]:
    result: dict[tuple[str, ...], dict[str, Any]] = {}
    for source in rows:
        row = dict(source)
        key = tuple(str(row.get(name) or "") for name in keys)
        current = result.get(key)
        if current is None or str(row.get("snapshot_time") or "") > str(
            current.get("snapshot_time") or ""
        ):
            result[key] = row
    return result


def _hourly_facts(
    rows: Sequence[Mapping[str, Any]], selected_dates: Sequence[str]
) -> tuple[dict[tuple[str, int], list[dict[str, Any]]], tuple[str, ...]]:
    expected = expected_room_type_set(rows)
    result: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for day in selected_dates:
        day_rows = [
            row for row in rows if date_part(row.get("stay_date")) == day
        ]
        for hour in range(24):
            selected = select_complete_batch(
                day_rows,
                expected_room_types=expected,
                requested_hour=hour,
            )
            if selected.status in {"ok", "partial"} and selected.rows:
                result[(day, hour)] = [
                    calculate_room_fact(row) for row in selected.rows
                ]
    return result, expected


def _sales_lines(
    selected_dates: Sequence[str],
    hourly: Mapping[tuple[str, int], Sequence[Mapping[str, Any]]],
    room_daily_rows: Sequence[Mapping[str, Any]],
    hotel_daily_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    room_daily = _group_latest(
        room_daily_rows, ("business_date", "room_type_id")
    )
    hotel_daily = _group_latest(
        hotel_daily_rows,
        (
            "business_date",
            "source_platform",
            "dimension_type",
            "dimension_name",
        ),
    )
    room_ids = sorted(
        {
            str(row.get("room_type_id"))
            for rows in hourly.values()
            for row in rows
            if row.get("room_type_id")
        }
    )
    room_results: dict[str, Any] = {}
    for room_id in room_ids:
        points = []
        for hour in range(24):
            capacities: list[float] = []
            completions: list[float] = []
            for day in selected_dates:
                row = next(
                    (
                        item
                        for item in hourly.get((day, hour), [])
                        if item.get("room_type_id") == room_id
                    ),
                    None,
                )
                if not row:
                    continue
                if as_float(row.get("capacity_progress")) is not None:
                    capacities.append(float(row["capacity_progress"]))
                final = room_daily.get((day, room_id))
                final_nights = (
                    as_float(final.get("room_nights")) if final else None
                )
                if final_nights not in (None, 0) and as_float(
                    row.get("committed_sold")
                ) is not None:
                    completions.append(
                        float(row["committed_sold"]) / final_nights
                    )
            capacity = summarize(capacities)
            completion = summarize(completions)
            count = max(
                capacity["sample_count"], completion["sample_count"]
            )
            coverage = count / max(len(selected_dates), 1)
            points.append(
                {
                    "hour": hour,
                    "capacity": capacity,
                    "target_completion": completion,
                    "coverage": coverage,
                    "maturity": maturity(count, coverage),
                }
            )
        finals = [
            as_float(room_daily.get((day, room_id), {}).get("room_nights"))
            for day in selected_dates
        ]
        revenues = [
            as_float(room_daily.get((day, room_id), {}).get("room_revenue"))
            for day in selected_dates
        ]
        room_results[room_id] = {
            "room_type_id": room_id,
            "hourly_points": points,
            "historical_target_room_nights": summarize(
                [value for value in finals if value is not None]
            ),
            "historical_revenue_target": summarize(
                [value for value in revenues if value is not None]
            ),
        }
    hotel_points = []
    for hour in range(24):
        capacities: list[float] = []
        completions: list[float] = []
        for day in selected_dates:
            fact = aggregate_hotel(hourly.get((day, hour), []))
            if as_float(fact.get("capacity_progress")) is not None:
                capacities.append(float(fact["capacity_progress"]))
            totals = [
                row for key, row in hotel_daily.items() if key[0] == day
            ]
            final_nights = (
                as_float(totals[0].get("room_nights"))
                if len(totals) == 1
                else None
            )
            if final_nights not in (None, 0) and as_float(
                fact.get("committed_sold")
            ) is not None:
                completions.append(
                    float(fact["committed_sold"]) / final_nights
                )
        capacity = summarize(capacities)
        completion = summarize(completions)
        count = max(capacity["sample_count"], completion["sample_count"])
        coverage = count / max(len(selected_dates), 1)
        hotel_points.append(
            {
                "hour": hour,
                "capacity": capacity,
                "target_completion": completion,
                "coverage": coverage,
                "maturity": maturity(count, coverage),
            }
        )
    final_nights: list[float] = []
    final_revenues: list[float] = []
    conflicts: list[str] = []
    room_total_conflicts: list[dict[str, Any]] = []
    for day in selected_dates:
        totals = [row for key, row in hotel_daily.items() if key[0] == day]
        if len(totals) == 1:
            nights = as_float(totals[0].get("room_nights"))
            revenue = as_float(totals[0].get("room_revenue"))
            if nights is not None:
                final_nights.append(nights)
            if revenue is not None:
                final_revenues.append(revenue)
            room_values = [
                as_float(row.get("room_nights"))
                for key, row in room_daily.items()
                if key[0] == day and key[1]
            ]
            canonical_sum = sum(
                value for value in room_values if value is not None
            )
            if (
                nights is not None
                and room_values
                and abs(canonical_sum - nights) > 0.01
            ):
                room_total_conflicts.append(
                    {
                        "business_date": day,
                        "jy01_hotel_room_nights": nights,
                        "jl01_canonical_room_nights_sum": canonical_sum,
                        "gap": canonical_sum - nights,
                    }
                )
        elif len(totals) > 1:
            conflicts.append(day)
    return (
        {
            "hourly_points": hotel_points,
            "historical_target_room_nights": summarize(final_nights),
            "historical_revenue_target": summarize(final_revenues),
            "jy01_total_dimension_conflict_dates": conflicts,
            "hotel_room_type_final_conflicts": room_total_conflicts,
        },
        room_results,
    )


def build_baseline(
    repository: Any,
    *,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
    date_contexts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    target_date = str(target_date)[:10]
    as_of_datetime = str(as_of_datetime)
    start_date, end_date = _date_window(target_date)
    gaps: list[str] = []

    def safe(method: str, *args: Any) -> list[dict[str, Any]]:
        try:
            return list(getattr(repository, method)(*args))
        except (RepositoryError, AttributeError, TypeError) as exc:
            gaps.append(f"{method}:{exc}")
            return []

    hourly_rows = safe(
        "hourly_history",
        hotel_id,
        start_date,
        end_date,
        as_of_datetime,
    )
    dates = sorted(
        {
            date_part(row.get("stay_date"))
            for row in hourly_rows
            if date_part(row.get("stay_date"))
        }
    )
    tier, selected_dates = _select_dates(
        target_date, dates, date_contexts
    )
    if not selected_dates:
        return {
            "status": "data_gap",
            "reason": "pms_hourly_history_unavailable",
            "hotel_id": hotel_id,
            "target_date": target_date,
            "formula_version": FORMULA_VERSION,
            "policy_version": S15_POLICY_VERSION,
            "data_gaps": gaps
            or ["pms_room_type_hourly_status:no_rows"],
        }
    hourly, expected = _hourly_facts(hourly_rows, selected_dates)
    hotel, rooms = _sales_lines(
        selected_dates,
        hourly,
        safe(
            "room_daily",
            hotel_id,
            start_date,
            end_date,
            as_of_datetime,
        ),
        safe(
            "hotel_daily_total",
            hotel_id,
            start_date,
            end_date,
            as_of_datetime,
        ),
    )
    prices = build_price_baselines(
        safe(
            "room_revenue",
            hotel_id,
            start_date,
            end_date,
            as_of_datetime,
        )
    )
    meituan = build_metric_baselines(
        safe(
            "ota_business_metrics",
            "meituan",
            hotel_id,
            start_date,
            end_date,
            as_of_datetime,
        ),
        MEITUAN_METRICS,
        "meituan",
    )
    ctrip = build_metric_baselines(
        safe(
            "ota_business_metrics",
            "ctrip",
            hotel_id,
            start_date,
            end_date,
            as_of_datetime,
        ),
        CTRIP_METRICS,
        "ctrip",
    )
    gross_booking_context = build_gross_booking_context(
        safe(
            "gross_booking_curve",
            hotel_id,
            start_date,
            end_date,
            as_of_datetime,
        )
    )
    hour_distribution_context = build_hour_distribution_context(
        safe(
            "ctrip_userprofile_hour_distribution",
            hotel_id,
            as_of_datetime,
        )
    )
    peer_demand_context = build_peer_demand_context(
        safe(
            "ctrip_competition_metrics_30d",
            hotel_id,
            as_of_datetime,
        )
    )
    hotel["effective_target_room_nights"] = hotel[
        "historical_target_room_nights"
    ].get("median")
    for room_id, room in rooms.items():
        room["effective_target_room_nights"] = room[
            "historical_target_room_nights"
        ].get("median")
        room["price_baseline"] = prices.get(
            room_id, {"status": "unavailable"}
        )
    payload: dict[str, Any] = {
        "status": "ok",
        "hotel_id": hotel_id,
        "target_date": target_date,
        "as_of_datetime": as_of_datetime,
        "formula_version": FORMULA_VERSION,
        "policy_version": S15_POLICY_VERSION,
        "selected_tier": tier,
        "date_context_status": (
            "available" if date_contexts else "weekday_only"
        ),
        "selected_dates": selected_dates,
        "selected_date_set_hash": stable_hash(selected_dates),
        "expected_room_type_ids": list(expected),
        "hotel": hotel,
        "room_types": rooms,
        "ota_baselines": {"meituan": meituan, "ctrip": ctrip},
        "gross_booking_created_curve_context": gross_booking_context,
        "gross_order_hour_distribution_context": (
            hour_distribution_context
        ),
        "peer_demand_proxy": peer_demand_context,
        "rolling_30d_context": {
            "meituan": safe(
                "flow_30d", "meituan", hotel_id, as_of_datetime
            ),
            "ctrip": safe(
                "flow_30d", "ctrip", hotel_id, as_of_datetime
            ),
            "status": "single_window_reference",
        },
        "unavailable_baseline_families": {
            "market_orders_baseline": "source_semantic_unavailable",
            "hotel_market_share_baseline": (
                "same_scope_market_denominator_unavailable"
            ),
            "stable_market_browse_pay_conversion_baseline": (
                "only_rolling_window_context_available"
            ),
            "stable_lead_price_rank_baseline": (
                "validated_historical_population_unavailable"
            ),
        },
        "data_gaps": gaps,
    }
    payload["baseline_revision"] = stable_hash(payload)
    return payload

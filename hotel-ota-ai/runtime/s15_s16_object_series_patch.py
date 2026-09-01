from __future__ import annotations

from typing import Any, Mapping, Sequence

_INSTALLED = False
_MATURITY_SCORE = {
    "trend_only": 0.25,
    "weak": 0.40,
    "temporary": 0.60,
    "stable": 0.80,
    "strong": 0.95,
}
_TIER_PENALTY = {
    "P0_previous_year_approved_window": 1.00,
    "P1_season_holiday_weekday": 1.00,
    "M1_season_holiday_weekday": 1.00,
    "P2_season_holiday_week_type": 0.90,
    "M2_season_holiday_week_type": 0.90,
    "P3_season_holiday": 0.80,
    "M3_season_holiday": 0.80,
    "P4_same_weekday": 0.70,
    "M4_same_weekday": 0.70,
    "P5_same_week_type": 0.55,
    "P5_cold_start": 0.55,
}


def _confidence(maturity_value: Any, tier: Any, coverage: float) -> float:
    score = _MATURITY_SCORE.get(str(maturity_value or ""), 0.25)
    penalty = _TIER_PENALTY.get(str(tier or ""), 0.55)
    return round(
        score * penalty * min(max(float(coverage), 0.0), 1.0),
        4,
    )


def _coverage_maturity(coverage: float) -> str:
    if coverage < 0.40:
        return "trend_only"
    if coverage < 0.60:
        return "weak"
    if coverage < 0.75:
        return "temporary"
    if coverage < 0.90:
        return "stable"
    return "strong"


def _minimum_maturity(*values: Any) -> str:
    order = {
        "trend_only": 0,
        "weak": 1,
        "temporary": 2,
        "stable": 3,
        "strong": 4,
    }
    clean = [str(value) for value in values if str(value or "") in order]
    return min(clean, key=lambda value: order[value]) if clean else "trend_only"


def rebuild_independent_baseline_series(
    payload: dict[str, Any],
    capture: Any,
    *,
    target_date: str,
    date_contexts: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if payload.get("status") != "ok":
        return payload

    from runtime.sales_progress import baseline_service
    from runtime.sales_progress.core import (
        aggregate_hotel,
        as_float,
        maturity,
        stable_hash,
        summarize,
    )
    from runtime.sales_progress.metrics import build_price_baselines

    hourly_rows = list(getattr(capture, "hourly_rows", []) or [])
    room_daily_rows = list(getattr(capture, "room_daily_rows", []) or [])
    hotel_daily_rows = list(getattr(capture, "hotel_daily_rows", []) or [])
    price_rows = list(getattr(capture, "price_rows", []) or [])
    hourly_dates = sorted(
        {
            str(row.get("stay_date") or "")[:10]
            for row in hourly_rows
            if str(row.get("stay_date") or "")[:10]
        }
    )

    # Hotel target completion uses the exact JY01 hotel total population.
    # JL01 remains the room-level final denominator and reconciliation source.
    hotel_daily_by_date = {
        str(row.get("business_date") or "")[:10]: row
        for row in hotel_daily_rows
        if str(row.get("business_date") or "")[:10]
        and as_float(row.get("room_nights")) is not None
    }
    hotel_dates_available = sorted(set(hourly_dates) & set(hotel_daily_by_date))
    hotel_tier, hotel_dates = baseline_service._select_dates(
        target_date,
        hotel_dates_available,
        date_contexts,
    )
    hotel_hourly, _ = baseline_service._hourly_facts(hourly_rows, hotel_dates)
    hotel = payload.get("hotel") or {}
    for point in hotel.get("hourly_points") or []:
        hour = int(point.get("hour") or 0)
        values: list[float] = []
        for day in hotel_dates:
            facts = list(hotel_hourly.get((day, hour), []))
            actual = as_float(aggregate_hotel(facts).get("committed_sold"))
            final = as_float(
                (hotel_daily_by_date.get(day) or {}).get("room_nights")
            )
            if actual is not None and final not in (None, 0):
                values.append(float(actual) / float(final))
        distribution = summarize(values)
        coverage = distribution["sample_count"] / max(len(hotel_dates), 1)
        target_maturity = maturity(distribution["sample_count"], coverage)
        point["target_completion"] = distribution
        point["target_completion_maturity"] = target_maturity
        point["capacity_maturity"] = (
            point.get("capacity_maturity") or point.get("maturity")
        )
        capacity_count = int(
            ((point.get("capacity") or {}).get("sample_count")) or 0
        )
        capacity_coverage = capacity_count / max(
            len(payload.get("selected_dates") or []),
            1,
        )
        point["capacity_confidence"] = _confidence(
            point.get("capacity_maturity"),
            payload.get("selected_tier"),
            capacity_coverage,
        )
        point["target_completion_confidence"] = _confidence(
            target_maturity,
            hotel_tier,
            coverage,
        )
        point["combined_maturity"] = _minimum_maturity(
            point.get("capacity_maturity"),
            target_maturity,
        )
        point["maturity"] = point["combined_maturity"]

    hotel_final_values = [
        as_float(hotel_daily_by_date[day].get("room_nights"))
        for day in hotel_dates
        if day in hotel_daily_by_date
    ]
    hotel_revenue_values = [
        as_float(hotel_daily_by_date[day].get("room_revenue"))
        for day in hotel_dates
        if day in hotel_daily_by_date
    ]
    hotel["historical_target_room_nights"] = summarize(
        [value for value in hotel_final_values if value is not None]
    )
    hotel["historical_revenue_target"] = summarize(
        [value for value in hotel_revenue_values if value is not None]
    )
    hotel["effective_target_room_nights"] = hotel[
        "historical_target_room_nights"
    ].get("median")
    hotel["target_series_tier"] = hotel_tier
    hotel["target_series_dates"] = hotel_dates
    hotel["target_final_source"] = "jy01_exact_total_business_metric"

    capacity_dates = payload.get("selected_dates") or []
    points = hotel.get("hourly_points") or []
    exact_cells = sum(
        int(point.get("exact_sample_count") or 0) for point in points
    )
    fallback_cells = sum(
        int(point.get("fallback_sample_count") or 0) for point in points
    )
    grid_denominator = max(len(capacity_dates) * 24, 1)
    hour_grid_coverage = exact_cells / grid_denominator
    checkpoint_hours = {12, 14, 16, 18, 20, 22}
    checkpoint_exact = sum(
        int(point.get("exact_sample_count") or 0)
        for point in points
        if int(point.get("hour") or -1) in checkpoint_hours
    )
    checkpoint_denominator = max(
        len(capacity_dates) * len(checkpoint_hours),
        1,
    )
    collector_last_success_at = max(
        (
            str(row.get("snapshot_time") or "")
            for row in hourly_rows
            if row.get("snapshot_time")
        ),
        default=None,
    )
    health = dict(hotel.get("baseline_health") or {})
    health.update(
        {
            "valid_exact_date_hour_cells": exact_cells,
            "fallback_date_hour_cells": fallback_cells,
            "hour_grid_coverage": hour_grid_coverage,
            "display_checkpoint_coverage": (
                checkpoint_exact / checkpoint_denominator
            ),
            "collector_last_success_at": collector_last_success_at,
            "object_maturity": _coverage_maturity(hour_grid_coverage),
        }
    )
    hotel["baseline_health"] = health
    hotel["capacity_series_confidence"] = _confidence(
        health["object_maturity"],
        payload.get("selected_tier"),
        hour_grid_coverage,
    )
    hotel["target_series_maturity"] = _minimum_maturity(
        *[
            point.get("target_completion_maturity")
            for point in points
            if int(
                ((point.get("target_completion") or {}).get("sample_count"))
                or 0
            )
            > 0
        ]
    )
    hotel["target_series_confidence"] = _confidence(
        hotel["target_series_maturity"],
        hotel_tier,
        len(hotel_dates) / max(len(hotel_dates_available), 1),
    )

    room_daily_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in room_daily_rows:
        day = str(row.get("business_date") or "")[:10]
        room_id = str(row.get("room_type_id") or "")
        if day and room_id:
            room_daily_by_key[(day, room_id)] = row

    hourly_cache: dict[
        tuple[str, ...],
        Mapping[tuple[str, int], Sequence[Mapping[str, Any]]],
    ] = {}
    for room_id, room in (payload.get("room_types") or {}).items():
        room_id = str(room_id)
        room_daily_dates = {
            day
            for day, candidate_room_id in room_daily_by_key
            if candidate_room_id == room_id
        }
        available = sorted(set(hourly_dates) & room_daily_dates)
        tier, dates = baseline_service._select_dates(
            target_date,
            available,
            date_contexts,
        )
        cache_key = tuple(dates)
        if cache_key not in hourly_cache:
            hourly_cache[cache_key] = baseline_service._hourly_facts(
                hourly_rows,
                dates,
            )[0]
        object_hourly = hourly_cache[cache_key]
        for point in room.get("hourly_points") or []:
            hour = int(point.get("hour") or 0)
            values: list[float] = []
            for day in dates:
                fact = next(
                    (
                        row
                        for row in object_hourly.get((day, hour), [])
                        if str(row.get("room_type_id")) == room_id
                    ),
                    None,
                )
                actual = as_float((fact or {}).get("committed_sold"))
                final = as_float(
                    (room_daily_by_key.get((day, room_id)) or {}).get(
                        "room_nights"
                    )
                )
                if actual is not None and final not in (None, 0):
                    values.append(float(actual) / float(final))
            distribution = summarize(values)
            coverage = distribution["sample_count"] / max(len(dates), 1)
            target_maturity = maturity(distribution["sample_count"], coverage)
            point["target_completion"] = distribution
            point["target_completion_maturity"] = target_maturity
            point["capacity_maturity"] = (
                point.get("capacity_maturity") or point.get("maturity")
            )
            capacity_count = int(
                ((point.get("capacity") or {}).get("sample_count")) or 0
            )
            capacity_coverage = capacity_count / max(
                len(payload.get("selected_dates") or []),
                1,
            )
            point["capacity_confidence"] = _confidence(
                point.get("capacity_maturity"),
                payload.get("selected_tier"),
                capacity_coverage,
            )
            point["target_completion_confidence"] = _confidence(
                target_maturity,
                tier,
                coverage,
            )
            point["combined_maturity"] = _minimum_maturity(
                point.get("capacity_maturity"),
                target_maturity,
            )
            point["maturity"] = point["combined_maturity"]

        final_values = [
            as_float(
                (room_daily_by_key.get((day, room_id)) or {}).get(
                    "room_nights"
                )
            )
            for day in dates
        ]
        revenue_values = [
            as_float(
                (room_daily_by_key.get((day, room_id)) or {}).get(
                    "room_revenue"
                )
            )
            for day in dates
        ]
        room["historical_target_room_nights"] = summarize(
            [value for value in final_values if value is not None]
        )
        room["historical_revenue_target"] = summarize(
            [value for value in revenue_values if value is not None]
        )
        room["effective_target_room_nights"] = room[
            "historical_target_room_nights"
        ].get("median")
        room["target_series_tier"] = tier
        room["target_series_dates"] = dates
        room["target_final_source"] = "jl01_exact_canonical_room_type"

        room_price_rows = [
            row
            for row in price_rows
            if str(row.get("room_type_id") or "") == room_id
        ]
        price_dates_available = sorted(
            {
                str(row.get("business_date") or "")[:10]
                for row in room_price_rows
                if str(row.get("business_date") or "")[:10]
            }
        )
        price_tier, price_dates = baseline_service._select_dates(
            target_date,
            price_dates_available,
            date_contexts,
        )
        price_date_set = set(price_dates)
        room["price_baseline"] = build_price_baselines(
            [
                row
                for row in room_price_rows
                if str(row.get("business_date") or "")[:10]
                in price_date_set
            ]
        ).get(room_id, {"status": "unavailable"})
        room["price_series_tier"] = price_tier
        room["price_series_dates"] = price_dates
        price_day_count = len(price_dates)
        room["price_series_maturity"] = (
            "trend_only"
            if price_day_count < 3
            else "weak"
            if price_day_count < 7
            else "temporary"
            if price_day_count < 30
            else "stable"
        )
        room["price_series_confidence"] = _confidence(
            room["price_series_maturity"],
            price_tier,
            1.0 if price_day_count else 0.0,
        )

    payload["baseline_object_selection"] = {
        "capacity_series": {
            "tier": payload.get("selected_tier"),
            "dates": payload.get("selected_dates") or [],
        },
        "hotel_target_completion_series": {
            "tier": hotel_tier,
            "dates": hotel_dates,
        },
        "room_target_completion_series": {
            str(room_id): {
                "tier": room.get("target_series_tier"),
                "dates": room.get("target_series_dates") or [],
            }
            for room_id, room in (payload.get("room_types") or {}).items()
        },
        "room_price_series": {
            str(room_id): {
                "tier": room.get("price_series_tier"),
                "dates": room.get("price_series_dates") or [],
            }
            for room_id, room in (payload.get("room_types") or {}).items()
        },
    }
    payload["baseline_object_algorithm_version"] = (
        "s15-independent-object-series.v1"
    )
    revision_source = dict(payload)
    revision_source.pop("baseline_revision", None)
    payload["baseline_revision"] = stable_hash(revision_source)
    return payload


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s15_s16_spec_alignment_patch

    capture_class = s15_s16_spec_alignment_patch._CaptureRepository
    original_capture_init = capture_class.__init__

    def capture_init(self: Any, delegate: Any) -> None:
        original_capture_init(self, delegate)
        self.hourly_rows = []
        self.room_daily_rows = []
        self.hotel_daily_rows = []

    def capture_hourly(
        self: Any,
        *args: Any,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        rows = list(self.delegate.hourly_history(*args, **kwargs))
        self.hourly_rows = [dict(row) for row in rows]
        return rows

    def capture_room_daily(
        self: Any,
        *args: Any,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        rows = list(self.delegate.room_daily(*args, **kwargs))
        self.room_daily_rows = [dict(row) for row in rows]
        return rows

    def capture_hotel_daily(
        self: Any,
        *args: Any,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        rows = list(self.delegate.hotel_daily_total(*args, **kwargs))
        self.hotel_daily_rows = [dict(row) for row in rows]
        return rows

    capture_class.__init__ = capture_init
    capture_class.hourly_history = capture_hourly
    capture_class.room_daily = capture_room_daily
    capture_class.hotel_daily_total = capture_hotel_daily

    previous_postprocess = s15_s16_spec_alignment_patch._postprocess_baseline

    def postprocess(
        payload: dict[str, Any],
        capture: Any,
        *,
        target_date: str,
        date_contexts: Any,
    ) -> dict[str, Any]:
        result = previous_postprocess(
            payload,
            capture,
            target_date=target_date,
            date_contexts=date_contexts,
        )
        return rebuild_independent_baseline_series(
            result,
            capture,
            target_date=target_date,
            date_contexts=date_contexts,
        )

    s15_s16_spec_alignment_patch._postprocess_baseline = postprocess

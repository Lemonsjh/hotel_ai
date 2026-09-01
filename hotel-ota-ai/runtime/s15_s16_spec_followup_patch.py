from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

_VERSION = "s15-s16-attachment-data-rules.v3"
_INSTALLED = False
_RECENT_SAMPLE_WINDOW = 6
_RECENT_SAMPLE_RECOVERY_THRESHOLD = 0.60


def _date(value: Any) -> str:
    return str(value or "")[:10]


def platform_maturity(sample_count: int) -> str:
    if sample_count < 3:
        return "trend_only"
    if sample_count < 7:
        return "weak"
    if sample_count < 30:
        return "temporary"
    return "stable"


def collector_health(points: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    observed: list[int] = []
    fallback_only: list[int] = []
    missing: list[int] = []
    recent_exact_cells = 0
    recent_sample_day_count = 0
    for hour in range(24):
        point = next((item for item in points if item.get("hour") == hour), None) or {}
        capacity_count = int(((point.get("capacity") or {}).get("sample_count")) or 0)
        completion_count = int(((point.get("target_completion") or {}).get("sample_count")) or 0)
        has_explicit_metadata = (
            "exact_sample_count" in point or "fallback_sample_count" in point
        )
        exact_count = (
            int(point.get("exact_sample_count") or 0)
            if has_explicit_metadata
            else max(capacity_count, completion_count)
        )
        fallback_count = int(point.get("fallback_sample_count") or 0)
        recent_exact_cells += int(point.get("recent_exact_sample_count") or 0)
        recent_sample_day_count = max(
            recent_sample_day_count,
            int(point.get("recent_sample_day_count") or 0),
        )
        if exact_count > 0:
            observed.append(hour)
        elif fallback_count > 0:
            fallback_only.append(hour)
        else:
            missing.append(hour)

    ratio = len(observed) / 24
    maturity = "trend_only" if ratio < 0.40 else "weak" if ratio < 0.75 else "temporary"
    recent_expected_cells = recent_sample_day_count * 24
    recent_ratio = (
        recent_exact_cells / recent_expected_cells
        if recent_expected_cells > 0
        else 0.0
    )
    recent_recovered = bool(
        recent_sample_day_count == _RECENT_SAMPLE_WINDOW
        and recent_ratio >= _RECENT_SAMPLE_RECOVERY_THRESHOLD
        and maturity != "temporary"
    )
    if recent_recovered:
        maturity = "temporary"

    return {
        "expected_hour_slots": 24,
        "observed_hour_slots": observed,
        "fallback_only_hour_slots": fallback_only,
        "missing_hour_slots": missing,
        "collector_coverage_ratio": ratio,
        "recent_sample_day_count": recent_sample_day_count,
        "recent_exact_sample_cell_count": recent_exact_cells,
        "recent_expected_sample_cell_count": recent_expected_cells,
        "recent_sample_coverage_ratio": recent_ratio,
        "recent_sample_recovery_threshold": _RECENT_SAMPLE_RECOVERY_THRESHOLD,
        "recent_sample_recovered": recent_recovered,
        "maturity_source": "recent_6_samples" if recent_recovered else "full_history",
        "object_maturity": maturity,
    }


def strict_hourly_facts(
    rows: Sequence[Mapping[str, Any]],
    selected_dates: Sequence[str],
) -> tuple[dict[tuple[str, int], list[dict[str, Any]]], tuple[str, ...]]:
    from runtime.sales_progress.core import (
        calculate_room_fact,
        date_part,
        expected_room_type_set,
        select_complete_batch,
    )

    expected = expected_room_type_set(rows)
    if not expected:
        return {}, ()
    result: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for day in selected_dates:
        day_rows = [row for row in rows if date_part(row.get("stay_date")) == day]
        for hour in range(24):
            selected = select_complete_batch(
                day_rows,
                expected_room_types=expected,
                requested_hour=hour,
            )
            if not selected.complete or not selected.rows:
                continue
            facts = [calculate_room_fact(row) for row in selected.rows]
            for fact in facts:
                fact["source_observed_hour"] = selected.observed_hour
                fact["checkpoint_gap_minutes"] = selected.checkpoint_gap_minutes or 0
                fact["is_exact_hour"] = selected.observed_hour == hour
            result[(day, hour)] = facts
    return result, expected


def aligned_sales_lines(
    previous: Any,
    selected_dates: Sequence[str],
    hourly: Mapping[tuple[str, int], Sequence[Mapping[str, Any]]],
    room_daily_rows: Sequence[Mapping[str, Any]],
    hotel_daily_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    from runtime.sales_progress.core import aggregate_hotel, as_float, summarize

    hotel, rooms = previous(selected_dates, hourly, room_daily_rows, hotel_daily_rows)
    recent_dates = tuple(sorted({_date(day) for day in selected_dates if _date(day)}, reverse=True)[:_RECENT_SAMPLE_WINDOW])
    recent_date_set = set(recent_dates)
    expected_room_ids = sorted(
        {
            str(row.get("room_type_id"))
            for facts in hourly.values()
            for row in facts
            if row.get("room_type_id")
        }
    )
    room_daily: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in room_daily_rows:
        day = _date(row.get("business_date"))
        room_id = str(row.get("room_type_id") or "")
        if day and room_id:
            room_daily[(day, room_id)] = row
    hotel_daily: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in hotel_daily_rows:
        day = _date(row.get("business_date"))
        if day:
            hotel_daily[day].append(row)

    final_by_day: dict[str, float] = {}
    final_source_by_day: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []
    for day in selected_dates:
        room_values = [
            as_float((room_daily.get((day, room_id)) or {}).get("room_nights"))
            for room_id in expected_room_ids
        ]
        jl_complete = bool(expected_room_ids) and all(value is not None for value in room_values)
        jl_sum = (
            sum(float(value) for value in room_values if value is not None)
            if jl_complete
            else None
        )
        exact_totals = [
            as_float(row.get("room_nights"))
            for row in hotel_daily.get(day, [])
            if as_float(row.get("room_nights")) is not None
        ]
        jy_total = exact_totals[0] if len(exact_totals) == 1 else None
        if jl_sum is not None:
            final_by_day[day] = jl_sum
            final_source_by_day[day] = "jl01_complete_canonical_sum"
        elif jy_total is not None:
            final_by_day[day] = float(jy_total)
            final_source_by_day[day] = "jy01_exact_hotel_total_fallback"
        if jl_sum is not None and jy_total is not None and abs(jl_sum - float(jy_total)) > 0.01:
            conflicts.append(
                {
                    "business_date": day,
                    "jl01_canonical_room_nights_sum": jl_sum,
                    "jy01_hotel_room_nights": float(jy_total),
                    "gap": jl_sum - float(jy_total),
                }
            )

    for point in hotel.get("hourly_points") or []:
        hour = int(point.get("hour") or 0)
        completions: list[float] = []
        exact_count = fallback_count = max_gap = recent_exact_count = 0
        for day in selected_dates:
            facts = list(hourly.get((day, hour), []))
            if facts:
                sample = facts[0]
                if sample.get("is_exact_hour"):
                    exact_count += 1
                    if _date(day) in recent_date_set:
                        recent_exact_count += 1
                else:
                    fallback_count += 1
                    max_gap = max(max_gap, int(sample.get("checkpoint_gap_minutes") or 0))
            actual = as_float(aggregate_hotel(facts).get("committed_sold"))
            final = final_by_day.get(day)
            if final not in (None, 0) and actual is not None:
                completions.append(float(actual) / float(final))
        point["target_completion"] = summarize(completions)
        point["exact_sample_count"] = exact_count
        point["fallback_sample_count"] = fallback_count
        point["recent_exact_sample_count"] = recent_exact_count
        point["recent_sample_day_count"] = len(recent_dates)
        point["max_checkpoint_gap_minutes"] = max_gap

    for room_id, room in rooms.items():
        for point in room.get("hourly_points") or []:
            hour = int(point.get("hour") or 0)
            exact_count = fallback_count = max_gap = recent_exact_count = 0
            for day in selected_dates:
                row = next(
                    (
                        item
                        for item in hourly.get((day, hour), [])
                        if str(item.get("room_type_id")) == str(room_id)
                    ),
                    None,
                )
                if row is None:
                    continue
                if row.get("is_exact_hour"):
                    exact_count += 1
                    if _date(day) in recent_date_set:
                        recent_exact_count += 1
                else:
                    fallback_count += 1
                    max_gap = max(max_gap, int(row.get("checkpoint_gap_minutes") or 0))
            point["exact_sample_count"] = exact_count
            point["fallback_sample_count"] = fallback_count
            point["recent_exact_sample_count"] = recent_exact_count
            point["recent_sample_day_count"] = len(recent_dates)
            point["max_checkpoint_gap_minutes"] = max_gap

    hotel["historical_target_room_nights"] = summarize(list(final_by_day.values()))
    hotel["final_room_nights_source_by_date"] = final_source_by_day
    hotel["hotel_room_type_final_conflicts"] = conflicts
    return hotel, rooms


def add_fallback_notes(text: str, payload: Mapping[str, Any]) -> str:
    hotel = payload.get("hotel") or {}
    points = hotel.get("hourly_points") or []
    notes: list[str] = []
    for point in points:
        fallback_count = int(point.get("fallback_sample_count") or 0)
        if fallback_count <= 0:
            continue
        notes.append(
            f"{int(point.get('hour') or 0):02d}时有{fallback_count}个样本使用前序完整批次"
            f"（最大间隔{int(point.get('max_checkpoint_gap_minutes') or 0)}分钟）"
        )
    health = hotel.get("baseline_health") or collector_health(points)
    fallback_only = health.get("fallback_only_hour_slots") or []
    if fallback_only:
        notes.append(
            "仅有前序批次、没有精确小时采集的时点："
            + "、".join(f"{int(hour):02d}时" for hour in fallback_only)
        )
    if health.get("recent_sample_recovered"):
        notes.append(
            "最近6个样本的精确小时网格覆盖已达到"
            f"{float(health.get('recent_sample_coverage_ratio') or 0) * 100:.1f}%，"
            "当前采集成熟度按恢复状态放行"
        )
    if not notes:
        return text
    block = "\n- 前序批次说明：" + "；".join(notes) + "。"
    marker = "\n\n二、房型基准"
    return text.replace(marker, block + marker, 1) if marker in text else text + block


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s15_s16_spec_alignment_patch as alignment
    from runtime.sales_progress import baseline_service, presentation

    alignment._PATCH_VERSION = _VERSION
    alignment.platform_maturity = platform_maturity
    alignment.collector_health = collector_health
    baseline_service._hourly_facts = strict_hourly_facts

    previous_sales_lines = baseline_service._sales_lines

    def wrapped_sales_lines(
        selected_dates: Sequence[str],
        hourly: Mapping[tuple[str, int], Sequence[Mapping[str, Any]]],
        room_daily_rows: Sequence[Mapping[str, Any]],
        hotel_daily_rows: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return aligned_sales_lines(
            previous_sales_lines,
            selected_dates,
            hourly,
            room_daily_rows,
            hotel_daily_rows,
        )

    baseline_service._sales_lines = wrapped_sales_lines
    original_s15 = presentation.build_s15_user_message

    def build_s15_user_message(payload: Mapping[str, Any]) -> str:
        return add_fallback_notes(original_s15(payload), payload)

    presentation.build_s15_user_message = build_s15_user_message

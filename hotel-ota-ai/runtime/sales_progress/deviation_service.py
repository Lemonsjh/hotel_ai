from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

from .baseline_service import build_baseline
from .core import (
    FORMULA_VERSION,
    S16_POLICY_VERSION,
    aggregate_hotel,
    as_float,
    as_int,
    calculate_room_fact,
    combined_diagnosis,
    deviation_line,
    select_complete_batch,
    stable_hash,
    structure_summary,
)
from .repository import RepositoryError


def _point_at_hour(
    points: Sequence[Mapping[str, Any]], hour: int
) -> Mapping[str, Any] | None:
    exact = next((point for point in points if as_int(point.get("hour")) == hour), None)
    if exact:
        return exact
    earlier = [
        point
        for point in points
        if as_int(point.get("hour")) is not None and int(point["hour"]) <= hour
    ]
    return max(earlier, key=lambda point: int(point["hour"])) if earlier else None


def _with_bands(
    line: dict[str, Any], distribution: Mapping[str, Any] | None
) -> dict[str, Any]:
    result = dict(line)
    distribution = distribution or {}
    result["baseline_p25"] = as_float(distribution.get("p25"))
    result["baseline_p80"] = as_float(distribution.get("p80"))
    return result


def _capacity_line(
    actual: float | None,
    total_rooms: float | None,
    distribution: Mapping[str, Any] | None,
) -> dict[str, Any]:
    distribution = distribution or {}
    result = _with_bands(
        deviation_line(actual, total_rooms, as_float(distribution.get("median"))),
        distribution,
    )
    result.update(
        {
            "actual_capacity_progress": result.get("actual_progress"),
            "capacity_progress_delta_pp": result.get("delta_pp"),
            "capacity_expected_sold": result.get("expected_sold"),
            "capacity_room_gap": result.get("room_gap"),
            "remaining_capacity_rooms": (
                total_rooms - actual
                if total_rooms is not None and actual is not None
                else None
            ),
        }
    )
    return result


def _target_line(
    actual: float | None,
    target: float | None,
    distribution: Mapping[str, Any] | None,
) -> dict[str, Any]:
    distribution = distribution or {}
    result = _with_bands(
        deviation_line(actual, target, as_float(distribution.get("median"))),
        distribution,
    )
    result.update(
        {
            "actual_target_completion": result.get("actual_progress"),
            "sales_progress_delta_pp": result.get("delta_pp"),
            "expected_sold_at_hour": result.get("expected_sold"),
            "checkpoint_room_gap": result.get("room_gap"),
            "remaining_target_gap": (
                target - actual if target is not None and actual is not None else None
            ),
        }
    )
    return result


def build_deviation(
    repository: Any,
    *,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
    baseline: Mapping[str, Any] | None = None,
    date_contexts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    target_date = str(target_date)[:10]
    as_of_datetime = str(as_of_datetime)
    as_of_date = as_of_datetime[:10]
    if baseline is None:
        baseline = build_baseline(
            repository,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_datetime=as_of_datetime,
            date_contexts=date_contexts,
        )
    if baseline.get("status") != "ok":
        return {
            "status": "data_gap",
            "reason": "s15_baseline_unavailable",
            "hotel_id": hotel_id,
            "target_date": target_date,
            "baseline": baseline,
            "formula_version": FORMULA_VERSION,
            "policy_version": S16_POLICY_VERSION,
        }
    if as_of_date < target_date:
        return {
            "status": "not_applicable",
            "reason": "future_stay_date_requires_lead_time_baseline",
            "hotel_id": hotel_id,
            "target_date": target_date,
            "baseline_revision": baseline.get("baseline_revision"),
            "formula_version": FORMULA_VERSION,
            "policy_version": S16_POLICY_VERSION,
        }
    if as_of_date > target_date:
        return {
            "status": "not_applicable",
            "reason": "historical_current_fact_requires_hourly_replay",
            "hotel_id": hotel_id,
            "target_date": target_date,
            "baseline_revision": baseline.get("baseline_revision"),
            "formula_version": FORMULA_VERSION,
            "policy_version": S16_POLICY_VERSION,
        }
    try:
        rows = list(repository.current_forecast(hotel_id, target_date, as_of_datetime))
    except (RepositoryError, AttributeError, TypeError) as exc:
        return {"status": "data_gap", "reason": f"current_forecast:{exc}"}
    requested_hour = dt.datetime.fromisoformat(
        as_of_datetime.replace("Z", "+00:00")
    ).hour
    selected = select_complete_batch(
        rows,
        expected_room_types=baseline.get("expected_room_type_ids") or [],
        requested_hour=requested_hour,
        as_of_datetime=as_of_datetime,
    )
    if not selected.rows:
        return {
            "status": "data_gap",
            "reason": selected.reason or "current_forecast_unavailable",
        }
    room_facts = [calculate_room_fact(row) for row in selected.rows]
    hotel_fact = aggregate_hotel(room_facts)
    comparison_hour = (
        selected.observed_hour
        if selected.observed_hour is not None
        else requested_hour
    )
    hotel_point = _point_at_hour(
        (baseline.get("hotel") or {}).get("hourly_points") or [], comparison_hour
    )
    hotel_target = as_float(
        (baseline.get("hotel") or {}).get("effective_target_room_nights")
    )
    hotel_actual = as_float(hotel_fact.get("committed_sold"))
    hotel_capacity_distribution = (hotel_point or {}).get("capacity") or {}
    hotel_target_distribution = (hotel_point or {}).get("target_completion") or {}
    hotel_capacity = _capacity_line(
        hotel_actual,
        as_float(hotel_fact.get("total_rooms")),
        hotel_capacity_distribution,
    )
    hotel_target_line = _target_line(
        hotel_actual, hotel_target, hotel_target_distribution
    )
    room_results: list[dict[str, Any]] = []
    for fact in room_facts:
        room_id = fact.get("room_type_id")
        room_baseline = (baseline.get("room_types") or {}).get(room_id) or {}
        point = _point_at_hour(
            room_baseline.get("hourly_points") or [], comparison_hour
        )
        actual = as_float(fact.get("committed_sold"))
        capacity_distribution = (point or {}).get("capacity") or {}
        target_distribution = (point or {}).get("target_completion") or {}
        capacity = _capacity_line(
            actual,
            as_float(fact.get("total_rooms")),
            capacity_distribution,
        )
        target = as_float(room_baseline.get("effective_target_room_nights"))
        target_line = _target_line(actual, target, target_distribution)
        room_results.append(
            {
                **fact,
                "effective_target_room_nights": target,
                "capacity_line": capacity,
                "target_line": target_line,
                "combined_diagnosis": combined_diagnosis(
                    target_line["status"], capacity["status"]
                ),
                "maturity": (point or {}).get("maturity"),
            }
        )
    hotel_result = {
        **hotel_fact,
        "effective_target_room_nights": hotel_target,
        "capacity_line": hotel_capacity,
        "target_line": hotel_target_line,
        "combined_diagnosis": combined_diagnosis(
            hotel_target_line["status"], hotel_capacity["status"]
        ),
    }
    room_gaps = [
        as_float((row.get("target_line") or {}).get("room_gap"))
        for row in room_results
    ]
    hotel_gap = as_float(hotel_target_line.get("room_gap"))
    if (
        selected.complete
        and room_results
        and all(value is not None for value in room_gaps)
        and hotel_gap is not None
    ):
        room_gap_sum = sum(float(value) for value in room_gaps if value is not None)
        difference = room_gap_sum - hotel_gap
        reconciliation = {
            "status": "ok" if abs(difference) <= 0.01 else "conflict",
            "hotel_checkpoint_gap": hotel_gap,
            "room_checkpoint_gap_sum": room_gap_sum,
            "difference": difference,
        }
    else:
        reconciliation = {
            "status": "not_applicable",
            "reason": "incomplete_room_scope_or_target_line",
        }
    report: dict[str, Any] = {
        "status": "ok" if selected.complete else "partial",
        "hotel_id": hotel_id,
        "target_date": target_date,
        "as_of_datetime": as_of_datetime,
        "requested_hour": requested_hour,
        "observed_hour": selected.observed_hour,
        "checkpoint_gap_minutes": selected.checkpoint_gap_minutes,
        "current_batch_complete": selected.complete,
        "missing_room_type_ids": list(selected.missing_room_type_ids),
        "formula_version": FORMULA_VERSION,
        "policy_version": S16_POLICY_VERSION,
        "baseline_revision": baseline.get("baseline_revision"),
        "hotel_result": hotel_result,
        "room_type_results": room_results,
        "structure_summary": structure_summary(
            room_results, hotel_target_line["status"]
        ),
        "structure_reconciliation": reconciliation,
    }
    report["report_revision"] = stable_hash(report)
    return report

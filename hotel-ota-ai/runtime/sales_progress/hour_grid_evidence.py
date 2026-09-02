from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

from .core import (
    as_float,
    canonical_room_type_id,
    date_part,
    expected_room_type_set,
    hour_value,
    maturity,
    parse_datetime,
)


VERSION = "s15-hour-grid-evidence.v1"
FORMAL_GLOBAL_MIN_COVERAGE = 0.40
FORMAL_DECISION_MATURITIES = {"temporary", "stable", "strong"}
PREVIEW_DECISION_MATURITIES = {"weak", "temporary", "stable", "strong"}


def _valid_exact_batch(
    rows: Sequence[Mapping[str, Any]],
    expected_room_types: set[str],
) -> bool:
    ids = [canonical_room_type_id(row) for row in rows]
    non_null = [item for item in ids if item]
    if not non_null or len(non_null) != len(set(non_null)):
        return False
    if expected_room_types and expected_room_types - set(non_null):
        return False
    return all(
        canonical_room_type_id(row)
        and as_float(row.get("total_rooms")) is not None
        and float(row["total_rooms"]) >= 0
        and as_float(row.get("available_rooms")) is not None
        and float(row["available_rooms"]) >= 0
        and as_float(row.get("overbooking_rooms")) is not None
        and float(row["overbooking_rooms"]) >= 0
        for row in rows
    )


def compute_hour_grid_evidence(
    rows: Sequence[Mapping[str, Any]],
    *,
    selected_dates: Sequence[str],
    expected_room_type_ids: Sequence[str] | None,
    decision_hour: int,
) -> dict[str, Any]:
    dates = list(dict.fromkeys(str(item)[:10] for item in selected_dates if item))
    selected = set(dates)
    expected = {
        str(item)
        for item in (expected_room_type_ids or expected_room_type_set(rows))
        if item not in (None, "")
    }

    grouped: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        day = date_part(row.get("stay_date"))
        snapshot = parse_datetime(row.get("snapshot_time"))
        hour = hour_value(row.get("snapshot_hour"), snapshot)
        if day not in selected or snapshot is None or hour is None:
            continue
        grouped[(day, hour, snapshot.isoformat(sep=" "))].append(row)

    exact_dates_by_hour: dict[int, set[str]] = {hour: set() for hour in range(24)}
    for (day, hour, _snapshot), batch_rows in grouped.items():
        if _valid_exact_batch(batch_rows, expected):
            exact_dates_by_hour[hour].add(day)

    sample_days = len(dates)
    per_hour: list[dict[str, Any]] = []
    exact_cells = 0
    for hour in range(24):
        sample_count = len(exact_dates_by_hour[hour])
        exact_cells += sample_count
        coverage = sample_count / sample_days if sample_days else 0.0
        per_hour.append(
            {
                "hour": hour,
                "exact_sample_count": sample_count,
                "exact_coverage_ratio": round(coverage, 4),
                "maturity": maturity(sample_count, coverage),
            }
        )

    total_cells = sample_days * 24
    global_coverage = exact_cells / total_cells if total_cells else 0.0
    decision = per_hour[decision_hour] if 0 <= decision_hour <= 23 else {
        "hour": decision_hour,
        "exact_sample_count": 0,
        "exact_coverage_ratio": 0.0,
        "maturity": "trend_only",
    }
    global_health = {
        "status": "ok" if sample_days and expected else "unavailable",
        "formula_version": VERSION,
        "selected_date_count": sample_days,
        "expected_room_type_count": len(expected),
        "exact_cell_count": exact_cells,
        "total_cell_count": total_cells,
        "exact_coverage_ratio": round(global_coverage, 4),
        "maturity": maturity(exact_cells, global_coverage),
        "formal_minimum_coverage": FORMAL_GLOBAL_MIN_COVERAGE,
        "formal_minimum_met": bool(
            sample_days
            and expected
            and global_coverage >= FORMAL_GLOBAL_MIN_COVERAGE
        ),
        "observed_hours": [
            point["hour"] for point in per_hour if point["exact_sample_count"] > 0
        ],
        "missing_all_hours": [
            point["hour"] for point in per_hour if point["exact_sample_count"] == 0
        ],
    }
    decision_evidence = {
        "status": "ok" if sample_days and expected else "unavailable",
        "formula_version": VERSION,
        **decision,
        "formal_maturity_allowed": decision.get("maturity")
        in FORMAL_DECISION_MATURITIES,
        "limited_preview_maturity_allowed": decision.get("maturity")
        in PREVIEW_DECISION_MATURITIES,
    }
    room_evidence = {
        room_id: dict(decision_evidence)
        for room_id in sorted(expected)
    }
    return {
        "formula_version": VERSION,
        "hour_grid_health": global_health,
        "decision_hour_evidence": decision_evidence,
        "hour_grid_points": per_hour,
        "room_type_decision_hour_evidence": room_evidence,
    }


def attach_hour_grid_evidence(
    result: Mapping[str, Any],
    *,
    rows: Sequence[Mapping[str, Any]],
    decision_hour: int,
    expected_room_type_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    copied = dict(result)
    evidence = compute_hour_grid_evidence(
        rows,
        selected_dates=copied.get("selected_dates") or [],
        expected_room_type_ids=(
            expected_room_type_ids
            if expected_room_type_ids is not None
            else copied.get("expected_room_type_ids") or []
        ),
        decision_hour=decision_hour,
    )
    copied.update(evidence)
    rooms = {
        str(key): dict(value)
        for key, value in (copied.get("room_types") or {}).items()
        if isinstance(value, Mapping)
    }
    room_evidence = evidence["room_type_decision_hour_evidence"]
    for room_id, room in rooms.items():
        room["decision_hour_evidence"] = dict(
            room_evidence.get(room_id) or evidence["decision_hour_evidence"]
        )
    copied["room_types"] = rooms
    return copied

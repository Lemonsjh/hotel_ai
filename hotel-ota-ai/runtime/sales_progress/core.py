from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Sequence

FORMULA_VERSION = "sales-progress.real-field.v1"
S15_POLICY_VERSION = "s15-baseline.v1"
S16_POLICY_VERSION = "s16-deviation.v1"
MAX_CHECKPOINT_GAP_MINUTES = 120


@dataclass(frozen=True)
class BatchSelection:
    status: str
    rows: list[dict[str, Any]]
    snapshot_time: str | None
    observed_hour: int | None
    requested_hour: int | None
    checkpoint_gap_minutes: int | None
    complete: bool
    missing_room_type_ids: tuple[str, ...]
    reason: str | None = None


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def as_int(value: Any) -> int | None:
    number = as_float(value)
    return None if number is None else int(round(number))


def parse_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value
    if value in (None, ""):
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return dt.datetime.strptime(text, fmt)
            except ValueError:
                pass
    return None


def hour_value(value: Any, fallback: Any = None) -> int | None:
    number = as_int(value)
    if number is not None and 0 <= number <= 23:
        return number
    parsed = parse_datetime(value) or parse_datetime(fallback)
    return parsed.hour if parsed is not None else None


def date_part(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    return text[:10] if len(text) >= 10 else None


def percentile(values: Sequence[float], q: float) -> float | None:
    clean = sorted(float(v) for v in values if as_float(v) is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    q = min(max(float(q), 0.0), 1.0)
    index = (len(clean) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return clean[lower]
    fraction = index - lower
    return clean[lower] + (clean[upper] - clean[lower]) * fraction


def weighted_quantile(pairs: Iterable[tuple[float, float]], q: float) -> float | None:
    clean = sorted(
        (float(value), float(weight))
        for value, weight in pairs
        if as_float(value) is not None and as_float(weight) is not None and float(weight) > 0
    )
    if not clean:
        return None
    total = sum(weight for _, weight in clean)
    threshold = total * min(max(float(q), 0.0), 1.0)
    running = 0.0
    for value, weight in clean:
        running += weight
        if running >= threshold:
            return value
    return clean[-1][0]


def round_half_up(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    quantum = Decimal("1").scaleb(-digits)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def canonical_room_type_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("room_type_id")
    if value in (None, ""):
        return None
    return str(value)


def calculate_room_fact(row: Mapping[str, Any]) -> dict[str, Any]:
    total = as_float(row.get("total_rooms"))
    available = as_float(row.get("available_rooms"))
    occupied = as_float(row.get("occupied_rooms"))
    overbooking = as_float(row.get("overbooking_rooms"))
    gaps: list[str] = []
    if total is None or total < 0:
        gaps.append("invalid_total_rooms")
    if available is None or available < 0:
        gaps.append("invalid_available_rooms")
    if overbooking is None or overbooking < 0:
        gaps.append("invalid_overbooking_rooms")
    if occupied is not None and occupied < 0:
        gaps.append("invalid_occupied_rooms")
    base = committed = capacity = physical = remaining = None
    if total is not None and available is not None and total >= 0 and available >= 0:
        base = max(total - available, 0.0)
        if overbooking is not None and overbooking >= 0:
            committed = max(total - available + overbooking, 0.0)
        if total > 0:
            remaining = available / total
            physical = occupied / total if occupied is not None and occupied >= 0 else None
            capacity = committed / total if committed is not None else None
    return {
        "room_type_id": canonical_room_type_id(row),
        "room_type_name": row.get("room_type_name"),
        "pms_room_type_id": row.get("pms_room_type_id"),
        "total_rooms": total,
        "available_rooms": available,
        "occupied_rooms": occupied,
        "overbooking_rooms": overbooking,
        "base_committed_sold": base,
        "committed_sold": committed,
        "capacity_progress": capacity,
        "physical_occupancy": physical,
        "remaining_ratio": remaining,
        "data_gaps": gaps,
    }


def aggregate_hotel(room_facts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    usable = [
        row
        for row in room_facts
        if row.get("total_rooms") is not None and row.get("committed_sold") is not None
    ]
    total = sum(float(row["total_rooms"]) for row in usable) if usable else None
    committed = sum(float(row["committed_sold"]) for row in usable) if usable else None
    available = sum(float(row.get("available_rooms") or 0) for row in usable) if usable else None
    overbooking = sum(float(row.get("overbooking_rooms") or 0) for row in usable) if usable else None
    return {
        "total_rooms": total,
        "available_rooms": available,
        "overbooking_rooms": overbooking,
        "committed_sold": committed,
        "capacity_progress": committed / total if total not in (None, 0) and committed is not None else None,
    }


def expected_room_type_set(rows: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    grouped: dict[tuple[str, int, str], set[str]] = defaultdict(set)
    for row in rows:
        room_id = canonical_room_type_id(row)
        day = date_part(row.get("stay_date"))
        snapshot = str(row.get("snapshot_time") or "")
        hour = hour_value(row.get("snapshot_hour"), snapshot)
        if room_id and day and hour is not None and snapshot:
            grouped[(day, hour, snapshot)].add(room_id)
    sets = [tuple(sorted(value)) for value in grouped.values() if value]
    if not sets:
        return ()
    candidate, count = Counter(sets).most_common(1)[0]
    return candidate if count >= 3 else ()


def select_complete_batch(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_room_types: Sequence[str] | None = None,
    requested_hour: int | None = None,
    max_gap_minutes: int = MAX_CHECKPOINT_GAP_MINUTES,
    as_of_datetime: Any = None,
) -> BatchSelection:
    expected = set(str(item) for item in (expected_room_types or []) if item not in (None, ""))
    as_of = parse_datetime(as_of_datetime)
    grouped: dict[tuple[int | None, str], list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        snapshot = parse_datetime(row.get("snapshot_time"))
        if snapshot is None or (as_of is not None and snapshot > as_of):
            continue
        hour = hour_value(row.get("snapshot_hour"), snapshot)
        grouped[(hour, snapshot.isoformat(sep=" "))].append(row)
    candidates: list[tuple[int, dt.datetime, list[dict[str, Any]], bool, tuple[str, ...]]] = []
    for (hour, snapshot_text), batch_rows in grouped.items():
        if hour is None:
            continue
        if requested_hour is not None and hour > requested_hour:
            continue
        ids = [canonical_room_type_id(row) for row in batch_rows]
        non_null = [item for item in ids if item]
        duplicate = len(non_null) != len(set(non_null))
        missing = tuple(sorted(expected - set(non_null))) if expected else ()
        valid_fields = all(
            canonical_room_type_id(row)
            and as_float(row.get("total_rooms")) is not None
            and as_float(row.get("total_rooms")) >= 0
            and as_float(row.get("available_rooms")) is not None
            and as_float(row.get("available_rooms")) >= 0
            and as_float(row.get("overbooking_rooms")) is not None
            and as_float(row.get("overbooking_rooms")) >= 0
            for row in batch_rows
        )
        complete = bool(non_null) and not duplicate and not missing and valid_fields
        candidates.append(
            (hour, parse_datetime(snapshot_text) or dt.datetime.min, batch_rows, complete, missing)
        )
    if not candidates:
        return BatchSelection(
            "data_gap", [], None, None, requested_hour, None, False, (), "no_candidate_batch"
        )
    complete_candidates = [item for item in candidates if item[3]]
    pool = complete_candidates or candidates
    pool.sort(key=lambda item: (item[0], item[1]), reverse=True)
    hour, snapshot, batch_rows, complete, missing = pool[0]
    gap = None
    if requested_hour is not None:
        gap = max((requested_hour - hour) * 60, 0)
        if as_of is not None and snapshot.date() == as_of.date() and snapshot <= as_of:
            gap = max(int((as_of - snapshot).total_seconds() // 60), 0)
        if gap > max_gap_minutes:
            return BatchSelection(
                "data_gap",
                [],
                None,
                hour,
                requested_hour,
                gap,
                False,
                missing,
                "checkpoint_gap_exceeds_limit",
            )
    status = "ok" if complete else "partial"
    return BatchSelection(
        status,
        batch_rows,
        snapshot.isoformat(sep=" "),
        hour,
        requested_hour,
        gap,
        complete,
        missing,
        None if complete else "partial_room_type_scope",
    )


def summarize(values: Sequence[float]) -> dict[str, Any]:
    clean = [float(value) for value in values if as_float(value) is not None]
    return {
        "median": percentile(clean, 0.5),
        "p25": percentile(clean, 0.25),
        "p80": percentile(clean, 0.8),
        "mean": sum(clean) / len(clean) if clean else None,
        "sample_count": len(clean),
    }


def maturity(sample_count: int, coverage: float) -> str:
    effective = min(max(float(coverage), 0.0), 1.0)
    if sample_count < 3 or effective < 0.40:
        return "trend_only"
    if effective < 0.60:
        return "weak"
    if effective < 0.75:
        return "temporary"
    if effective < 0.90:
        return "stable"
    return "strong"


def classify_delta(delta_pp: float | None) -> str:
    if delta_pp is None:
        return "unavailable"
    if delta_pp <= -25:
        return "severe_slow"
    if delta_pp <= -15:
        return "significant_slow"
    if delta_pp < -8:
        return "slow"
    if delta_pp < 8:
        return "normal"
    if delta_pp < 15:
        return "fast"
    return "significant_fast"


def is_slow(status: str) -> bool:
    return status in {"severe_slow", "significant_slow", "slow"}


def is_fast_or_normal(status: str) -> bool:
    return status in {"normal", "fast", "significant_fast"}


def combined_diagnosis(target_status: str, capacity_status: str) -> str:
    if "unavailable" in {target_status, capacity_status}:
        return "partial_single_line"
    target_slow = is_slow(target_status)
    capacity_slow = is_slow(capacity_status)
    if target_slow and capacity_slow:
        return "genuine_sales_lag"
    if target_slow and is_fast_or_normal(capacity_status):
        return "ambitious_target_gap"
    if is_fast_or_normal(target_status) and capacity_slow:
        return "conservative_target_on_track"
    return "on_track_or_ahead"


def deviation_line(
    actual: float | None,
    denominator: float | None,
    historical: float | None,
) -> dict[str, Any]:
    progress = actual / denominator if actual is not None and denominator not in (None, 0) else None
    delta = (progress - historical) * 100 if progress is not None and historical is not None else None
    expected = denominator * historical if denominator is not None and historical is not None else None
    gap = actual - expected if actual is not None and expected is not None else None
    return {
        "actual_progress": progress,
        "baseline_median": historical,
        "delta_pp": delta,
        "expected_sold": expected,
        "room_gap": gap,
        "status": classify_delta(delta),
    }


def structure_summary(
    room_results: Sequence[Mapping[str, Any]], hotel_target_status: str
) -> dict[str, Any]:
    usable = [
        row for row in room_results if row.get("effective_target_room_nights") not in (None, 0)
    ]
    total_target = sum(float(row["effective_target_room_nights"]) for row in usable)
    slow_rows = [
        row for row in usable if is_slow(str((row.get("target_line") or {}).get("status")))
    ]
    fast_rows = [
        row
        for row in usable
        if str((row.get("target_line") or {}).get("status")) in {"fast", "significant_fast"}
    ]
    slow_target = sum(float(row["effective_target_room_nights"]) for row in slow_rows)
    with_gap = [
        row
        for row in usable
        if as_float((row.get("target_line") or {}).get("room_gap")) is not None
    ]
    largest_negative = (
        min(with_gap, key=lambda row: float((row.get("target_line") or {})["room_gap"]))
        if with_gap
        else None
    )
    largest_positive = (
        max(with_gap, key=lambda row: float((row.get("target_line") or {})["room_gap"]))
        if with_gap
        else None
    )
    labels: list[str] = []
    slow_share = slow_target / total_target if total_target > 0 else None
    if is_slow(hotel_target_status) and slow_share is not None and slow_share >= 0.5:
        labels.append("broad_based_slowdown")
    if hotel_target_status == "normal":
        for row in slow_rows:
            share = float(row["effective_target_room_nights"]) / total_target if total_target else 0
            status = str((row.get("target_line") or {}).get("status"))
            if share >= 0.15 and status in {"significant_slow", "severe_slow"}:
                labels.append("room_type_structural_lag")
                break
    if slow_rows and fast_rows and hotel_target_status == "normal":
        labels.append("mix_offset_detected")
    return {
        "slow_room_type_count": len(slow_rows),
        "fast_room_type_count": len(fast_rows),
        "slow_target_share": slow_share,
        "largest_negative_gap_room_type": (
            largest_negative.get("room_type_id") if largest_negative else None
        ),
        "largest_positive_gap_room_type": (
            largest_positive.get("room_type_id") if largest_positive else None
        ),
        "structure_labels": labels,
    }


def stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

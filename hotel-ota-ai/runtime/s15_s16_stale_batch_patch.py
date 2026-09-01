from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Mapping, Sequence

_INSTALLED = False
VERSION = "s15-s16-stale-batch.v2"
STALE_MINUTES = 120


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        result = value
    elif value in (None, ""):
        return None
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            result = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    return result.replace(tzinfo=None) if result.tzinfo else result


def _explicit_hour(value: Any) -> int | None:
    parsed = _datetime(value)
    if parsed is not None:
        return parsed.hour
    number = _number(value)
    return int(number) if number is not None and 0 <= number <= 23 else None


def _room_id(row: Mapping[str, Any]) -> str | None:
    value = row.get("room_type_id")
    return None if value in (None, "") else str(value)


def select_batch(
    rows: Sequence[Mapping[str, Any]],
    *,
    expected_room_types: Sequence[str] | None = None,
    requested_hour: int | None = None,
    max_gap_minutes: int = STALE_MINUTES,
    as_of_datetime: Any = None,
) -> Any:
    """Select one internally consistent batch without discarding stale facts.

    Historical hourly rows have an explicit `snapshot_hour`; their selection is
    hour-first and retains the strict checkpoint-gap rule. Current forecast rows
    have no `snapshot_hour`; they are selected snapshot-time-first, because
    collection time determines which current fact is newest. A stale current
    forecast remains visible with downgraded freshness and cannot drive actions.
    """

    from runtime.sales_progress.core import BatchSelection

    expected = {
        str(value)
        for value in (expected_room_types or [])
        if value not in (None, "")
    }
    as_of = _datetime(as_of_datetime)
    grouped: dict[
        tuple[int | None, str, bool], list[dict[str, Any]]
    ] = defaultdict(list)

    for source in rows:
        row = dict(source)
        snapshot = _datetime(row.get("snapshot_time"))
        if snapshot is None or (as_of is not None and snapshot > as_of):
            continue
        explicit = _explicit_hour(row.get("snapshot_hour"))
        is_current_forecast = explicit is None
        if explicit is not None:
            comparison_hour = explicit
        elif (
            as_of is not None
            and snapshot.date() < as_of.date()
            and requested_hour is not None
        ):
            comparison_hour = requested_hour
        else:
            comparison_hour = snapshot.hour
        grouped[
            (
                comparison_hour,
                snapshot.isoformat(sep=" "),
                is_current_forecast,
            )
        ].append(row)

    candidates: list[
        tuple[int, dt.datetime, list[dict[str, Any]], bool, tuple[str, ...], bool]
    ] = []
    for (hour, snapshot_text, is_current_forecast), batch in grouped.items():
        if hour is None:
            continue
        if requested_hour is not None and hour > requested_hour:
            continue
        ids = [_room_id(row) for row in batch]
        non_null = [value for value in ids if value]
        missing = tuple(sorted(expected - set(non_null))) if expected else ()
        valid = all(
            _room_id(row)
            and _number(row.get("total_rooms")) is not None
            and float(row.get("total_rooms")) >= 0
            and _number(row.get("available_rooms")) is not None
            and float(row.get("available_rooms")) >= 0
            and _number(row.get("overbooking_rooms")) is not None
            and float(row.get("overbooking_rooms")) >= 0
            for row in batch
        )
        complete = (
            bool(non_null)
            and len(non_null) == len(set(non_null))
            and not missing
            and valid
        )
        candidates.append(
            (
                hour,
                _datetime(snapshot_text) or dt.datetime.min,
                batch,
                complete,
                missing,
                is_current_forecast,
            )
        )

    if not candidates:
        return BatchSelection(
            "data_gap",
            [],
            None,
            None,
            requested_hour,
            None,
            False,
            (),
            "no_candidate_batch",
        )

    complete_candidates = [item for item in candidates if item[3]]
    pool = complete_candidates or candidates
    current_pool = [item for item in pool if item[5]]
    if current_pool:
        selected = max(current_pool, key=lambda item: item[1])
    else:
        selected = max(pool, key=lambda item: (item[0], item[1]))
    hour, snapshot, batch, complete, missing, is_current_forecast = selected

    gap: int | None = None
    if as_of is not None:
        gap = max(int((as_of - snapshot).total_seconds() // 60), 0)
    elif requested_hour is not None:
        gap = max((requested_hour - hour) * 60, 0)

    if (
        not is_current_forecast
        and as_of is None
        and gap is not None
        and gap > max_gap_minutes
    ):
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

    if not complete:
        reason = "partial_room_type_scope"
    elif gap is not None and gap > max_gap_minutes:
        reason = (
            "stale_cross_day_forecast_used"
            if is_current_forecast
            and as_of is not None
            and snapshot.date() < as_of.date()
            else "stale_checkpoint_used"
        )
    else:
        reason = None

    return BatchSelection(
        "ok" if complete else "partial",
        batch,
        snapshot.isoformat(sep=" "),
        hour,
        requested_hour,
        gap,
        complete,
        missing,
        reason,
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.sales_progress import baseline_service, core, deviation_service

    core.select_complete_batch = select_batch
    baseline_service.select_complete_batch = select_batch
    deviation_service.select_complete_batch = select_batch

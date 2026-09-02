from __future__ import annotations

import datetime as dt
from typing import Any

from .baseline_service import build_baseline as _build_baseline
from .core import expected_room_type_set, parse_datetime
from .deviation_service import build_deviation as _build_deviation
from .hour_grid_evidence import VERSION as HOUR_GRID_VERSION
from .hour_grid_evidence import attach_hour_grid_evidence


def _argument(args: tuple[Any, ...], kwargs: dict[str, Any], name: str, index: int) -> Any:
    if name in kwargs:
        return kwargs[name]
    return args[index] if len(args) > index else None


def _attach_exact_hour_grid(
    result: dict[str, Any],
    *,
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> dict[str, Any]:
    parsed_as_of = parse_datetime(as_of_datetime)
    decision_hour = parsed_as_of.hour if parsed_as_of is not None else 23
    try:
        target = dt.date.fromisoformat(target_date[:10])
        start_date = (target - dt.timedelta(days=365)).isoformat()
        end_date = (target - dt.timedelta(days=1)).isoformat()
        rows = list(
            repository.hourly_history(
                hotel_id,
                start_date,
                end_date,
                as_of_datetime,
            )
        )
        # Keep the evidence gate aligned with S15's read-only room-identity
        # fallback.  The canonical IDs in ``result`` may be intentionally
        # duplicated or absent in historical PMS snapshots.
        from runtime.s15_s16_stale_batch_patch import prepare_read_only_hourly_rows

        prepared_rows = prepare_read_only_hourly_rows(rows)
        return attach_hour_grid_evidence(
            result,
            rows=prepared_rows,
            decision_hour=decision_hour,
            expected_room_type_ids=expected_room_type_set(prepared_rows),
        )
    except Exception as exc:
        copied = dict(result)
        reason = f"hour_grid_evidence:{exc.__class__.__name__}"
        copied["hour_grid_health"] = {
            "status": "unavailable",
            "formula_version": HOUR_GRID_VERSION,
            "reason": reason,
            "formal_minimum_met": False,
        }
        copied["decision_hour_evidence"] = {
            "status": "unavailable",
            "formula_version": HOUR_GRID_VERSION,
            "hour": decision_hour,
            "reason": reason,
            "formal_maturity_allowed": False,
            "limited_preview_maturity_allowed": False,
        }
        copied["data_gaps"] = list(copied.get("data_gaps") or []) + [reason]
        return copied


def build_baseline(*args: Any, **kwargs: Any) -> dict[str, Any]:
    result = _build_baseline(*args, **kwargs)
    if result.get("status") == "ok" and not result.get(
        "expected_room_type_ids"
    ):
        return {
            "status": "data_gap",
            "reason": "stable_room_type_scope_unavailable",
            "hotel_id": result.get("hotel_id"),
            "target_date": result.get("target_date"),
            "formula_version": result.get("formula_version"),
            "policy_version": result.get("policy_version"),
            "selected_tier": result.get("selected_tier"),
            "selected_dates": result.get("selected_dates") or [],
            "data_gaps": list(result.get("data_gaps") or [])
            + ["pms_room_type_hourly_status:stable_scope_unknown"],
        }
    if result.get("status") != "ok":
        return result

    repository = _argument(args, kwargs, "repository", 0)
    hotel_id = str(_argument(args, kwargs, "hotel_id", 1) or result.get("hotel_id") or "")
    target_date = str(
        _argument(args, kwargs, "target_date", 2)
        or result.get("target_date")
        or ""
    )
    as_of_datetime = str(
        _argument(args, kwargs, "as_of_datetime", 3)
        or result.get("as_of_datetime")
        or ""
    )
    if repository is None or not hotel_id or not target_date:
        return result
    return _attach_exact_hour_grid(
        result,
        repository=repository,
        hotel_id=hotel_id,
        target_date=target_date,
        as_of_datetime=as_of_datetime,
    )


def build_deviation(*args: Any, **kwargs: Any) -> dict[str, Any]:
    baseline = kwargs.get("baseline")
    if baseline is None:
        repository = args[0] if args else kwargs.get("repository")
        baseline = build_baseline(
            repository,
            hotel_id=kwargs["hotel_id"],
            target_date=kwargs["target_date"],
            as_of_datetime=kwargs["as_of_datetime"],
            date_contexts=kwargs.get("date_contexts"),
        )
        kwargs["baseline"] = baseline
    if baseline.get("status") != "ok" or not baseline.get(
        "expected_room_type_ids"
    ):
        return {
            "status": "data_gap",
            "reason": baseline.get("reason")
            or "stable_room_type_scope_unavailable",
            "hotel_id": kwargs.get("hotel_id"),
            "target_date": kwargs.get("target_date"),
            "baseline": baseline,
        }
    return _build_deviation(*args, **kwargs)


__all__ = ["build_baseline", "build_deviation"]

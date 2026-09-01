from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from contextlib import closing
from typing import Any

# Retained as import-compatible symbols for callers/tests that patch the legacy adapter.
from runtime.adapters.database import database_source_enabled, database_template_result  # noqa: F401
from runtime.common import DEFAULT_DB, emit, json_dumps, now_local, today
from runtime.sales_progress import DirectSalesProgressRepository, RepositoryError, build_baseline
from runtime.sales_progress.calendar import load_calendar_contexts
from runtime.sales_progress.presentation import attach_s15_user_view
from runtime.storage import connect, init_schema

DEFAULT_HOURLY_ANCHORS = [
    (7, 0.07),
    (10, 0.20),
    (12, 0.34),
    (15, 0.54),
    (16, 0.62),
    (18, 0.74),
    (20, 0.86),
    (22, 1.0),
]
DEFAULT_PROGRESS_CHECKPOINTS = [
    (12, "midday", 0.34),
    (14, "early_afternoon", 0.46),
    (16, "afternoon", 0.62),
    (18, "evening", 0.74),
    (20, "evening_peak", 0.86),
    (22, "close", 1.0),
]


def _hourly_curve(target_room_nights: int) -> list[dict[str, int]]:
    """Legacy advisory helper only; production S15 never uses this curve."""
    result = []
    for hour, ratio in DEFAULT_HOURLY_ANCHORS:
        value = int(round(max(target_room_nights, 0) * ratio))
        result.append({"hour": hour, "target_room_nights": value})
    if result:
        result[-1]["target_room_nights"] = max(target_room_nights, 0)
    return result


def _progress_checkpoints(target_room_nights: int) -> list[dict[str, Any]]:
    result = []
    for hour, name, ratio in DEFAULT_PROGRESS_CHECKPOINTS:
        value = int(round(max(target_room_nights, 0) * ratio))
        result.append(
            {
                "hour": hour,
                "checkpoint": name,
                "checkpoint_target_room_nights": value,
                "target_room_nights": value,
            }
        )
    return result


def _curve_policy(source: str) -> dict[str, Any]:
    historical = source == "pms_room_type_hourly_status"
    return {
        "source": source,
        "default_anchor_curve": source
        in {"derived_default_anchor", "fallback_ratio_curve", "synthetic_sample_curve"},
        "historical_curve": historical,
        "materialized_baseline_available": historical,
        "baseline_status": "real_field_baseline" if historical else "advisory_only",
        "direct_execution_allowed": False,
        "fallback_curve_allows_auto_pricing": False,
        "s16_deviation_allowed": historical,
        "usage": "s15_sales_progress" if historical else "advisory_only_not_s15_baseline",
        "not_allowed_conclusions": []
        if historical
        else ["s16_time_line_or_deviation", "price_candidate_or_task"],
    }


def _target_curve(payload: dict[str, Any]) -> list[dict[str, Any]]:
    target = (payload.get("hotel") or {}).get("effective_target_room_nights")
    points = (payload.get("hotel") or {}).get("hourly_points") or []
    if target is None:
        return []
    curve = []
    for point in points:
        completion = (point.get("target_completion") or {}).get("median")
        expected = float(target) * float(completion) if completion is not None else None
        curve.append(
            {
                "hour": point.get("hour"),
                "target_room_nights": expected,
                "capacity_progress_median": (point.get("capacity") or {}).get("median"),
                "target_completion_median": completion,
                "target_completion_p25": (point.get("target_completion") or {}).get("p25"),
                "target_completion_p80": (point.get("target_completion") or {}).get("p80"),
                "sample_count": max(
                    int((point.get("capacity") or {}).get("sample_count") or 0),
                    int((point.get("target_completion") or {}).get("sample_count") or 0),
                ),
                "maturity": point.get("maturity"),
            }
        )
    return curve


def _with_legacy_aliases(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    if payload.get("status") != "ok":
        result.setdefault("hourly_target_curve", [])
        result.setdefault("hourly_curve", [])
        result.setdefault("progress_checkpoints", [])
        result.setdefault("checkpoint_targets", [])
        result.setdefault("target_orders", None)
        return attach_s15_user_view(result)
    target = (payload.get("hotel") or {}).get("effective_target_room_nights")
    curve = _target_curve(payload)
    checkpoints = [
        row for row in curve if row.get("hour") in {12, 14, 16, 18, 20, 22}
    ]
    for row in checkpoints:
        row["checkpoint_target_room_nights"] = row.get("target_room_nights")
    result.update(
        {
            "business_date": payload.get("target_date"),
            "data_business_date": payload.get("target_date"),
            "target_room_nights": target,
            "target_orders": None,
            "target_orders_basis": "unavailable_orders_not_derivable_from_room_nights",
            "daily_target_room_nights": target,
            "target_occupancy_rate": None,
            "target_daily_occupancy_rate": None,
            "hourly_target_curve": curve,
            "hourly_curve": curve,
            "hourly_curve_source": "pms_room_type_hourly_status",
            "hourly_curve_evidence": {
                "status": "ok",
                "source_table": "pms_room_type_hourly_status",
                "selected_dates": payload.get("selected_dates") or [],
                "selected_tier": payload.get("selected_tier"),
            },
            "hourly_curve_policy": _curve_policy("pms_room_type_hourly_status"),
            "progress_granularity": "hourly",
            "checkpoint_targets": checkpoints,
            "progress_checkpoints": checkpoints,
            "progress_checkpoint_policy": (
                "24-hour real-field curve; 12/14/16/18/20/22 are display "
                "checkpoints only."
            ),
            "sales_baseline": {
                "target_room_nights": target,
                "target_source": "historical_inferred_target",
                "hotel": payload.get("hotel"),
                "room_types": payload.get("room_types"),
            },
            "baseline_confidence": "object_level",
            "source_confidence": "object_level",
            "decision_confidence": "object_level",
            "active_target_source": "historical_inferred_target",
            "sample_target_active": False,
            "sample_target_room_nights": None,
            "synthetic_today_target_room_nights": None,
            "real_business_target_room_nights": target,
            "method": "real_field_sales_progress_v1",
            "data_source": "business_database_fixed_schema",
            "freshness_status": "as_of_bounded",
            "business_status": "historical_baseline",
        }
    )
    return attach_s15_user_view(result)


def _cached_baseline(
    db_path: str,
    hotel_id: str,
    business_date: str,
    *,
    max_age_seconds: int,
) -> dict[str, Any] | None:
    if max_age_seconds <= 0:
        return None
    try:
        with closing(connect(db_path)) as conn:
            init_schema(conn)
            row = conn.execute(
                "SELECT payload_json, created_at FROM baselines "
                "WHERE hotel_id=? AND business_date=? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (hotel_id, business_date),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        created_at = dt.datetime.fromisoformat(str(row["created_at"]))
        age_seconds = max((dt.datetime.now() - created_at).total_seconds(), 0)
        payload = json.loads(str(row["payload_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if age_seconds > max_age_seconds or payload.get("status") != "ok":
        return None
    payload["cache_status"] = "hit"
    payload["cache_age_seconds"] = int(age_seconds)
    return payload


def _persist(
    db_path: str, hotel_id: str, business_date: str, payload: dict[str, Any]
) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO baselines(hotel_id, business_date, payload_json, created_at)
                VALUES(?,?,?,?)
                ON CONFLICT(hotel_id, business_date) DO UPDATE SET
                  payload_json=excluded.payload_json,
                  created_at=excluded.created_at
                """,
                (hotel_id, business_date, json_dumps(payload), now_local()),
            )


def baseline(args: argparse.Namespace) -> None:
    hotel_id = str(args.hotel_id)
    business_date = str(getattr(args, "date", None) or today())[:10]
    as_of = str(getattr(args, "as_of_time", None) or now_local())
    if len(as_of) <= 8 and ":" in as_of:
        as_of = f"{business_date} {as_of}"
    db_path = str(getattr(args, "db", None) or DEFAULT_DB)
    try:
        cache_ttl = int(os.environ.get("HOTEL_OTA_S15_CACHE_TTL_SECONDS", "900"))
    except ValueError:
        cache_ttl = 900
    explicit_as_of = getattr(args, "as_of_time", None) not in (None, "")
    force_rebuild = bool(getattr(args, "force_rebuild", False))
    cached = (
        None
        if explicit_as_of or force_rebuild
        else _cached_baseline(
            db_path, hotel_id, business_date, max_age_seconds=cache_ttl
        )
    )
    if cached is not None:
        payload = _with_legacy_aliases(cached)
        emit(
            {
                "status": payload.get("status"),
                "hotel_id": hotel_id,
                "summary": payload.get("summary"),
                "user_message": payload.get("user_message"),
                "baseline": payload,
            }
        )
        return

    repository = None
    try:
        repository = DirectSalesProgressRepository.from_environment(hotel_id)
        start_date = (
            dt.date.fromisoformat(business_date) - dt.timedelta(days=365)
        ).isoformat()
        date_contexts = load_calendar_contexts(
            db_path, start_date, business_date, business_date
        )
        payload = build_baseline(
            repository,
            hotel_id=hotel_id,
            target_date=business_date,
            as_of_datetime=as_of,
            date_contexts=date_contexts,
        )
    except RepositoryError as exc:
        payload = {
            "status": "data_gap",
            "reason": str(exc),
            "hotel_id": hotel_id,
            "target_date": business_date,
            "as_of_datetime": as_of,
            "data_gaps": [str(exc)],
        }
    finally:
        if repository is not None:
            repository.close()
    payload = _with_legacy_aliases(payload)
    _persist(db_path, hotel_id, business_date, payload)
    emit(
        {
            "status": payload.get("status"),
            "hotel_id": hotel_id,
            "summary": payload.get("summary"),
            "user_message": payload.get("user_message"),
            "baseline": payload,
        }
    )


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "baseline", help="Build S15 real-field sales baseline"
    )
    parser.add_argument("--hotel-id", required=True)
    parser.add_argument("--date")
    parser.add_argument("--as-of-time")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.set_defaults(func=baseline)

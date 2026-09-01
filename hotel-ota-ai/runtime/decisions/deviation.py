from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from contextlib import closing
from typing import Any

# Retained as import-compatible symbols for callers/tests that patch the legacy adapter.
from runtime.adapters.database import database_source_enabled, database_template_result  # noqa: F401
from runtime.common import DEFAULT_DB, emit, now_local, today
from runtime.decisions.progress_diagnosis import build_progress_diagnosis
from runtime.sales_progress import DirectSalesProgressRepository, RepositoryError, build_deviation
from runtime.sales_progress.calendar import load_calendar_contexts
from runtime.sales_progress.presentation import attach_s16_user_view
from runtime.storage import connect


def _latest_baseline(db_path: str, hotel_id: str, business_date: str) -> dict[str, Any] | None:
    try:
        with closing(connect(db_path)) as conn:
            row = conn.execute(
                "SELECT payload_json FROM baselines WHERE hotel_id=? AND business_date=? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (hotel_id, business_date),
            ).fetchone()
    except Exception:
        return None
    if row is None:
        return None
    try:
        return json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None


def _legacy_progress_status(status: str) -> str:
    if status in {"severe_slow", "significant_slow", "slow"}:
        return "behind"
    if status == "normal":
        return "normal"
    if status in {"fast", "significant_fast"}:
        return "ahead"
    return "data_gap"


def _with_legacy_aliases(report: dict[str, Any]) -> dict[str, Any]:
    result = dict(report)
    if report.get("status") not in {"ok", "partial"}:
        result.setdefault("actual_room_nights", None)
        result.setdefault("actual_orders", None)
        result.setdefault("target_room_nights", None)
        result.setdefault("target_orders", None)
        result.setdefault("checkpoint_target_room_nights", None)
        result.setdefault("room_night_gap", None)
        result.setdefault("progress_status", "data_gap")
        result.setdefault("deviation_reasons", [report.get("reason") or "progress_data_gap"])
        result.setdefault("urgency_level", "unknown")
        return attach_s16_user_view(result)
    hotel = report.get("hotel_result") or {}
    target_line = hotel.get("target_line") or {}
    actual = hotel.get("committed_sold")
    target = hotel.get("effective_target_room_nights")
    status = str(target_line.get("status") or "unavailable")
    result.update(
        {
            "actual_room_nights": actual,
            "actual_orders": None,
            "target_room_nights": target,
            "target_orders": None,
            "target_orders_basis": "unavailable_orders_not_derivable_from_room_nights",
            "checkpoint_target_room_nights": target_line.get("expected_sold"),
            "checkpoint_target_orders": None,
            "room_night_gap": target_line.get("room_gap"),
            "order_gap": None,
            "daily_remaining_room_nights": target_line.get("remaining_target_gap"),
            "progress_status": _legacy_progress_status(status),
            "deviation_reasons": [hotel.get("combined_diagnosis")],
            "urgency_level": (
                "high"
                if status in {"severe_slow", "significant_slow"}
                else ("medium" if status == "slow" else "low")
            ),
            "actual_source": "pms_room_type_forecast.committed_sold",
            "actual_basis_date": report.get("target_date"),
            "actual_freshness": "as_of_bounded",
            "today_checked_in_rooms": None,
            "today_reserved_arrival_rooms": None,
        }
    )
    return attach_s16_user_view(result)


def _normalize_as_of(target_date: str, value: Any) -> str:
    if value in (None, ""):
        return now_local()
    text = str(value)
    if len(text) <= 8 and ":" in text:
        return f"{target_date} {text}"
    return text


def deviation(args: argparse.Namespace) -> None:
    hotel_id = str(args.hotel_id)
    target_date = str(getattr(args, "date", None) or today())[:10]
    raw_as_of = getattr(args, "as_of_time", None)
    as_of = _normalize_as_of(target_date, raw_as_of)
    db_path = str(getattr(args, "db", None) or DEFAULT_DB)
    use_generated_today = bool(getattr(args, "use_generated_today", False))
    strict_generated_today = bool(getattr(args, "strict_generated_today", False))
    if use_generated_today or strict_generated_today or os.environ.get("HOTEL_OTA_DEMO_MODE") == "1":
        emit(
            build_progress_diagnosis(
                db_path=db_path,
                hotel_id=hotel_id,
                business_date=target_date,
                as_of_time=raw_as_of,
                use_generated_today=True,
                strict_generated_today=strict_generated_today,
            )
        )
        return

    baseline_payload = _latest_baseline(db_path, hotel_id, target_date)
    repository = None
    try:
        repository = DirectSalesProgressRepository.from_environment(hotel_id)
        start_date = (dt.date.fromisoformat(target_date) - dt.timedelta(days=365)).isoformat()
        date_contexts = load_calendar_contexts(db_path, start_date, target_date, target_date)
        report = build_deviation(
            repository,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_datetime=as_of,
            baseline=baseline_payload,
            date_contexts=date_contexts,
        )
    except RepositoryError as exc:
        report = {
            "status": "data_gap",
            "reason": str(exc),
            "hotel_id": hotel_id,
            "target_date": target_date,
            "as_of_datetime": as_of,
        }
    finally:
        if repository is not None:
            repository.close()
    if baseline_payload:
        report.setdefault(
            "target_source",
            baseline_payload.get("active_target_source")
            or baseline_payload.get("target_source")
            or "historical_inferred_target",
        )
    else:
        report.setdefault("target_source", "historical_inferred_target")
    emit(_with_legacy_aliases(report))


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("deviation", help="Build S16 real-field progress deviation")
    parser.add_argument("--hotel-id", required=True)
    parser.add_argument("--date")
    parser.add_argument("--as-of-time")
    parser.add_argument("--use-generated-today", action="store_true")
    parser.add_argument("--strict-generated-today", action="store_true")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.set_defaults(func=deviation)

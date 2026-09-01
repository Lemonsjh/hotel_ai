from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit, today


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("payload") if isinstance(result.get("payload"), dict) else {}


def _business_date(row: dict[str, Any], fallback: str) -> str:
    value = row.get("business_date") or row.get("date") or row.get("stat_date") or fallback
    return str(value)[:10]


def _rs01_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("rows") or payload.get("records") or payload.get("room_fee_daily_rows") or []
    return [dict(item) for item in rows if isinstance(item, dict)]


def jy01_rs01_alignment_result(args: argparse.Namespace) -> dict[str, Any]:
    business_date = str(getattr(args, "date", None) or today())[:10]
    if not database_source_enabled():
        return {
            "status": "data_gap",
            "reason": "database_source_disabled",
            "hotel_id": args.hotel_id,
            "business_date": business_date,
        }

    jy01 = database_template_result("daily_metrics", args.hotel_id, date=business_date)
    rs01 = database_template_result("room_fee_daily", args.hotel_id, date=business_date)
    jy01_payload = _payload(jy01)
    rs01_payload = _payload(rs01)
    normalized = jy01_payload.get("normalized_metrics") or {}
    jy01_date = str(jy01_payload.get("data_business_date") or business_date)[:10]
    jy01_room_count = _to_float(normalized.get("room_count"))
    jy01_room_nights = _to_float(normalized.get("room_nights"))

    fee_only_by_date: dict[str, float] = defaultdict(float)
    all_by_date: dict[str, float] = defaultdict(float)
    excluded_subjects: set[str] = set()
    for row in _rs01_rows(rs01_payload):
        date_key = _business_date(row, business_date)
        room_nights = _to_float(row.get("room_nights") or row.get("room_night_count") or row.get("nights"))
        charge_subject = str(row.get("charge_subject") or row.get("subject") or "").strip()
        all_by_date[date_key] += room_nights
        if charge_subject == "房费":
            fee_only_by_date[date_key] += room_nights
        else:
            excluded_subjects.add(charge_subject or "missing_charge_subject")

    if not fee_only_by_date and rs01_payload.get("room_nights") is not None:
        fee_only_by_date[business_date] = _to_float(rs01_payload.get("room_nights"))
        all_by_date[business_date] = _to_float(rs01_payload.get("room_nights"))

    rs01_fee_only = fee_only_by_date.get(jy01_date, fee_only_by_date.get(business_date, 0.0))
    rs01_all = all_by_date.get(jy01_date, all_by_date.get(business_date, rs01_fee_only))
    difference = round(jy01_room_nights - rs01_fee_only, 4)
    match_status = "match" if abs(difference) < 0.0001 else "mismatch"
    diagnostics = []
    if excluded_subjects:
        diagnostics.append("rs01_non_room_fee_charge_subjects_excluded")
    if abs(rs01_all - rs01_fee_only) >= 0.0001:
        diagnostics.append("rs01_unfiltered_total_differs_from_room_fee_only")

    row = {
        "business_date": jy01_date,
        "jy01_room_count": int(jy01_room_count) if jy01_room_count.is_integer() else jy01_room_count,
        "jy01_room_nights": int(jy01_room_nights) if jy01_room_nights.is_integer() else jy01_room_nights,
        "rs01_room_nights_room_fee_only": int(rs01_fee_only) if rs01_fee_only.is_integer() else rs01_fee_only,
        "rs01_room_nights_all_charge_subjects": int(rs01_all) if rs01_all.is_integer() else rs01_all,
        "difference": int(difference) if float(difference).is_integer() else difference,
        "match_status": match_status,
    }
    return {
        "status": "ok" if jy01.get("status") == "ok" and rs01.get("status") == "ok" else "data_gap",
        "hotel_id": args.hotel_id,
        "business_date": business_date,
        "alignment_rows": [row],
        "diagnostics": diagnostics,
        "source_templates": ["daily_metrics", "room_fee_daily"],
        "source_granularity": {
            "jy01": "historical_daily",
            "rs01": "historical_daily_detail_room_fee_only",
            "realtime": "not_used",
        },
        "database_evidence_status": {
            "daily_metrics": jy01.get("status"),
            "room_fee_daily": rs01.get("status"),
        },
    }


def jy01_rs01_alignment(args: argparse.Namespace) -> None:
    emit(jy01_rs01_alignment_result(args))

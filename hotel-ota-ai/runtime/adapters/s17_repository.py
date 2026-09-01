from __future__ import annotations

import argparse
import datetime as dt
import os
from collections import Counter
from typing import Any

from runtime.algorithms.customer_arrival import aggregate_arrivals
from runtime.algorithms.customer_order import (
    aggregate_bookings,
    aggregate_extensions,
    aggregate_realized,
    suppress_cells,
)


CORE_TABLES = {
    "booking": "reservation_snapshot",
    "realized": "room_fee_daily",
    "extension": "stayover_snapshot",
}
PROVIDER_TABLES = {
    "meituan_scan_order": "meituan_scan_order_detail",
    "meituan_monthly_background": "meituan_user_source_monthly",
    "provider_order_detail": "ctrip_order_detail",
    "provider_profile_background": "ctrip_userprofile_distribution",
    "meituan_loss": "meituan_order_loss_monthly",
    "ctrip_loss": "ctrip_order_loss_monthly",
    "room_mix_background": "room_type_classification",
}


def _parse_datetime(value: Any, fallback: dt.datetime) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return fallback


def _identifier(value: str) -> str:
    from runtime.adapters.database import _safe_identifier

    return _safe_identifier(value, "identifier")


def _mapped_rows(
    conn: Any,
    profile: dict[str, Any],
    table_key: str,
    hotel_id: str,
    *,
    as_of: dt.datetime,
    fields: tuple[str, ...],
    extra_where: list[tuple[str, str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tables = profile.get("tables") if isinstance(profile.get("tables"), dict) else {}
    columns_by_table = profile.get("columns") if isinstance(profile.get("columns"), dict) else {}
    table = tables.get(table_key)
    columns = columns_by_table.get(table_key) if isinstance(columns_by_table.get(table_key), dict) else {}
    if not table:
        return [], {"status": "unavailable", "reason": "table_mapping_missing", "table_key": table_key}
    if not columns.get("hotel_id"):
        return [], {"status": "schema_drift", "reason": "exact_hotel_id_column_required", "table_key": table_key}
    selected = [field for field in fields if columns.get(field)]
    if not selected:
        return [], {"status": "schema_drift", "reason": "no_approved_columns_mapped", "table_key": table_key}
    projection = [f"{_identifier(columns[field])} AS `{field}`" for field in selected]
    where = [f"{_identifier(columns['hotel_id'])} = %s"]
    params: list[Any] = [hotel_id]
    if columns.get("snapshot_time"):
        where.append(f"{_identifier(columns['snapshot_time'])} <= %s")
        params.append(as_of.strftime("%Y-%m-%d %H:%M:%S"))
    for canonical, operator, value in extra_where or []:
        physical = columns.get(canonical)
        if not physical:
            continue
        where.append(f"{_identifier(physical)} {operator} %s")
        params.append(value)
    sql = f"SELECT {', '.join(projection)} FROM {_identifier(table)} WHERE {' AND '.join(where)}"
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        return [], {
            "status": "schema_drift",
            "reason": "s17_source_query_failed",
            "table_key": table_key,
            "error_type": exc.__class__.__name__,
        }
    return rows, {"status": "ok", "table_key": table_key, "source_table": table, "row_count": len(rows)}


def _provider_scan(rows: list[dict[str, Any]], minimum: int) -> dict[str, Any]:
    latest: dict[str, tuple[dt.datetime, dict[str, Any]]] = {}
    for row in rows:
        key = str(row.get("order_id") or "")
        if key:
            captured = _parse_datetime(row.get("snapshot_time"), dt.datetime.min)
            if key not in latest or captured > latest[key][0]:
                latest[key] = (captured, row)
    buckets: Counter[str] = Counter()
    amounts: Counter[str] = Counter()
    mapping = {"门店新客": "provider_new", "酒店新客": "provider_new", "门店老客": "provider_returning"}
    for _, row in latest.values():
        bucket = mapping.get(str(row.get("user_type") or "").strip(), "unknown")
        buckets[bucket] += 1
        try:
            amounts[bucket] += float(row.get("paid_amount") or 0)
        except (TypeError, ValueError):
            pass
    cells, suppressed = suppress_cells(
        [{"bucket": key, "order_count": value, "paid_amount": round(amounts[key], 2)} for key, value in buckets.items()],
        count_field="order_count", minimum_cohort_size=minimum, max_output_cells=20,
    )
    return {"population_id": "meituan_scan_order", "cells": cells, "suppressed_cell_count": suppressed, "total_orders": len(latest)}


def _provider_orders(rows: list[dict[str, Any]], minimum: int) -> dict[str, Any]:
    latest: dict[tuple[str, str], tuple[dt.datetime, dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("platform_scope") or "unknown"), str(row.get("form_id") or ""))
        if key[1]:
            captured = _parse_datetime(row.get("snapshot_time"), dt.datetime.min)
            if key not in latest or captured > latest[key][0]:
                latest[key] = (captured, row)
    counts: Counter[str] = Counter()
    rooms: Counter[str] = Counter()
    nights: Counter[str] = Counter()
    for (scope, _), (_, row) in latest.items():
        counts[scope] += 1
        rooms[scope] += int(row.get("room_count") or 0)
        nights[scope] += int(row.get("room_nights") or 0)
    cells, suppressed = suppress_cells(
        [{"platform_scope": key, "order_count": value, "room_count": rooms[key], "room_nights": nights[key]} for key, value in counts.items()],
        count_field="order_count", minimum_cohort_size=minimum, max_output_cells=20,
    )
    return {"population_id": "provider_order_detail", "cells": cells, "suppressed_cell_count": suppressed, "hotel_level_only": True}


def _background(rows: list[dict[str, Any]], population_id: str, minimum: int) -> dict[str, Any]:
    cells = []
    unknown_denominator = 0
    for row in rows:
        denominator = row.get("cohort_size") or row.get("sample_count") or row.get("denominator")
        try:
            cohort = int(denominator)
        except (TypeError, ValueError):
            unknown_denominator += 1
            continue
        if cohort < minimum:
            continue
        cells.append({
            "dimension_code": row.get("dimension_code") or row.get("dimension_name") or row.get("metric_name"),
            "bucket_label": row.get("bucket_label") or row.get("user_type") or row.get("metric_value_name"),
            "rate": row.get("rate") or row.get("rate_pct") or row.get("metric_value"),
            "privacy_cohort_size": cohort,
            "suppression_status": "visible",
        })
    return {
        "population_id": population_id,
        "cells": cells[:20],
        "unknown_denominator_count": unknown_denominator,
        "status": "ok" if cells else "unavailable",
        "reason": None if cells else "privacy_cohort_size_unknown_or_below_threshold",
    }


def _loss(rows: list[dict[str, Any]], population_id: str) -> dict[str, Any]:
    periods: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("source_platform") or population_id), str(row.get("period_start_date") or ""), str(row.get("period_end_date") or ""))
        periods.setdefault(key, []).append(row)
    if not periods:
        return {"population_id": population_id, "status": "unavailable"}
    key = sorted(periods)[-1]
    selected = periods[key]
    total_orders = {row.get("total_loss_order_count") for row in selected if row.get("total_loss_order_count") is not None}
    total_nights = {row.get("total_loss_room_night_count") for row in selected if row.get("total_loss_room_night_count") is not None}
    total_amounts = {row.get("total_loss_order_amount") for row in selected if row.get("total_loss_order_amount") is not None}
    if any(len(values) > 1 for values in (total_orders, total_nights, total_amounts)):
        return {"population_id": population_id, "status": "metric_conflict", "period_start": key[1], "period_end": key[2]}
    return {
        "population_id": population_id,
        "status": "ok",
        "metric_kind": "provider_order_loss_proxy",
        "period_start": key[1], "period_end": key[2],
        "provider_loss_orders": next(iter(total_orders), None),
        "provider_loss_room_nights": next(iter(total_nights), None),
        "provider_loss_amount": next(iter(total_amounts), None),
    }


def query_mysql_s17(conn: Any, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    now = dt.datetime.now()
    as_of = _parse_datetime(getattr(args, "as_of_time", None), now)
    requested_end = _parse_datetime(getattr(args, "period_end", None), as_of)
    if requested_end.time() == dt.time.min:
        requested_end += dt.timedelta(days=1)
    window_end = min(requested_end, as_of)
    default_start = window_end - dt.timedelta(days=30)
    window_start = _parse_datetime(getattr(args, "period_start", None), default_start)
    if not window_start < window_end:
        return {"status": "blocked", "reason": "invalid_s17_window"}
    window_days = (window_end - window_start).total_seconds() / 86400
    if window_days < 7 or window_days > 365:
        return {"status": "blocked", "reason": "s17_window_outside_policy", "allowed_window_days": [7, 365]}
    minimum = int(getattr(args, "minimum_cohort_size", None) or os.environ.get("HOTEL_OTA_S17_MIN_COHORT_SIZE", "5"))
    maximum = int(getattr(args, "max_output_cells", None) or os.environ.get("HOTEL_OTA_S17_MAX_OUTPUT_CELLS", "100"))
    if minimum < 3 or minimum > 100 or maximum < 10 or maximum > 500:
        return {"status": "blocked", "reason": "invalid_s17_privacy_policy"}

    booking_fields = (
        "hotel_id", "source_platform", "order_id", "booking_time", "arrival_time", "departure_time", "room_type_id",
        "room_count", "booking_status", "guest_source", "member_level", "contact", "snapshot_time",
    )
    realized_fields = (
        "hotel_id", "source_platform", "order_id", "room_no", "charge_subject", "business_date", "customer_source",
        "room_type_id", "room_type_name", "room_nights", "room_fee", "snapshot_time",
    )
    extension_fields = (
        "hotel_id", "source_platform", "order_id", "room_no", "room_type_id", "checkin_time", "original_checkout_time", "checkout_time", "snapshot_time",
    )
    bookings, booking_meta = _mapped_rows(conn, profile, CORE_TABLES["booking"], args.hotel_id, as_of=as_of, fields=booking_fields)
    realized, realized_meta = _mapped_rows(conn, profile, CORE_TABLES["realized"], args.hotel_id, as_of=as_of, fields=realized_fields)
    extensions, extension_meta = _mapped_rows(conn, profile, CORE_TABLES["extension"], args.hotel_id, as_of=as_of, fields=extension_fields)
    sources = {"booking": booking_meta, "realized": realized_meta, "extension": extension_meta}
    secret = os.environ.get("HOTEL_OTA_S17_CONTACT_HMAC_SECRET")
    populations: dict[str, Any] = {
        "pms_booking_created": aggregate_bookings(
            bookings,
            hotel_id=args.hotel_id,
            window_start=window_start,
            window_end=window_end,
            as_of=as_of,
            contact_hmac_secret=secret,
            contact_lookup_value=getattr(args, "contact_lookup_value", None),
        ),
        "pms_arrival_cohort": aggregate_arrivals(
            bookings,
            hotel_id=args.hotel_id,
            window_start=window_start,
            window_end=window_end,
            as_of=as_of,
        ),
        "realized_stay": aggregate_realized(realized, hotel_id=args.hotel_id, window_start=window_start, window_end=window_end, as_of=as_of),
        "extension_reconciliation": aggregate_extensions(extensions, hotel_id=args.hotel_id, as_of=as_of),
    }
    provider_fields = {
        "meituan_scan_order": ("hotel_id", "order_id", "scan_time", "user_type", "paid_amount", "snapshot_time"),
        "meituan_monthly_background": ("hotel_id", "dimension_code", "bucket_label", "rate_pct", "cohort_size", "period_end_date", "snapshot_time"),
        "provider_order_detail": ("hotel_id", "platform_scope", "form_id", "booking_time", "arrival_date", "room_count", "room_nights", "order_status", "snapshot_time"),
        "provider_profile_background": ("hotel_id", "platform_scope", "dimension_code", "bucket_label", "rate_pct", "cohort_size", "snapshot_time"),
        "meituan_loss": ("hotel_id", "source_platform", "period_start_date", "period_end_date", "total_loss_order_count", "total_loss_room_night_count", "total_loss_order_amount", "snapshot_time"),
        "ctrip_loss": ("hotel_id", "source_platform", "period_start_date", "period_end_date", "total_loss_order_count", "total_loss_room_night_count", "total_loss_order_amount", "snapshot_time"),
        "room_mix_background": ("hotel_id", "period_start_date", "period_end_date", "section", "dimension_code", "room_type_id", "room_nights", "snapshot_time"),
    }
    for population_id, table_key in PROVIDER_TABLES.items():
        rows, meta = _mapped_rows(conn, profile, table_key, args.hotel_id, as_of=as_of, fields=provider_fields[population_id])
        if population_id == "meituan_scan_order":
            rows = [row for row in rows if window_start <= _parse_datetime(row.get("scan_time"), dt.datetime.min) < window_end]
        elif population_id == "provider_order_detail":
            rows = [
                row for row in rows
                if window_start <= _parse_datetime(row.get("booking_time") or row.get("arrival_date"), dt.datetime.min) < window_end
            ]
        elif population_id in {"meituan_monthly_background", "meituan_loss", "ctrip_loss", "room_mix_background"}:
            rows = [row for row in rows if _parse_datetime(row.get("period_end_date"), dt.datetime.min) <= as_of]
        sources[population_id] = meta
        if meta.get("status") != "ok":
            populations[population_id] = {"population_id": population_id, "status": "unavailable", "reason": meta.get("reason")}
        elif population_id == "meituan_scan_order":
            populations[population_id] = _provider_scan(rows, minimum)
        elif population_id == "provider_order_detail":
            populations[population_id] = _provider_orders(rows, minimum)
        elif population_id in {"meituan_monthly_background", "provider_profile_background"}:
            populations[population_id] = _background(rows, population_id, minimum)
        elif population_id in {"meituan_loss", "ctrip_loss"}:
            populations[population_id] = _loss(rows, population_id)
        else:
            populations[population_id] = {"population_id": population_id, "status": "available_for_cross_check", "row_count": len(rows)}

    booking_matrix = populations["pms_booking_created"].get("booking_matrix") or []
    visible_matrix, suppressed = suppress_cells(
        booking_matrix, count_field="created_order_count", minimum_cohort_size=minimum, max_output_cells=maximum
    )
    populations["pms_booking_created"]["booking_matrix"] = visible_matrix
    populations["pms_booking_created"]["suppressed_booking_matrix_cell_count"] = suppressed
    booking_population = populations["pms_booking_created"]
    booking_columns = ((profile.get("columns") or {}).get(CORE_TABLES["booking"]) or {})
    mapping_gaps: list[str] = []
    if not booking_columns.get("member_level"):
        booking_population["booking_channel_status"] = "unavailable"
        booking_population["booking_channel_reason"] = "booking_channel_field_mapping_missing"
        booking_population["booking_channel_order_distribution"] = []
        booking_population["booking_channel_room_distribution"] = []
        mapping_gaps.append("booking_channel_field_mapping_missing")
    else:
        booking_population["booking_channel_status"] = "ok"
        booking_population["booking_channel_reason"] = None
    distribution_policies = {
        "booking_channel_order_distribution": "value",
        "booking_channel_room_distribution": "value",
        "guest_source_order_distribution": "value",
        "room_type_order_distribution": "value",
        "room_type_room_distribution": "value",
        "lead_time_buckets": "value",
        "stay_duration_buckets": "value",
    }
    for field, count_field in distribution_policies.items():
        cells, field_suppressed = suppress_cells(
            booking_population.get(field) or [], count_field=count_field,
            minimum_cohort_size=minimum, max_output_cells=maximum,
        )
        booking_population[field] = cells
        booking_population[f"suppressed_{field}_cell_count"] = field_suppressed
    contact_proxy = booking_population.get("contact_proxy") or {}
    contact_cells, contact_suppressed = suppress_cells(
        contact_proxy.get("contact_frequency_distribution") or [], count_field="value",
        minimum_cohort_size=minimum, max_output_cells=maximum,
    )
    contact_proxy["contact_frequency_distribution"] = contact_cells
    contact_proxy["suppressed_contact_frequency_cell_count"] = contact_suppressed

    arrival_population = populations["pms_arrival_cohort"]
    for field in ("room_type_order_distribution", "room_type_room_distribution", "stay_duration_buckets"):
        cells, field_suppressed = suppress_cells(
            arrival_population.get(field) or [],
            count_field="value",
            minimum_cohort_size=minimum,
            max_output_cells=maximum,
        )
        arrival_population[field] = cells
        arrival_population[f"suppressed_{field}_cell_count"] = field_suppressed

    for population_id, field, count_field in (
        ("realized_stay", "source_distribution", "record_count"),
        ("realized_stay", "room_type_distribution", "record_count"),
        ("extension_reconciliation", "room_type_distribution", "active_extension_records"),
    ):
        population = populations[population_id]
        cells, field_suppressed = suppress_cells(
            population.get(field) or [], count_field=count_field,
            minimum_cohort_size=minimum, max_output_cells=maximum,
        )
        population[field] = cells
        population[f"suppressed_{field}_cell_count"] = field_suppressed
    unavailable = [key for key, value in sources.items() if value.get("status") != "ok"]
    contact_gap = booking_population.get("contact_proxy", {}).get("reason")
    return {
        "status": "ok" if booking_meta.get("status") == "ok" else "data_gap",
        "hotel_id": args.hotel_id,
        "window_start": window_start.isoformat(sep=" "),
        "window_end": window_end.isoformat(sep=" "),
        "as_of_datetime": as_of.isoformat(sep=" "),
        "privacy_policy": {
            "policy_key": "s17_privacy_policy",
            "policy_version": "s17-privacy.v1",
            "minimum_cohort_size": minimum,
            "max_output_cells": maximum,
            "window_days": round(window_days, 4),
        },
        "populations": populations,
        "source_status": sources,
        "data_gaps": unavailable + mapping_gaps + ([contact_gap] if contact_gap else []),
        "direct_action_allowed": False,
        "row_level_export_allowed": False,
        "raw_contact_included": False,
        "raw_order_rows_included": False,
    }

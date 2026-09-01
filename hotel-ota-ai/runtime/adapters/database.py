from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from typing import Any

from runtime.adapters.normalized_query import build_room_mapping_index, normalize_rows_for_template, normalize_source_platform
from runtime.common import DEFAULT_DB, DEFAULT_LOG_DIR, emit, json_dumps, now_local, redacted_request
from runtime.contracts import validate_contract


DB_KINDS = ("sqlite", "mysql", "postgres")
TEMPLATES = (
    "operating_snapshot",
    "price_snapshot",
    "order_snapshot",
    "customer_order_analysis",
    "demand_context",
    "operation_diagnosis",
    "sales_baseline",
    "daily_metrics",
    "monthly_metrics",
    "reservation_snapshot",
    "stayover_snapshot",
    "room_status_snapshot",
    "room_fee_daily",
    "plugin_status",
    "plugin_run_log",
    "ota_business_metrics",
    "ota_price_mapping",
    "ota_order_loss_monthly",
    "ctrip_competition_metrics_30d",
    "ota_activity_summary",
    "ota_activity_product_detail",
    "ota_promotion_performance_30d",
    "ota_joined_rights",
    "ctrip_psi_metrics",
    "ota_review_overview",
    "ota_review_ranking",
    "price_task_queue",
)
INSPECT_MODES = ("connection", "tables", "columns", "sample", "mapping-draft")
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
SENSITIVE_FIELD_PATTERNS = (
    "password",
    "token",
    "secret",
    "mobile",
    "phone",
    "id_card",
    "guest_name",
    "room_no",
    "order_id",
    "order_no",
    "operator_name",
    "metadata_json",
    "product_cipher",
    "contact",
)
PUBLIC_REVIEW_TEXT_FIELDS = {
    "review_text",
    "review_content",
    "comment_content",
    "comment",
    "public_review_text",
    "public_comment",
}
DAILY_PERIOD_TYPE_ALIASES = ("本日", "今日", "当天", "当日", "日", "day", "daily", "today", "current_day")

CANONICAL_FIELD_HINTS: dict[str, tuple[str, ...]] = {
    "hotel_id": ("hotel_id", "hotel_name", "property_id"),
    "business_date": ("business_date", "date", "snapshot_date", "report_date"),
    "room_type_id": ("room_type_id", "room_type", "roomtype"),
    "current_price": ("current_price", "daily_price", "normal_price", "rack_rate"),
    "available_rooms": ("available_rooms", "remaining_rooms", "inventory"),
    "sold_rooms": ("sold_rooms", "occupied_rooms", "room_nights"),
    "payment_conversion_rate": ("payment_conversion_rate", "pay_conversion_rate", "conversion_rate"),
    "rating_total": ("rating_total", "rating", "review_score"),
    "order_id": ("order_id", "booking_id", "reservation_id"),
    "room_nights": ("room_nights", "nights", "stay_nights"),
    "inventory": ("inventory", "available_rooms", "remaining_rooms"),
    "review_text": ("review_text", "comment", "review_content"),
    "review_sentiment": ("review_sentiment", "sentiment", "review_label"),
    "updated_at": ("updated_at", "update_time", "modified_at", "last_updated"),
}

INSPECT_DATE_EXACT_FIELDS = {
    "business_date",
    "snapshot_date",
    "report_date",
    "data_date",
    "stat_date",
    "created_at",
    "updated_at",
    "snapshot_time",
    "data_snapshot_time",
    "booking_time",
    "arrival_time",
    "departure_time",
    "checkin_time",
    "checkout_time",
    "original_checkout_time",
    "op_time",
    "started_at",
    "finished_at",
    "event_start_date",
    "event_end_date",
    "last_cookie_update_at",
    "last_invalid_at",
}
INSPECT_NON_DATE_TOKENS = ("type", "status", "count", "days", "rate", "price", "amount", "name", "id")

TEMPLATE_REQUIRED_CANONICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "operating_snapshot": ("hotel_id", "business_date", "available_rooms", "sold_rooms"),
    "price_snapshot": ("hotel_id", "room_type_id", "current_price"),
    "order_snapshot": ("hotel_id", "business_date"),
    "reservation_snapshot": ("hotel_id", "business_date"),
    "stayover_snapshot": ("hotel_id", "business_date"),
    "operation_diagnosis": ("hotel_id", "business_date", "payment_conversion_rate", "rating_total"),
    "sales_baseline": ("hotel_id", "business_date", "sold_rooms"),
    "plugin_status": ("hotel_id",),
    "plugin_run_log": ("hotel_id",),
    "ota_business_metrics": ("hotel_id", "business_date"),
    "ota_price_mapping": ("hotel_id", "room_type_id", "current_price"),
    "ota_order_loss_monthly": ("hotel_id",),
    "ctrip_competition_metrics_30d": ("hotel_id",),
    "ota_activity_summary": ("hotel_id",),
    "ota_activity_product_detail": ("hotel_id", "room_type_id"),
    "ota_promotion_performance_30d": ("hotel_id",),
    "ota_joined_rights": ("hotel_id",),
    "ctrip_psi_metrics": ("hotel_id",),
    "ota_review_overview": ("hotel_id",),
    "ota_review_ranking": ("hotel_id",),
    "price_task_queue": ("hotel_id", "business_date", "room_type_id", "current_price"),
}

V4_TEMPLATE_TABLE_KEYS: dict[str, tuple[str, ...]] = {
    "plugin_status": ("plugin_auth_status",),
    "plugin_run_log": ("plugin_run_log",),
    "ota_business_metrics": ("ctrip_business_metrics", "meituan_business_metrics"),
    "ota_price_mapping": ("ctrip_price_mapping", "meituan_price_mapping"),
    "ota_order_loss_monthly": ("ctrip_order_loss_monthly", "meituan_order_loss_monthly"),
    "ctrip_competition_metrics_30d": ("ctrip_competition_metrics_30d",),
    "ota_activity_summary": ("ctrip_promotion_activity", "meituan_promotion_activity"),
    "ota_activity_product_detail": ("ctrip_activity_product_detail", "meituan_activity_product_detail"),
    "ota_promotion_performance_30d": ("ctrip_promotion_performance_30d", "meituan_promotion_performance_30d"),
    "ota_joined_rights": ("ctrip_joined_rights", "meituan_joined_rights"),
    "ctrip_psi_metrics": ("ctrip_psi_metric", "ctrip_psi_score"),
    "ota_review_overview": ("ctrip_review_overview", "meituan_review_overview"),
    "ota_review_ranking": ("ctrip_review_ranking", "meituan_review_ranking"),
    "price_task_queue": ("ctrip_price_task", "meituan_price_task"),
}

# These templates are consumed as read-only evidence panels.  The default
# page size is fine for operational rows, but is too small to describe an
# activity catalogue or a vertical metric set without silently truncating it.
# The renderer still emits only compact aggregates.
V4_TEMPLATE_RESULT_LIMITS: dict[str, int] = {
    "ota_business_metrics": 500,
    "ota_activity_summary": 100,
    "ota_activity_product_detail": 500,
    "ota_promotion_performance_30d": 500,
}

# The S2 production query is a fixed PMS schema contract. Connection target
# selection remains private deployment configuration, but table/column mapping
# must not decide which operating algorithm runs.
PMS_S2_FORECAST_CONTRACT: dict[str, Any] = {
    "tables": {"pms_room_type_forecast": "pms_room_type_forecast"},
    "columns": {
        "pms_room_type_forecast": {
            "hotel_id": "hotel_id",
            "snapshot_time": "snapshot_time",
            "stay_date": "stay_date",
            "room_type_id": "room_type_id",
            "room_type_name": "room_type_name",
            "total_rooms": "total_rooms",
            "available_rooms": "available_rooms",
            "occupied_rooms": "occupied_rooms",
            "overbooking_rooms": "overbooking_rooms",
            "room_revenue": "room_revenue",
            "adr": "adr",
            "revpar": "revpar",
        }
    },
}


def infer_canonical_field_candidates(columns: list[str]) -> dict[str, list[str]]:
    """Return conservative name-based candidates; never map values or query data."""
    safe_columns = [str(column) for column in columns if str(column).lower() not in SENSITIVE_FIELD_PATTERNS]
    result: dict[str, list[str]] = {}
    for canonical, hints in CANONICAL_FIELD_HINTS.items():
        matches = [column for column in safe_columns if column.lower() in hints]
        if matches:
            result[canonical] = matches
    return result


def _has_any_column(column_names: list[str], *names: str) -> bool:
    lowered = {str(column).lower() for column in column_names}
    return any(name.lower() in lowered for name in names)


def _is_inspect_date_candidate(column_name: str) -> bool:
    name = str(column_name or "").lower()
    if not name:
        return False
    if name in INSPECT_DATE_EXACT_FIELDS:
        return True
    if any(token in name for token in INSPECT_NON_DATE_TOKENS):
        return False
    return name.endswith("_date") or name.endswith("_time") or name.endswith("_at")


def _inspect_table_readiness(
    *,
    table_name: str,
    column_names: list[str],
    row_count_estimate: Any,
    latest_business_date: Any = None,
    updated_at: Any = None,
) -> dict[str, Any]:
    row_count = row_count_estimate
    has_hotel_id = _has_any_column(column_names, "hotel_id")
    has_hotel_name = _has_any_column(column_names, "hotel_name")
    has_room_type_id = _has_any_column(column_names, "room_type_id", "pms_room_type_id")
    has_room_type_name = _has_any_column(column_names, "room_type_name", "pms_room_type_name")
    has_source_platform = _has_any_column(column_names, "source_platform", "channel_source")
    has_source_room_type_id = _has_any_column(column_names, "source_room_type_id", "ota_room_type_id")
    has_source_product_id = _has_any_column(column_names, "source_product_id", "ota_product_id")
    has_business_date = _has_any_column(column_names, "business_date")
    risk_flags: list[str] = []
    if not has_hotel_id and has_hotel_name:
        risk_flags.append("hotel_name_legacy")
    if (has_room_type_name or has_source_room_type_id) and not has_room_type_id:
        risk_flags.append("room_type_mapping_pending")
    if has_source_product_id and not has_room_type_id:
        risk_flags.append("source_product_mapping_requires_room_type")
    try:
        numeric_rows = int(row_count or 0)
    except (TypeError, ValueError):
        numeric_rows = None
    if numeric_rows == 0:
        data_status = "empty"
    elif has_hotel_id and (has_business_date or has_source_product_id or has_room_type_id):
        data_status = "ready"
    elif has_hotel_name or has_business_date or has_source_platform or has_room_type_name or has_source_room_type_id:
        data_status = "partial"
    else:
        data_status = "schema_drift"
    return {
        "table_name": table_name,
        "has_hotel_id": has_hotel_id,
        "has_hotel_name": has_hotel_name,
        "has_room_type_id": has_room_type_id,
        "has_room_type_name": has_room_type_name,
        "has_source_platform": has_source_platform,
        "has_source_room_type_id": has_source_room_type_id,
        "has_source_product_id": has_source_product_id,
        "has_business_date": has_business_date,
        "latest_business_date": str(latest_business_date) if latest_business_date not in (None, "") else None,
        "row_count_estimate": row_count,
        "updated_at": str(updated_at) if updated_at not in (None, "") else None,
        "data_status": data_status,
        "risk_flags": risk_flags,
    }


def validate_canonical_mapping_profile(profile: dict[str, Any], *, required_fields: list[str]) -> dict[str, Any]:
    mapping = profile.get("canonical_fields") if isinstance(profile, dict) else None
    if not isinstance(mapping, dict) or not profile.get("mapping_version"):
        return {"status": "data_gap", "reason": "mapping_profile_invalid", "missing_fields": list(required_fields)}
    missing = [field for field in required_fields if not mapping.get(field)]
    return {
        "status": "ok" if not missing else "data_gap",
        "reason": None if not missing else "canonical_mapping_incomplete",
        "missing_fields": missing,
        "mapping_version": profile.get("mapping_version"),
    }


def inspect_canonical_mapping_draft(columns: list[dict[str, Any]], *, table: str) -> dict[str, Any]:
    """Create a non-binding mapping suggestion from read-only metadata only."""
    names = [str(column.get("column_name") or "") for column in columns]
    candidates = infer_canonical_field_candidates(names)
    required = ["hotel_id", "business_date"]
    missing = [field for field in required if not candidates.get(field)]
    template_readiness = {
        template: {
            "status": "ok" if not (template_missing := [field for field in fields if not candidates.get(field)]) else "data_gap",
            "missing_fields": template_missing,
        }
        for template, fields in TEMPLATE_REQUIRED_CANONICAL_FIELDS.items()
    }
    annotated = []
    for column in columns:
        item = dict(column)
        name = str(item.get("column_name") or "")
        item["sensitive"] = any(token in name.lower() for token in SENSITIVE_FIELD_PATTERNS)
        item["canonical_candidates"] = [field for field, matches in candidates.items() if name in matches]
        annotated.append(item)
    return {
        "status": "ok" if not missing else "data_gap",
        "table": table,
        "mapping_version": "candidate_draft_v1",
        "canonical_candidates": candidates,
        "template_readiness": template_readiness,
        "missing_fields": missing,
        "readiness_hint": "create_ascii_alias_view_before_mapping" if any(not SAFE_IDENTIFIER.fullmatch(name) for name in names) else "map_required_fields_before_runtime_use",
        "columns": annotated,
        "sensitive_column_flags": {item["column_name"]: item["sensitive"] for item in annotated if item.get("column_name")},
        "profile_draft": {
            "mapping_version": "candidate_draft_v1",
            "tables": {"primary": table},
            "columns": names,
            "hotel_ids": candidates.get("hotel_id") or [],
            "status_aliases": {},
            "metric_aliases": {field: values[0] for field, values in candidates.items() if len(values) == 1},
            "canonical_fields": {field: values[0] if len(values) == 1 else None for field, values in candidates.items()},
        },
        "write_performed": False,
        "free_sql_allowed": False,
    }


SQLITE_TEMPLATES = {
    "operating_snapshot": """
        SELECT
          h.hotel_id,
          h.name AS hotel_name,
          COUNT(rt.room_type_id) AS room_type_count,
          COALESCE(SUM(rt.inventory), 0) AS available_rooms,
          COALESCE(AVG(rt.floor_price), 0) AS avg_floor_price,
          COALESCE(AVG(rt.ceiling_price), 0) AS avg_ceiling_price
        FROM hotels h
        LEFT JOIN room_types rt ON rt.hotel_id = h.hotel_id
        WHERE h.hotel_id = ?
        GROUP BY h.hotel_id, h.name
    """,
    "price_snapshot": """
        SELECT
          room_type_id,
          name AS room_type_name,
          floor_price,
          ceiling_price,
          inventory
        FROM room_types
        WHERE hotel_id = ?
        ORDER BY room_type_id
    """,
    "order_snapshot": """
        SELECT
          hotel_id,
          captured_at,
          payload_json
        FROM snapshots
        WHERE hotel_id = ?
        ORDER BY captured_at DESC, id DESC
        LIMIT 5
    """,
}


def _source(
    db_kind: str,
    field_quality: str = "confirmed",
    *,
    channel_source: str = "pms",
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_mode = f"{db_kind}_runtime" if db_kind in {"mysql", "sqlite"} else db_kind
    source_capability = (profile or {}).get("source_capability") or "read_only"
    return {
        "adapter_vendor": "database",
        "channel_source": channel_source,
        "data_source_type": f"{db_kind}_db",
        "source_mode": source_mode,
        "data_source_label": source_mode,
        "source_capability": source_capability,
        "field_quality": field_quality,
        "captured_at": now_local(),
        "approval_allowed": False,
        "live_allowed": False,
        "downstream_allowed": False,
        "downstream_blocked_reason": "database_read_only_runtime" if source_capability == "read_only" else "database_write_pending_runtime",
    }


def _parse_data_datetime(value: Any) -> dt.datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time.min)
    text = str(value).strip()
    if not text:
        return None
    for candidate in (text, text.replace("Z", "+00:00")):
        try:
            parsed = dt.datetime.fromisoformat(candidate)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone().replace(tzinfo=None)
            return parsed
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(text[: len(fmt)], fmt)
        except ValueError:
            pass
    return None


def freshness_metadata(value: Any, *, demo_data: bool = False) -> dict[str, Any]:
    if demo_data:
        return {
            "freshness_status": "demo_data",
            "data_age_hours": None,
            "data_business_date": None,
            "data_snapshot_time": None,
            "business_status": "demo_or_historical",
            "today_label_allowed": False,
        }
    parsed = _parse_data_datetime(value)
    if parsed is None:
        return {
            "freshness_status": "missing_date",
            "data_age_hours": None,
            "data_business_date": None,
            "data_snapshot_time": None,
            "business_status": "demo_or_historical",
            "today_label_allowed": False,
        }
    now = dt.datetime.now()
    age_hours = max(0.0, (now - parsed).total_seconds() / 3600)
    status = "fresh" if parsed.date() == now.date() and age_hours <= 24 else "stale"
    today_label_allowed = status == "fresh" and age_hours <= 72
    return {
        "freshness_status": status,
        "data_age_hours": round(age_hours, 2),
        "data_business_date": parsed.date().isoformat(),
        "data_snapshot_time": parsed.strftime("%Y-%m-%d %H:%M:%S"),
        "business_status": "current" if status == "fresh" else "demo_or_historical",
        "today_label_allowed": today_label_allowed,
    }


def _append_freshness_risk(payload: dict[str, Any]) -> None:
    status = payload.get("freshness_status")
    if status not in ("stale", "missing_date", "demo_data"):
        return
    risks = payload.setdefault("risk_flags", [])
    risk = f"data_freshness_{status}"
    if risk not in risks:
        risks.append(risk)
    if (payload.get("data_age_hours") or 0) > 72 and "data_stale_over_72h" not in risks:
        risks.append("data_stale_over_72h")


def _connect_sqlite(dsn: str | None) -> sqlite3.Connection:
    path = dsn or os.environ.get("HOTEL_OTA_DB_DSN") or os.environ.get("HOTEL_OTA_DB") or DEFAULT_DB
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _mask(value: Any) -> Any:
    if value in (None, ""):
        return value
    text = str(value)
    if len(text) <= 2:
        return "***"
    if len(text) <= 6:
        return text[:1] + "***"
    return text[:2] + "***" + text[-2:]


def _redact_row(row: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in row.items():
        lowered = key.lower()
        if lowered in PUBLIC_REVIEW_TEXT_FIELDS:
            redacted[key] = value
        elif any(pattern in lowered for pattern in SENSITIVE_FIELD_PATTERNS):
            redacted[key] = _mask(value)
        else:
            redacted[key] = value
    return redacted


def _redact_sensitive_fields(row: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile_fields = set(((profile or {}).get("privacy") or {}).get("redact_fields") or [])
    redacted = _redact_row(row)
    for key in list(redacted):
        if key.lower() in PUBLIC_REVIEW_TEXT_FIELDS:
            continue
        if key in profile_fields and redacted[key] not in (None, ""):
            redacted[key] = _mask(redacted[key])
    return redacted


def _template_source_metadata(
    *,
    template: str,
    table: str,
    platform_key: str | None = None,
    raw_row_count: int = 0,
    filtered_row_count: int = 0,
    data_business_date: Any = None,
    data_snapshot_time: Any = None,
    risk_flags: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "template": template,
        "source_table": table,
        "source_platform": platform_key,
        "source_status": "ok" if filtered_row_count else "no_rows",
        "raw_row_count": raw_row_count,
        "filtered_row_count": filtered_row_count,
        "data_business_date": str(data_business_date) if data_business_date is not None else None,
        "data_snapshot_time": str(data_snapshot_time) if data_snapshot_time is not None else None,
        "risk_flags": risk_flags or [],
        "free_sql_allowed": False,
        "write_performed": False,
    }


def _safe_identifier(name: str, label: str = "identifier") -> str:
    if not name or not SAFE_IDENTIFIER.match(name):
        raise ValueError(f"unsafe {label}: {name}")
    return f"`{name}`"


def _missing_driver(db_kind: str) -> dict[str, Any]:
    driver = "pymysql" if db_kind == "mysql" else "psycopg"
    try:
        __import__(driver)
    except ImportError:
        return {
            "status": "blocked",
            "reason": "missing_driver",
            "db_kind": db_kind,
            "required_driver": driver,
            "message": f"Install {driver} and configure HOTEL_OTA_DB_DSN before using {db_kind}.",
        }
    return {}


def _load_mapping_config(path: str | None = None) -> dict[str, Any] | None:
    config_path = path or os.environ.get("HOTEL_OTA_DB_MAPPING_CONFIG")
    if not config_path:
        return None
    with open(config_path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _profile(
    config: dict[str, Any] | None,
    profile_name: str | None = None,
    hotel_id: str | None = None,
) -> dict[str, Any] | None:
    if not config:
        return None
    profiles = config.get("profiles") or {}
    explicit_profile = bool(profile_name)
    # === 新增：按 hotel_id 解析 profile （多酒店） ===
    # 当调用方显式传入 profile_name 时优先使用；否则若提供 hotel_id，
    # 通过 hotel_profile_map 路由到对应酒店的 profile；未显式传 hotel_id 时
    # 保持原有向后兼容行为（顺序：配置 HOTEL_OTA_DB_PROFILE → default_profile）。
    if not profile_name and hotel_id:
        hotel_map = config.get("hotel_profile_map") or {}
        profile_name = hotel_map.get(hotel_id)
    if not profile_name:
        if hotel_id and not explicit_profile:
            # 提供了 hotel_id 但不在 hotel_profile_map 中 → fail closed，
            # 绝不静默回退到全局默认 profile（防写入连错璞悦库）。
            return None
        profile_name = os.environ.get("HOTEL_OTA_DB_PROFILE") or config.get("default_profile")
    if not profile_name:
        return None
    profile = profiles.get(profile_name)
    if profile:
        parent_name = profile.get("inherits")
        if parent_name and parent_name in profiles:
            parent = json.loads(json.dumps(profiles[parent_name]))
            parent.update(profile)
            # Schema mappings may inherit; hotel identity is tenant-specific and
            # must be declared by each child profile, never merged from a parent.
            for key in ("tables", "columns", "metric_aliases", "status_aliases", "privacy"):
                if isinstance(profiles[parent_name].get(key), dict):
                    merged = dict(profiles[parent_name][key])
                    merged.update(profile.get(key) or {})
                    parent[key] = merged
            profile = parent
        else:
            profile = dict(profile)
        profile["_profile_name"] = profile_name
    return profile


def _dsn_from_args(args: argparse.Namespace, profile: dict[str, Any] | None = None) -> str:
    dsn_env = (profile or {}).get("dsn_env")
    return (
        getattr(args, "dsn", None)
        or (os.environ.get(dsn_env) if dsn_env else None)
        or os.environ.get("HOTEL_OTA_DB_DSN")
        or (profile or {}).get("dsn")
        or ""
    )


def resolve_hotel_dsn(hotel_id: str | None, base_env: str, explicit_dsn: str | None = None) -> str:
    """Resolve one request-scoped DSN without cross-hotel fallback.

    A resolved hotel must use an exact hotel-scoped variable. Global variables
    remain available only to legacy/local callers that have no hotel context.
    """
    if explicit_dsn:
        return explicit_dsn

    if hotel_id:
        suffix = str(hotel_id).upper().replace("-", "_")
        hotel_specific = os.environ.get(f"{base_env}_{suffix}")
        if hotel_specific:
            return hotel_specific
        # Read sources may use the hotel's main database when no dedicated read
        # source is configured. Writer purposes never inherit this fallback.
        if base_env not in {
            "HOTEL_OTA_PRICE_TASK_DB_DSN",
            "HOTEL_OTA_PROMOTION_CONTROL_DSN",
            "HOTEL_OTA_REVIEW_TASK_DSN",
        }:
            main_dsn = os.environ.get(f"HOTEL_OTA_DB_DSN_{suffix}")
            if main_dsn:
                return main_dsn
        raise RuntimeError(f"DSN not configured for hotel={hotel_id}, base_env={base_env}")

    return os.environ.get(base_env) or os.environ.get("HOTEL_OTA_DB_DSN_PUYUE") or ""

def resolve_mapping_profile_dsn(mapping_config: str | None = None, profile_name: str | None = None) -> str | None:
    """Resolve the configured DB profile DSN for shared runtime writers."""
    config = _load_mapping_config(mapping_config)
    profile = _profile(config, profile_name)
    if not profile:
        return None
    dsn_env = profile.get("dsn_env")
    return (os.environ.get(dsn_env) if dsn_env else None) or profile.get("dsn")


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    if not dsn:
        raise ValueError("HOTEL_OTA_DB_DSN is required for mysql")
    parsed = urlparse(dsn)
    if parsed.scheme not in ("mysql", "mysql+pymysql"):
        raise ValueError("mysql DSN must start with mysql://")
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/"),
        "charset": query.get("charset", ["utf8mb4"])[0],
        "connect_timeout": int(query.get("connect_timeout", ["10"])[0]),
    }


def _connect_mysql(args: argparse.Namespace, profile: dict[str, Any] | None = None):
    missing = _missing_driver("mysql")
    if missing:
        return None, missing
    import pymysql

    params = _parse_mysql_dsn(_dsn_from_args(args, profile))
    conn = pymysql.connect(
        host=params["host"],
        port=params["port"],
        user=params["user"],
        password=params["password"],
        database=params["database"],
        charset=params["charset"],
        connect_timeout=params["connect_timeout"],
        read_timeout=20,
        write_timeout=20,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )
    return conn, {}


def _table(profile: dict[str, Any], key: str) -> str:
    tables = profile.get("tables") or {}
    table = tables.get(key)
    if not table:
        raise KeyError(f"database table mapping required: {key}")
    return table


def _columns(profile: dict[str, Any], key: str) -> dict[str, str]:
    columns = (profile.get("columns") or {}).get(key) or {}
    if not columns:
        raise KeyError(f"database column mapping required: {key}")
    return columns


def _col(columns: dict[str, str], key: str) -> str:
    value = columns.get(key)
    if not value:
        raise KeyError(f"database column mapping required: {key}")
    return value


def _hotel_name(profile: dict[str, Any], hotel_id: str) -> str:
    names = _hotel_names(profile, hotel_id)
    return names[0] if names else hotel_id


def _hotel_names(profile: dict[str, Any], hotel_id: str) -> list[str]:
    hotels = profile.get("hotel_ids") or {}
    hotel = hotels.get(hotel_id)
    names: list[str] = []
    if isinstance(hotel, dict):
        for key in ("hotel_name", "display_name", "name"):
            value = hotel.get(key)
            if value:
                names.append(str(value))
        aliases = hotel.get("aliases") or hotel.get("hotel_aliases") or []
        if isinstance(aliases, str):
            names.append(aliases)
        elif isinstance(aliases, list):
            names.extend(str(item) for item in aliases if item)
    elif isinstance(hotel, str):
        names.append(hotel)
    names.append(hotel_id)
    return list(dict.fromkeys(item.strip() for item in names if item and item.strip()))


def _normalize_metric_name(metric_name: str, aliases: dict[str, list[str]]) -> str:
    normalized = str(metric_name).strip()
    for key, names in aliases.items():
        if normalized == key or normalized in names:
            return key
    return normalized


def _normalize_status(status: str, aliases: dict[str, list[str]]) -> str:
    normalized = str(status).strip()
    for key, names in aliases.items():
        if normalized == key or normalized in names:
            return key
    return "other"


def _latest_date_condition(table: str, hotel_col: str, date_col: str) -> str:
    safe_table = _safe_identifier(table, "table")
    safe_hotel = _safe_identifier(hotel_col, "column")
    safe_date = _safe_identifier(date_col, "column")
    return f"{safe_date} = (SELECT MAX({safe_date}) FROM {safe_table} WHERE {safe_hotel} = %s)"


def _target_date(args: argparse.Namespace) -> str:
    value = getattr(args, "date", None)
    if value:
        return str(value)[:10]
    return dt.datetime.now().date().isoformat()


def _target_as_of_datetime(args: argparse.Namespace, target_date: str) -> str:
    value = getattr(args, "as_of_time", None)
    if value:
        text = str(value).strip()
        if len(text) <= 5 and ":" in text:
            return f"{target_date} {text}:00"
        return text[:19]
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _first_existing(columns: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        if key in columns and columns[key]:
            return columns[key]
    return None


def _has_template_mapping(profile: dict[str, Any], key: str) -> bool:
    return bool((profile.get("tables") or {}).get(key) and (profile.get("columns") or {}).get(key))


def _has_any_template_mapping(profile: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(_has_template_mapping(profile, key) for key in keys)


def _view_migration_risks(profile: dict[str, Any]) -> list[str]:
    tables = profile.get("tables") or {}
    uses_openclaw_view = any(str(table).startswith("v_openclaw_") for table in tables.values())
    if uses_openclaw_view and not profile.get("view_migration_version"):
        return ["view_migration_untracked"]
    return []


def _inspect_profile_metadata(profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = profile or {}
    return {
        "profile": profile.get("_profile_name"),
        "source_capability": profile.get("source_capability") or "read_only",
        "free_sql_allowed": False,
        "write_performed": False,
        "risk_flags": _view_migration_risks(profile),
    }


def _source_platform_filter_clause(profile: dict[str, Any], columns: dict[str, str], platform_key: str | None) -> tuple[str, list[Any]]:
    platform_col = columns.get("source_platform") or columns.get("channel_source")
    if not platform_key or not platform_col:
        return "", []
    aliases = profile.get("platform_aliases") or {}
    values = aliases.get(str(platform_key), [str(platform_key)])
    if platform_key == "pms" and str(platform_key) not in aliases:
        values = ["pms", "walkin", "\u6563\u5ba2", ""]
    safe_col = _safe_identifier(platform_col, "column")
    normalized_values = [str(item).strip() for item in values if item is not None]
    non_empty_values = [item for item in normalized_values if item]
    include_empty = len(non_empty_values) != len(normalized_values)
    clauses: list[str] = []
    params: list[Any] = []
    if non_empty_values:
        placeholders = ", ".join(["%s"] * len(non_empty_values))
        clauses.append(f"TRIM({safe_col}) IN ({placeholders})")
        params.extend(non_empty_values)
    if include_empty:
        clauses.append(f"({safe_col} IS NULL OR TRIM({safe_col}) = '')")
    if not clauses:
        return "", []
    return f"({' OR '.join(clauses)})", params


def _tenant_filter_clause(
    columns: dict[str, str],
    *,
    hotel_id: str,
    hotel_name: str | list[str],
) -> tuple[str, list[Any], str, list[str]]:
    hotel_id_col = columns.get("hotel_id")
    hotel_name_col = columns.get("hotel_name")
    risks: list[str] = []
    hotel_names = [hotel_name] if isinstance(hotel_name, str) else list(hotel_name)
    hotel_names = list(dict.fromkeys(str(item).strip() for item in hotel_names if item and str(item).strip()))
    if not hotel_names:
        hotel_names = [hotel_id]
    if hotel_id_col and hotel_name_col:
        safe_hotel_id = _safe_identifier(hotel_id_col, "column")
        safe_hotel_name = _safe_identifier(hotel_name_col, "column")
        placeholders = ", ".join(["%s"] * len(hotel_names))
        clause = (
            f"({safe_hotel_id} = %s OR "
            f"(({safe_hotel_id} IS NULL OR TRIM({safe_hotel_id}) = '') AND {safe_hotel_name} IN ({placeholders})))"
        )
        return clause, [hotel_id, *hotel_names], "hotel_id_or_empty_hotel_name_legacy", ["legacy_hotel_name_filter"]
    if hotel_id_col:
        return f"{_safe_identifier(hotel_id_col, 'column')} = %s", [hotel_id], "hotel_id", risks
    if hotel_name_col:
        risks.append("legacy_hotel_name_filter")
        placeholders = ", ".join(["%s"] * len(hotel_names))
        return f"{_safe_identifier(hotel_name_col, 'column')} IN ({placeholders})", hotel_names, "hotel_name_legacy", risks
    raise KeyError("database column mapping required: hotel_id or hotel_name")


def _optional_col(columns: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = columns.get(key)
        if value:
            return value
    return None


def _date_filter_clause(args: argparse.Namespace, table: str, hotel_col: str, date_col: str, hotel_name: str) -> tuple[str, list[Any]]:
    if getattr(args, "date", None):
        return f"DATE({_safe_identifier(date_col, 'column')}) = %s", [_target_date(args)]
    return _latest_date_condition(table, hotel_col, date_col), [hotel_name]


def _platform_key(args: argparse.Namespace, default: str | None = None) -> str | None:
    return getattr(args, "source_platform", None) or default


def _template_channel_source(template: str, source_platform: str | None = None) -> str:
    if template in V4_TEMPLATE_TABLE_KEYS or template.startswith("ota_") or template == "price_task_queue":
        return str(source_platform or "ota")
    return "pms"


def _ota_channel_for_table_key(table_key: str) -> str | None:
    key = str(table_key or "").lower()
    if key.startswith("meituan"):
        return "meituan"
    if key.startswith("ctrip"):
        return "ctrip"
    return None


def _canonical_ota_channel(value: Any) -> str | None:
    text = str(value or "").strip()
    lowered = text.lower()
    if lowered in {"mtop", "qzagent"}:
        return "meituan"
    channel = normalize_source_platform(text)
    return channel if channel in {"meituan", "ctrip"} else None


_KNOWN_OTA_CHANNELS = {"meituan", "ctrip"}


def _normalize_ota_channels(value: Any) -> set[str] | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [item.strip() for item in re.split(r"[,，\s]+", text) if item.strip()]
        return _normalize_ota_channels(parsed)
    if isinstance(value, dict):
        return _normalize_ota_channels(value.get("channels") or value.get("enabled_channels"))
    if isinstance(value, (list, tuple, set)):
        channels = {_canonical_ota_channel(item) for item in value}
        result = {item for item in channels if item}
        return result or None
    return None


def _load_hotel_enabled_ota_channels(conn, args: argparse.Namespace, profile: dict[str, Any]) -> tuple[set[str] | None, list[str]]:
    # 运维环境变量覆盖(优先于 MySQL hotels.config_json,因为生产 OTA 库通常没有 hotels 表):
    # HOTEL_OTA_ENABLED_CHANNELS 白名单,或 HOTEL_OTA_DISABLED_CHANNELS 黑名单(从已知 OTA 渠道扣除)。
    env_enabled = os.environ.get("HOTEL_OTA_ENABLED_CHANNELS")
    if env_enabled and env_enabled.strip():
        return _normalize_ota_channels(env_enabled), []
    env_disabled = os.environ.get("HOTEL_OTA_DISABLED_CHANNELS")
    if env_disabled and env_disabled.strip():
        disabled = _normalize_ota_channels(env_disabled) or set()
        return {channel for channel in _KNOWN_OTA_CHANNELS if channel not in disabled}, []
    tables = profile.get("tables") or {}
    columns = (profile.get("columns") or {}).get("hotels") or {}
    table = tables.get("hotels") or "hotels"
    hotel_id_col = columns.get("hotel_id") or "hotel_id"
    config_col = columns.get("config_json") or "config_json"
    try:
        sql = (
            f"SELECT {_safe_identifier(config_col, 'column')} AS `config_json` "
            f"FROM {_safe_identifier(table, 'table')} "
            f"WHERE {_safe_identifier(hotel_id_col, 'column')} = %s LIMIT 1"
        )
        with conn.cursor() as cursor:
            cursor.execute(sql, (args.hotel_id,))
            row = cursor.fetchone() or {}
    except Exception:
        return None, ["ota_channel_config_unavailable"]
    channels = _normalize_ota_channels(row.get("config_json"))
    return channels, []


def _filter_ota_table_keys_by_enabled_channels(
    table_keys: tuple[str, ...],
    *,
    enabled_channels: set[str] | None,
    requested_platform: str | None,
) -> tuple[tuple[str, ...], list[str], list[str]]:
    if not enabled_channels:
        return table_keys, [], []
    requested_channel = _canonical_ota_channel(requested_platform)
    risks: list[str] = []
    if requested_channel and requested_channel not in enabled_channels:
        risks.append("requested_ota_channel_disabled")
    filtered: list[str] = []
    skipped: list[str] = []
    for key in table_keys:
        channel = _ota_channel_for_table_key(key)
        if channel and channel not in enabled_channels:
            skipped.append(key)
            continue
        filtered.append(key)
    return tuple(filtered), skipped, risks


def _latest_snapshot_clause(
    table: str,
    columns: dict[str, str],
    scope_parts: list[str],
    scope_params: list[Any],
) -> tuple[str, list[Any]]:
    snapshot_col = columns.get("snapshot_time")
    if not snapshot_col:
        return "", []
    safe_table = _safe_identifier(table, "table")
    safe_snapshot = _safe_identifier(snapshot_col, "column")
    return (
        f"{safe_snapshot} = (SELECT MAX({safe_snapshot}) FROM {safe_table} WHERE {' AND '.join(scope_parts)})",
        list(scope_params),
    )


def _load_room_mapping_rows(conn, args: argparse.Namespace, profile: dict[str, Any], *, limit: int = 5000) -> list[dict[str, Any]]:
    if not _has_template_mapping(profile, "room_type_mapping"):
        return []
    table = _table(profile, "room_type_mapping")
    columns = _columns(profile, "room_type_mapping")
    tenant_clause, tenant_params, _mode, _risks = _tenant_filter_clause(
        columns,
        hotel_id=args.hotel_id,
        hotel_name=_hotel_names(profile, args.hotel_id),
    )
    projection_keys = [
        key
        for key in columns
        if key
        not in {
            "reviewed_by",
            "review_note",
            "remark",
        }
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in projection_keys]
    where_parts = [tenant_clause]
    where_params = list(tenant_params)
    # 不在 SQL 层过滤 is_active:载入 active+inactive 全部行,让 resolver 能诊断 mapping_inactive
    # (active 命中由 _pick_candidate 的 active 优先保证不被 inactive 兄弟误判为 conflict)。
    platform_clause, platform_params = _source_platform_filter_clause(profile, columns, getattr(args, "source_platform", None))
    if platform_clause:
        where_parts.append(platform_clause)
        where_params.extend(platform_params)
    sql = (
        f"SELECT {', '.join(projection)} FROM {_safe_identifier(table, 'table')} "
        f"WHERE {' AND '.join(where_parts)} LIMIT %s"
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(where_params + [limit]))
            return [dict(row) for row in cursor.fetchall()]
    except Exception:
        return []


def _to_float_or_none(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int_or_none(value: Any) -> int | None:
    number = _to_float_or_none(value)
    if number is None:
        return None
    return int(round(number))


def _parse_structured_value(value: Any) -> Any:
    if value in (None, ""):
        return None
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _parse_field_pairs(value: Any) -> dict[str, Any]:
    parsed = _parse_structured_value(value)
    if isinstance(parsed, dict):
        return parsed
    if not isinstance(parsed, str):
        return {}
    result: dict[str, Any] = {}
    for part in re.split(r"[;,\n]+", parsed):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if not key:
            continue
        number = _to_float_or_none(raw)
        result[key] = number if number is not None else raw
    return result


def _is_summary_metric_row(row: dict[str, Any]) -> bool:
    summary_tokens = (
        "\u5168\u5e97",
        "\u603b\u8ba1",
        "\u5408\u8ba1",
        "\u5168\u90e8\u623f\u578b",
        "\u603b\u8425\u4e1a\u6307\u6807",
        "overall",
        "total",
        "summary",
    )
    for key in ("dimension_type", "dimension_name", "room_type_name", "room_type", "metric_group", "metric_item"):
        value = str(row.get(key) or "").strip().lower()
        if value and any(token.lower() in value for token in summary_tokens):
            return True
    tokens = ("全店", "总计", "合计", "全部房型", "overall", "total", "summary")
    for key in ("room_type_name", "room_type", "metric_group", "metric_item"):
        value = str(row.get(key) or "").strip().lower()
        if value and any(token.lower() in value for token in tokens):
            return True
    return False


def _is_room_type_metric_row(row: dict[str, Any]) -> bool:
    dimension_type = str(row.get("dimension_type") or "").strip().lower()
    if dimension_type in {"\u623f\u578b", "room_type", "room type"}:
        return True
    return bool(str(row.get("room_type_name") or row.get("room_type") or "").strip())


def _derive_daily_metric_fields(normalized: dict[str, Any], derived_metrics: list[str]) -> None:
    room_count = _to_float_or_none(normalized.get("room_count") or normalized.get("total_rooms"))
    sold_rooms = _to_float_or_none(normalized.get("sold_rooms"))
    room_revenue = _to_float_or_none(normalized.get("room_revenue"))
    room_nights = _to_float_or_none(normalized.get("room_nights"))
    occupancy_rate = _to_float_or_none(normalized.get("occupancy_rate"))
    adr = _to_float_or_none(normalized.get("adr"))
    revpar = _to_float_or_none(normalized.get("revpar"))
    if room_nights is None and sold_rooms is not None:
        room_nights = sold_rooms
        normalized["room_nights"] = int(round(sold_rooms))
        if "room_nights_from_sold_rooms" not in derived_metrics:
            derived_metrics.append("room_nights_from_sold_rooms")
    if occupancy_rate is None and room_count and room_nights is not None:
        occupancy_rate = room_nights / room_count
        normalized["occupancy_rate"] = round(occupancy_rate, 4)
        if "occupancy_rate_from_room_nights_room_count" not in derived_metrics:
            derived_metrics.append("occupancy_rate_from_room_nights_room_count")
    if adr is None and room_revenue is not None and room_nights:
        adr = room_revenue / room_nights
        normalized["adr"] = round(adr, 2)
        if "adr_from_room_revenue_room_nights" not in derived_metrics:
            derived_metrics.append("adr_from_room_revenue_room_nights")
    if revpar is None and adr is not None and occupancy_rate is not None:
        normalized["revpar"] = round(adr * occupancy_rate, 2)
        if "revpar_from_adr_occupancy" not in derived_metrics:
            derived_metrics.append("revpar_from_adr_occupancy")
    elif revpar is None and room_revenue is not None and room_count:
        normalized["revpar"] = round(room_revenue / room_count, 2)
        if "revpar_from_room_revenue_room_count" not in derived_metrics:
            derived_metrics.append("revpar_from_room_revenue_room_count")


def _aggregate_horizontal_daily_rows(rows: list[dict[str, Any]], metric_keys: tuple[str, ...]) -> tuple[dict[str, Any], str, bool, list[str], list[str]]:
    if len(rows) <= 1:
        normalized: dict[str, Any] = {}
        for item in rows:
            for key in metric_keys:
                if key in item and item.get(key) not in (None, "") and key not in normalized:
                    normalized[key] = item.get(key)
        return normalized, "horizontal_latest_snapshot_first_non_empty", True, [], []
    dimensioned = [row for row in rows if _is_room_type_metric_row(row)]
    if not dimensioned:
        return {}, "ambiguous_multiple_rows_blocked", False, ["daily_metrics_ambiguous_multiple_rows"], []
    additive_keys = ("sold_rooms", "remaining_rooms", "orders_today", "available_rooms", "total_rooms", "room_nights", "room_revenue", "room_count")
    normalized = {}
    for key in additive_keys:
        values = [_to_float_or_none(row.get(key)) for row in dimensioned if row.get(key) not in (None, "")]
        if values:
            total = sum(value for value in values if value is not None)
            normalized[key] = int(round(total)) if key not in {"room_revenue"} else round(total, 2)
    derived_metrics: list[str] = []
    if "room_revenue" not in normalized:
        estimated_revenue = 0.0
        estimated_any = False
        for row in dimensioned:
            adr = _to_float_or_none(row.get("adr"))
            nights = _to_float_or_none(row.get("room_nights") or row.get("sold_rooms"))
            if adr is not None and nights:
                estimated_revenue += adr * nights
                estimated_any = True
        if estimated_any:
            normalized["room_revenue"] = round(estimated_revenue, 2)
            derived_metrics.append("room_revenue_from_adr_room_nights")
    room_count = _to_float_or_none(normalized.get("room_count") or normalized.get("total_rooms"))
    sold_rooms = _to_float_or_none(normalized.get("sold_rooms"))
    room_revenue = _to_float_or_none(normalized.get("room_revenue"))
    room_nights = _to_float_or_none(normalized.get("room_nights"))
    _derive_daily_metric_fields(normalized, derived_metrics)
    room_count = _to_float_or_none(normalized.get("room_count") or normalized.get("total_rooms"))
    room_nights = _to_float_or_none(normalized.get("room_nights"))
    missing_denominator = []
    if sold_rooms is not None and not room_count:
        missing_denominator.append("room_count")
    if room_revenue is not None and not room_nights:
        missing_denominator.append("room_nights")
    if missing_denominator:
        return normalized, "partial_insufficient_denominator", False, ["daily_metrics_denominator_missing"], derived_metrics
    if not normalized:
        return {}, "ambiguous_multiple_rows_blocked", False, ["daily_metrics_ambiguous_multiple_rows"], derived_metrics
    return normalized, "room_type_aggregated", True, [], derived_metrics


def _normalize_hourly_curve(value: Any, target_orders: int | None = None) -> list[dict[str, int]]:
    parsed = _parse_structured_value(value)
    rows: list[dict[str, int]] = []
    if isinstance(parsed, dict):
        items = parsed.items()
        for hour, target in items:
            if isinstance(target, dict):
                target = target.get("target_orders") or target.get("target")
            hour_int = _to_int_or_none(hour)
            target_int = _to_int_or_none(target)
            if hour_int is not None and target_int is not None:
                rows.append({"hour": hour_int, "target_orders": target_int})
    elif isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                hour_int = _to_int_or_none(item.get("hour"))
                target_int = _to_int_or_none(item.get("target_orders") or item.get("target"))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                hour_int = _to_int_or_none(item[0])
                target_int = _to_int_or_none(item[1])
            else:
                continue
            if hour_int is not None and target_int is not None:
                rows.append({"hour": hour_int, "target_orders": target_int})
    rows = sorted(rows, key=lambda item: item["hour"])
    if rows:
        return rows
    if target_orders is None:
        return []
    anchors = [(12, 0.34), (16, 0.62), (20, 0.86)]
    return [{"hour": hour, "target_orders": max(1, int(round(target_orders * ratio)))} for hour, ratio in anchors]


def _progress_checkpoints_from_curve(curve: list[dict[str, int]], target_orders: int) -> list[dict[str, int | str]]:
    names = {12: "midday", 16: "afternoon", 20: "evening_peak"}
    result = []
    for hour in (12, 16, 20):
        match = next((item for item in curve if int(item.get("hour", -1)) == hour), None)
        if match:
            target = int(match.get("target_orders") or 0)
        else:
            ratio = {12: 0.34, 16: 0.62, 20: 0.86}[hour]
            target = int(round(target_orders * ratio))
        result.append({"hour": hour, "checkpoint": names[hour], "target_orders": max(target, 1)})
    return result


def _sqlite_operating_snapshot(row: sqlite3.Row | None, hotel_id: str) -> dict[str, Any]:
    if row is None:
        payload = {"hotel_id": hotel_id, "available_rooms": 0, "sold_rooms": 0, "remaining_rooms": 0, "risk_flags": ["database_no_hotel_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    available = int(row["available_rooms"] or 0)
    payload = {
        "hotel_id": row["hotel_id"],
        "hotel_name": row["hotel_name"],
        "room_type_count": int(row["room_type_count"] or 0),
        "available_rooms": available,
        "sold_rooms": 0,
        "remaining_rooms": available,
        "occupancy_rate": 0,
        "adr": round(float(row["avg_floor_price"] or 0), 2),
        "revpar": 0,
        "risk_flags": ["database_read_only_snapshot"],
        **freshness_metadata(None),
    }
    _append_freshness_risk(payload)
    return payload


def _sqlite_price_snapshot(rows: list[sqlite3.Row]) -> dict[str, Any]:
    prices = []
    for row in rows:
        prices.append(
            {
                "room_type_id": row["room_type_id"],
                "room_type_name": row["room_type_name"],
                "current_price": row["floor_price"],
                "listed_price": row["ceiling_price"],
                "price_floor": row["floor_price"],
                "price_ceiling": row["ceiling_price"],
                "available_rooms": row["inventory"],
            }
        )
    return {"price_snapshots": prices}


def _sqlite_order_snapshot(rows: list[sqlite3.Row]) -> dict[str, Any]:
    orders = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except json.JSONDecodeError:
            payload = {"raw": row["payload_json"]}
        orders.append(
            {
                "hotel_id": row["hotel_id"],
                "captured_at": row["captured_at"],
                "order_status": "snapshot_reference",
                "order_status_raw": "snapshot_payload",
                "price_detail": payload,
            }
        )
    return {"orders": orders}


def _query_sqlite(args: argparse.Namespace) -> dict[str, Any]:
    with closing(_connect_sqlite(args.dsn)) as conn:
        sql = SQLITE_TEMPLATES[args.template]
        if args.template == "operating_snapshot":
            row = conn.execute(sql, (args.hotel_id,)).fetchone()
            payload = _sqlite_operating_snapshot(row, args.hotel_id)
        elif args.template == "price_snapshot":
            rows = conn.execute(sql, (args.hotel_id,)).fetchall()
            payload = _sqlite_price_snapshot(rows)
        elif args.template == "order_snapshot":
            rows = conn.execute(sql, (args.hotel_id,)).fetchall()
            payload = _sqlite_order_snapshot(rows)
        else:
            raise ValueError(f"unsupported template: {args.template}")
    return {**_source("sqlite"), "template": args.template, "hotel_id": args.hotel_id, "payload": payload}


def _mysql_latest_horizontal_metrics(
    conn,
    profile: dict[str, Any],
    hotel_name: str,
    monthly: bool = False,
    date: str | None = None,
    source_platform: str | None = None,
    hotel_id: str | None = None,
) -> dict[str, Any]:
    table_key = "monthly_metrics" if monthly else "daily_metrics"
    date_key = "period_month" if monthly else "business_date"
    metric_keys = (
        ("room_count", "room_nights", "room_revenue", "maintain_rooms", "occupancy_rate", "adr", "revpar")
        if monthly
        else ("occupancy_rate", "adr", "revpar", "sold_rooms", "remaining_rooms", "orders_today", "available_rooms", "total_rooms", "room_nights", "room_revenue", "room_count")
    )
    table = _table(profile, table_key)
    columns = _columns(profile, table_key)
    date_col = _col(columns, date_key)
    snapshot_col = columns.get("snapshot_time")
    safe_table = _safe_identifier(table, "table")
    safe_date_col = _safe_identifier(date_col, "column")
    dimension_keys = ("dimension_type", "dimension_name", "room_type_name", "room_type", "metric_group", "metric_item")
    select_cols = ["hotel_name", "source_platform", date_key, "snapshot_time", *dimension_keys, *metric_keys]
    projection = ", ".join(
        f"{_safe_identifier(columns[key], 'column')} AS `{key}`"
        for key in select_cols
        if key in columns and columns[key]
    )
    tenant_clause, tenant_params, tenant_filter_mode, tenant_risks = _tenant_filter_clause(
        columns,
        hotel_id=hotel_id or hotel_name,
        hotel_name=hotel_name,
    )
    where_parts = [tenant_clause]
    where_params: list[Any] = list(tenant_params)
    platform_clause, platform_params = _source_platform_filter_clause(profile, columns, source_platform)
    if platform_clause:
        where_parts.append(platform_clause)
        where_params.extend(platform_params)
    if date:
        if monthly:
            date_condition = f"{safe_date_col} = %s"
            date_params: list[Any] = [str(date)[:7]]
        else:
            date_condition = f"DATE({safe_date_col}) = %s"
            date_params = [str(date)[:10]]
    else:
        latest_date_scope = [tenant_clause]
        latest_date_params: list[Any] = list(tenant_params)
        if platform_clause:
            latest_date_scope.append(platform_clause)
            latest_date_params.extend(platform_params)
        date_condition = f"{safe_date_col} = (SELECT MAX({safe_date_col}) FROM {safe_table} WHERE {' AND '.join(latest_date_scope)})"
        date_params = latest_date_params
    where_parts.append(date_condition)
    where_params.extend(date_params)
    if snapshot_col:
        safe_snapshot_col = _safe_identifier(snapshot_col, "column")
        snapshot_scope = [tenant_clause]
        snapshot_params: list[Any] = list(tenant_params)
        if platform_clause:
            snapshot_scope.append(platform_clause)
            snapshot_params.extend(platform_params)
        snapshot_scope.append(date_condition)
        snapshot_params.extend(date_params)
        where_parts.append(
            f"{safe_snapshot_col} = (SELECT MAX({safe_snapshot_col}) FROM {safe_table} WHERE {' AND '.join(snapshot_scope)})"
        )
        where_params.extend(snapshot_params)
    order_cols = [safe_date_col]
    if snapshot_col:
        order_cols.append(_safe_identifier(snapshot_col, "column"))
    sql = (
        f"SELECT {projection} FROM {safe_table} "
        f"WHERE {' AND '.join(where_parts)} "
        f"ORDER BY {', '.join(f'{col} DESC' for col in order_cols)}"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(where_params))
        rows = cursor.fetchall()
    metrics = [dict(row) for row in rows]
    normalized: dict[str, Any] = {}
    data_date = None
    snapshot_time = None
    source_rows = metrics
    resolution_policy = "horizontal_latest_snapshot_first_non_empty"
    downstream_revenue_allowed = True
    risk_flags: list[str] = []
    derived_metrics: list[str] = []
    summary_rows = [item for item in metrics if _is_summary_metric_row(item)]
    if summary_rows:
        source_rows = summary_rows
        resolution_policy = "summary_row_selected"
        for item in source_rows:
            data_date = data_date or item.get(date_key)
            snapshot_time = snapshot_time or item.get("snapshot_time")
            for key in metric_keys:
                if key in item and item.get(key) not in (None, "") and key not in normalized:
                    normalized[key] = item.get(key)
        _derive_daily_metric_fields(normalized, derived_metrics)
    else:
        for item in source_rows:
            data_date = data_date or item.get(date_key)
            snapshot_time = snapshot_time or item.get("snapshot_time")
        normalized, resolution_policy, downstream_revenue_allowed, risk_flags, derived_metrics = _aggregate_horizontal_daily_rows(source_rows, metric_keys)
    result: dict[str, Any] = {
        "shape": "horizontal_metrics",
        "metrics": metrics,
        "normalized_metrics": normalized,
        "metric_resolution_policy": resolution_policy,
        "data_snapshot_time": str(snapshot_time) if snapshot_time is not None else None,
        "downstream_revenue_allowed": downstream_revenue_allowed,
        "tenant_filter_mode": tenant_filter_mode,
    }
    risk_flags = list(dict.fromkeys([*tenant_risks, *risk_flags]))
    if risk_flags:
        result["risk_flags"] = risk_flags
    if derived_metrics:
        result["derived_metrics"] = derived_metrics
    if monthly:
        result["data_period_month"] = str(data_date) if data_date is not None else None
    else:
        result["data_business_date"] = str(data_date) if data_date is not None else None
    return result


def _mysql_latest_metrics(
    conn,
    profile: dict[str, Any],
    hotel_name: str,
    monthly: bool = False,
    date: str | None = None,
    source_platform: str | None = None,
    hotel_id: str | None = None,
) -> dict[str, Any]:
    table_key = "monthly_metrics" if monthly else "daily_metrics"
    date_key = "period_month" if monthly else "business_date"
    table = _table(profile, table_key)
    columns = _columns(profile, table_key)
    if not columns.get("metric_name") or not columns.get("metric_value"):
        return _mysql_latest_horizontal_metrics(
            conn,
            profile,
            hotel_name,
            monthly=monthly,
            date=date,
            source_platform=source_platform,
            hotel_id=hotel_id,
        )
    date_col = _col(columns, date_key)
    aliases = profile.get("metric_aliases") or {}
    safe_table = _safe_identifier(table, "table")
    select_cols = {
        "metric_name": _col(columns, "metric_name"),
        "metric_value": _col(columns, "metric_value"),
        date_key: date_col,
    }
    for optional_metric_key in ("metric_group", "metric_item", "metric_display_name"):
        if columns.get(optional_metric_key):
            select_cols[optional_metric_key] = columns[optional_metric_key]
    optional = "compare_type" if monthly else "period_type"
    if optional in columns:
        select_cols[optional] = columns[optional]
    projection = ", ".join(f"{_safe_identifier(col, 'column')} AS `{alias}`" for alias, col in select_cols.items())
    safe_date_col = _safe_identifier(date_col, "column")
    tenant_clause, tenant_params, tenant_filter_mode, tenant_risks = _tenant_filter_clause(
        columns,
        hotel_id=hotel_id or hotel_name,
        hotel_name=hotel_name,
    )
    where_parts = [tenant_clause]
    where_params: list[Any] = list(tenant_params)
    latest_parts = [tenant_clause]
    latest_params: list[Any] = list(tenant_params)
    platform_clause, platform_params = _source_platform_filter_clause(profile, columns, source_platform)
    if platform_clause:
        where_parts.append(platform_clause)
        where_params.extend(platform_params)
        latest_parts.append(platform_clause)
        latest_params.extend(platform_params)
    if not monthly and "period_type" in columns:
        period_col = _safe_identifier(columns["period_type"], "column")
        period_aliases = tuple(str(item) for item in (profile.get("daily_period_type_aliases") or DAILY_PERIOD_TYPE_ALIASES))
        placeholders = ", ".join(["%s"] * len(period_aliases))
        where_parts.append(f"TRIM({period_col}) IN ({placeholders})")
        where_params.extend(period_aliases)
        latest_parts.append(f"TRIM({period_col}) IN ({placeholders})")
        latest_params.extend(period_aliases)
    if date:
        where_latest = f"DATE({safe_date_col}) = %s" if not monthly else f"{safe_date_col} = %s"
        where_params.append(str(date)[:7] if monthly else str(date)[:10])
        latest_params = []
    else:
        where_latest = f"{safe_date_col} = (SELECT MAX({safe_date_col}) FROM {safe_table} WHERE {' AND '.join(latest_parts)})"
    sql = f"SELECT {projection} FROM {safe_table} WHERE {' AND '.join(where_parts)} AND {where_latest}"
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(where_params + latest_params))
        rows = cursor.fetchall()
    metrics = []
    normalized: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    data_date = None
    for row in rows:
        item = dict(row)
        data_date = data_date or item.get(date_key)
        name = str(item.get("metric_name") or "")
        unified = _normalize_metric_name(name, aliases)
        item["metric_key"] = unified
        metrics.append(item)
        if unified in normalized:
            existing = normalized.get(unified)
            incoming = item.get("metric_value")
            if str(existing) != str(incoming):
                conflicts.append({"metric_key": unified, "kept_value": existing, "ignored_value": incoming})
            continue
        normalized[unified] = item.get("metric_value")
    result = {"metrics": metrics, "normalized_metrics": normalized, "metric_resolution_policy": "first_metric_value_wins", "tenant_filter_mode": tenant_filter_mode}
    if conflicts:
        result["metric_conflict_warning"] = conflicts
        result["risk_flags"] = list(dict.fromkeys([*tenant_risks, "metric_conflict_warning"]))
    elif tenant_risks:
        result["risk_flags"] = tenant_risks
    if monthly:
        result["data_period_month"] = str(data_date) if data_date is not None else None
    else:
        result["data_business_date"] = str(data_date) if data_date is not None else None
    return result


def _query_mysql_business_operating_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "operating_snapshot")
    columns = _columns(profile, "operating_snapshot")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "occupancy_rate",
        "adr",
        "revpar",
        "available_rooms",
        "sold_rooms",
        "remaining_rooms",
        "orders_today",
        "risk_flags",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC LIMIT 1"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        row = cursor.fetchone()
    if not row:
        payload = {"hotel_id": args.hotel_id, "hotel_name": hotel_name, "risk_flags": ["business_dataset_no_operating_snapshot_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    data_date = row.get("business_date")
    sold_rooms = _to_int_or_none(row.get("sold_rooms")) or 0
    remaining_rooms = _to_int_or_none(row.get("remaining_rooms"))
    available_rooms = _to_int_or_none(row.get("available_rooms"))
    total_rooms = (sold_rooms + remaining_rooms) if remaining_rooms is not None else (sold_rooms + (available_rooms or 0))
    risk_flags = _parse_structured_value(row.get("risk_flags"))
    if isinstance(risk_flags, str):
        risk_flags = [item.strip() for item in re.split(r"[,;]", risk_flags) if item.strip()]
    if not isinstance(risk_flags, list):
        risk_flags = []
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": row.get("hotel_name") or hotel_name,
        "total_rooms": total_rooms,
        "available_rooms": available_rooms,
        "sold_rooms": sold_rooms,
        "occupied_rooms": sold_rooms,
        "remaining_rooms": remaining_rooms,
        "orders_today": _to_int_or_none(row.get("orders_today")),
        "occupancy_rate": _to_float_or_none(row.get("occupancy_rate")) or 0,
        "adr": _to_float_or_none(row.get("adr")) or 0,
        "revpar": _to_float_or_none(row.get("revpar")) or 0,
        "risk_flags": ["business_dataset_v1_operating_snapshot"] + risk_flags,
        "source_table": table,
        **freshness_metadata(data_date),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_business_price_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "price_data")
    columns = _columns(profile, "price_data")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "room_type_id",
        "room_type_name",
        "channel",
        "current_price",
        "price_floor",
        "price_ceiling",
        "normal_price",
        "weekend_price",
        "begin_date",
        "end_date",
        "competitor_price",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        rows = cursor.fetchall()
    prices = []
    latest_business_date = None
    for row in rows:
        room_type = str(row.get("room_type_id") or "unknown")
        room_type_name = row.get("room_type_name") or room_type
        latest_business_date = latest_business_date or row.get("business_date")
        prices.append(
            {
                "room_type_id": room_type,
                "room_type_name": room_type_name,
                "channel": row.get("channel"),
                "current_price": row.get("current_price"),
                "listed_price": row.get("normal_price") or row.get("current_price"),
                "price_floor": row.get("price_floor"),
                "price_ceiling": row.get("price_ceiling"),
                "normal_price": row.get("normal_price"),
                "weekend_price": row.get("weekend_price"),
                "begin_date": str(row.get("begin_date"))[:10] if row.get("begin_date") is not None else None,
                "end_date": str(row.get("end_date"))[:10] if row.get("end_date") is not None else None,
                "competitor_price": row.get("competitor_price"),
                "business_date": str(row.get("business_date"))[:10] if row.get("business_date") is not None else None,
                "price_guard_source": "price_data",
            }
        )
    payload = {
        "price_snapshots": prices,
        "price_snapshot_source": "business_dataset_v1.price_data",
        "risk_flags": ["business_dataset_v1_price_data", "current_price_may_be_rs01_actual_average_not_realtime_ota_listing"],
        **freshness_metadata(latest_business_date),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_demand_context(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "demand_context")
    columns = _columns(profile, "demand_context")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "calendar_context",
        "weather_context",
        "event_context",
        "competitor_context",
        "operating_context",
        "progress_context",
        "demand_signal",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC LIMIT 1"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        row = cursor.fetchone()
    if not row:
        payload = {"hotel_id": args.hotel_id, "hotel_name": hotel_name, "risk_flags": ["business_dataset_no_demand_context_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    demand_signal = _parse_field_pairs(row.get("demand_signal"))
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": row.get("hotel_name") or hotel_name,
        "calendar_context": _parse_field_pairs(row.get("calendar_context")),
        "weather_context": _parse_field_pairs(row.get("weather_context")),
        "event_context": _parse_field_pairs(row.get("event_context")),
        "competitor_context": _parse_field_pairs(row.get("competitor_context")),
        "operating_context": _parse_field_pairs(row.get("operating_context")),
        "progress_context": _parse_field_pairs(row.get("progress_context")),
        "demand_signal": demand_signal or _parse_structured_value(row.get("demand_signal")),
        "demand_index": demand_signal.get("demand_index"),
        "demand_level": demand_signal.get("demand_level"),
        "risk_flags": ["business_dataset_v1_demand_context"],
        "source_table": table,
        **freshness_metadata(row.get("business_date")),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_operation_diagnosis(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    if not _has_template_mapping(profile, "operation_diagnosis"):
        return _query_mysql_operation_diagnosis_from_v4(conn, args, profile)
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "operation_diagnosis")
    columns = _columns(profile, "operation_diagnosis")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "hos_score",
        "merchant_operation_score",
        "peer_rank",
        "exposure",
        "views",
        "payment_conversion_rate",
        "rating_total",
        "bad_review_rate",
        "ota_health_score",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC LIMIT 1"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        row = cursor.fetchone()
    if not row:
        payload = {"hotel_id": args.hotel_id, "hotel_name": hotel_name, "risk_flags": ["business_dataset_no_operation_diagnosis_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": row.get("hotel_name") or hotel_name,
        "hos_score": _to_float_or_none(row.get("hos_score")),
        "merchant_operation_score": _to_float_or_none(row.get("merchant_operation_score")),
        "peer_rank": _to_int_or_none(row.get("peer_rank")),
        "exposure": _to_int_or_none(row.get("exposure")),
        "views": _to_int_or_none(row.get("views")),
        "payment_conversion_rate": _to_float_or_none(row.get("payment_conversion_rate")),
        "rating_total": _to_float_or_none(row.get("rating_total")),
        "bad_review_rate": _to_float_or_none(row.get("bad_review_rate")),
        "ota_health_score": _to_float_or_none(row.get("ota_health_score")),
        "risk_flags": ["business_dataset_v1_operation_diagnosis"],
        "source_table": table,
        **freshness_metadata(row.get("business_date")),
    }
    _append_freshness_risk(payload)
    return payload


def _row_metric_name(row: dict[str, Any]) -> str:
    return " ".join(str(row.get(key) or "") for key in ("metric_name", "metric_display_name", "metric_group")).strip().lower()


def _first_metric_value(rows: list[dict[str, Any]], *tokens: str) -> float | None:
    normalized_tokens = tuple(token.lower() for token in tokens)
    for row in rows:
        name = _row_metric_name(row)
        if any(token in name for token in normalized_tokens):
            value = _to_float_or_none(row.get("metric_value") or row.get("compare_value"))
            if value is not None:
                return value
    return None


def _metric_value_and_name(rows: list[dict[str, Any]], *tokens: str) -> tuple[float | None, str | None]:
    normalized_tokens = tuple(token.lower() for token in tokens)
    for row in rows:
        name = _row_metric_name(row)
        if any(token in name for token in normalized_tokens):
            value = _to_float_or_none(row.get("metric_value") if row.get("metric_value") is not None else row.get("compare_value"))
            if value is not None:
                return value, str(row.get("metric_display_name") or row.get("metric_name") or row.get("metric_group") or "").strip() or None
    return None, None


def _exposure_metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    value, name = _metric_value_and_name(rows, "曝光量", "exposure", "impression")
    if value is not None:
        return {"exposure": value, "exposure_unit": "次", "exposure_metric_name": name}
    value, name = _metric_value_and_name(rows, "曝光人数", "exposure_users", "impression_users")
    if value is not None:
        return {"exposure": value, "exposure_unit": "人", "exposure_metric_name": name}
    return {"exposure": None, "exposure_unit": None, "exposure_metric_name": None}


def _payment_conversion_metric(rows: list[dict[str, Any]]) -> dict[str, Any]:
    value, name = _metric_value_and_name(rows, "浏览支付转化率", "payment_conversion_rate", "pay_conversion_rate", "支付转化率")
    if value is None:
        value, name = _metric_value_and_name(rows, "conversion", "转化")
    basis = None
    lowered = str(name or "").lower()
    if value is not None:
        basis = "exposure_to_payment" if "曝光" in str(name or "") or "exposure" in lowered or "impression" in lowered else "view_to_payment"
    return {"payment_conversion_rate": value, "payment_conversion_rate_basis": basis, "payment_conversion_rate_metric_name": name}


def _peer_rank_from_rows(rows: list[dict[str, Any]], *keys: str) -> float | None:
    # competitor_rank 生产是 "12/21"(排名/总数)字符串,取分子作排名;兼容纯数字。
    for row in rows:
        for key in keys:
            raw = row.get(key)
            if raw in (None, ""):
                continue
            match = re.match(r"^\s*(\d+(?:\.\d+)?)", str(raw))
            if match:
                return float(match.group(1))
    return None


def _avg_row_number(rows: list[dict[str, Any]], *keys: str) -> float | None:
    values: list[float] = []
    for row in rows:
        for key in keys:
            value = _to_float_or_none(row.get(key))
            if value is not None:
                values.append(value)
                break
    return round(sum(values) / len(values), 4) if values else None


def _sum_row_number(rows: list[dict[str, Any]], *keys: str) -> float | None:
    values: list[float] = []
    for row in rows:
        for key in keys:
            value = _to_float_or_none(row.get(key))
            if value is not None:
                values.append(value)
                break
    return round(sum(values), 4) if values else None


def _safe_payload_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else result
    rows = payload.get("rows") if isinstance(payload, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _query_mysql_latest_score_metric_rows(conn, args: argparse.Namespace, profile: dict[str, Any]) -> list[dict[str, Any]]:
    hotel_names = _hotel_names(profile, args.hotel_id)
    rows: list[dict[str, Any]] = []
    for key in ("ctrip_business_metrics", "meituan_business_metrics"):
        if not _has_template_mapping(profile, key):
            continue
        table = _table(profile, key)
        columns = _columns(profile, key)
        if not all(name in columns for name in ("metric_name", "metric_value", "snapshot_time")):
            continue
        try:
            tenant_clause, tenant_params, _, _ = _tenant_filter_clause(columns, hotel_id=args.hotel_id, hotel_name=hotel_names)
        except KeyError:
            continue
        projection_keys = [
            name
            for name in ("metric_name", "metric_display_name", "metric_group", "metric_value", "metric_unit", "compare_label", "compare_value", "competitor_rank", "peer_average", "business_date", "stats_period_type", "snapshot_time")
            if name in columns
        ]
        projection = [f"{_safe_identifier(columns[name], 'column')} AS `{name}`" for name in projection_keys]
        safe_table = _safe_identifier(table, "table")
        safe_snapshot = _safe_identifier(columns["snapshot_time"], "column")
        scope_parts = [tenant_clause]
        scope_params = list(tenant_params)
        if columns.get("stats_period_type"):
            safe_period = _safe_identifier(columns["stats_period_type"], "column")
            scope_parts.append(f"{safe_period} = %s")
            scope_params.append("latest_score")
        sql = (
            f"SELECT {', '.join(projection)} FROM {safe_table} "
            f"WHERE {' AND '.join(scope_parts)} "
            f"AND {safe_snapshot} = (SELECT MAX({safe_snapshot}) FROM {safe_table} WHERE {' AND '.join(scope_parts)})"
        )
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(scope_params + scope_params))
            rows.extend(dict(row) for row in cursor.fetchall())
    return rows


def _query_mysql_operation_diagnosis_from_v4(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    risk_flags = ["database_mysql_v4_operation_diagnosis_derived"]
    daily = _mysql_latest_metrics(
        conn,
        profile,
        hotel_name,
        monthly=False,
        date=getattr(args, "date", None),
        source_platform="pms",
    )
    metrics = _query_mysql_v4_rows(
        conn,
        args,
        profile,
        template="ota_business_metrics",
        table_keys=("ctrip_business_metrics", "meituan_business_metrics"),
    )
    reviews = _query_mysql_v4_rows(
        conn,
        args,
        profile,
        template="ota_review_overview",
        table_keys=("ctrip_review_overview", "meituan_review_overview"),
    )
    revenue = _query_mysql_v4_rows(
        conn,
        args,
        profile,
        template="room_fee_daily",
        table_keys=("room_fee_daily",),
    )
    metric_rows = _safe_payload_rows(metrics)
    metric_rows.extend(_query_mysql_latest_score_metric_rows(conn, args, profile))
    review_rows = _safe_payload_rows(reviews)
    revenue_rows = _safe_payload_rows(revenue)
    daily_metrics = daily.get("normalized_metrics") if isinstance(daily.get("normalized_metrics"), dict) else {}

    exposure_info = _exposure_metric(metric_rows)
    views = _first_metric_value(metric_rows, "view", "browse", "浏览")
    payment_conversion_info = _payment_conversion_metric(metric_rows)
    hos_score = _first_metric_value(metric_rows, "HOS", "hos")
    ota_health_score = _first_metric_value(metric_rows, "信息分", "info_score", "information_score", "health", "健康")
    merchant_operation_score = _first_metric_value(metric_rows, "商家运营", "operation_score", "运营分", "运营评分", "psi")
    peer_rank = _peer_rank_from_rows(metric_rows, "competitor_rank", "peer_rank", "rank_position", "ranking_position")
    rating_total = _avg_row_number(review_rows, "review_score", "rating_total", "rating")
    negative_count = _sum_row_number(review_rows, "negative_review_count", "bad_review_count")
    total_reviews = _sum_row_number(review_rows, "total_review_count")
    bad_review_rate = round(negative_count / total_reviews, 4) if negative_count is not None and total_reviews else None
    room_revenue = _sum_row_number(revenue_rows, "room_fee", "room_revenue")
    room_nights = _sum_row_number(revenue_rows, "room_nights")

    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": hotel_name,
        "source_table": "derived_from_puyue_27_tables",
        "source_tables": [
            "jy01_hotel_statistics_daily",
            "ctrip_ota_business_metrics",
            "meituan_ota_business_metrics",
            "ctrip_ota_review_overview",
            "meituan_ota_review_overview",
            "rs01_room_revenue_daily",
        ],
        "diagnosis_source": "mysql_runtime_23_table_derived",
        "source_status": "ok" if any([daily_metrics, metric_rows, review_rows, revenue_rows]) else "no_rows",
        "occupancy": daily_metrics.get("occupancy_rate"),
        "adr": daily_metrics.get("adr"),
        "revpar": daily_metrics.get("revpar"),
        "sold_room_nights": daily_metrics.get("room_nights") or daily_metrics.get("sold_rooms"),
        "available_room_nights": daily_metrics.get("room_count"),
        "room_revenue": daily_metrics.get("room_revenue") or room_revenue,
        "room_nights": daily_metrics.get("room_nights") or room_nights,
        "exposure": exposure_info["exposure"],
        "exposure_unit": exposure_info["exposure_unit"],
        "exposure_metric_name": exposure_info["exposure_metric_name"],
        "views": views,
        "payment_conversion_rate": payment_conversion_info["payment_conversion_rate"],
        "payment_conversion_rate_basis": payment_conversion_info["payment_conversion_rate_basis"],
        "payment_conversion_rate_metric_name": payment_conversion_info["payment_conversion_rate_metric_name"],
        "hos_score": hos_score,
        "ota_health_score": ota_health_score,
        "merchant_operation_score": merchant_operation_score,
        "peer_rank": peer_rank,
        "rating_total": rating_total,
        "bad_review_rate": bad_review_rate,
        "field_completeness": None,
        "data_business_date": daily.get("data_business_date") or metrics.get("data_business_date") or revenue.get("data_business_date"),
        "data_snapshot_time": daily.get("data_snapshot_time") or metrics.get("data_snapshot_time") or reviews.get("data_snapshot_time"),
        "risk_flags": risk_flags,
        "free_sql_allowed": False,
        "write_performed": False,
    }
    payload.update(freshness_metadata(payload.get("data_snapshot_time") or payload.get("data_business_date")))
    _append_freshness_risk(payload)
    return payload


def _query_mysql_sales_baseline(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "sales_baseline")
    columns = _columns(profile, "sales_baseline")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    wanted = [
        "hotel_name",
        "business_date",
        "target_orders",
        "hourly_curve",
        "historical_same_weekday",
        "historical_same_date_type",
        "holiday_history",
        "completion_rate",
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in wanted if key in columns]
    safe_table = _safe_identifier(table, "table")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {date_clause} "
        f"ORDER BY {_safe_identifier(date_col, 'column')} DESC LIMIT 1"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple([hotel_name] + date_params))
        row = cursor.fetchone()
    if not row:
        payload = {"hotel_id": args.hotel_id, "hotel_name": hotel_name, "risk_flags": ["business_dataset_no_sales_baseline_row"], **freshness_metadata(None)}
        _append_freshness_risk(payload)
        return payload
    target_orders = max(_to_int_or_none(row.get("target_orders")) or 0, 1)
    hourly_curve = _normalize_hourly_curve(row.get("hourly_curve"), target_orders)
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": row.get("hotel_name") or hotel_name,
        "target_orders": target_orders,
        "hourly_curve": hourly_curve,
        "progress_checkpoints": _progress_checkpoints_from_curve(hourly_curve, target_orders),
        "historical_same_weekday": _parse_structured_value(row.get("historical_same_weekday")),
        "historical_same_date_type": _parse_structured_value(row.get("historical_same_date_type")),
        "holiday_history": _parse_structured_value(row.get("holiday_history")),
        "completion_rate": _to_float_or_none(row.get("completion_rate")),
        "risk_flags": ["business_dataset_v1_sales_baseline"],
        "source_table": table,
        **freshness_metadata(row.get("business_date")),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_pms_operating_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    table = _table(profile, "pms_room_type_forecast")
    columns = _columns(profile, "pms_room_type_forecast")
    required = ("stay_date", "snapshot_time", "total_rooms", "available_rooms", "overbooking_rooms")
    if any(not columns.get(key) for key in required) or not columns.get("hotel_id"):
        raise KeyError("database column mapping required: pms_room_type_forecast")
    tenant_clause, tenant_params, tenant_filter_mode, tenant_risks = _tenant_filter_clause(
        columns,
        hotel_id=args.hotel_id,
        hotel_name=_hotel_names(profile, args.hotel_id),
    )
    date_clause = f"DATE({_safe_identifier(columns['stay_date'], 'column')}) = %s"
    date_params = [_target_date(args)]
    platform_clause, platform_params = _source_platform_filter_clause(profile, columns, _platform_key(args, "pms"))
    scope_parts = [tenant_clause, date_clause]
    scope_params: list[Any] = [*tenant_params, *date_params]
    if getattr(args, "as_of_time", None):
        scope_parts.append(f"{_safe_identifier(columns['snapshot_time'], 'column')} <= %s")
        scope_params.append(_target_as_of_datetime(args, _target_date(args)))
    if platform_clause:
        scope_parts.append(platform_clause)
        scope_params.extend(platform_params)
    snapshot_clause, snapshot_params = _latest_snapshot_clause(table, columns, scope_parts, scope_params)
    projection_keys = [
        key for key in (
            "stay_date", "room_type_id", "room_type_name", "total_rooms", "available_rooms",
            "occupied_rooms", "overbooking_rooms", "room_revenue", "adr", "revpar", "snapshot_time",
        ) if columns.get(key)
    ]
    projection = [f"{_safe_identifier(columns[key], 'column')} AS `{key}`" for key in projection_keys]
    where_parts = [*scope_parts]
    where_params = list(scope_params)
    if snapshot_clause:
        where_parts.append(snapshot_clause)
        where_params.extend(snapshot_params)
    sql = (
        f"SELECT {', '.join(projection)} FROM {_safe_identifier(table, 'table')} "
        f"WHERE {' AND '.join(where_parts)} "
        f"ORDER BY {_safe_identifier(columns.get('room_type_id') or columns.get('room_type_name'), 'column')}"
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(where_params))
            rows = [dict(row) for row in cursor.fetchall()]
    except Exception as exc:
        payload = {
            "hotel_id": args.hotel_id,
            "source_table": table,
            "source_status": "data_gap",
            "risk_flags": [f"pms_room_type_forecast_query_failed:{exc.__class__.__name__}", *tenant_risks],
            "tenant_filter_mode": tenant_filter_mode,
            **freshness_metadata(None),
        }
        _append_freshness_risk(payload)
        return payload
    if not rows:
        payload = {
            "hotel_id": args.hotel_id,
            "source_table": table,
            "source_status": "data_gap",
            "risk_flags": ["pms_room_type_forecast_no_rows", *tenant_risks],
            "tenant_filter_mode": tenant_filter_mode,
            **freshness_metadata(None),
        }
        _append_freshness_risk(payload)
        return payload

    def total_for(key: str) -> float:
        return sum(_to_float_or_none(row.get(key)) or 0 for row in rows)

    total_rooms = total_for("total_rooms")
    available_rooms = total_for("available_rooms")
    base_committed_sold = max(total_rooms - available_rooms, 0)
    overbooking_rooms = max(total_for("overbooking_rooms"), 0)
    committed_sold_rooms = base_committed_sold + overbooking_rooms
    physical_occupied_rooms = total_for("occupied_rooms") if columns.get("occupied_rooms") else None
    room_revenue = total_for("room_revenue") if columns.get("room_revenue") else None
    snapshot_time = rows[0].get("snapshot_time")
    room_type_forecasts = [
        {
            "room_type_id": row.get("room_type_id"),
            "room_type_name": row.get("room_type_name"),
            "total_rooms": _to_float_or_none(row.get("total_rooms")),
            "available_rooms": _to_float_or_none(row.get("available_rooms")),
            "overbooking_rooms": _to_float_or_none(row.get("overbooking_rooms")) or 0,
            "committed_sold_rooms": max(
                (_to_float_or_none(row.get("total_rooms")) or 0) - (_to_float_or_none(row.get("available_rooms")) or 0), 0
            ) + max(_to_float_or_none(row.get("overbooking_rooms")) or 0, 0),
            "physical_occupied_rooms": _to_float_or_none(row.get("occupied_rooms")),
        }
        for row in rows
    ]
    payload = {
        "hotel_id": args.hotel_id,
        "source_status": "ok",
        "source_table": table,
        "source_tables": [{"table_key": "pms_room_type_forecast", "table": table, "row_count": len(rows)}],
        "data_business_date": str(rows[0].get("stay_date"))[:10],
        "data_snapshot_time": str(snapshot_time) if snapshot_time is not None else None,
        "total_rooms": total_rooms,
        "available_rooms": available_rooms,
        "remaining_rooms": available_rooms,
        "base_committed_sold_rooms": base_committed_sold,
        "overbooking_rooms": overbooking_rooms,
        "committed_sold_rooms": committed_sold_rooms,
        "sold_rooms": committed_sold_rooms,
        "committed_occupancy_rate": round(committed_sold_rooms / total_rooms, 4) if total_rooms else None,
        "occupancy_rate": round(committed_sold_rooms / total_rooms, 4) if total_rooms else None,
        "physical_occupied_rooms": physical_occupied_rooms,
        "physical_occupancy_rate": round(physical_occupied_rooms / total_rooms, 4) if total_rooms and physical_occupied_rooms is not None else None,
        "room_revenue": room_revenue,
        "adr": round(room_revenue / committed_sold_rooms, 2) if room_revenue is not None and committed_sold_rooms else None,
        "revpar": round(room_revenue / total_rooms, 2) if room_revenue is not None and total_rooms else None,
        "room_type_forecasts": room_type_forecasts,
        "tenant_filter_mode": tenant_filter_mode,
        "s2_contract": "pms_room_type_forecast_v1",
        "risk_flags": ["pms_room_type_forecast_primary", *tenant_risks],
        **freshness_metadata(snapshot_time),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_operating_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    """Read S2 through the fixed PMS contract; legacy room-status is never a fallback."""
    del profile
    return _query_mysql_pms_operating_snapshot(conn, args, PMS_S2_FORECAST_CONTRACT)


def _query_mysql_price_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    if _has_any_template_mapping(profile, V4_TEMPLATE_TABLE_KEYS["ota_price_mapping"]):
        return _query_mysql_ota_price_mapping(conn, args, profile)
    if _has_template_mapping(profile, "price_data"):
        return _query_mysql_business_price_snapshot(conn, args, profile)
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "room_fee_daily")
    columns = _columns(profile, "room_fee_daily")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    room_type_col = _col(columns, "room_type")
    daily_price_col = _col(columns, "daily_price")
    rack_rate_col = _col(columns, "rack_rate")
    room_fee_col = _col(columns, "room_fee")
    room_nights_col = _col(columns, "room_nights")
    order_col = _col(columns, "order_no")
    safe_table = _safe_identifier(table, "table")
    latest = _latest_date_condition(table, hotel_col, date_col)
    sql = (
        f"SELECT {_safe_identifier(room_type_col, 'column')} AS room_type, "
        f"AVG({_safe_identifier(daily_price_col, 'column')}) AS avg_daily_price, "
        f"MAX({_safe_identifier(rack_rate_col, 'column')}) AS rack_rate, "
        f"SUM({_safe_identifier(room_fee_col, 'column')}) AS room_fee, "
        f"SUM({_safe_identifier(room_nights_col, 'column')}) AS room_nights, "
        f"COUNT(DISTINCT {_safe_identifier(order_col, 'column')}) AS order_count, "
        f"MAX({_safe_identifier(date_col, 'column')}) AS business_date "
        f"FROM {safe_table} WHERE {_safe_identifier(hotel_col, 'column')} = %s AND {latest} "
        f"GROUP BY {_safe_identifier(room_type_col, 'column')} ORDER BY {_safe_identifier(room_type_col, 'column')}"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, (hotel_name, hotel_name))
        rows = cursor.fetchall()
    prices = []
    latest_business_date = None
    for row in rows:
        room_type = str(row.get("room_type") or "unknown")
        latest_business_date = latest_business_date or row.get("business_date")
        prices.append(
            {
                "room_type_id": room_type,
                "room_type_name": room_type,
                "current_price": row.get("avg_daily_price"),
                "listed_price": row.get("rack_rate"),
                "price_floor": None,
                "price_ceiling": row.get("rack_rate"),
                "available_rooms": None,
                "room_nights": row.get("room_nights"),
                "room_fee": row.get("room_fee"),
                "order_count": row.get("order_count"),
                "business_date": str(row.get("business_date")) if row.get("business_date") is not None else None,
            }
        )
    payload = {"price_snapshots": prices, "risk_flags": ["database_mysql_read_only_price_snapshot"], **freshness_metadata(latest_business_date)}
    _append_freshness_risk(payload)
    return payload


def _query_mysql_order_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    table = _table(profile, "room_fee_daily")
    columns = _columns(profile, "room_fee_daily")
    hotel_col = _col(columns, "hotel_name")
    date_col = _col(columns, "business_date")
    safe_table = _safe_identifier(table, "table")
    wanted = [
        "source_platform",
        "snapshot_time",
        "order_id",
        "order_no",
        "guest_name",
        "room_no",
        "room_type_name",
        "room_type",
        "customer_source",
        "checkin_time",
        "checkout_time",
        "rack_rate",
        "price_type",
        "room_daily_price",
        "daily_price",
        "stay_type",
        "charge_subject",
        "room_nights",
        "room_fee",
        "operator_name",
        "business_date",
    ]
    projection = []
    for key in wanted:
        if key in columns:
            projection.append(f"{_safe_identifier(columns[key], 'column')} AS `{key}`")
    if not projection:
        raise KeyError("database column mapping required: room_fee_daily order fields")
    safe_hotel = _safe_identifier(hotel_col, "column")
    date_clause, date_params = _date_filter_clause(args, table, hotel_col, date_col, hotel_name)
    platform_key = _platform_key(args, "pms")
    platform_clause, platform_params = _source_platform_filter_clause(profile, columns, platform_key)
    where_parts = [f"{safe_hotel} = %s", date_clause]
    where_params: list[Any] = [hotel_name, *date_params]
    scope_parts = [f"{safe_hotel} = %s", date_clause]
    scope_params: list[Any] = [hotel_name, *date_params]
    if platform_clause:
        where_parts.append(platform_clause)
        where_params.extend(platform_params)
        scope_parts.append(platform_clause)
        scope_params.extend(platform_params)
    snapshot_clause, snapshot_params = _latest_snapshot_clause(table, columns, scope_parts, scope_params)
    if snapshot_clause:
        where_parts.append(snapshot_clause)
        where_params.extend(snapshot_params)
    order_cols = [f"{_safe_identifier(date_col, 'column')} DESC"]
    if columns.get("snapshot_time"):
        order_cols.append(f"{_safe_identifier(columns['snapshot_time'], 'column')} DESC")
    if columns.get("id"):
        order_cols.append(f"{_safe_identifier(columns['id'], 'column')} DESC")
    sql = (
        f"SELECT {', '.join(projection)} FROM {safe_table} "
        f"WHERE {' AND '.join(where_parts)} "
        f"ORDER BY {', '.join(order_cols)} LIMIT 50"
    )
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(where_params))
        rows = cursor.fetchall()
    orders = []
    latest_business_date = None
    latest_snapshot_time = None
    for row in rows:
        redacted = _redact_row(dict(row))
        latest_business_date = latest_business_date or redacted.get("business_date")
        latest_snapshot_time = latest_snapshot_time or redacted.get("snapshot_time")
        order_id = redacted.get("order_id") or redacted.get("order_no")
        room_type = redacted.get("room_type_name") or redacted.get("room_type")
        daily_price = redacted.get("room_daily_price") if redacted.get("room_daily_price") not in (None, "") else redacted.get("daily_price")
        orders.append(
            {
                "order_id": order_id,
                "third_order_id": order_id,
                "order_status": "reported_fee_record",
                "order_status_raw": "rs01_room_revenue_daily",
                "room_type_id": room_type,
                "room_type_name": room_type,
                "room_nights": redacted.get("room_nights"),
                "business_date": str(redacted.get("business_date")) if redacted.get("business_date") is not None else None,
                "snapshot_time": str(redacted.get("snapshot_time")) if redacted.get("snapshot_time") is not None else None,
                "checkin_time": str(redacted.get("checkin_time")) if redacted.get("checkin_time") is not None else None,
                "checkout_time": str(redacted.get("checkout_time")) if redacted.get("checkout_time") is not None else None,
                "payment_type": redacted.get("price_type"),
                "customer_source": redacted.get("customer_source"),
                "price_detail": {
                    "rack_rate": redacted.get("rack_rate"),
                    "room_daily_price": daily_price,
                    "daily_price": daily_price,
                    "room_fee": redacted.get("room_fee"),
                    "charge_subject": redacted.get("charge_subject"),
                    "stay_type": redacted.get("stay_type"),
                },
                "privacy": {
                    "guest_name": redacted.get("guest_name"),
                    "room_no": redacted.get("room_no"),
                    "operator_name": redacted.get("operator_name"),
                },
                "risk_flags": ["database_sensitive_fields_redacted"],
            }
        )
    payload = {
        "orders": orders,
        **_template_source_metadata(
            template="order_snapshot",
            table=table,
            platform_key=platform_key,
            raw_row_count=len(rows),
            filtered_row_count=len(rows),
            data_business_date=latest_business_date,
            data_snapshot_time=latest_snapshot_time,
        ),
        **freshness_metadata(latest_snapshot_time or latest_business_date),
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_reservation_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    table = _table(profile, "reservation_snapshot")
    columns = _columns(profile, "reservation_snapshot")
    date_col = _first_existing(columns, "business_date", "arrival_time", "arrive_date", "checkin_date", "arrival_date", "prearrival_date")
    if not date_col:
        raise KeyError("database column mapping required: reservation_snapshot business/checkin date")
    room_count_col = _first_existing(columns, "room_count")
    order_dedupe_col = _first_existing(columns, "order_id", "order_no", "reservation_no")
    count_col = _first_existing(columns, "room_no", "order_id", "order_no", "reservation_no")
    room_type_col = _first_existing(columns, "room_type", "room_type_name")
    status_col = _first_existing(columns, "status", "order_status", "booking_status")
    departure_col = _first_existing(columns, "departure_time", "checkout_time", "curr_departure", "departure_date")
    safe_table = _safe_identifier(table, "table")
    tenant_clause, tenant_params, tenant_filter_mode, tenant_risks = _tenant_filter_clause(
        columns,
        hotel_id=args.hotel_id,
        hotel_name=_hotel_names(profile, args.hotel_id),
    )
    target_date = _target_date(args)
    safe_date = _safe_identifier(date_col, "column")
    select_params: list[Any] = []
    realtime_as_of_time: str | None = None
    sql_override: str | None = None
    if status_col and departure_col:
        safe_status = _safe_identifier(status_col, "column")
        safe_departure = _safe_identifier(departure_col, "column")
        unit_expr = f"COALESCE({_safe_identifier(room_count_col, 'column')}, 1)" if room_count_col else "1"
        checked_aliases = profile.get("reservation_status_checked_in_aliases") or [
            "\u5df2\u5165\u4f4f",
            "\u5165\u4f4f",
            "\u5728\u4f4f",
            "\u5df2\u5230\u5e97",
            "checked_in",
            "checkin",
            "in_house",
            "staying",
        ]
        reserved_aliases = profile.get("reservation_status_reserved_aliases") or [
            "\u9884\u8ba2",
            "\u5df2\u9884\u8ba2",
            "confirmed",
            "booked",
            "reserved",
        ]
        cancelled_aliases = profile.get("reservation_status_cancelled_aliases") or [
            "\u53d6\u6d88",
            "\u5df2\u53d6\u6d88",
            "\u53d6\u6d88\u9884\u8ba2",
            "cancel",
            "cancelled",
            "canceled",
        ]
        checked_placeholders = ", ".join(["%s"] * len(checked_aliases))
        reserved_placeholders = ", ".join(["%s"] * len(reserved_aliases))
        cancelled_placeholders = ", ".join(["%s"] * len(cancelled_aliases))
        as_of_time = _target_as_of_datetime(args, target_date)
        realtime_as_of_time = as_of_time
        checked_condition = f"TRIM({safe_status}) IN ({checked_placeholders}) AND {safe_departure} > %s"
        reserved_condition = f"TRIM({safe_status}) IN ({reserved_placeholders}) AND DATE({safe_date}) = %s"
        cancelled_condition = f"TRIM({safe_status}) IN ({cancelled_placeholders}) AND DATE({safe_date}) = %s"
        select_parts = [
            f"SUM(CASE WHEN {checked_condition} THEN {unit_expr} ELSE 0 END) AS jd01_checked_in_departure_after_as_of",
            f"SUM(CASE WHEN {reserved_condition} THEN {unit_expr} ELSE 0 END) AS jd01_reserved_raw_arrival_today",
            f"GREATEST(SUM(CASE WHEN {reserved_condition} THEN {unit_expr} ELSE 0 END) - SUM(CASE WHEN {cancelled_condition} THEN {unit_expr} ELSE 0 END), 0) AS jd01_reserved_arrival_today",
            f"SUM(CASE WHEN {cancelled_condition} THEN {unit_expr} ELSE 0 END) AS jd01_cancelled_arrival_today",
            f"MAX({safe_date}) AS business_date",
        ]
        select_params = [
            *checked_aliases,
            as_of_time,
            *reserved_aliases,
            target_date,
            *reserved_aliases,
            target_date,
            *cancelled_aliases,
            target_date,
            *cancelled_aliases,
            target_date,
        ]
        dedupe_select_params = [
            *checked_aliases,
            as_of_time,
            *reserved_aliases,
            target_date,
            *cancelled_aliases,
            target_date,
        ]
        relevance_clause = f"(({checked_condition}) OR ({reserved_condition}) OR ({cancelled_condition}))"
        base_where_parts = [tenant_clause, relevance_clause]
        base_params: list[Any] = [*tenant_params, *checked_aliases, as_of_time, *reserved_aliases, target_date, *cancelled_aliases, target_date]
        status_filter_aliases = list(dict.fromkeys([*checked_aliases, *reserved_aliases, *cancelled_aliases]))
    else:
        if room_count_col:
            count_expr = f"SUM(COALESCE({_safe_identifier(room_count_col, 'column')}, 1)) AS new_arrival_rooms"
        elif count_col:
            count_expr = f"COUNT(DISTINCT {_safe_identifier(count_col, 'column')}) AS new_arrival_rooms"
        else:
            count_expr = "COUNT(*) AS new_arrival_rooms"
        select_parts = [count_expr, f"MAX({safe_date}) AS business_date"]
        base_where_parts = [tenant_clause, f"DATE({safe_date}) = %s"]
        base_params = [*tenant_params, target_date]
        status_filter_aliases = profile.get("reservation_status_active_aliases") or [
            "\u9884\u8ba2",
            "\u5df2\u9884\u8ba2",
            "\u5df2\u5165\u4f4f",
            "\u5165\u4f4f",
            "\u5df2\u5230\u5e97",
            "confirmed",
            "booked",
            "reserved",
            "checked_in",
        ]
    if columns.get("snapshot_time"):
        select_parts.append(f"MAX({_safe_identifier(columns['snapshot_time'], 'column')}) AS data_snapshot_time")
    if room_type_col:
        select_parts.append(f"{_safe_identifier(room_type_col, 'column')} AS room_type")
    platform_key = _platform_key(args, "pms")
    platform_clause, platform_params = _source_platform_filter_clause(profile, columns, platform_key)
    if platform_clause:
        base_where_parts.append(platform_clause)
        base_params.extend(platform_params)
    where_parts = list(base_where_parts)
    params: list[Any] = [*select_params, *base_params]
    if status_col and not departure_col:
        aliases = status_filter_aliases
        placeholders = ", ".join(["%s"] * len(aliases))
        where_parts.append(f"TRIM({_safe_identifier(status_col, 'column')}) IN ({placeholders})")
        params.extend(aliases)
    group_by = f" GROUP BY {_safe_identifier(room_type_col, 'column')}" if room_type_col else ""
    if status_col and departure_col and order_dedupe_col:
        safe_order_dedupe = _safe_identifier(order_dedupe_col, "column")
        dedupe_group_cols = [safe_order_dedupe]
        inner_select_parts = [
            f"{safe_order_dedupe} AS dedupe_key",
            f"MAX(CASE WHEN {checked_condition} THEN {unit_expr} ELSE 0 END) AS jd01_checked_in_departure_after_as_of",
            f"MAX(CASE WHEN {reserved_condition} THEN {unit_expr} ELSE 0 END) AS jd01_reserved_raw_arrival_today",
            f"MAX(CASE WHEN {cancelled_condition} THEN {unit_expr} ELSE 0 END) AS jd01_cancelled_arrival_today",
            f"MAX({safe_date}) AS business_date",
        ]
        if columns.get("snapshot_time"):
            inner_select_parts.append(f"MAX({_safe_identifier(columns['snapshot_time'], 'column')}) AS data_snapshot_time")
        if room_type_col:
            inner_select_parts.append(f"{_safe_identifier(room_type_col, 'column')} AS room_type")
            dedupe_group_cols.append(_safe_identifier(room_type_col, "column"))
        outer_select_parts = [
            "SUM(jd01_checked_in_departure_after_as_of) AS jd01_checked_in_departure_after_as_of",
            "SUM(jd01_reserved_raw_arrival_today) AS jd01_reserved_raw_arrival_today",
            "GREATEST(SUM(jd01_reserved_raw_arrival_today) - SUM(jd01_cancelled_arrival_today), 0) AS jd01_reserved_arrival_today",
            "SUM(jd01_cancelled_arrival_today) AS jd01_cancelled_arrival_today",
            "MAX(business_date) AS business_date",
        ]
        if columns.get("snapshot_time"):
            outer_select_parts.append("MAX(data_snapshot_time) AS data_snapshot_time")
        if room_type_col:
            outer_select_parts.append("room_type")
        outer_group_by = " GROUP BY room_type" if room_type_col else ""
        inner_sql = (
            f"SELECT {', '.join(inner_select_parts)} FROM {safe_table} "
            f"WHERE {' AND '.join(where_parts)} GROUP BY {', '.join(dedupe_group_cols)}"
        )
        params = [*dedupe_select_params, *base_params]
        sql_override = f"SELECT {', '.join(outer_select_parts)} FROM ({inner_sql}) AS deduped{outer_group_by}"
    sql = sql_override or f"SELECT {', '.join(select_parts)} FROM {safe_table} WHERE {' AND '.join(where_parts)}{group_by}"
    with conn.cursor() as cursor:
        raw_count_sql = f"SELECT COUNT(*) AS raw_row_count FROM {safe_table} WHERE {' AND '.join(base_where_parts)}"
        cursor.execute(raw_count_sql, tuple(base_params))
        raw_row = cursor.fetchone() or {}
        raw_row_count = int(raw_row.get("raw_row_count") or 0)
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
    room_type_breakdown = []
    total = 0
    checked_in_total = 0
    reserved_raw_total = 0
    reserved_total = 0
    cancelled_total = 0
    data_date = target_date
    data_snapshot_time = None
    for row in rows:
        checked_count = int(row.get("jd01_checked_in_departure_after_as_of") or 0)
        reserved_raw_count = int(row.get("jd01_reserved_raw_arrival_today") or row.get("jd01_reserved_arrival_today") or 0)
        reserved_count = int(row.get("jd01_reserved_arrival_today") or 0)
        cancelled_count = int(row.get("jd01_cancelled_arrival_today") or 0)
        count = int(row.get("new_arrival_rooms") if row.get("new_arrival_rooms") is not None else checked_count + reserved_count)
        total += count
        checked_in_total += checked_count
        reserved_raw_total += reserved_raw_count
        reserved_total += reserved_count
        cancelled_total += cancelled_count
        data_date = target_date if checked_count or reserved_count else str(row.get("business_date") or data_date)[:10]
        data_snapshot_time = data_snapshot_time or row.get("data_snapshot_time")
        if room_type_col:
            room_type_breakdown.append(
                {
                    "room_type": row.get("room_type"),
                    "new_arrival_rooms": count,
                    "jd01_checked_in_departure_after_as_of": checked_count,
                    "jd01_reserved_raw_arrival_today": reserved_raw_count,
                    "jd01_reserved_arrival_today": reserved_count,
                    "jd01_cancelled_arrival_today": cancelled_count,
                }
            )
    source_status = "ok"
    if raw_row_count == 0:
        source_status = "no_rows"
    elif total == 0:
        source_status = "status_filtered_zero"
    risk_flags = list(tenant_risks)
    if source_status == "status_filtered_zero":
        risk_flags.append("reservation_status_unmatched")
    payload = {
        "new_arrival_rooms": total,
        "room_type_breakdown": room_type_breakdown,
        "source_table": table,
        "raw_row_count": raw_row_count,
        "filtered_room_count": total,
        "tenant_filter_mode": tenant_filter_mode,
        "status_filter_aliases": status_filter_aliases,
        "jd01_checked_in_departure_after_as_of": checked_in_total,
        "jd01_reserved_raw_arrival_today": reserved_raw_total,
        "jd01_reserved_arrival_today": reserved_total,
        "jd01_cancelled_arrival_today": cancelled_total,
        "as_of_time": realtime_as_of_time,
        **_template_source_metadata(
            template="reservation_snapshot",
            table=table,
            platform_key=platform_key,
            raw_row_count=raw_row_count,
            filtered_row_count=total,
            data_business_date=data_date,
            data_snapshot_time=data_snapshot_time,
        ),
        **freshness_metadata(data_snapshot_time or data_date),
        "source_status": source_status,
        "risk_flags": risk_flags,
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_stayover_snapshot(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    table = _table(profile, "stayover_snapshot")
    columns = _columns(profile, "stayover_snapshot")
    room_col = _first_existing(columns, "room_no", "order_no", "guest_id")
    stayover_date_col = _first_existing(columns, "business_date", "stayover_date")
    checkout_col = _first_existing(columns, "checkout_date", "checkout_time", "curr_departure", "departure_date")
    checkin_col = _first_existing(columns, "checkin_time")
    status_col = _first_existing(columns, "status")
    room_type_col = _first_existing(columns, "room_type", "room_type_name")
    if not stayover_date_col and not checkout_col:
        raise KeyError("database column mapping required: stayover_snapshot stayover date or checkout date")
    safe_table = _safe_identifier(table, "table")
    select_parts = [
        f"COUNT(DISTINCT {_safe_identifier(room_col, 'column')}) AS stayover_rooms" if room_col else "COUNT(*) AS stayover_rooms",
    ]
    date_projection_col = stayover_date_col or checkout_col
    select_parts.append(f"MAX({_safe_identifier(date_projection_col, 'column')}) AS business_date")
    if room_type_col:
        select_parts.append(f"{_safe_identifier(room_type_col, 'column')} AS room_type")
    if columns.get("snapshot_time"):
        select_parts.append(f"MAX({_safe_identifier(columns['snapshot_time'], 'column')}) AS data_snapshot_time")
    tenant_clause, tenant_params, tenant_filter_mode, tenant_risks = _tenant_filter_clause(
        columns,
        hotel_id=args.hotel_id,
        hotel_name=_hotel_names(profile, args.hotel_id),
    )
    where_parts = [tenant_clause]
    params: list[Any] = list(tenant_params)
    target_date = _target_date(args)
    as_of_time = _target_as_of_datetime(args, target_date)
    if stayover_date_col:
        where_parts.append(f"DATE({_safe_identifier(stayover_date_col, 'column')}) = %s")
        params.append(target_date)
    else:
        where_parts.append(f"{_safe_identifier(checkout_col, 'column')} > %s")
        params.append(as_of_time)
        if checkin_col:
            where_parts.append(f"DATE({_safe_identifier(checkin_col, 'column')}) <= %s")
            params.append(target_date)
    base_where_parts = list(where_parts)
    base_params = list(params)
    platform_key = _platform_key(args, "pms")
    platform_clause, platform_params = _source_platform_filter_clause(profile, columns, platform_key)
    if platform_clause:
        base_where_parts.append(platform_clause)
        base_params.extend(platform_params)
        where_parts.append(platform_clause)
        params.extend(platform_params)
    if status_col:
        aliases = profile.get("stayover_status_active_aliases") or ["\u5728\u4f4f", "\u7eed\u4f4f", "\u5df2\u7eed\u4f4f", "active", "staying", "stayover"]
        placeholders = ", ".join(["%s"] * len(aliases))
        where_parts.append(f"TRIM({_safe_identifier(status_col, 'column')}) IN ({placeholders})")
        params.extend(aliases)
    group_by = f" GROUP BY {_safe_identifier(room_type_col, 'column')}" if room_type_col else ""
    sql = f"SELECT {', '.join(select_parts)} FROM {safe_table} WHERE {' AND '.join(where_parts)}{group_by}"
    with conn.cursor() as cursor:
        raw_count_sql = f"SELECT COUNT(*) AS raw_row_count FROM {safe_table} WHERE {' AND '.join(base_where_parts)}"
        cursor.execute(raw_count_sql, tuple(base_params))
        raw_row = cursor.fetchone() or {}
        raw_row_count = int(raw_row.get("raw_row_count") or 0)
        cursor.execute(sql, tuple(params))
        rows = cursor.fetchall()
    room_type_breakdown = []
    total = 0
    data_date = target_date
    data_snapshot_time = None
    for row in rows:
        count = int(row.get("stayover_rooms") or 0)
        total += count
        data_date = str(row.get("business_date") or data_date)[:10]
        data_snapshot_time = data_snapshot_time or row.get("data_snapshot_time")
        if room_type_col:
            room_type_breakdown.append({"room_type": row.get("room_type"), "stayover_rooms": count})
    aliases = profile.get("stayover_status_active_aliases") or ["\u5728\u4f4f", "\u7eed\u4f4f", "\u5df2\u7eed\u4f4f", "active", "staying", "stayover"]
    source_status = "ok"
    if raw_row_count == 0:
        source_status = "no_rows"
    elif total == 0:
        source_status = "status_filtered_zero"
    risk_flags = list(tenant_risks)
    if source_status == "status_filtered_zero":
        risk_flags.append("stayover_status_unmatched")
    payload = {
        "stayover_rooms": total,
        "jd04_checkout_after_as_of": total,
        "room_type_breakdown": room_type_breakdown,
        "source_table": table,
        "raw_row_count": raw_row_count,
        "filtered_room_count": total,
        "tenant_filter_mode": tenant_filter_mode,
        "status_filter_aliases": aliases,
        "as_of_time": as_of_time,
        **_template_source_metadata(
            template="stayover_snapshot",
            table=table,
            platform_key=platform_key,
            raw_row_count=raw_row_count,
            filtered_row_count=total,
            data_business_date=data_date,
            data_snapshot_time=data_snapshot_time,
        ),
        **freshness_metadata(data_snapshot_time or data_date),
        "source_status": source_status,
        "risk_flags": risk_flags,
    }
    _append_freshness_risk(payload)
    return payload


def _query_mysql_metrics(conn, args: argparse.Namespace, profile: dict[str, Any], monthly: bool = False) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    payload = _mysql_latest_metrics(
        conn,
        profile,
        hotel_name,
        monthly=monthly,
        date=getattr(args, "date", None),
        source_platform=getattr(args, "source_platform", None),
        hotel_id=args.hotel_id,
    )
    payload["hotel_id"] = args.hotel_id
    payload["hotel_name"] = hotel_name
    risk_flags = list(payload.get("risk_flags") or [])
    if "database_mysql_read_only_metrics" not in risk_flags:
        risk_flags.append("database_mysql_read_only_metrics")
    payload["risk_flags"] = risk_flags
    if not monthly:
        payload.update(freshness_metadata(payload.get("data_business_date")))
        _append_freshness_risk(payload)
    return payload


def _query_mysql_v4_rows(
    conn,
    args: argparse.Namespace,
    profile: dict[str, Any],
    *,
    template: str,
    table_keys: tuple[str, ...],
    limit: int = 50,
) -> dict[str, Any]:
    hotel_name = _hotel_name(profile, args.hotel_id)
    hotel_names = _hotel_names(profile, args.hotel_id)
    enabled_ota_channels: set[str] | None = None
    skipped_channel_table_keys: list[str] = []
    channel_config_risks: list[str] = []
    channel_filter_risks: list[str] = []
    if any(_ota_channel_for_table_key(key) for key in table_keys):
        enabled_ota_channels, channel_config_risks = _load_hotel_enabled_ota_channels(conn, args, profile)
        table_keys, skipped_channel_table_keys, channel_filter_risks = _filter_ota_table_keys_by_enabled_channels(
            table_keys,
            enabled_channels=enabled_ota_channels,
            requested_platform=getattr(args, "source_platform", None),
        )
    collected: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    latest_time: Any = None
    latest_business_date: Any = None
    latest_period_month: Any = None
    latest_snapshot_time: Any = None
    missing_mappings: list[str] = []
    truncated_table_keys: list[str] = []
    runtime_risks: list[str] = [*channel_config_risks, *channel_filter_risks]
    for key in table_keys:
        if not _has_template_mapping(profile, key):
            missing_mappings.append(key)
            continue
        table = _table(profile, key)
        columns = _columns(profile, key)
        try:
            tenant_clause, tenant_params, tenant_filter_mode, tenant_risks = _tenant_filter_clause(
                columns,
                hotel_id=args.hotel_id,
                hotel_name=hotel_names,
            )
        except KeyError:
            return {
                "status": "schema_drift",
                "hotel_id": args.hotel_id,
                "hotel_name": hotel_name,
                "template": template,
                "rows": [],
                "row_count": 0,
                "source_status": "schema_drift",
                "missing_fields": ["hotel_id_or_hotel_name"],
                "risk_flags": [f"database_mysql_v4_{template}", "schema_drift"],
                "free_sql_allowed": False,
                "write_performed": False,
            }
        for risk in tenant_risks:
            if risk not in runtime_risks:
                runtime_risks.append(risk)
        date_col = _optional_col(columns, "business_date", "period_month", "snapshot_time", "updated_at", "created_at")
        if not date_col:
            raise KeyError(f"database column mapping required: {key} business_date or snapshot_time")
        projection_keys = [
            name
            for name in columns
            if name not in {"guest_name", "room_no", "order_id", "contact", "operator_name", "metadata_json"}
        ]
        projection = [f"{_safe_identifier(columns[name], 'column')} AS `{name}`" for name in projection_keys]
        platform_clause, platform_params = _source_platform_filter_clause(profile, columns, getattr(args, "source_platform", None))
        safe_table = _safe_identifier(table, "table")
        safe_date = _safe_identifier(date_col, "column")
        snapshot_as_of_clause = ""
        snapshot_as_of_params: list[Any] = []
        if getattr(args, "as_of_time", None) and columns.get("snapshot_time"):
            snapshot_as_of_clause = f"{_safe_identifier(columns['snapshot_time'], 'column')} <= %s"
            snapshot_as_of_params = [_target_as_of_datetime(args, _target_date(args))]
        if getattr(args, "date", None):
            date_clause = f"DATE({safe_date}) = %s"
            date_params = [_target_date(args)]
        else:
            latest_scope_parts = [tenant_clause]
            latest_scope_params: list[Any] = list(tenant_params)
            if snapshot_as_of_clause:
                latest_scope_parts.append(snapshot_as_of_clause)
                latest_scope_params.extend(snapshot_as_of_params)
            if platform_clause:
                latest_scope_parts.append(platform_clause)
                latest_scope_params.extend(platform_params)
            date_clause = f"{safe_date} = (SELECT MAX({safe_date}) FROM {safe_table} WHERE {' AND '.join(latest_scope_parts)})"
            date_params = latest_scope_params
        where_parts = [tenant_clause, date_clause]
        where_params: list[Any] = [*tenant_params, *date_params]
        scope_parts = [tenant_clause, date_clause]
        scope_params: list[Any] = [*tenant_params, *date_params]
        if snapshot_as_of_clause:
            where_parts.append(snapshot_as_of_clause)
            where_params.extend(snapshot_as_of_params)
            scope_parts.append(snapshot_as_of_clause)
            scope_params.extend(snapshot_as_of_params)
        if platform_clause:
            where_parts.append(platform_clause)
            where_params.extend(platform_params)
            scope_parts.append(platform_clause)
            scope_params.extend(platform_params)
        snapshot_clause, snapshot_params = _latest_snapshot_clause(table, columns, scope_parts, scope_params)
        if snapshot_clause and (date_col != columns.get("snapshot_time") or getattr(args, "date", None)):
            where_parts.append(snapshot_clause)
            where_params.extend(snapshot_params)
        elif not columns.get("snapshot_time") and date_col in {columns.get("updated_at"), columns.get("created_at")}:
            fallback_name = "updated_at" if date_col == columns.get("updated_at") else "created_at"
            risk = f"snapshot_time_missing_used_{fallback_name}"
            if risk not in runtime_risks:
                runtime_risks.append(risk)
        order_cols = [_safe_identifier(date_col, "column")]
        if columns.get("snapshot_time") and date_col != columns.get("snapshot_time"):
            order_cols.append(_safe_identifier(columns["snapshot_time"], "column"))
        sql = (
            f"SELECT {', '.join(projection)} FROM {safe_table} "
            f"WHERE {' AND '.join(where_parts)} "
            f"ORDER BY {', '.join(f'{col} DESC' for col in order_cols)} LIMIT %s"
        )
        with conn.cursor() as cursor:
            cursor.execute(sql, tuple(where_params + [limit]))
            rows = cursor.fetchall()
        if len(rows) >= limit:
            truncated_table_keys.append(key)
        sources.append({"table_key": key, "table": table, "row_count": len(rows)})
        for row in rows:
            raw_row = dict(row)
            row_risk_flags: list[str] = []
            has_product_cipher: bool | None = None
            if "product_cipher" in raw_row:
                has_cipher = raw_row.get("product_cipher") not in (None, "")
                has_product_cipher = bool(has_cipher)
                raw_row["has_product_cipher"] = bool(has_cipher)
                if key == "ctrip_price_task" and not has_cipher:
                    row_risk_flags.append("ctrip_product_cipher_missing")
            safe_row = _redact_sensitive_fields(raw_row, profile)
            safe_row.pop("product_cipher", None)
            if has_product_cipher is not None:
                safe_row["has_product_cipher"] = has_product_cipher
            safe_row["table_key"] = key
            safe_row["tenant_filter_mode"] = tenant_filter_mode
            if row_risk_flags:
                safe_row["row_risk_flags"] = row_risk_flags
            collected.append(safe_row)
            for risk in row_risk_flags:
                if risk not in runtime_risks:
                    runtime_risks.append(risk)
            latest_business_date = latest_business_date or safe_row.get("business_date")
            latest_period_month = latest_period_month or safe_row.get("period_month")
            latest_snapshot_time = latest_snapshot_time or safe_row.get("snapshot_time")
            latest_time = latest_time or safe_row.get("snapshot_time") or safe_row.get("business_date") or safe_row.get("period_month")
    normalizer_profile = {
        **profile,
        "hotel_id": args.hotel_id,
        "hotel_name": hotel_name,
        "legacy_hotel_names": {args.hotel_id: hotel_name},
    }
    mapping_rows = _load_room_mapping_rows(conn, args, profile)
    mapping_index = build_room_mapping_index(mapping_rows)
    normalized_rows = normalize_rows_for_template(template, collected, mapping_index, normalizer_profile)
    collected = normalized_rows
    source_status = "ok" if collected else ("mapping_missing" if missing_mappings and not sources else "no_rows")
    payload = {
        "hotel_id": args.hotel_id,
        "hotel_name": hotel_name,
        "template": template,
        "rows": collected,
        "row_count": len(collected),
        "raw_row_count": len(collected),
        "filtered_row_count": len(collected),
        "source_status": source_status,
        "result_limit": limit,
        "truncated_table_keys": truncated_table_keys,
        "data_business_date": str(latest_business_date) if latest_business_date is not None else None,
        "data_period_month": str(latest_period_month) if latest_period_month is not None else None,
        "data_snapshot_time": str(latest_snapshot_time) if latest_snapshot_time is not None else None,
        "source_tables": sources,
        "missing_table_mappings": missing_mappings,
        "enabled_ota_channels": sorted(enabled_ota_channels) if enabled_ota_channels else None,
        "skipped_channel_table_keys": skipped_channel_table_keys,
        "risk_flags": [f"database_mysql_v4_{template}", *runtime_risks],
        "free_sql_allowed": False,
        "write_performed": False,
        **freshness_metadata(latest_time),
    }
    if missing_mappings:
        payload["risk_flags"].append("database_mysql_v4_partial_mapping")
    _append_freshness_risk(payload)
    return payload


def _count_table_rows(conn, table: str, where_parts: list[str] | None = None, where_params: list[Any] | None = None) -> int:
    safe_table = _safe_identifier(table, "table")
    sql = f"SELECT COUNT(*) AS row_count FROM {safe_table}"
    params = tuple(where_params or [])
    if where_parts:
        sql += " WHERE " + " AND ".join(where_parts)
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone() or {}
    return int(row.get("row_count") or row.get("COUNT(*)") or 0)


def _price_mapping_platform_name(table_key: str) -> str:
    if table_key.startswith("meituan"):
        return "meituan"
    if table_key.startswith("ctrip"):
        return "ctrip"
    return table_key.replace("_price_mapping", "")


def _ota_price_mapping_coverage(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    requested_platform = getattr(args, "source_platform", None)
    coverage: dict[str, Any] = {
        "hotel_id": args.hotel_id,
        "requested_platform": requested_platform,
        "tables": {},
    }
    for key in V4_TEMPLATE_TABLE_KEYS["ota_price_mapping"]:
        if not _has_template_mapping(profile, key):
            continue
        table = _table(profile, key)
        columns = _columns(profile, key)
        hotel_col = _col(columns, "hotel_id")
        safe_hotel = _safe_identifier(hotel_col, "column")
        platform_clause, platform_params = _source_platform_filter_clause(profile, columns, requested_platform)
        total_count = _count_table_rows(conn, table)
        hotel_count = _count_table_rows(conn, table, [f"{safe_hotel} = %s"], [args.hotel_id])
        platform_count: int | None = None
        if requested_platform and platform_clause:
            platform_count = _count_table_rows(conn, table, [f"{safe_hotel} = %s", platform_clause], [args.hotel_id, *platform_params])
        coverage[_price_mapping_platform_name(key)] = {
            "table_key": key,
            "source_table": table,
            "table_row_count": total_count,
            "hotel_row_count": hotel_count,
            "hotel_platform_row_count": platform_count,
        }
        coverage["tables"][key] = coverage[_price_mapping_platform_name(key)]
    return coverage


def _classify_ota_price_mapping_empty_result(raw: dict[str, Any], coverage: dict[str, Any]) -> tuple[str, list[str]]:
    if raw.get("row_count") or raw.get("price_snapshots"):
        return "ok", []
    table_items = [value for key, value in coverage.items() if isinstance(value, dict) and key not in {"tables"}]
    total_rows = sum(int(item.get("table_row_count") or 0) for item in table_items)
    hotel_rows = sum(int(item.get("hotel_row_count") or 0) for item in table_items)
    requested_platform = coverage.get("requested_platform")
    platform_counts = [item.get("hotel_platform_row_count") for item in table_items if item.get("hotel_platform_row_count") is not None]
    platform_rows = sum(int(value or 0) for value in platform_counts)
    if total_rows == 0:
        return "mapping_table_empty", ["ota_mapping_table_empty"]
    if hotel_rows == 0:
        return "hotel_mapping_not_configured", ["ota_mapping_missing_for_current_hotel"]
    if requested_platform and platform_counts and platform_rows == 0:
        return "platform_mapping_not_configured", ["platform_mapping_not_configured"]
    if requested_platform and platform_counts and platform_rows > 0:
        return "mapping_filter_bug_suspected", ["ota_mapping_filter_bug_suspected"]
    return "hotel_mapping_not_configured", ["ota_mapping_missing_for_current_hotel"]


def _truthy_mapping_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) == 1.0
    text = str(value or "").strip().lower()
    if text in {"1", "1.0", "1.0000", "true", "yes", "y"}:
        return True
    try:
        return float(text) == 1.0
    except ValueError:
        return False


def _product_price_guard_candidate(row: dict[str, Any], *, room_type_id: str, room_type_name: str) -> dict[str, Any] | None:
    channel = normalize_source_platform(
        row.get("source_platform") or row.get("channel_source") or _price_mapping_platform_name(str(row.get("table_key") or ""))
    )
    current_price = _to_float_or_none(row.get("ota_sale_price") or row.get("current_price"))
    product_id = row.get("ota_product_id") or row.get("source_product_id")
    if channel != "meituan" or current_price is None or not product_id:
        return None
    product_name = str(row.get("ota_product_name") or row.get("source_product_name") or "")
    is_hour_room = any(token in product_name.lower() for token in ("钟点房", "小时", "hour")) or _truthy_mapping_flag(row.get("is_hour_room"))
    if is_hour_room:
        product_type = "hour_room"
        limit = 0.15
        full_day_applicable = False
    elif _truthy_mapping_flag(row.get("is_super_deal")):
        product_type = "super_deal"
        limit = 0.15
        full_day_applicable = True
    else:
        product_type = "listed_full_day"
        limit = 0.20
        full_day_applicable = True
    floor = round(current_price * (1 - limit), 2)
    ceiling = round(current_price * (1 + limit), 2)
    return {
        "policy_scope": "product",
        "product_type": product_type,
        "channel_source": channel,
        "room_type_id": str(room_type_id),
        "room_type_name": room_type_name,
        "ota_product_id": product_id,
        "ota_product_name": row.get("ota_product_name"),
        "current_price": current_price,
        "floor_price": floor,
        "ceiling_price": ceiling,
        "max_increase_pct": limit,
        "max_decrease_pct": limit,
        "min_increase_pct": 0.0,
        "min_decrease_pct": 0.0,
        "full_day_price_guard_applicable": full_day_applicable,
        "activation_required": True,
        "execution_allowed": False,
        "source": "ota_price_mapping_product_type_candidate",
    }


def _query_mysql_ota_price_mapping(conn, args: argparse.Namespace, profile: dict[str, Any]) -> dict[str, Any]:
    mapping_coverage = _ota_price_mapping_coverage(conn, args, profile)
    exact_profile = dict(profile)
    exact_profile["columns"] = {key: dict(value) for key, value in (profile.get("columns") or {}).items()}
    for key in V4_TEMPLATE_TABLE_KEYS["ota_price_mapping"]:
        if key in exact_profile["columns"]:
            exact_profile["columns"][key].pop("hotel_name", None)
    raw = _query_mysql_v4_rows(
        conn,
        args,
        exact_profile,
        template="ota_price_mapping",
        table_keys=V4_TEMPLATE_TABLE_KEYS["ota_price_mapping"],
    )
    prices: list[dict[str, Any]] = []
    mapping_risks: list[str] = []
    for row in raw.get("rows") or []:
        mapping_incomplete = not str(row.get("room_type_id") or "").strip()
        row_risk_flags = list(row.get("row_risk_flags") or [])
        if mapping_incomplete and "ota_room_type_mapping_incomplete" not in row_risk_flags:
            row_risk_flags.append("ota_room_type_mapping_incomplete")
        for risk in row_risk_flags:
            if risk not in mapping_risks:
                mapping_risks.append(risk)
        room_type_id = row.get("room_type_id") or "unknown"
        # Keep the OTA-side name separate from the canonical/PMS room type.
        # S5 displays the product being priced, while its inventory and
        # historical-revenue evidence remains tied to the canonical room type.
        ota_room_type_name = (
            row.get("source_room_type_name")
            or row.get("ota_room_type_name")
            or row.get("room_type_name")
        )
        room_type_name = row.get("pms_room_type_name") or row.get("room_type_name") or str(room_type_id)
        channel = normalize_source_platform(
            row.get("source_platform") or row.get("channel_source") or _price_mapping_platform_name(str(row.get("table_key") or ""))
        )
        candidate = _product_price_guard_candidate(row, room_type_id=str(room_type_id), room_type_name=room_type_name)
        prices.append(
            {
                "room_type_id": str(room_type_id),
                "room_type_name": room_type_name,
                "ota_room_type_name": ota_room_type_name,
                "channel": channel,
                "current_price": row.get("ota_sale_price"),
                "listed_price": row.get("ota_sale_price"),
                "price_floor": None,
                "price_ceiling": None,
                "ota_product_id": row.get("ota_product_id"),
                "ota_product_name": row.get("ota_product_name"),
                "commission_rate": row.get("commission_rate"),
                "price_editable_flag": row.get("price_editable_flag"),
                "is_hour_room": row.get("is_hour_room"),
                "is_super_deal": row.get("is_super_deal"),
                "mapping_id": row.get("mapping_id"),
                "mapping_status": row.get("mapping_status"),
                "match_rule": row.get("match_rule"),
                "mapping_active": row.get("mapping_active"),
                "mapping_resolution_status": row.get("mapping_resolution_status"),
                "business_date": row.get("business_date"),
                "snapshot_time": row.get("snapshot_time"),
                "price_guard_source": "ota_price_mapping",
                "source_table_key": row.get("table_key"),
                "has_product_cipher": row.get("has_product_cipher"),
                "row_risk_flags": row_risk_flags,
                "risk_flags": list(row.get("risk_flags") or []),
                "product_type": candidate.get("product_type") if candidate else None,
                "product_price_guard_candidate": candidate,
            }
        )
    risk_flags = list(raw.get("risk_flags") or [])
    for risk in mapping_risks:
        if risk not in risk_flags:
            risk_flags.append(risk)
    source_status, empty_risks = _classify_ota_price_mapping_empty_result(raw, mapping_coverage)
    if source_status != "ok":
        raw["source_status"] = source_status
    for risk in empty_risks:
        if risk not in risk_flags:
            risk_flags.append(risk)
    return {
        **raw,
        "risk_flags": risk_flags,
        "mapping_coverage": mapping_coverage,
        "price_snapshots": prices,
        "price_snapshot_source": "puyue_27_tables.ota_price_mapping",
    }


def _query_mysql(args: argparse.Namespace) -> dict[str, Any]:
    config = _load_mapping_config(getattr(args, "mapping_config", None))
    profile = _profile(config, getattr(args, "profile", None), hotel_id=getattr(args, "hotel_id", None))
    if not profile:
        return {
            "status": "blocked",
            "reason": "database_mapping_required",
            "db_kind": "mysql",
            "template": args.template,
            "message": "Configure HOTEL_OTA_DB_MAPPING_CONFIG and HOTEL_OTA_DB_PROFILE before using mysql templates.",
        }
    if profile.get("db_kind", "mysql") != "mysql":
        return {"status": "blocked", "reason": "database_profile_kind_mismatch", "profile": profile.get("_profile_name"), "db_kind": profile.get("db_kind")}
    conn, blocked = _connect_mysql(args, profile)
    if blocked:
        return blocked
    assert conn is not None
    with conn:
        if args.template == "operating_snapshot":
            payload = _query_mysql_operating_snapshot(conn, args, profile)
        elif args.template == "price_snapshot":
            payload = _query_mysql_price_snapshot(conn, args, profile)
        elif args.template == "order_snapshot":
            payload = _query_mysql_order_snapshot(conn, args, profile)
        elif args.template == "customer_order_analysis":
            from runtime.adapters.s17_repository import query_mysql_s17

            payload = query_mysql_s17(conn, args, profile)
        elif args.template == "demand_context":
            payload = _query_mysql_demand_context(conn, args, profile)
        elif args.template == "operation_diagnosis":
            payload = _query_mysql_operation_diagnosis(conn, args, profile)
        elif args.template == "sales_baseline":
            payload = _query_mysql_sales_baseline(conn, args, profile)
        elif args.template == "daily_metrics":
            payload = _query_mysql_metrics(conn, args, profile, monthly=False)
        elif args.template == "monthly_metrics":
            payload = _query_mysql_metrics(conn, args, profile, monthly=True)
        elif args.template == "reservation_snapshot":
            payload = _query_mysql_reservation_snapshot(conn, args, profile)
        elif args.template == "stayover_snapshot":
            payload = _query_mysql_stayover_snapshot(conn, args, profile)
        elif args.template == "room_status_snapshot":
            payload = _query_mysql_v4_rows(conn, args, profile, template=args.template, table_keys=("room_status_snapshot",))
        elif args.template == "room_fee_daily":
            payload = _query_mysql_v4_rows(conn, args, profile, template=args.template, table_keys=("room_fee_daily",))
        elif args.template == "ota_price_mapping":
            payload = _query_mysql_ota_price_mapping(conn, args, profile)
        elif args.template in V4_TEMPLATE_TABLE_KEYS:
            payload = _query_mysql_v4_rows(
                conn,
                args,
                profile,
                template=args.template,
                table_keys=V4_TEMPLATE_TABLE_KEYS[args.template],
                limit=V4_TEMPLATE_RESULT_LIMITS.get(args.template, 50),
            )
        else:
            raise ValueError(f"unsupported mysql template: {args.template}")
    return {
        **_source(
            "mysql",
            "confirmed",
            channel_source=_template_channel_source(args.template, getattr(args, "source_platform", None)),
            profile=profile,
        ),
        "template": args.template,
        "profile": profile.get("_profile_name"),
        "hotel_id": args.hotel_id,
        "risk_flags": _view_migration_risks(profile),
        "payload": payload,
    }


def _query_external(args: argparse.Namespace) -> dict[str, Any]:
    missing = _missing_driver(args.db_kind)
    if missing:
        return missing
    return {
        "status": "blocked",
        "reason": "external_database_template_not_enabled",
        "db_kind": args.db_kind,
        "template": args.template,
        "message": "Postgres requires confirmed driver, DSN, and field mapping before live templates are enabled.",
    }


def database_source_enabled() -> bool:
    return os.environ.get("HOTEL_OTA_DB_SOURCE_ENABLE", "0") == "1"


def _timing_row_count(result: dict[str, Any]) -> int | None:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    for key in ("row_count", "raw_row_count", "filtered_row_count"):
        if payload.get(key) is not None:
            try:
                return int(payload.get(key))
            except (TypeError, ValueError):
                return None
    for key in ("rows", "orders", "price_snapshots"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return None


def _finish_database_template_result(result: dict[str, Any], *, started_at: float, template: str, hotel_id: str) -> dict[str, Any]:
    if os.environ.get("HOTEL_OTA_DB_TIMING_LOG", "0") != "1":
        return result
    try:
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        path = Path(os.environ.get("HOTEL_OTA_DB_TIMING_LOG_PATH") or os.environ.get("HOTEL_OTA_LOG_DIR") or DEFAULT_LOG_DIR) / "database-template-timing.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": now_local(),
            "template": template,
            "hotel_id": hotel_id,
            "status": result.get("status"),
            "duration_ms": int((time.perf_counter() - started_at) * 1000),
            "source_status": payload.get("source_status"),
            "reason": result.get("reason") or payload.get("reason"),
            "row_count": _timing_row_count(result),
            "risk_flags": payload.get("risk_flags") or result.get("risk_flags") or [],
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json_dumps(record) + "\n")
    except Exception:
        return result
    return result


def database_template_result(
    template: str,
    hotel_id: str,
    db_kind: str | None = None,
    dsn: str | None = None,
    profile: str | None = None,
    mapping_config: str | None = None,
    date: str | None = None,
    source_platform: str | None = None,
    as_of_time: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    minimum_cohort_size: int | None = None,
    max_output_cells: int | None = None,
    contact_lookup_value: str | None = None,
) -> dict[str, Any]:
    started_at = time.perf_counter()
    if template not in TEMPLATES:
        return _finish_database_template_result({"status": "blocked", "reason": "unknown_template", "allowed_templates": list(TEMPLATES)}, started_at=started_at, template=template, hotel_id=hotel_id)
    if os.environ.get("HOTEL_OTA_DB_READONLY", "1") != "1":
        return _finish_database_template_result({"status": "blocked", "reason": "database_adapter_requires_readonly"}, started_at=started_at, template=template, hotel_id=hotel_id)
    args = argparse.Namespace(
        db_kind=db_kind or os.environ.get("HOTEL_OTA_DB_KIND", "sqlite"),
        template=template,
        hotel_id=hotel_id,
        dsn=dsn,
        profile=profile,
        mapping_config=mapping_config,
        date=date,
        source_platform=source_platform,
        as_of_time=as_of_time,
        period_start=period_start,
        period_end=period_end,
        minimum_cohort_size=minimum_cohort_size,
        max_output_cells=max_output_cells,
        contact_lookup_value=contact_lookup_value,
        sql=None,
    )
    if args.db_kind == "sqlite":
        if template not in SQLITE_TEMPLATES:
            return _finish_database_template_result({"status": "blocked", "reason": "sqlite_template_not_enabled", "template": template}, started_at=started_at, template=template, hotel_id=hotel_id)
        payload = _query_sqlite(args)
        return _finish_database_template_result({"status": "ok", **redacted_request(payload), "contract_validation": validate_contract(payload)}, started_at=started_at, template=template, hotel_id=hotel_id)
    if args.db_kind == "mysql":
        try:
            result = _query_mysql(args)
        except (KeyError, ValueError) as exc:
            return _finish_database_template_result({
                "status": "blocked",
                "reason": "database_mapping_invalid",
                "template": template,
                "message": "Database table or column mapping is invalid. Update the private mapping profile with confirmed source tables and columns; do not create views from Feishu or Agent output.",
                "error_type": exc.__class__.__name__,
            }, started_at=started_at, template=template, hotel_id=hotel_id)
        if result.get("status") == "blocked":
            return _finish_database_template_result(result, started_at=started_at, template=template, hotel_id=hotel_id)
        return _finish_database_template_result({"status": "ok", **redacted_request(result), "contract_validation": validate_contract(result)}, started_at=started_at, template=template, hotel_id=hotel_id)
    return _finish_database_template_result(_query_external(args), started_at=started_at, template=template, hotel_id=hotel_id)


def database_inspect(args: argparse.Namespace) -> None:
    if args.mode not in INSPECT_MODES:
        emit({"status": "blocked", "reason": "unknown_inspect_mode", "allowed_modes": list(INSPECT_MODES)})
        return
    if os.environ.get("HOTEL_OTA_DB_READONLY", "1") != "1":
        emit({"status": "blocked", "reason": "database_adapter_requires_readonly"})
        return
    if args.db_kind != "mysql":
        emit({"status": "blocked", "reason": "inspect_only_enabled_for_mysql_v1", "db_kind": args.db_kind})
        return

    config = _load_mapping_config(getattr(args, "mapping_config", None))
    profile = _profile(config, getattr(args, "profile", None))
    conn, blocked = _connect_mysql(args, profile)
    if blocked:
        emit(blocked)
        return
    assert conn is not None
    inspect_meta = _inspect_profile_metadata(profile)
    with conn:
        with conn.cursor() as cursor:
            if args.mode == "connection":
                cursor.execute("SELECT 1 AS ok")
                cursor.fetchone()
                emit({"status": "ok", "db_kind": "mysql", "mode": "connection", **inspect_meta})
                return
            if args.mode == "tables":
                cursor.execute(
                    """
                    SELECT TABLE_NAME AS table_name, TABLE_ROWS AS estimated_row_count, UPDATE_TIME AS updated_at
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'
                    ORDER BY TABLE_NAME
                    """
                )
                rows = [dict(row) for row in cursor.fetchall()]
                metadata = []
                for row in rows:
                    table_name = str(row.get("table_name") or "")
                    cursor.execute(
                        """
                        SELECT COLUMN_NAME AS column_name
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                        ORDER BY ORDINAL_POSITION
                        """,
                        (table_name,),
                    )
                    column_names = [str(item.get("column_name") or "") for item in cursor.fetchall()]
                    candidates = infer_canonical_field_candidates(column_names)
                    latest_business_date = None
                    latest_candidate = None
                    for column_name in column_names:
                        if str(column_name).lower() == "business_date":
                            latest_candidate = column_name
                            break
                    if latest_candidate is None:
                        latest_candidate = next((column_name for column_name in column_names if _is_inspect_date_candidate(column_name)), None)
                    if latest_candidate:
                        try:
                            safe_table = _safe_identifier(table_name, "table")
                            safe_column = _safe_identifier(str(latest_candidate), "column")
                            cursor.execute(f"SELECT MAX({safe_column}) AS latest_value FROM {safe_table}")
                            latest_row = cursor.fetchone() or {}
                            latest_business_date = latest_row.get("latest_value")
                        except Exception:
                            latest_business_date = None
                    readiness = _inspect_table_readiness(
                        table_name=table_name,
                        column_names=column_names,
                        row_count_estimate=row.get("estimated_row_count"),
                        latest_business_date=latest_business_date,
                        updated_at=row.get("updated_at"),
                    )
                    metadata.append(
                        {
                            "estimated_row_count": row.get("estimated_row_count"),
                            "latest_update_candidates": candidates.get("updated_at") or candidates.get("business_date") or [],
                            "canonical_candidates": candidates,
                            "latest_value_column": latest_candidate,
                            **readiness,
                        }
                    )
                emit(
                    {
                        "status": "ok",
                        "db_kind": "mysql",
                        "mode": "tables",
                        "tables": [item["table_name"] for item in metadata],
                        "table_metadata": metadata,
                        **inspect_meta,
                    }
                )
                return
            if not args.table:
                emit({"status": "blocked", "reason": "table_required", "mode": args.mode})
                return
            table = args.table
            _safe_identifier(table, "table")
            if args.mode == "columns":
                cursor.execute(
                    """
                    SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type, COLUMN_TYPE AS column_type, COLUMN_COMMENT AS column_comment
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                    """,
                    (table,),
                )
                columns = [dict(row) for row in cursor.fetchall()]
                draft = inspect_canonical_mapping_draft(columns, table=table)
                emit({"status": "ok", "db_kind": "mysql", "mode": "columns", "table": table, "columns": draft["columns"], "canonical_candidates": draft["canonical_candidates"], "sensitive_column_flags": draft["sensitive_column_flags"], "template_readiness_hint": draft["readiness_hint"], "template_readiness": draft["template_readiness"], **inspect_meta})
                return
            if args.mode == "mapping-draft":
                cursor.execute(
                    """
                    SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type, COLUMN_TYPE AS column_type, COLUMN_COMMENT AS column_comment
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                    ORDER BY ORDINAL_POSITION
                    """,
                    (table,),
                )
                draft = inspect_canonical_mapping_draft([dict(row) for row in cursor.fetchall()], table=table)
                emit({"db_kind": "mysql", "mode": "mapping-draft", **draft, **inspect_meta})
                return
            limit = max(1, min(int(args.limit or 5), 5))
            cursor.execute(f"SELECT * FROM {_safe_identifier(table, 'table')} LIMIT %s", (limit,))
            sample = [_redact_row(dict(row)) for row in cursor.fetchall()]
            sample_columns = list(sample[0]) if sample else []
            candidates = infer_canonical_field_candidates(sample_columns)
            missing_required = [field for field in ("hotel_id", "business_date") if not candidates.get(field)]
            emit({"status": "ok", "db_kind": "mysql", "mode": "sample", "table": table, "limit": limit, "sample": sample, "sample_value_profile": {"column_count": len(sample_columns), "row_count": len(sample), "redacted": True}, "canonical_candidates": candidates, "missing_required_fields": missing_required, "sample_profile": {"canonical_candidates": candidates, "missing_fields": missing_required}, **inspect_meta})


def database_query(args: argparse.Namespace) -> None:
    if args.template not in TEMPLATES:
        emit({"status": "blocked", "reason": "unknown_template", "allowed_templates": list(TEMPLATES)})
        return
    if args.sql:
        emit({"status": "blocked", "reason": "free_sql_not_allowed", "allowed_templates": list(TEMPLATES)})
        return
    if os.environ.get("HOTEL_OTA_DB_READONLY", "1") != "1":
        emit({"status": "blocked", "reason": "database_adapter_requires_readonly"})
        return
    emit(
       database_template_result(
        template=args.template,
        hotel_id=args.hotel_id,
        db_kind=args.db_kind,
        dsn=getattr(args, "dsn", None),
        profile=getattr(args, "profile", None),
        mapping_config=getattr(args, "mapping_config", None),
        date=getattr(args, "date", None),
        source_platform=getattr(args, "source_platform", None),
        as_of_time=getattr(args, "as_of_time", None),
    )
    )

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from typing import Any

from runtime.common import now_local
from runtime.adapters.normalized_query import (
    build_room_mapping_index,
    is_price_task_mapping_ready,
    normalize_source_platform,
    resolve_room_type_mapping,
)
from runtime.storage import connect, init_schema


ALLOWED_EXECUTE_STATUSES = {"PENDING", "SUCCESS", "FAILED"}
SUPPORTED_CHANNELS = {"meituan", "ctrip"}
ROOM_MAPPING_TABLE = "hotel_room_type_mapping"


def normalize_price_task_channel(channel_source: str | None) -> str | None:
    text = str(channel_source or "").strip().lower()
    aliases = {
        "mtop": "meituan",
        "meituan": "meituan",
        "美团": "meituan",
        "ctrip": "ctrip",
        "携程": "ctrip",
    }
    return aliases.get(text)


def _task_table(channel_source: str, *, dialect: str = "sqlite") -> str:
    env_key = f"HOTEL_OTA_PRICE_TASK_TABLE_{channel_source.upper()}"
    configured = os.environ.get(env_key)
    if configured:
        return configured
    if dialect == "mysql":
        if channel_source == "meituan":
            return "meituan_price_task"
        if channel_source == "ctrip":
            return "ctrip_price_task"
    if channel_source == "meituan":
        return "meituan_zhiting_price_task"
    if channel_source == "ctrip":
        return "ctrip_zhiting_price_task"
    raise ValueError("unsupported_channel")


def _mapping_table(channel_source: str) -> str:
    if channel_source == "meituan":
        return "meituan_ota_goods_price_mapping"
    if channel_source == "ctrip":
        return "ctrip_ota_goods_price_mapping"
    raise ValueError("unsupported_channel")


def _allowed_channels(value: list[str] | str | None) -> set[str]:
    if value is None:
        value = os.environ.get("HOTEL_OTA_PRICE_TASK_ALLOWED_CHANNELS", "ctrip,meituan")
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = value
    return {channel for channel in (normalize_price_task_channel(item) for item in items) if channel}


def _row_to_product(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return dict(row)


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _product_type(product: dict[str, Any]) -> str:
    explicit = product.get("product_type")
    if explicit not in (None, ""):
        return str(explicit)
    name = str(product.get("ota_product_name") or product.get("source_product_name") or product.get("rate_plan_name") or "").lower()
    if _truthy(product.get("is_hour_room")) or "钟点" in name or "小时" in name or "hour" in name:
        return "hour_room"
    if _truthy(product.get("is_super_deal")):
        return "super_deal"
    if "activity" in name or "活动" in name:
        return "activity"
    return "listed_full_day"


def _product_candidate_summary(product: dict[str, Any], channel_source: str) -> dict[str, Any]:
    gate = is_price_task_mapping_ready({**product, "source_platform": channel_source})
    blocked_reason = _product_skip_reason(channel_source, product)
    ready = blocked_reason is None
    return {
        "ota_product_id": _product_id(product),
        "room_type_name": product.get("room_type_name") or product.get("pms_room_type_name"),
        "ota_sale_price": product.get("ota_sale_price"),
        "product_type": _product_type(product),
        "mapping_status": "mapped" if ready else gate.get("mapping_resolution_status"),
        "mapping_trust_basis": gate.get("mapping_trust_basis"),
        "ready_for_price_task": ready,
        "blocked_reason": blocked_reason or gate.get("blocked_reason"),
        "price_guard_source": product.get("price_guard_source") or product.get("price_guard_policy_source") or "not_evaluated_in_outbox",
    }


def _connect_task_db(db_path: str, *, db_kind: str | None = None, dsn: str | None = None) -> tuple[Any | None, str, dict[str, Any] | None]:
    kind = (db_kind or os.environ.get("HOTEL_OTA_PRICE_TASK_DB_KIND") or os.environ.get("HOTEL_OTA_DB_KIND") or "sqlite").lower()
    if kind == "mysql":
        try:
            import pymysql
            from runtime.adapters.database import _parse_mysql_dsn
        except Exception:
            return None, "mysql", {
                "status": "blocked",
                "blocked_reason": "missing_mysql_driver",
                "message": "Install PyMySQL before writing zhiting price task outbox to MySQL.",
            }
        if not dsn:
            return None, "mysql", {"status": "blocked", "blocked_reason": "price_task_dsn_not_configured"}
        params = _parse_mysql_dsn(dsn)
        conn = pymysql.connect(
            host=params["host"],
            port=params["port"],
            user=params["user"],
            password=params["password"],
            database=params["database"],
            charset=params["charset"],
            autocommit=False,
            cursorclass=pymysql.cursors.DictCursor,
        )
        return conn, "mysql", None
    if kind != "sqlite":
        return None, kind, {"status": "blocked", "blocked_reason": "unsupported_price_task_db_kind", "db_kind": kind}
    conn = connect(db_path)
    init_schema(conn)
    return conn, "sqlite", None


def _placeholder(dialect: str) -> str:
    return "%s" if dialect == "mysql" else "?"


def _fetchall(conn: Any, dialect: str, sql: str, params: tuple[Any, ...] | list[Any]) -> list[dict[str, Any]]:
    if dialect == "mysql":
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]
    return [_row_to_product(row) for row in conn.execute(sql, params).fetchall()]


def _fetchone(conn: Any, dialect: str, sql: str, params: tuple[Any, ...] | list[Any]) -> dict[str, Any] | None:
    if dialect == "mysql":
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row else None
    row = conn.execute(sql, params).fetchone()
    return _row_to_product(row) if row else None


def _table_columns(conn: Any, dialect: str, table: str) -> set[str]:
    if dialect == "mysql":
        with conn.cursor() as cur:
            cur.execute(f"SHOW COLUMNS FROM {table}")
            return {str(row.get("Field") or row.get("field") or "") for row in cur.fetchall()}
    return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _execute(conn: Any, dialect: str, sql: str, params: tuple[Any, ...] | list[Any]) -> None:
    if dialect == "mysql":
        with conn.cursor() as cur:
            cur.execute(sql, params)
        return
    conn.execute(sql, params)


def _mapping_rows_for_room_type(
    conn: Any,
    *,
    dialect: str,
    channel_source: str,
    hotel_id: str | None,
    hotel_name: str,
    room_type_id: str | None,
    room_type_name: str,
    ota_product_id: str | None = None,
) -> list[dict[str, Any]]:
    try:
        columns = _table_columns(conn, dialect, ROOM_MAPPING_TABLE)
    except Exception:
        return []
    if not columns:
        return []
    projection_names = [
        "id",
        "hotel_id",
        "hotel_name",
        "room_type_id",
        "room_type_name",
        "source_platform",
        "source_room_type_id",
        "source_room_type_name",
        "source_product_id",
        "source_product_name",
        "rate_plan_name",
        "product_cipher",
        "price_editable_flag",
        "is_hour_room",
        "mapping_status",
        "match_rule",
        "is_active",
    ]
    projection = [name for name in projection_names if name in columns]
    if not projection:
        return []
    ph = _placeholder(dialect)
    where: list[str] = []
    params: list[Any] = []
    if "hotel_id" in columns and hotel_id:
        where.append(f"hotel_id={ph}")
        params.append(hotel_id)
    elif "hotel_name" in columns:
        where.append(f"hotel_name={ph}")
        params.append(hotel_name)
    if room_type_id and "room_type_id" in columns:
        where.append(f"room_type_id={ph}")
        params.append(room_type_id)
    elif room_type_name and "room_type_name" in columns:
        where.append(f"room_type_name={ph}")
        params.append(room_type_name)
    if ota_product_id and "source_product_id" in columns:
        # A confirmed write always targets one OTA product.  Narrow the mapping
        # lookup as well, rather than expanding every product under the room type.
        where.append(f"source_product_id={ph}")
        params.append(str(ota_product_id).strip())
    if not where:
        return []
    try:
        rows = _fetchall(
            conn,
            dialect,
            f"""
            SELECT {', '.join(projection)}
            FROM {ROOM_MAPPING_TABLE}
            WHERE {' AND '.join(where)}
            LIMIT 200
            """,
            params,
        )
    except Exception:
        return []
    return [
        row
        for row in rows
        if normalize_source_platform(row.get("source_platform")) == channel_source
    ]


def _enrich_product_with_mapping(product: dict[str, Any], mapping_rows: list[dict[str, Any]], channel_source: str) -> dict[str, Any]:
    if not mapping_rows:
        return product
    mapping_index = build_room_mapping_index(mapping_rows)
    raw = {
        **product,
        "source_platform": channel_source,
        "source_product_id": product.get("source_product_id") or product.get("ota_product_id"),
        "source_room_type_id": product.get("source_room_type_id") or product.get("ota_room_type_id"),
        "source_room_type_name": product.get("source_room_type_name") or product.get("room_type_name"),
    }
    mapping = resolve_room_type_mapping(raw, mapping_index)
    if not mapping.get("mapping_id"):
        # A mapping row exists but does not have a trusted exact-match signal.
        # Preserve that fact so the write gate fails closed instead of treating
        # the raw OTA product as an ungoverned legacy row.
        return {
            **product,
            "mapping_status": mapping.get("mapping_status") or "PENDING",
            "match_rule": mapping.get("match_rule"),
            "mapping_active": bool(mapping.get("mapping_active")),
            "mapping_resolution_status": mapping.get("mapping_resolution_status"),
        }
    enriched = dict(product)
    for key in (
        "mapping_id",
        "mapping_status",
        "match_rule",
        "mapping_active",
        "room_type_id",
        "source_room_type_id",
        "source_product_id",
        "source_product_name",
        "price_editable_flag",
        "is_hour_room",
        "product_cipher",
    ):
        if mapping.get(key) not in (None, ""):
            enriched[key] = mapping.get(key)
    if mapping.get("room_type_name") not in (None, ""):
        enriched.setdefault("pms_room_type_name", mapping.get("room_type_name"))
    return enriched


def _select_products(
    conn: Any,
    *,
    dialect: str,
    channel_source: str,
    hotel_id: str | None,
    hotel_name: str,
    room_type_id: str | None,
    room_type_name: str,
    business_date: str,
    ota_product_id: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    table = _mapping_table(channel_source)
    columns = _table_columns(conn, dialect, table)
    required = {"ota_product_id", "business_date"}
    missing = sorted(required - columns)
    if missing:
        return [], [f"mapping_missing_required_columns:{','.join(missing)}"]
    ph = _placeholder(dialect)
    where = [f"business_date={ph}"]
    params: list[Any] = [business_date]
    warnings: list[str] = []
    if "hotel_id" in columns and hotel_id:
        where.append(f"hotel_id={ph}")
        params.append(hotel_id)
    elif "hotel_name" in columns:
        where.append(f"(hotel_name={ph} OR hotel_name IS NULL OR hotel_name='')")
        params.append(hotel_name)
        if not hotel_id:
            warnings.append("mapping_hotel_id_not_available_used_hotel_name")
    else:
        warnings.append("mapping_hotel_scope_column_missing")
    mapping_rows = _mapping_rows_for_room_type(
        conn,
        dialect=dialect,
        channel_source=channel_source,
        hotel_id=hotel_id,
        hotel_name=hotel_name,
        room_type_id=room_type_id,
        room_type_name=room_type_name,
        ota_product_id=ota_product_id,
    )
    room_clauses: list[str] = []
    room_params: list[Any] = []
    mapped_product_ids = [str(row.get("source_product_id") or "").strip() for row in mapping_rows]
    mapped_room_type_ids = [str(row.get("source_room_type_id") or "").strip() for row in mapping_rows]
    mapped_room_type_names = [str(row.get("source_room_type_name") or row.get("room_type_name") or "").strip() for row in mapping_rows]
    if mapped_product_ids and "ota_product_id" in columns:
        placeholders = ", ".join([ph] * len(list(dict.fromkeys(mapped_product_ids))))
        room_clauses.append(f"ota_product_id IN ({placeholders})")
        room_params.extend(list(dict.fromkeys(mapped_product_ids)))
    if mapped_room_type_ids and "ota_room_type_id" in columns:
        placeholders = ", ".join([ph] * len(list(dict.fromkeys(mapped_room_type_ids))))
        room_clauses.append(f"ota_room_type_id IN ({placeholders})")
        room_params.extend(list(dict.fromkeys(mapped_room_type_ids)))
    if mapped_room_type_names and "room_type_name" in columns:
        placeholders = ", ".join([ph] * len(list(dict.fromkeys(mapped_room_type_names))))
        room_clauses.append(f"room_type_name IN ({placeholders})")
        room_params.extend(list(dict.fromkeys(mapped_room_type_names)))
    if room_type_id:
        for col in ("room_type_id", "pms_room_type_id"):
            if col in columns:
                room_clauses.append(f"{col}={ph}")
                room_params.append(room_type_id)
    if room_type_name and "room_type_name" in columns:
        room_clauses.append(f"room_type_name={ph}")
        room_params.append(room_type_name)
    if ota_product_id:
        # Keep the post-read mapping gate, but make the source query exact for
        # the approved product.  This is the common confirmed-write path.
        where.append(f"ota_product_id={ph}")
        params.append(str(ota_product_id).strip())
    elif not room_clauses:
        return [], ["mapping_missing_room_type_columns"]
    if room_clauses:
        where.append(f"({' OR '.join(room_clauses)})")
        params.extend(room_params)
    rows = _fetchall(
        conn,
        dialect,
        f"""
        SELECT *
        FROM {table}
        WHERE {' AND '.join(where)}
        ORDER BY ota_product_id
        """,
        params,
    )
    return [_enrich_product_with_mapping(dict(row), mapping_rows, channel_source) for row in rows], warnings


def _pending_exists(conn: Any, dialect: str, *, table: str, ota_product_id: str, business_date: str) -> bool:
    ph = _placeholder(dialect)
    row = _fetchone(
        conn,
        dialect,
        f"SELECT id FROM {table} WHERE ota_product_id={ph} AND business_date={ph} AND execute_status='PENDING' LIMIT 1",
        (ota_product_id, business_date),
    )
    return row is not None


def _review_lifecycle_for_execute_status(execute_status: str | None) -> tuple[str, list[str]]:
    base = ["created", "pending_review", "approved", "queued_to_plugin"]
    status = str(execute_status or "").strip().upper()
    if status == "SUCCESS":
        return "verification_pending", [*base, "plugin_success", "verification_pending"]
    if status == "FAILED":
        return "plugin_failed", [*base, "plugin_failed"]
    return "queued_to_plugin", base


def _product_skip_reason(channel_source: str, product: dict[str, Any]) -> str | None:
    if not (product.get("ota_product_id") or product.get("source_product_id")):
        return "ota_product_id_missing"
    governance_fields = {"mapping_status", "mapping_active", "is_active", "room_type_id", "source_product_id", "is_hour_room"}
    governance_present = any(product.get(name) not in (None, "") for name in governance_fields)
    if governance_present:
        gate = is_price_task_mapping_ready({**product, "source_platform": channel_source})
        if not gate.get("ready_for_price_task"):
            return str(gate.get("blocked_reason") or gate.get("mapping_resolution_status") or "mapping_pending")
    if channel_source == "ctrip" and not product.get("product_cipher"):
        return "ctrip_product_cipher_missing"
    return None


def _product_id(product: dict[str, Any]) -> str:
    return str(product.get("ota_product_id") or product.get("source_product_id") or "")


def _insert_task(
    conn: Any,
    *,
    dialect: str,
    channel_source: str,
    table: str,
    hotel_name: str,
    product: dict[str, Any],
    room_type_name: str,
    business_date: str,
    target_sale_price: float,
    source_decision_id: str,
    created_by: str,
    created_at: str,
) -> None:
    ph = _placeholder(dialect)
    columns = _table_columns(conn, dialect, table)
    current_price = product.get("ota_sale_price") or product.get("current_sale_price")
    try:
        price_delta = float(target_sale_price) - float(current_price) if current_price not in (None, "") else None
        price_delta_pct = price_delta / float(current_price) if current_price not in (None, "", 0) else None
    except (TypeError, ValueError, ZeroDivisionError):
        price_delta = None
        price_delta_pct = None
    values = {
        "hotel_id": product.get("hotel_id"),
        "hotel_name": product.get("hotel_name") or hotel_name,
        "channel_source": channel_source,
        "room_type_id": product.get("room_type_id") or product.get("pms_room_type_id"),
        "room_type_name": product.get("room_type_name") or product.get("pms_room_type_name") or room_type_name,
        "ota_room_type_id": product.get("ota_room_type_id") or product.get("source_room_type_id"),
        "ota_product_id": _product_id(product),
        "ota_product_name": product.get("ota_product_name") or product.get("source_product_name"),
        "business_date": business_date,
        "current_sale_price": current_price,
        "target_sale_price": float(target_sale_price),
        "price_delta": price_delta,
        "price_delta_pct": price_delta_pct,
        "product_cipher": product.get("product_cipher"),
        "price_editable_flag": product.get("price_editable_flag"),
        "is_hour_room": product.get("is_hour_room"),
        "execute_status": "PENDING",
        "review_status": "approved",
        "plugin_status": "pending",
        "verification_status": "pending",
        "created_at": created_at,
        "source_decision_id": source_decision_id,
        "created_by": created_by,
        "error_message": None,
        "executed_at": None,
    }
    insert_columns = [name for name in values if name in columns]
    if "ota_product_id" not in insert_columns or "target_sale_price" not in insert_columns or "execute_status" not in insert_columns:
        raise RuntimeError("price_task_table_schema_drift")
    _execute(
        conn,
        dialect,
        f"""
        INSERT INTO {table} ({', '.join(insert_columns)})
        VALUES ({', '.join([ph] * len(insert_columns))})
        """,
        tuple(values[name] for name in insert_columns),
    )


def write_zhiting_price_tasks(
    db_path: str,
    *,
    channel_source: str,
    hotel_name: str,
    room_type_name: str,
    business_date: str,
    hotel_id: str | None = None,
    room_type_id: str | None = None,
    ota_product_id: str | None = None,
    target_sale_price: float,
    source_decision_id: str,
    created_by: str,
    write_enabled: bool,
    confirmed: bool,
    allowed_channels: list[str] | str | None = None,
    now: str | None = None,
    db_kind: str | None = None,
    dsn: str | None = None,
) -> dict[str, Any]:
    channel = normalize_price_task_channel(channel_source)
    if channel not in SUPPORTED_CHANNELS:
        return {"status": "blocked", "blocked_reason": "unsupported_price_task_channel", "channel_source": channel_source}
    if channel not in _allowed_channels(allowed_channels):
        return {"status": "blocked", "blocked_reason": "price_task_channel_not_allowed", "channel_source": channel}
    if not confirmed:
        return {"status": "blocked", "blocked_reason": "price_task_confirmation_required", "channel_source": channel, "write_performed": False, "live_api_called": False}

    created_at = now or now_local()
    conn, dialect, blocked = _connect_task_db(db_path, db_kind=db_kind, dsn=dsn)
    if blocked:
        return {**blocked, "channel_source": channel, "write_performed": False, "live_api_called": False}
    table = _task_table(channel, dialect=dialect)
    with closing(conn):
        try:
            products, mapping_warnings = _select_products(
                conn,
                dialect=dialect,
                channel_source=channel,
                hotel_id=hotel_id,
                hotel_name=hotel_name,
                room_type_id=room_type_id,
                room_type_name=room_type_name,
                business_date=business_date,
                ota_product_id=ota_product_id,
            )
            if not products:
                return {
                    "status": "data_gap",
                    "reason": "ota_product_mapping_not_found",
                    "channel_source": channel,
                    "hotel_name": hotel_name,
                    "room_type_name": room_type_name,
                    "business_date": business_date,
                    "mapping_warnings": mapping_warnings,
                    "write_performed": False,
                }
            skipped: list[dict[str, Any]] = []
            eligible: list[dict[str, Any]] = []
            for product in products:
                reason = _product_skip_reason(channel, product)
                if reason:
                    skipped.append({"ota_product_id": product.get("ota_product_id") or product.get("source_product_id"), "reason": reason})
                    continue
                product_id = _product_id(product)
                if _pending_exists(conn, dialect, table=table, ota_product_id=product_id, business_date=business_date):
                    skipped.append({"ota_product_id": product_id, "reason": "duplicate_pending_task_skipped"})
                    continue
                eligible.append(product)

            # 按商品精确调价:同房型下多个商品价差可能巨大(挂牌 vs 团购 vs 钟点),
            # 单一 target_sale_price 不得灌给全部。指定 ota_product_id 时只写该商品;
            # 未指定且有多个候选商品时,拒绝并要求指定,避免团购价被挂牌价覆盖。
            if ota_product_id:
                target_pid = str(ota_product_id).strip()
                matched = [product for product in eligible if _product_id(product) == target_pid]
                if not matched:
                    return {
                        "status": "blocked",
                        "blocked_reason": "price_task_target_product_not_eligible",
                        "channel_source": channel,
                        "ota_product_id": target_pid,
                        "expanded_product_count": len(products),
                        "inserted_task_count": 0,
                        "skipped_product_count": len(skipped),
                        "skipped_products": skipped,
                        "eligible_products": [_product_candidate_summary(product, channel) for product in eligible],
                        "mapping_warnings": mapping_warnings,
                        "write_performed": False,
                        "live_api_called": False,
                    }
                eligible = matched
            elif len(eligible) > 1:
                return {
                    "status": "blocked",
                    "blocked_reason": "price_task_requires_ota_product_id",
                    "channel_source": channel,
                    "expanded_product_count": len(products),
                    "inserted_task_count": 0,
                    "skipped_product_count": len(skipped),
                    "skipped_products": skipped,
                    "eligible_products": [_product_candidate_summary(product, channel) for product in eligible],
                    "mapping_warnings": mapping_warnings,
                    "write_performed": False,
                    "live_api_called": False,
                }

            preview_rows = [
                {
                    "hotel_name": hotel_name,
                    "channel_source": channel,
                    "ota_product_id": _product_id(product),
                    "room_type_name": product.get("room_type_name") or product.get("pms_room_type_name") or room_type_name,
                    "business_date": business_date,
                    "target_sale_price": float(target_sale_price),
                    "execute_status": "PENDING",
                    "source_decision_id": source_decision_id,
                    "created_by": created_by,
                    "has_product_cipher": bool(product.get("product_cipher")),
                }
                for product in eligible
            ]
            if not eligible and skipped:
                return {
                    "status": "data_gap",
                    "blocked_reason": "price_task_mapping_not_ready",
                    "channel_source": channel,
                    "execute_status": "PENDING",
                    "expanded_product_count": len(products),
                    "inserted_task_count": 0,
                    "skipped_product_count": len(skipped),
                    "skipped_products": skipped,
                    "task_rows_preview": [],
                    "mapping_warnings": mapping_warnings,
                    "write_performed": False,
                    "live_api_called": False,
                }
            if not write_enabled:
                return {
                    "status": "dry_run",
                    "blocked_reason": "price_task_write_disabled",
                    "channel_source": channel,
                    "execute_status": "PENDING",
                    "expanded_product_count": len(products),
                    "inserted_task_count": 0,
                    "skipped_product_count": len(skipped),
                    "skipped_products": skipped,
                    "task_rows_preview": preview_rows,
                    "mapping_warnings": mapping_warnings,
                    "write_performed": False,
                    "live_api_called": False,
                }
            inserted = 0
            for product in eligible:
                _insert_task(
                    conn,
                    dialect=dialect,
                    channel_source=channel,
                    table=table,
                    hotel_name=hotel_name,
                    product=product,
                    room_type_name=room_type_name,
                    business_date=business_date,
                    target_sale_price=target_sale_price,
                    source_decision_id=source_decision_id,
                    created_by=created_by,
                    created_at=created_at,
                )
                inserted += 1
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    return {
        "status": "queued" if inserted else ("data_gap" if not eligible and not skipped else "ok"),
        "channel_source": channel,
        "execute_status": "PENDING",
        "hotel_name": hotel_name,
        "room_type_name": room_type_name,
        "business_date": business_date,
        "source_decision_id": source_decision_id,
        "expanded_product_count": len(products),
        "inserted_task_count": inserted,
        "skipped_product_count": len(skipped),
        "skipped_products": skipped,
        "write_performed": inserted > 0,
        "live_api_called": False,
        "task_db_kind": dialect,
        "mapping_warnings": mapping_warnings,
        "completion_scope": "outbox_write_only",
        "plugin_waited": False,
        "platform_readback_waited": False,
        "message": "price_tasks_written_waiting_for_plugin" if inserted else "no_new_pending_tasks_written",
    }


def read_price_task_status(
    db_path: str,
    *,
    channel_source: str,
    hotel_name: str | None = None,
    business_date: str | None = None,
    source_decision_id: str | None = None,
    db_kind: str | None = None,
    dsn: str | None = None,
) -> dict[str, Any]:
    channel = normalize_price_task_channel(channel_source)
    if channel not in SUPPORTED_CHANNELS:
        return {"status": "blocked", "blocked_reason": "unsupported_price_task_channel"}
    where = []
    params: list[Any] = []
    dialect = (db_kind or os.environ.get("HOTEL_OTA_PRICE_TASK_DB_KIND") or os.environ.get("HOTEL_OTA_DB_KIND") or "sqlite").lower()
    ph = _placeholder("mysql" if dialect == "mysql" else "sqlite")
    if hotel_name:
        where.append(f"hotel_name={ph}")
        params.append(hotel_name)
    if business_date:
        where.append(f"business_date={ph}")
        params.append(business_date)
    if source_decision_id:
        where.append(f"source_decision_id={ph}")
        params.append(source_decision_id)
    where_sql = " WHERE " + " AND ".join(where) if where else ""
    conn, dialect, blocked = _connect_task_db(db_path, db_kind=db_kind, dsn=dsn)
    if blocked:
        return {**blocked, "channel_source": channel}
    table = _task_table(channel, dialect=dialect)
    with closing(conn):
        rows = _fetchall(
            conn,
            dialect,
            f"""
            SELECT hotel_name, ota_product_id, room_type_name, business_date, target_sale_price,
                   execute_status, source_decision_id, created_by, error_message, created_at, executed_at
            FROM {table}{where_sql}
            ORDER BY created_at, ota_product_id
            """,
            params,
        )
    tasks = [dict(row) for row in rows]
    counts: dict[str, int] = {}
    lifecycle_counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("execute_status") or "")
        counts[status] = counts.get(status, 0) + 1
        lifecycle_status, lifecycle_transitions = _review_lifecycle_for_execute_status(status)
        task["review_lifecycle_status"] = lifecycle_status
        task["review_lifecycle_transitions"] = lifecycle_transitions
        lifecycle_counts[lifecycle_status] = lifecycle_counts.get(lifecycle_status, 0) + 1
    return {
        "status": "ok",
        "channel_source": channel,
        "business_date": business_date,
        "source_decision_id": source_decision_id,
        "task_db_kind": dialect,
        "status_counts": dict(sorted(counts.items())),
        "lifecycle_status_counts": dict(sorted(lifecycle_counts.items())),
        "tasks": tasks,
    }

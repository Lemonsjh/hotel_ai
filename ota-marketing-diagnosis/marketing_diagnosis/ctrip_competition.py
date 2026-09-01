from __future__ import annotations

import os
import re
from typing import Any

from marketing_diagnosis import db_loader as base
from marketing_diagnosis import db_loader_v16 as upstream


DEFAULT_MYSQL_TABLES = {
    **upstream.DEFAULT_MYSQL_TABLES,
    "ctrip_competition_metrics_30d": "ctrip_ota_competition_metrics_30d",
    "ctrip_order_loss_monthly": "ctrip_ota_order_loss_monthly",
    "ctrip_promotion_performance_30d": "ctrip_ota_promotion_performance_30d",
}

_ORDER_COLUMNS = (
    "snapshot_time",
    "updated_at",
    "created_at",
    "business_date",
    "data_date",
    "period_month",
    "stat_month",
    "id",
)

_CORE_METRICS = ("订单量", "销售额", "出租率", "转化率")

_FUNNEL_DEFINITIONS = (
    {
        "key": "list_exposure",
        "label": "列表页曝光量",
        "hotel_keys": (
            "exposure",
            "exposure_uv",
            "list_exposure",
            "list_exposure_uv",
            "list_page_exposure",
            "list_page_exposure_uv",
        ),
        "peer_keys": (
            "peer_exposure",
            "competitor_exposure",
            "competitor_avg_exposure",
            "peer_list_exposure",
        ),
        "aliases": (
            "列表页曝光",
            "列表曝光",
            "list_page_exposure",
            "list_exposure",
            "exposure_uv",
            "曝光人数",
            "曝光量",
        ),
    },
    {
        "key": "detail_visitors",
        "label": "详情页访客量",
        "hotel_keys": (
            "views",
            "view_uv",
            "browse_uv",
            "detail_visitors",
            "detail_visitor_uv",
            "detail_page_visitors",
            "detail_page_visitor_uv",
            "app_visitors",
            "app_visitor_uv",
        ),
        "peer_keys": (
            "peer_views",
            "competitor_views",
            "peer_detail_visitors",
            "competitor_detail_visitors",
            "competitor_avg_visitors",
        ),
        "aliases": (
            "详情页访客",
            "详情访客",
            "detail_page_visitor",
            "detail_visitor",
            "app访客",
            "app_visitor",
            "浏览人数",
            "browse_uv",
            "访客量",
            "访客",
        ),
    },
    {
        "key": "order_page_visitors",
        "label": "订单页访客量",
        "hotel_keys": (
            "order_page_visitors",
            "order_page_visitor_uv",
            "order_visitors",
            "order_visitor_uv",
        ),
        "peer_keys": (
            "peer_order_page_visitors",
            "competitor_order_page_visitors",
            "competitor_avg_order_page_visitors",
        ),
        "aliases": (
            "订单页访客",
            "订单页浏览",
            "order_page_visitor",
            "order_page_uv",
            "order_visitor",
        ),
    },
    {
        "key": "submitted_orders",
        "label": "订单提交人数",
        "hotel_keys": (
            "submitted_orders",
            "submitted_order_count",
            "order_submit_users",
            "order_submit_count",
            "submit_order_count",
        ),
        "peer_keys": (
            "peer_submitted_orders",
            "competitor_submitted_orders",
            "competitor_avg_submitted_orders",
        ),
        "aliases": (
            "订单提交人数",
            "提交订单人数",
            "提交订单",
            "订单提交",
            "submit_order",
            "submitted_order",
            "order_submit",
        ),
    },
    {
        "key": "completed_orders",
        "label": "成交订单数",
        "hotel_keys": (
            "paid_orders",
            "paid_order_count",
            "booking_order_count",
            "completed_orders",
            "completed_order_count",
        ),
        "peer_keys": (
            "peer_paid_orders",
            "competitor_paid_orders",
            "peer_booking_order_count",
            "competitor_avg",
            "competitor_avg_orders",
        ),
        "aliases": (
            "成交订单",
            "支付订单",
            "预订订单",
            "booking_order_count",
            "paid_order_count",
            "completed_order",
        ),
    },
)


def _diagnostics(dataset: dict[str, Any]) -> dict[str, Any] | None:
    records = dataset.get("__source_diagnostics__") or []
    return records[0] if records and isinstance(records[0], dict) else None


def _text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        number = float(match.group(0))
    except ValueError:
        return None
    return None if number != number else number


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _order_key(row: dict[str, Any], index: int) -> tuple[str, ...]:
    values = [str(row.get(column) or "") for column in _ORDER_COLUMNS[:-1]]
    try:
        row_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        row_id = 0
    values.extend((f"{row_id:020d}", f"{index:020d}"))
    return tuple(values)


def _latest_by_metric(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[tuple[str, str], tuple[tuple[str, ...], dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        key = (
            _text(row.get("metric_code")),
            _text(row.get("metric_name") or row.get("metric_label")),
        )
        if not any(key):
            key = ("row", str(index))
        order = _order_key(row, index)
        current = selected.get(key)
        if current is None or order >= current[0]:
            selected[key] = (order, dict(row))
    return [value[1] for value in selected.values()]


def _combined_metric_text(row: dict[str, Any]) -> str:
    return " ".join(
        _text(row.get(key)).lower()
        for key in ("metric_group", "metric_name", "metric_label", "metric_code")
        if _text(row.get(key))
    )


def _funnel_definition(row: dict[str, Any]) -> dict[str, Any] | None:
    combined = _combined_metric_text(row)
    if not combined or "流失" in combined or "转化" in combined:
        return None

    # More specific stages must be checked before generic visitor/order wording.
    for definition in (_FUNNEL_DEFINITIONS[2], _FUNNEL_DEFINITIONS[3], _FUNNEL_DEFINITIONS[4], _FUNNEL_DEFINITIONS[0]):
        if any(alias.lower() in combined for alias in definition["aliases"]):
            return definition
    definition = _FUNNEL_DEFINITIONS[1]
    if any(alias.lower() in combined for alias in definition["aliases"]):
        return definition
    return None


def _load_competition_metrics(
    cursor,
    table: str,
    limit: int,
    hotel_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    columns, schema_error = base._table_columns(cursor, table)
    if schema_error:
        return [], {"table": table, "rows": 0, "status": "error", "error": schema_error}
    if not ({"metric_code", "metric_name"} & columns):
        return [], {
            "table": table,
            "rows": 0,
            "status": "error",
            "error": "required column missing: metric_code or metric_name",
            "table_columns": sorted(columns),
        }
    order_candidates = tuple(
        [f"{name} DESC" for name in _ORDER_COLUMNS if name in columns]
        + [
            value
            for value in ("metric_code ASC", "metric_name ASC")
            if value.rsplit(" ", 1)[0] in columns
        ]
    )
    rows, diag = base._profiled_fetch(
        cursor,
        table,
        max(limit, 10000),
        hotel_id=hotel_id,
        order_candidates=order_candidates,
    )
    latest = _latest_by_metric(rows)
    return latest, {
        **diag,
        "rows_read": len(rows),
        "rows_used": len(latest),
        "selection_rule": "latest row per metric_code + metric_name",
    }


def _load_business_funnel_metrics(
    cursor,
    table: str,
    limit: int,
    hotel_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    columns, schema_error = base._table_columns(cursor, table)
    if schema_error:
        return [], {"table": table, "rows": 0, "status": "error", "error": schema_error}
    if not ({"metric_code", "metric_name"} & columns):
        return [], {
            "table": table,
            "rows": 0,
            "status": "error",
            "error": "required column missing: metric_code or metric_name",
            "table_columns": sorted(columns),
        }
    order_candidates = tuple(
        [f"{name} DESC" for name in _ORDER_COLUMNS if name in columns]
        + [
            value
            for value in ("stats_period_type DESC", "period_type DESC", "metric_name ASC")
            if value.rsplit(" ", 1)[0] in columns
        ]
    )
    rows, diag = base._profiled_fetch(
        cursor,
        table,
        max(limit, 20000),
        hotel_id=hotel_id,
        order_candidates=order_candidates,
    )
    filtered = [row for row in rows if _funnel_definition(row) is not None]
    latest = _latest_by_metric(filtered)
    return latest, {
        **diag,
        "rows_read": len(rows),
        "rows_used": len(latest),
        "row_filter": "recognized exposure/visitor/order funnel metric",
        "selection_rule": "latest row per metric_code + metric_name",
    }


def _load_yesterday_loss_metrics(
    cursor,
    table: str,
    hotel_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    columns, schema_error = base._table_columns(cursor, table)
    if schema_error:
        return [], {"table": table, "rows": 0, "status": "error", "error": schema_error}
    required = {"business_date", "metric_group", "metric_name"}
    missing = required - columns
    if missing:
        return [], {
            "table": table,
            "rows": 0,
            "status": "error",
            "error": "required columns missing: " + ", ".join(sorted(missing)),
            "table_columns": sorted(columns),
        }

    filters = [
        "DATE(`business_date`) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)",
        "`metric_group` = %s",
        "`metric_name` IN (%s, %s)",
    ]
    params: list[Any] = ["流失诊断", "流失订单量", "流失订单金额"]
    if hotel_id and "hotel_id" in columns:
        filters.insert(0, "`hotel_id` = %s")
        params.insert(0, hotel_id)
    sql = (
        f"SELECT * FROM {base._safe_identifier(table)} "
        f"WHERE {base._where(filters)} ORDER BY `business_date` DESC, `metric_name` ASC"
    )
    try:
        cursor.execute(sql, params)
        rows = [dict(row) for row in cursor.fetchall()]
        return rows, {
            "table": table,
            "rows": len(rows),
            "status": "ok" if rows else "empty",
            "where": "database yesterday + metric_group=流失诊断 + two loss metrics",
            "hotel_filter_applied": bool(hotel_id and "hotel_id" in columns),
        }
    except Exception as exc:
        return [], {
            "table": table,
            "rows": 0,
            "status": "error",
            "error": str(exc),
            "where": "database yesterday + loss metrics",
        }


def _load_order_loss(
    cursor,
    table: str,
    limit: int,
    hotel_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    columns, schema_error = base._table_columns(cursor, table)
    if schema_error:
        return [], {"table": table, "rows": 0, "status": "error", "error": schema_error}
    required = {"platform_scope", "competitor_hotel_name"}
    missing = required - columns
    if missing:
        return [], {
            "table": table,
            "rows": 0,
            "status": "error",
            "error": "required columns missing: " + ", ".join(sorted(missing)),
            "table_columns": sorted(columns),
        }
    order_candidates = tuple(
        [f"{name} DESC" for name in _ORDER_COLUMNS if name in columns]
        + [
            value
            for value in ("platform_scope ASC", "ranking_position ASC")
            if value.rsplit(" ", 1)[0] in columns
        ]
    )
    rows, diag = base._profiled_fetch(
        cursor,
        table,
        max(limit, 10000),
        hotel_id=hotel_id,
        order_candidates=order_candidates,
    )
    rows = [
        row
        for row in rows
        if _text(row.get("platform_scope")).lower() in {"ctrip", "qunar"}
    ]
    return rows, {
        **diag,
        "rows_used": len(rows),
        "row_filter": "platform_scope in (ctrip, qunar)",
    }


def _load_page_entry(
    cursor,
    table: str,
    limit: int,
    hotel_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    columns, schema_error = base._table_columns(cursor, table)
    if schema_error:
        return [], {"table": table, "rows": 0, "status": "error", "error": schema_error}
    if "hotel_name" not in columns:
        return [], {
            "table": table,
            "rows": 0,
            "status": "error",
            "error": "required column missing: hotel_name",
            "table_columns": sorted(columns),
        }
    rows, diag = base._profiled_fetch(
        cursor,
        table,
        limit,
        hotel_id=hotel_id,
        order_candidates=("snapshot_time DESC", "period_end_date DESC"),
    )
    latest = base._latest_snapshot(rows)
    return latest, {
        **diag,
        "rows_read": len(rows),
        "rows_used": len(latest),
        "selection_rule": "latest snapshot; only hotel_name is currently used by item 10",
    }


def load_mysql_dsn_dataset(
    dsn: str,
    limit: int = 5000,
    tables: dict[str, str] | None = None,
    hotel_id: str | None = "puyue",
    ctrip_hotel_id: str | None = None,
    platform: str | None = "multi",
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    table_map = {**DEFAULT_MYSQL_TABLES, **(tables or {})}
    dataset = upstream.load_mysql_dsn_dataset(
        dsn,
        limit=limit,
        tables=table_map,
        hotel_id=hotel_id,
        ctrip_hotel_id=ctrip_hotel_id,
        platform=platform,
        period_start=period_start,
        period_end=period_end,
    )

    if "ctrip" not in base._enabled_platforms(platform):
        dataset.setdefault("ctrip_competition_metrics_30d", [])
        dataset.setdefault("ctrip_business_metrics_funnel", [])
        dataset.setdefault("ctrip_business_metrics_loss", [])
        dataset.setdefault("ctrip_order_loss_monthly", [])
        dataset.setdefault("ctrip_promotion_performance_30d", [])
        return dataset

    ctrip_id = ctrip_hotel_id or hotel_id
    with base._connect_mysql(dsn) as conn:
        with conn.cursor() as cursor:
            competition, competition_diag = _load_competition_metrics(
                cursor,
                table_map["ctrip_competition_metrics_30d"],
                limit,
                ctrip_id,
            )
            funnel_metrics, funnel_metrics_diag = _load_business_funnel_metrics(
                cursor,
                table_map["ctrip_funnel"],
                limit,
                ctrip_id,
            )
            loss_metrics, loss_metrics_diag = _load_yesterday_loss_metrics(
                cursor,
                table_map["ctrip_funnel"],
                ctrip_id,
            )
            loss_competitors, loss_competitors_diag = _load_order_loss(
                cursor,
                table_map["ctrip_order_loss_monthly"],
                limit,
                ctrip_id,
            )
            page_entry, page_entry_diag = _load_page_entry(
                cursor,
                table_map["ctrip_promotion_performance_30d"],
                limit,
                ctrip_id,
            )

    dataset["ctrip_competition_metrics_30d"] = base._tag_rows(
        competition,
        table_map["ctrip_competition_metrics_30d"],
    )
    dataset["ctrip_business_metrics_funnel"] = base._tag_rows(
        funnel_metrics,
        table_map["ctrip_funnel"],
    )
    dataset["ctrip_business_metrics_loss"] = base._tag_rows(
        loss_metrics,
        table_map["ctrip_funnel"],
    )
    dataset["ctrip_order_loss_monthly"] = base._tag_rows(
        loss_competitors,
        table_map["ctrip_order_loss_monthly"],
    )
    dataset["ctrip_promotion_performance_30d"] = base._tag_rows(
        page_entry,
        table_map["ctrip_promotion_performance_30d"],
    )

    diagnostics = _diagnostics(dataset)
    if diagnostics is not None:
        diagnostics.setdefault("tables", {}).update(
            {
                "ctrip_competition_metrics_30d": competition_diag,
                "ctrip_business_metrics_funnel": funnel_metrics_diag,
                "ctrip_business_metrics_loss": loss_metrics_diag,
                "ctrip_order_loss_monthly": loss_competitors_diag,
                "ctrip_promotion_performance_30d": page_entry_diag,
            }
        )
        diagnostics.setdefault("transformations", []).extend(
            [
                {
                    "section": "ctrip_competition_metrics_30d",
                    "rows": len(competition),
                    "rule": "latest row per metric_code + metric_name",
                },
                {
                    "section": "ctrip_business_metrics_funnel",
                    "rows": len(funnel_metrics),
                    "rule": "latest recognized funnel metric from ctrip_ota_business_metrics",
                },
                {
                    "section": "ctrip_business_metrics_loss",
                    "rows": len(loss_metrics),
                    "rule": "database yesterday; metric_group=流失诊断",
                },
                {
                    "section": "ctrip_order_loss_monthly",
                    "rows": len(loss_competitors),
                    "rule": "ctrip/qunar rows retained; renderer selects latest Top5",
                },
                {
                    "section": "ctrip_promotion_performance_30d",
                    "rows": len(page_entry),
                    "rule": "latest snapshot; item 10 currently uses hotel_name only",
                },
            ]
        )
    return dataset


def load_database_dataset(config_path):
    config = base._load_json(config_path)
    kind = str(config.get("kind") or config.get("type") or "sqlite").lower()
    if kind not in {"mysql", "mysql+pymysql"}:
        return upstream.load_database_dataset(config_path)
    dsn = config.get("dsn") or os.environ.get(str(config.get("dsn_env") or ""))
    if not dsn:
        raise ValueError("MySQL config requires dsn or dsn_env")
    return load_mysql_dsn_dataset(
        dsn,
        limit=int(config.get("limit") or 5000),
        tables=config.get("tables") or {},
        hotel_id=config.get("hotel_id") or "puyue",
        ctrip_hotel_id=config.get("ctrip_hotel_id"),
        platform=config.get("platform") or "multi",
        period_start=config.get("period_start"),
        period_end=config.get("period_end"),
    )


def _metric_label(row: dict[str, Any]) -> str | None:
    name = _text(row.get("metric_name") or row.get("metric_label"))
    code = _text(row.get("metric_code"))
    name_lower = name.lower()
    code_lower = code.lower()

    # The source can reuse booking_order_count for several rows. Chinese metric
    # name therefore has priority over metric_code.
    if "销售" in name or "金额" in name:
        return "销售额"
    if "出租率" in name or "入住率" in name:
        return "出租率"
    if "转化" in name:
        return "转化率"
    if "订单" in name and "流失" not in name:
        return "订单量"

    if any(key in code_lower for key in ("sales_amount", "sale_amount", "sales_revenue", "revenue", "gmv")):
        return "销售额"
    if "occupancy" in code_lower:
        return "出租率"
    if "conversion" in code_lower:
        return "转化率"
    if "booking_order" in code_lower or "paid_order" in code_lower:
        return "订单量"
    if name_lower in {"order", "orders"}:
        return "订单量"
    return None


def _metric_unit(row: dict[str, Any], label: str) -> str:
    # Display unit follows the business meaning, not raw English unit codes.
    if label == "销售额":
        return "元"
    if label == "订单量":
        return "单"
    if label in {"出租率", "转化率"}:
        return "%"

    explicit = _text(row.get("metric_unit") or row.get("unit")).lower()
    aliases = {
        "cny": "元",
        "rmb": "元",
        "yuan": "元",
        "order": "单",
        "orders": "单",
        "room_night": "间夜",
        "room_nights": "间夜",
        "person": "人",
        "people": "人",
        "percent": "%",
        "percentage": "%",
        "pct": "%",
    }
    return aliases.get(explicit, _text(row.get("metric_unit") or row.get("unit")))


def _rank_and_count(row: dict[str, Any]) -> tuple[float | None, float | None]:
    raw_rank = _first(row, "competitor_rank", "ranking_position", "rank_position", "rank")
    rank = _number(raw_rank)
    count = _number(_first(row, "competitor_count", "circle_hotel_count", "peer_hotel_count"))
    text = _text(raw_rank)
    if count is None and "/" in text:
        count = _number(text.split("/", 1)[1])
    return rank, count


def _competition_entries(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {label: index for index, label in enumerate(_CORE_METRICS)}
    selected: dict[str, tuple[int, dict[str, Any]]] = {}
    for row in rows:
        label = _metric_label(row)
        if label not in priority:
            continue
        rank, count = _rank_and_count(row)
        entry = {
            "label": label,
            "metric_code": _text(row.get("metric_code")),
            "hotel_value": _number(
                _first(row, "metric_value", "hotel_value", "hotel_metric_value", "current_value", "my_value")
            ),
            "competitor_avg": _number(
                _first(row, "competitor_avg", "competitor_average", "peer_average", "avg_value")
            ),
            "competitor_rank": rank,
            "competitor_count": count,
            "unit": _metric_unit(row, label),
        }
        completeness = sum(
            entry.get(key) is not None
            for key in ("hotel_value", "competitor_avg", "competitor_rank")
        )
        current = selected.get(label)
        if current is None or completeness > current[0]:
            selected[label] = (completeness, entry)
    output = [value[1] for value in selected.values()]
    output.sort(key=lambda entry: priority[str(entry.get("label"))])
    return output


def _latest_funnel(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    ctrip_rows = [
        row
        for row in rows
        if _text(row.get("platform")).lower() in {"ctrip", "携程"}
    ]
    if not ctrip_rows:
        return None
    ctrip_rows.sort(
        key=lambda row: (
            _text(row.get("business_date")),
            "30" in _text(row.get("period_type")),
        ),
        reverse=True,
    )
    return dict(ctrip_rows[0])


def _funnel_from_wide_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    row = _latest_funnel(rows)
    if not row:
        return {}
    output: dict[str, dict[str, Any]] = {}
    for definition in _FUNNEL_DEFINITIONS:
        hotel_value = _number(_first(row, *definition["hotel_keys"]))
        competitor_avg = _number(_first(row, *definition["peer_keys"]))
        if hotel_value is not None or competitor_avg is not None:
            output[str(definition["key"])] = {
                "label": definition["label"],
                "hotel_value": hotel_value,
                "competitor_avg": competitor_avg,
            }
    return output


def _funnel_from_metric_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        definition = _funnel_definition(row)
        if definition is None:
            continue
        key = str(definition["key"])
        candidate = {
            "label": definition["label"],
            "hotel_value": _number(
                _first(row, "metric_value", "hotel_value", "hotel_metric_value", "current_value", "my_value")
            ),
            "competitor_avg": _number(
                _first(row, "competitor_avg", "competitor_average", "peer_average", "avg_value")
            ),
        }
        current = output.get(key)
        if current is None:
            output[key] = candidate
            continue
        for value_key in ("hotel_value", "competitor_avg"):
            if current.get(value_key) is None and candidate.get(value_key) is not None:
                current[value_key] = candidate[value_key]
    return output


def _merge_funnel_source(
    merged: dict[str, dict[str, Any]],
    source: dict[str, dict[str, Any]],
) -> None:
    for key, candidate in source.items():
        current = merged.setdefault(
            key,
            {
                "label": candidate.get("label"),
                "hotel_value": None,
                "competitor_avg": None,
            },
        )
        for value_key in ("hotel_value", "competitor_avg"):
            if current.get(value_key) is None and candidate.get(value_key) is not None:
                current[value_key] = candidate[value_key]


def _funnel_stages(
    ota_rows: list[dict[str, Any]],
    business_rows: list[dict[str, Any]],
    competition_rows: list[dict[str, Any]],
    existing: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    existing_stages = (existing or {}).get("funnel_stages")
    if isinstance(existing_stages, list):
        for stage in existing_stages:
            if not isinstance(stage, dict):
                continue
            label = _text(stage.get("label"))
            definition = next(
                (item for item in _FUNNEL_DEFINITIONS if item["label"] == label),
                None,
            )
            if definition is not None:
                merged[str(definition["key"])] = dict(stage)

    _merge_funnel_source(merged, _funnel_from_wide_rows(ota_rows))
    _merge_funnel_source(merged, _funnel_from_metric_rows(business_rows))
    _merge_funnel_source(merged, _funnel_from_metric_rows(competition_rows))

    if not any(
        entry.get("hotel_value") is not None or entry.get("competitor_avg") is not None
        for entry in merged.values()
    ):
        return []

    # Once at least one real funnel metric exists, retain the fixed five-stage
    # structure. Missing individual stages stay visibly marked as 待接入.
    return [
        {
            "label": definition["label"],
            "hotel_value": (merged.get(str(definition["key"])) or {}).get("hotel_value"),
            "competitor_avg": (merged.get(str(definition["key"])) or {}).get("competitor_avg"),
        }
        for definition in _FUNNEL_DEFINITIONS
    ]


def _loss_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "order_count": None,
        "order_amount": None,
        "business_date": None,
    }
    for row in rows:
        name = _text(row.get("metric_name"))
        value = _number(_first(row, "metric_value", "value", "current_value"))
        if name == "流失订单量":
            result["order_count"] = value
        elif name == "流失订单金额":
            result["order_amount"] = value
        day = _text(row.get("business_date"))[:10]
        if day:
            result["business_date"] = max(_text(result.get("business_date")), day)
    return result


def _platform(value: Any) -> str:
    text = _text(value).lower()
    aliases = {"携程": "ctrip", "去哪儿": "qunar", "去哪兒": "qunar"}
    return aliases.get(_text(value), text)


def _period_key(row: dict[str, Any]) -> str:
    return _text(
        _first(
            row,
            "period_month",
            "business_month",
            "stat_month",
            "data_month",
            "business_date",
            "snapshot_time",
            "updated_at",
            "created_at",
        )
    )[:19]


def _loss_competitors(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {"ctrip": [], "qunar": []}
    for platform in output:
        platform_rows = [
            row
            for row in rows
            if _platform(row.get("platform_scope")) == platform
        ]
        if not platform_rows:
            continue
        periods = [_period_key(row) for row in platform_rows if _period_key(row)]
        latest = max(periods) if periods else ""
        if latest:
            platform_rows = [
                row for row in platform_rows if _period_key(row) == latest
            ]
        normalized: list[dict[str, Any]] = []
        for row in platform_rows:
            name = _text(row.get("competitor_hotel_name"))
            if not name:
                continue
            rank = _number(
                _first(
                    row,
                    "ranking_position",
                    "rank_position",
                    "competitor_rank",
                    "rank",
                )
            )
            normalized.append(
                {
                    "ranking_position": rank,
                    "competitor_hotel_name": name,
                    "loss_order_count": _number(
                        _first(row, "loss_order_count", "order_count", "lost_order_count")
                    ),
                    "loss_order_amount": _number(
                        _first(row, "loss_order_amount", "loss_amount", "order_amount")
                    ),
                    "period": latest,
                }
            )
        normalized.sort(
            key=lambda row: (
                row.get("ranking_position")
                if row.get("ranking_position") is not None
                else 999999,
                row.get("competitor_hotel_name"),
            )
        )
        output[platform] = normalized[:5]
    return output


def build_competition_item(
    sections: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    competition_rows = [
        dict(row)
        for row in sections.get("ctrip_competition_metrics_30d") or []
        if isinstance(row, dict)
    ]
    business_funnel_rows = [
        dict(row)
        for row in sections.get("ctrip_business_metrics_funnel") or []
        if isinstance(row, dict)
    ]
    loss_rows = [
        dict(row)
        for row in sections.get("ctrip_business_metrics_loss") or []
        if isinstance(row, dict)
    ]
    competitor_rows = [
        dict(row)
        for row in sections.get("ctrip_order_loss_monthly") or []
        if isinstance(row, dict)
    ]
    ota_funnel_rows = [
        dict(row)
        for row in sections.get("ota_funnel") or []
        if isinstance(row, dict)
    ]

    competition_metrics = _competition_entries(competition_rows)
    loss_summary = _loss_summary(loss_rows)
    loss_competitors = _loss_competitors(competitor_rows)
    funnel_stages = _funnel_stages(
        ota_funnel_rows,
        business_funnel_rows,
        competition_rows,
        existing,
    )
    has_data = bool(
        competition_metrics
        or funnel_stages
        or loss_summary.get("order_count") is not None
        or loss_summary.get("order_amount") is not None
        or loss_competitors["ctrip"]
        or loss_competitors["qunar"]
    )

    fields = [
        {
            "label": entry.get("label"),
            "value": entry.get("competitor_avg"),
            "note": "竞争圈平均 / 排名",
        }
        for entry in competition_metrics
    ]
    item = {
        "standard_item_id": 3,
        "item_name": "平台流量漏斗分析",
        "participates_in_score": True,
        "full_score": 15,
        "data_status": "success" if has_data else "missing",
        "source": (
            "ctrip_ota_competition_metrics_30d、"
            "ctrip_ota_business_metrics、ctrip_ota_order_loss_monthly"
        ),
        "source_path": "携程 eBooking -> 数据中心 -> 竞争圈动态",
        "fields": fields,
        "fields_complete": True,
        "funnel_stages": funnel_stages,
        "competition_metrics": competition_metrics,
        "loss_summary": loss_summary,
        "loss_competitors": loss_competitors,
        "records": (
            competition_rows
            + business_funnel_rows
            + loss_rows
            + competitor_rows
        ),
    }
    for key in ("item_score", "diagnosis_score", "score", "current_score"):
        if isinstance(existing, dict) and existing.get(key) not in (None, ""):
            item[key] = existing[key]
            break
    return item


__all__ = [
    "DEFAULT_MYSQL_TABLES",
    "build_competition_item",
    "load_database_dataset",
    "load_mysql_dsn_dataset",
]

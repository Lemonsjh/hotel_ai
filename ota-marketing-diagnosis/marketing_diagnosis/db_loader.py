from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from marketing_diagnosis.data import SECTIONS


DEFAULT_MYSQL_TABLES = {
    "jy01": "jy01_hotel_statistics_daily",
    "jy03": "jy03_hotel_statistics_month",
    "jl02": "jl02_hotel_performance_daily",
    "jl01": "jl01_room_type_performance_daily",
    "rs01": "rs01_room_revenue_daily",
    "meituan_funnel": "meituan_ota_business_metrics",
    "ctrip_funnel": "ctrip_ota_business_metrics",
    "meituan_products": "meituan_ota_goods_price_mapping",
    "ctrip_products": "ctrip_ota_goods_price_mapping",
    "meituan_promotions": "meituan_ota_promotion_activity",
    "ctrip_promotions": "ctrip_ota_promotion_activity",
    "meituan_promotion_products": "meituan_ota_activity_product_detail",
    "ctrip_promotion_products": "ctrip_ota_activity_product_detail",
    "meituan_reviews": "meituan_ota_review_detail",
    "ctrip_reviews": "ctrip_ota_review_detail",
    "meituan_review_overview": "meituan_ota_review_overview",
    "ctrip_review_overview": "ctrip_ota_review_overview",
    "meituan_review_ranking": "meituan_ota_review_ranking",
    "ctrip_review_ranking": "ctrip_ota_review_ranking",
    "meituan_nearby_events": "meituan_ota_nearby_event",
    "meituan_exposure_monthly": "meituan_ota_exposure_source_monthly",
    "meituan_user_source_monthly": "meituan_ota_user_source_monthly",
    "meituan_promotion_finance": "meituan_ota_promotion_finance_detail",
    "meituan_order_loss_monthly": "meituan_ota_order_loss_monthly",
    "meituan_joined_rights": "meituan_ota_joined_rights",
    "meituan_promotion_status": "meituan_ota_promotion_status",
    "meituan_video_upload_status": "meituan_ota_video_upload_status",
}


def _safe_identifier(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError(f"unsafe identifier: {value}")
    return f"`{value}`"


def _load_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _sqlite_dataset(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    db_path = config.get("path")
    if not db_path:
        raise ValueError("SQLite config requires path")
    tables = config.get("tables") or {}
    limit = int(config.get("limit") or 5000)
    dataset: dict[str, list[dict[str, Any]]] = {section: [] for section in SECTIONS}
    source_diagnostics = {"kind": "sqlite", "path": str(db_path), "tables": {}}
    with closing(sqlite3.connect(str(db_path))) as conn:
        conn.row_factory = sqlite3.Row
        for section in SECTIONS:
            table = tables.get(section)
            if not table:
                continue
            rows = conn.execute(f"SELECT * FROM {_safe_identifier(str(table))} LIMIT ?", (limit,)).fetchall()
            dataset[section] = [dict(row) for row in rows]
            source_diagnostics["tables"][section] = {"table": table, "rows": len(rows), "status": "ok" if rows else "empty"}
    dataset["__source_diagnostics__"] = [source_diagnostics]
    return dataset


def _mysql_params(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": (parsed.path or "/").lstrip("/"),
        "charset": query.get("charset", ["utf8mb4"])[0],
    }


def _masked_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    user = unquote(parsed.username or "")
    host = parsed.hostname or "localhost"
    port = parsed.port or 3306
    database = (parsed.path or "/").lstrip("/")
    return f"mysql+pymysql://{user}:***@{host}:{port}/{database}"


def _connect_mysql(dsn: str):
    try:
        import pymysql
    except ImportError as exc:
        raise RuntimeError("MySQL support requires pymysql") from exc
    params = _mysql_params(str(dsn))
    return pymysql.connect(
        host=params["host"], port=params["port"], user=params["user"], password=params["password"],
        database=params["database"], charset=params["charset"], cursorclass=pymysql.cursors.DictCursor,
        autocommit=True, connect_timeout=10, read_timeout=20, write_timeout=20,
    )


def _fetch(cursor, table: str, limit: int, where: str | None = None, params: list[Any] | None = None, order_by: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sql = f"SELECT * FROM {_safe_identifier(table)}"
    if where:
        sql += f" WHERE {where}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    sql += " LIMIT %s"
    final_params = list(params or []) + [limit]
    try:
        cursor.execute(sql, final_params)
        rows = [dict(row) for row in cursor.fetchall()]
        fields = sorted({key for row in rows[:20] for key in row.keys()})
        return rows, {"table": table, "where": where, "rows": len(rows), "fields_sample": fields, "status": "ok" if rows else "empty"}
    except Exception as exc:
        return [], {"table": table, "where": where, "rows": 0, "fields_sample": [], "status": "error", "error": str(exc)}


def _table_columns(cursor, table: str) -> tuple[set[str], str | None]:
    """Return the live table columns so optional filters never break a query."""
    try:
        cursor.execute(f"SHOW COLUMNS FROM {_safe_identifier(table)}")
        return {str(row.get("Field") or "") for row in cursor.fetchall()}, None
    except Exception as exc:
        return set(), str(exc)


def _profiled_fetch(
    cursor,
    table: str,
    limit: int,
    *,
    hotel_id: str | None = None,
    date_column: str | None = None,
    period_start: str | None = None,
    period_end: str | None = None,
    order_candidates: tuple[str, ...] = (),
    extra_filters: list[tuple[str, str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Query against actual columns while preserving every applied filter in diagnostics.

    The ``hotel_puyue`` schema is already hotel-scoped.  If a table has no
    ``hotel_id`` column we therefore do not invent a filter that would make the
    query fail.  Date/order clauses follow the same rule.
    """
    columns, schema_error = _table_columns(cursor, table)
    if schema_error:
        return [], {
            "table": table, "rows": 0, "status": "error", "fields_sample": [],
            "error": schema_error, "stage": "SHOW COLUMNS",
        }
    params: list[Any] = []
    filters: list[str] = []
    if hotel_id and "hotel_id" in columns:
        filters.append("hotel_id = %s")
        params.append(hotel_id)
    if date_column and date_column in columns:
        date_filter = _date_range(date_column, period_start, period_end, params)
        if date_filter:
            filters.append(date_filter)
    for column, operator, value in extra_filters or []:
        if column not in columns or value is None:
            continue
        filters.append(f"{_safe_identifier(column)} {operator} %s")
        params.append(value)
    order_by = ", ".join(f"{_safe_identifier(column)} {direction}" for column, direction in (
        (candidate.rsplit(" ", 1)[0], candidate.rsplit(" ", 1)[1].upper())
        for candidate in order_candidates if candidate.rsplit(" ", 1)[0] in columns
    ) if direction in {"ASC", "DESC"}) or None
    rows, diag = _fetch(cursor, table, limit, _where(filters), params, order_by)
    return rows, {**diag, "table_columns": sorted(columns), "hotel_filter_applied": "hotel_id" in columns}


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "").rstrip("%")
    if not text or text.lower() == "nan":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _ratio(value: Any) -> float | None:
    number = _float(value)
    if number is None:
        return None
    return number / 100 if number > 1 else number


def _rank(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    return _float(text.split("/")[0])


def _where(parts: list[str]) -> str | None:
    clean = [part for part in parts if part]
    return " AND ".join(clean) if clean else None


def _date_range(column: str, start: str | None, end: str | None, params: list[Any]) -> str | None:
    parts = []
    if start:
        parts.append(f"LEFT({column}, 10) >= %s")
        params.append(start)
    if end:
        parts.append(f"LEFT({column}, 10) <= %s")
        params.append(end)
    return " AND ".join(parts) if parts else None


def _hotel_filter(hotel_id: str | None, params: list[Any]) -> str | None:
    if not hotel_id:
        return None
    params.append(hotel_id)
    return "hotel_id = %s"


def _latest_snapshot(rows: list[dict[str, Any]], key: str = "snapshot_time") -> list[dict[str, Any]]:
    if not rows:
        return rows
    best = max(str(row.get(key) or "")[:19] for row in rows)
    return [row for row in rows if str(row.get(key) or "")[:19] == best] if best else rows


def _pivot_funnel(rows: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    metric_map = {
        "曝光量": "exposure", "曝光人数": "exposure",
        "浏览人数": "views", "浏览量": "views",
        "支付订单数": "paid_orders", "订单数": "paid_orders",
        "销售间夜": "sold_room_nights", "销售均价": "sale_adr", "销售额": "sales_revenue", "入住间夜": "checkin_room_nights",
        "满房率": "full_occupancy_rate", "引流价": "entry_price", "评价分": "rating_score", "信息分": "content_score", "HOS分": "hos_score",
        "支付转化率": "payment_conversion_rate", "浏览-支付转化率": "payment_conversion_rate", "曝光-浏览转化率": "exposure_to_view_rate",
    }
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        period = str(row.get("stats_period_type") or row.get("period_type") or "")
        day = str(row.get("business_date") or row.get("snapshot_time") or "")[:10]
        item = grouped.setdefault((platform, period, day), {"platform": platform, "business_date": day, "period_type": period, "source_table": row.get("__source_table")})
        metric = str(row.get("metric_name") or "").strip()
        target = metric_map.get(metric)
        if not target:
            continue
        if target in {"payment_conversion_rate", "exposure_to_view_rate", "full_occupancy_rate"}:
            item[target] = _ratio(row.get("metric_value"))
            peer = _ratio(row.get("peer_average"))
            if peer is not None:
                item[f"peer_{target}"] = peer
                if target == "payment_conversion_rate":
                    item["peer_avg_conversion_rate"] = peer
        else:
            item[target] = _float(row.get("metric_value"))
            peer = _float(row.get("peer_average"))
            if peer is not None:
                item[f"peer_{target}"] = peer
        rank = _rank(row.get("competitor_rank"))
        if rank is not None:
            item[f"{target}_rank"] = rank
            item.setdefault("peer_rank", rank)
        if row.get("metric_code") not in (None, ""):
            item[f"{target}_metric_code"] = row.get("metric_code")
    return list(grouped.values())


def _rs01_daily(cursor, table: str, hotel_id: str | None = None, period_start: str | None = None, period_end: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params: list[Any] = []
    filters = ["charge_subject='房费'"]
    hotel = _hotel_filter(hotel_id, params)
    if hotel:
        filters.append(hotel)
    date = _date_range("business_date", period_start, period_end, params)
    if date:
        filters.append(date)
    where = _where(filters)
    sql = (
        f"SELECT DATE(business_date) AS business_date, SUM(room_nights) AS room_nights, "
        f"SUM(room_fee) AS room_revenue, 'rs01_room_revenue_daily' AS source_table "
        f"FROM {_safe_identifier(table)} WHERE {where} GROUP BY DATE(business_date) ORDER BY DATE(business_date) ASC"
    )
    try:
        cursor.execute(sql, params)
        rows = [dict(row) for row in cursor.fetchall()]
        return rows, {"table": table, "where": where, "rows": len(rows), "aggregation": "sum(room_nights), sum(room_fee) by business_date", "status": "ok" if rows else "empty"}
    except Exception as exc:
        return [], {"table": table, "where": where, "rows": 0, "aggregation": "sum by business_date", "status": "error", "error": str(exc)}


def _products(rows: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        is_group = str(row.get("is_super_deal") or "").lower() in {"1", "true", "yes"}
        out.append({
            "platform": platform,
            "source_table": row.get("__source_table"),
            "business_date": str(row.get("business_date") or row.get("snapshot_time") or "")[:10],
            "room_type_name": row.get("room_type_name") or row.get("source_room_type_name"),
            "room_type_id": row.get("room_type_id"),
            "ota_room_type_id": row.get("ota_room_type_id"),
            "ota_product_id": row.get("ota_product_id"),
            "product_name": row.get("ota_product_name") or row.get("source_product_name"),
            "product_type": "group_buy" if is_group else row.get("rate_plan_name"),
            "listed_price": row.get("ota_sale_price") or row.get("current_sale_price"),
            "final_price": row.get("ota_sale_price") or row.get("current_sale_price"),
            "commission_rate": row.get("commission_rate"),
            "is_group_buy": is_group,
            "is_hour_room": row.get("is_hour_room"),
        })
    return out


def _reviews(rows: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    return [{
        "platform": platform,
        "source_table": row.get("__source_table"),
        "review_date": str(row.get("review_time") or row.get("stay_date") or "")[:10],
        "stay_date": str(row.get("stay_date") or "")[:10],
        "rating": row.get("review_score"),
        "review_text": row.get("review_content"),
        "is_negative": row.get("is_negative_review"),
        "is_replied": row.get("is_replied"),
        "merchant_reply_time": row.get("merchant_reply_time"),
        "room_type_name": row.get("room_type_name"),
        "hygiene_score": row.get("hygiene_score"),
        "facility_score": row.get("facility_score"),
        "location_score": row.get("location_score"),
        "service_score": row.get("service_score"),
    } for row in rows]


def _copy_rows(rows: list[dict[str, Any]], platform: str, table: str) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        item = dict(row)
        item["platform"] = platform
        item["source_table"] = table
        out.append(item)
    return out


def _tag_rows(rows: list[dict[str, Any]], table: str) -> list[dict[str, Any]]:
    for row in rows:
        row["__source_table"] = table
    return rows


def _enabled_platforms(platform: str | None) -> list[str]:
    value = str(platform or "multi").lower()
    if value in {"meituan", "美团"}:
        return ["meituan"]
    if value in {"ctrip", "携程"}:
        return ["ctrip"]
    return ["meituan", "ctrip"]


def _base_filters(hotel_id: str | None, params: list[Any], date_column: str | None = None, period_start: str | None = None, period_end: str | None = None) -> list[str]:
    filters: list[str] = []
    hotel = _hotel_filter(hotel_id, params)
    if hotel:
        filters.append(hotel)
    if date_column:
        date = _date_range(date_column, period_start, period_end, params)
        if date:
            filters.append(date)
    return filters


def load_mysql_dsn_dataset(
    dsn: str,
    limit: int = 5000,
    tables: dict[str, str] | None = None,
    hotel_id: str | None = "puyue",
    platform: str | None = "multi",
    period_start: str | None = None,
    period_end: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    table_map = {**DEFAULT_MYSQL_TABLES, **(tables or {})}
    dataset: dict[str, list[dict[str, Any]]] = {section: [] for section in SECTIONS}
    enabled = _enabled_platforms(platform)
    diagnostics: dict[str, Any] = {"kind": "mysql", "dsn": _masked_dsn(dsn), "profile": "puyue_mysql_export_20260703", "hotel_id": hotel_id, "platform": platform, "period_start": period_start, "period_end": period_end, "tables": {}, "transformations": []}
    with _connect_mysql(dsn) as conn:
        with conn.cursor() as cursor:
            params: list[Any] = []
            filters = ["dimension_type='总营业指标'", "dimension_name='总营业指标'"] + _base_filters(hotel_id, params, "business_date", period_start, period_end)
            jy01, diag = _fetch(cursor, table_map["jy01"], limit, _where(filters), params, "business_date ASC")
            diagnostics["tables"]["jy01"] = diag
            if jy01:
                dataset["hotel_daily"].extend(_tag_rows(jy01, table_map["jy01"]))
            else:
                rs01_rows, rs01_diag = _rs01_daily(cursor, table_map["rs01"], hotel_id, period_start, period_end)
                diagnostics["tables"]["rs01_fallback"] = rs01_diag
                dataset["hotel_daily"].extend(rs01_rows)
            diagnostics["transformations"].append({"section": "hotel_daily", "rows": len(dataset["hotel_daily"]), "rule": "PMS total operating rows filtered by hotel_id and requested date range"})

            params = []
            filters = ["dimension_type='总营业指标'", "dimension_name='总营业指标'"] + _base_filters(hotel_id, params)
            rows, diag = _fetch(cursor, table_map["jy03"], 36, _where(filters), params, "period_month ASC")
            diagnostics["tables"]["jy03"] = diag
            dataset["hotel_monthly"].extend(_tag_rows(rows, table_map["jy03"]))
            diagnostics["transformations"].append({"section": "hotel_monthly", "rows": len(dataset["hotel_monthly"]), "rule": "monthly PMS trend from jy03_hotel_statistics_month"})

            # 经营诊断专用宽口径表：metric_name 对应本日/本月/本年三列。
            # jl02 保留历史快照以计算去年同期；jl01 只使用最新快照展示全部房型。
            rows, diag = _profiled_fetch(
                cursor, table_map["jl02"], max(limit, 50000), hotel_id=hotel_id,
                order_candidates=("snapshot_time DESC", "metric_name ASC"),
            )
            diagnostics["tables"]["jl02"] = diag
            dataset["hotel_performance_daily"].extend(_tag_rows(rows, table_map["jl02"]))

            rows, diag = _profiled_fetch(
                cursor, table_map["jl01"], limit, hotel_id=hotel_id,
                order_candidates=("snapshot_time DESC", "room_type_id ASC", "metric_name ASC"),
            )
            latest = _latest_snapshot(rows)
            diagnostics["tables"]["jl01"] = {**diag, "rows_used": len(latest)}
            dataset["room_type_performance_daily"].extend(_tag_rows(latest, table_map["jl01"]))

            # 美团推广 ROI 的订单金额口径：本月、渠道、美团 EBK。
            params = []
            filters = ["dimension_type='渠道'", "dimension_name='美团EBK'"] + _base_filters(hotel_id, params)
            rows, diag = _fetch(cursor, table_map["jy03"], 24, _where(filters), params, "period_month DESC")
            diagnostics["tables"]["jy03_meituan_revenue"] = diag
            dataset["promotion_revenue"].extend(_tag_rows(rows, table_map["jy03"]))

            for plat in enabled:
                # OTA business metrics: actual export is metric_name rows by period_type/date.
                rows, diag = _profiled_fetch(
                    cursor, table_map[f"{plat}_funnel"], limit,
                    hotel_id=hotel_id, date_column="business_date",
                    period_start=period_start, period_end=period_end,
                    order_candidates=("business_date ASC", "stats_period_type ASC", "metric_name ASC"),
                )
                if plat == "meituan":
                    allowed_names = {
                        "浏览人数", "支付订单数", "支付转化率", "曝光-浏览转化率",
                        "浏览-支付转化率", "曝光人数", "HOS分", "信息分",
                    }
                    rows = [row for row in rows if str(row.get("metric_code") or "").startswith("flow")
                            or str(row.get("metric_name") or "") in allowed_names]
                    diag = {**diag, "rows_used": len(rows),
                            "row_filter": "metric_code startswith flow OR metric_name in configured list"}
                diagnostics["tables"][f"{plat}_funnel"] = diag
                dataset["ota_funnel"].extend(_pivot_funnel(_tag_rows(rows, table_map[f"{plat}_funnel"]), plat))

                # Product price mapping: use latest snapshot within requested period.
                params = []
                filters = _base_filters(hotel_id, params, "business_date", period_start, period_end)
                rows, diag = _fetch(cursor, table_map[f"{plat}_products"], limit, _where(filters), params, "business_date DESC, snapshot_time DESC")
                latest = _latest_snapshot(rows)
                diagnostics["tables"][f"{plat}_products"] = {**diag, "rows_used": len(latest)}
                dataset["products"].extend(_products(_tag_rows(latest, table_map[f"{plat}_products"]), plat))

                # Promotion/activity tables do not contain business_date; use latest snapshot for current configuration.
                if f"{plat}_promotions" in table_map:
                    params = []
                    filters = _base_filters(hotel_id, params)
                    rows, diag = _fetch(cursor, table_map[f"{plat}_promotions"], limit, _where(filters), params, "snapshot_time DESC")
                    latest = _latest_snapshot(rows)
                    diagnostics["tables"][f"{plat}_promotions"] = {**diag, "rows_used": len(latest)}
                    dataset["promotions"].extend(_copy_rows(latest, plat, table_map[f"{plat}_promotions"]))
                if f"{plat}_promotion_products" in table_map:
                    params = []
                    filters = _base_filters(hotel_id, params)
                    rows, diag = _fetch(cursor, table_map[f"{plat}_promotion_products"], limit, _where(filters), params, "snapshot_time DESC")
                    latest = _latest_snapshot(rows)
                    diagnostics["tables"][f"{plat}_promotion_products"] = {**diag, "rows_used": len(latest)}
                    dataset["promotion_products"].extend(_copy_rows(latest, plat, table_map[f"{plat}_promotion_products"]))

                # Review details are filtered by review_time. Overview/ranking are latest snapshot summary tables.
                params = []
                filters = _base_filters(hotel_id, params, "review_time", period_start, period_end)
                rows, diag = _fetch(cursor, table_map[f"{plat}_reviews"], limit, _where(filters), params, "review_time DESC")
                diagnostics["tables"][f"{plat}_reviews"] = diag
                dataset["reviews"].extend(_reviews(_tag_rows(rows, table_map[f"{plat}_reviews"]), plat))

                rows, diag = _profiled_fetch(
                    cursor, table_map[f"{plat}_review_overview"], 20,
                    hotel_id=hotel_id, order_candidates=("snapshot_time DESC",),
                )
                latest = _latest_snapshot(rows)
                diagnostics["tables"][f"{plat}_review_overview"] = {**diag, "rows_used": len(latest)}
                dataset["review_overviews"].extend(_copy_rows(latest, plat, table_map[f"{plat}_review_overview"]))

                params = []
                filters = _base_filters(hotel_id, params)
                rows, diag = _fetch(cursor, table_map[f"{plat}_review_ranking"], 200, _where(filters), params, "snapshot_time DESC, ranking_type ASC, ranking_position ASC")
                latest = _latest_snapshot(rows)
                diagnostics["tables"][f"{plat}_review_ranking"] = {**diag, "rows_used": len(latest)}
                dataset["review_rankings"].extend(_copy_rows(latest, plat, table_map[f"{plat}_review_ranking"]))

            if "meituan" in enabled and "meituan_nearby_events" in table_map:
                params = []
                filters = _base_filters(hotel_id, params)
                rows, diag = _fetch(cursor, table_map["meituan_nearby_events"], 200, _where(filters), params, "event_start_date ASC")
                diagnostics["tables"]["meituan_nearby_events"] = diag
                dataset["nearby_events"].extend(_copy_rows(rows, "meituan", table_map["meituan_nearby_events"]))

            if "meituan" in enabled:
                # 以下表直接服务于 23 项可视化规则。所有查询均保留空表/失败诊断，
                # 由上层把 empty/error 与真实 0 分开处理。
                yesterday = (date.today() - timedelta(days=1)).isoformat()
                specs = [
                    ("exposure_daily", "meituan_exposure_monthly", "business_date", "business_date DESC, snapshot_time DESC"),
                    ("user_source_monthly", "meituan_user_source_monthly", None, "period_month DESC"),
                    ("promotion_finance", "meituan_promotion_finance", "transaction_time", "transaction_time DESC"),
                    ("order_loss_monthly", "meituan_order_loss_monthly", None, "period_month DESC"),
                    ("joined_rights", "meituan_joined_rights", None, None),
                    ("promotion_status", "meituan_promotion_status", None, None),
                    ("video_upload_status", "meituan_video_upload_status", None, None),
                ]
                for section, table_key, date_column, order_by in specs:
                    order_candidates = tuple(
                        candidate.strip() for candidate in str(order_by or "").split(",") if candidate.strip()
                    )
                    query_start = yesterday if table_key == "meituan_exposure_monthly" else period_start
                    query_end = yesterday if table_key == "meituan_exposure_monthly" else period_end
                    rows, diag = _profiled_fetch(
                        cursor, table_map[table_key], limit,
                        hotel_id=hotel_id, date_column=date_column,
                        period_start=query_start if date_column else None,
                        period_end=query_end if date_column else None,
                        order_candidates=order_candidates,
                    )
                    if section == "exposure_daily":
                        rows = _latest_snapshot(rows)
                    if section in {"joined_rights", "promotion_status", "video_upload_status"}:
                        rows = _latest_snapshot(rows)
                    if section == "order_loss_monthly" and rows:
                        latest_month = max(str(row.get("period_month") or "")[:7] for row in rows)
                        if latest_month:
                            rows = [row for row in rows if str(row.get("period_month") or "")[:7] == latest_month]
                    diagnostics["tables"][table_key] = diag
                    dataset[section].extend(_tag_rows(rows, table_map[table_key]))

            diagnostics["transformations"].extend([
                {"section": "ota_funnel", "rows": len(dataset["ota_funnel"]), "rule": "metric_name tall table pivoted into funnel metrics"},
                {"section": "hotel_performance_daily", "rows": len(dataset["hotel_performance_daily"]), "rule": "jl02 metric rows with value_day/value_month/value_year"},
                {"section": "room_type_performance_daily", "rows": len(dataset["room_type_performance_daily"]), "rule": "latest jl01 room-type metric snapshot"},
                {"section": "products", "rows": len(dataset["products"]), "rule": "latest OTA goods price snapshot"},
                {"section": "promotions", "rows": len(dataset["promotions"]), "rule": "latest OTA promotion activity snapshot"},
                {"section": "promotion_products", "rows": len(dataset["promotion_products"]), "rule": "latest activity-room mapping snapshot"},
                {"section": "reviews", "rows": len(dataset["reviews"]), "rule": "review details filtered by review_time"},
                {"section": "review_overviews", "rows": len(dataset["review_overviews"]), "rule": "latest platform review score/count summary"},
                {"section": "review_rankings", "rows": len(dataset["review_rankings"]), "rule": "latest platform review keyword ranking"},
                {"section": "nearby_events", "rows": len(dataset["nearby_events"]), "rule": "nearby event feed for demand context"},
                {"section": "exposure_daily", "rows": len(dataset["exposure_daily"]), "rule": "yesterday latest monthly-source total/non-ad/ad exposure snapshot"},
                {"section": "user_source_monthly", "rows": len(dataset["user_source_monthly"]), "rule": "latest monthly local/nonlocal/new/returning user mix"},
                {"section": "promotion_finance", "rows": len(dataset["promotion_finance"]), "rule": "promotion spend transactions in requested period"},
                {"section": "promotion_revenue", "rows": len(dataset["promotion_revenue"]), "rule": "current-month Meituan EBK room revenue"},
                {"section": "order_loss_monthly", "rows": len(dataset["order_loss_monthly"]), "rule": "latest monthly competitor order loss"},
                {"section": "joined_rights", "rows": len(dataset["joined_rights"]), "rule": "joined rights list"},
                {"section": "promotion_status", "rows": len(dataset["promotion_status"]), "rule": "promotion/configuration status snapshot"},
                {"section": "video_upload_status", "rows": len(dataset["video_upload_status"]), "rule": "video uploaded/required counts"},
            ])
    dataset["__source_diagnostics__"] = [diagnostics]
    return dataset


def _mysql_dataset(config: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    dsn = config.get("dsn") or os.environ.get(str(config.get("dsn_env") or ""))
    if not dsn:
        raise ValueError("MySQL config requires dsn or dsn_env")
    tables = config.get("tables") or {}
    limit = int(config.get("limit") or 5000)
    if config.get("profile") in {"puyue_mysql_reference", "puyue_mysql", "puyue_mysql_export_20260703"} or not tables:
        return load_mysql_dsn_dataset(
            dsn,
            limit=limit,
            tables=tables,
            hotel_id=config.get("hotel_id") or "puyue",
            platform=config.get("platform") or "multi",
            period_start=config.get("period_start"),
            period_end=config.get("period_end"),
        )
    dataset: dict[str, list[dict[str, Any]]] = {section: [] for section in SECTIONS}
    source_diagnostics = {"kind": "mysql", "dsn": _masked_dsn(dsn), "tables": {}}
    with _connect_mysql(dsn) as conn:
        with conn.cursor() as cursor:
            for section in SECTIONS:
                table = tables.get(section)
                if not table:
                    continue
                rows, diag = _fetch(cursor, str(table), limit)
                dataset[section] = rows
                source_diagnostics["tables"][section] = diag
    dataset["__source_diagnostics__"] = [source_diagnostics]
    return dataset


def load_database_dataset(config_path: str | Path) -> dict[str, list[dict[str, Any]]]:
    config = _load_json(config_path)
    kind = str(config.get("kind") or config.get("type") or "sqlite").lower()
    if kind == "sqlite":
        return _sqlite_dataset(config)
    if kind in {"mysql", "mysql+pymysql"}:
        return _mysql_dataset(config)
    raise ValueError(f"unsupported database kind: {kind}")

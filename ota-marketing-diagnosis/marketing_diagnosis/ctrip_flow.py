from __future__ import annotations

import os
import re
from typing import Any

from marketing_diagnosis import db_loader as base
from marketing_diagnosis import ctrip_psi as upstream


DEFAULT_MYSQL_TABLES = {
    **upstream.DEFAULT_MYSQL_TABLES,
    "ctrip_flow_conversion_30d": "ctrip_ota_flow_conversion_30d",
}

_ORDER_COLUMNS = (
    "snapshot_time",
    "updated_at",
    "created_at",
    "business_date",
    "period_end_date",
    "period_start_date",
    "id",
)

_COUNT_ALIASES = (
    "peer_hotel_count",
    "competition_hotel_count",
    "competition_circle_hotel_count",
    "competitor_count",
    "circle_hotel_count",
    "peer_count",
)

_RATIO_SUBITEMS = (
    {
        "name": "列表曝光 / 访客规模",
        "metrics": (
            ("列表页曝光量", "list_exposure", "peer_list_exposure", "count"),
            ("APP访客", "app_visitors", "peer_app_visitors", "count"),
        ),
    },
    {
        "name": "曝光到详情转化",
        "metrics": (
            (
                "曝光到详情转化率",
                "exposure_to_detail_rate_pct",
                "peer_exposure_to_detail_rate_pct",
                "percent",
            ),
            ("详情页访客量", "detail_exposure", "peer_detail_exposure", "count"),
        ),
    },
    {
        "name": "详情到订单页转化",
        "metrics": (
            ("订单页访客量", "order_filling_count", "peer_order_filling_count", "count"),
            (
                "详情到订单页转化率",
                "detail_to_order_rate_pct",
                "peer_detail_to_order_rate_pct",
                "percent",
            ),
        ),
    },
    {
        # The confirmed source ends at submitted orders. It must not be labelled
        # as paid/completed orders because ctrip_ota_flow_conversion_30d has no
        # payment or completion field.
        "name": "订单页到提交转化",
        "metrics": (
            ("提交订单量", "order_submit_count", "peer_order_submit_count", "count"),
            (
                "订单页到提交订单转化率",
                "order_to_submit_rate_pct",
                "peer_order_to_submit_rate_pct",
                "percent",
            ),
        ),
    },
)

_RANK_METRICS = (
    ("曝光排名", "list_exposure_peer_rank"),
    ("访客排名", "detail_exposure_peer_rank"),
    ("转化排名", "detail_to_order_rate_peer_rank"),
)


def _text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", "").rstrip("%")
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


def _platform(value: Any) -> str:
    text = _text(value).lower()
    aliases = {
        "携程": "ctrip",
        "去哪儿": "qunar",
        "去哪兒": "qunar",
        "qunar.com": "qunar",
    }
    return aliases.get(_text(value), text or "ctrip")


def _order_key(row: dict[str, Any], index: int) -> tuple[str, ...]:
    values = [str(row.get(column) or "") for column in _ORDER_COLUMNS[:-1]]
    try:
        row_id = int(row.get("id") or 0)
    except (TypeError, ValueError):
        row_id = 0
    values.extend((f"{row_id:020d}", f"{index:020d}"))
    return tuple(values)


def _latest_platform_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selected: dict[str, tuple[tuple[str, ...], dict[str, Any]]] = {}
    for index, source in enumerate(rows):
        row = dict(source)
        platform = _platform(_first(row, "platform_scope", "platform", "source_platform"))
        if platform not in {"ctrip", "qunar"}:
            continue
        order = _order_key(row, index)
        current = selected.get(platform)
        if current is None or order >= current[0]:
            selected[platform] = (order, row)
    return {platform: value[1] for platform, value in selected.items()}


def _load_flow_rows(
    cursor,
    table: str,
    limit: int,
    hotel_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    columns, schema_error = base._table_columns(cursor, table)
    if schema_error:
        return [], {"table": table, "rows": 0, "status": "error", "error": schema_error}
    required_any = {
        "list_exposure",
        "app_visitors",
        "detail_exposure",
        "order_filling_count",
        "order_submit_count",
    }
    if not (required_any & columns):
        return [], {
            "table": table,
            "rows": 0,
            "status": "error",
            "error": "required flow fields missing",
            "table_columns": sorted(columns),
        }
    order_candidates = tuple(f"{name} DESC" for name in _ORDER_COLUMNS if name in columns)
    rows, diag = base._profiled_fetch(
        cursor,
        table,
        max(limit, 1000),
        hotel_id=hotel_id,
        order_candidates=order_candidates,
    )
    latest = list(_latest_platform_rows(rows).values())
    return latest, {
        **diag,
        "rows_read": len(rows),
        "rows_used": len(latest),
        "selection_rule": "latest row per platform_scope/platform",
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
        dataset.setdefault("ctrip_business_metrics_funnel", [])
        return dataset

    ctrip_id = ctrip_hotel_id or hotel_id
    with base._connect_mysql(dsn) as conn:
        with conn.cursor() as cursor:
            rows, diag = _load_flow_rows(
                cursor,
                table_map["ctrip_flow_conversion_30d"],
                limit,
                ctrip_id,
            )

    # data_v4 already preserves this section. Replacing the old generic funnel
    # rows makes item 03 use only ctrip_ota_flow_conversion_30d while item 05
    # continues to use its own competition/loss sections.
    dataset["ctrip_business_metrics_funnel"] = base._tag_rows(
        rows,
        table_map["ctrip_flow_conversion_30d"],
    )

    diagnostics = dataset.get("__source_diagnostics__") or []
    if diagnostics and isinstance(diagnostics[0], dict):
        diagnostic = diagnostics[0]
        diagnostic.setdefault("tables", {})["ctrip_flow_conversion_30d"] = diag
        diagnostic.setdefault("transformations", []).append(
            {
                "section": "ctrip_business_metrics_funnel",
                "rows": len(rows),
                "rule": "latest Ctrip/Qunar row from ctrip_ota_flow_conversion_30d",
            }
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


def ratio_score_level(ratio: Any) -> float | None:
    value = _number(ratio)
    if value is None:
        return None
    if value >= 2:
        return 1.0
    if value >= 1.5:
        return 0.8
    if value >= 1:
        return 0.6
    return 0.0


def rank_score_level(percentile: Any) -> float | None:
    value = _number(percentile)
    if value is None:
        return None
    if value >= 0.8:
        return 1.0
    if value >= 0.6:
        return 0.8
    if value >= 0.4:
        return 0.6
    return 0.0


def _ratio(hotel_value: float | None, peer_value: float | None) -> float | None:
    if hotel_value is None or peer_value is None or peer_value < 0:
        return None
    if peer_value == 0:
        return float("inf") if hotel_value > 0 else None
    return hotel_value / peer_value


def _rank_and_count(row: dict[str, Any], rank_key: str) -> tuple[float | None, float | None]:
    raw_rank = row.get(rank_key)
    rank = _number(raw_rank)
    count = _number(_first(row, *_COUNT_ALIASES))
    text = _text(raw_rank)
    if count is None and "/" in text:
        count = _number(text.split("/", 1)[1])
    return rank, count


def _period(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "period_start": _first(row, "period_start_date", "start_date"),
        "period_end": _first(row, "period_end_date", "end_date", "business_date"),
        "snapshot_time": row.get("snapshot_time"),
    }


def _ratio_subitem(row: dict[str, Any], index: int, spec: dict[str, Any]) -> dict[str, Any]:
    definitions = list(spec["metrics"])
    metric_full_score = 3.0 / len(definitions)
    metrics: list[dict[str, Any]] = []
    complete = True
    score = 0.0
    for label, hotel_key, peer_key, value_type in definitions:
        hotel_value = _number(row.get(hotel_key))
        peer_value = _number(row.get(peer_key))
        ratio = _ratio(hotel_value, peer_value)
        level = ratio_score_level(ratio)
        metric_score = None if level is None else metric_full_score * level
        if metric_score is None:
            complete = False
        else:
            score += metric_score
        metrics.append(
            {
                "label": label,
                "hotel_field": hotel_key,
                "peer_field": peer_key,
                "hotel_value": hotel_value,
                "peer_value": peer_value,
                "ratio": ratio,
                "score_level": level,
                "metric_score": metric_score,
                "metric_full_score": metric_full_score,
                "value_type": value_type,
            }
        )
    return {
        "index": index,
        "name": spec["name"],
        "full_score": 3.0,
        "subitem_score": round(score, 4) if complete else None,
        "score_status": "success" if complete else "missing",
        "metrics": metrics,
    }


def _rank_subitem(row: dict[str, Any]) -> dict[str, Any]:
    metrics: list[dict[str, Any]] = []
    complete = True
    score = 0.0
    for label, rank_key in _RANK_METRICS:
        rank, count = _rank_and_count(row, rank_key)
        percentile = None
        if rank is not None and count is not None and count > 0:
            percentile = 1 - (rank - 1) / count
            percentile = max(0.0, min(1.0, percentile))
        level = rank_score_level(percentile)
        metric_score = None if level is None else level
        if metric_score is None:
            complete = False
        else:
            score += metric_score
        metrics.append(
            {
                "label": label,
                "rank_field": rank_key,
                "rank": rank,
                "competition_hotel_count": count,
                "rank_percentile": percentile,
                "score_level": level,
                "metric_score": metric_score,
                "metric_full_score": 1.0,
                "value_type": "rank",
            }
        )
    return {
        "index": 5,
        "name": "竞争圈排名表现",
        "full_score": 3.0,
        "subitem_score": round(score, 4) if complete else None,
        "score_status": "success" if complete else "missing",
        "metrics": metrics,
    }


def _platform_payload(platform: str, row: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(row or {})
    subitems = [
        _ratio_subitem(source, index, spec)
        for index, spec in enumerate(_RATIO_SUBITEMS, start=1)
    ]
    subitems.append(_rank_subitem(source))
    calculated = [item["subitem_score"] for item in subitems if item["subitem_score"] is not None]
    connected = any(
        metric.get("hotel_value") is not None
        or metric.get("peer_value") is not None
        or metric.get("rank") is not None
        for item in subitems
        for metric in item["metrics"]
    )
    complete = len(calculated) == len(subitems)
    return {
        "platform": platform,
        "platform_name": "携程" if platform == "ctrip" else "去哪儿",
        "participates_in_score": platform == "ctrip",
        "full_score": 15.0,
        "item_score": round(sum(calculated), 4) if calculated else None,
        "data_status": "success" if complete else "partial" if connected else "missing",
        "subitems": subitems,
        **_period(source),
        "record": source,
    }


def build_flow_item(
    sections: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in sections.get("ctrip_business_metrics_funnel") or []
        if isinstance(row, dict)
    ]
    latest = _latest_platform_rows(rows)
    platforms = {
        "ctrip": _platform_payload("ctrip", latest.get("ctrip")),
        "qunar": _platform_payload("qunar", latest.get("qunar")),
    }
    main = platforms["ctrip"]
    return {
        "standard_item_id": 3,
        "item_name": "平台流量漏斗分析",
        "participates_in_score": True,
        "full_score": 15,
        "item_score": main.get("item_score"),
        "data_status": main.get("data_status"),
        "source": "ctrip_ota_flow_conversion_30d",
        "source_path": "携程 eBooking -> 数据中心 -> 流量与转化",
        "fields": [
            {
                "label": item["name"],
                "value": item["subitem_score"],
                "note": "满分3分",
            }
            for item in main["subitems"]
        ],
        "fields_complete": True,
        "platforms": platforms,
        "active_platform": "ctrip",
        "scoring_rule": {
            "ratio": "酒店指标 / 竞争圈平均；>=2得100%，>=1.5得80%，>=1得60%，<1得0%",
            "rank": "1-(排名-1)/竞争圈酒店数；>=80%得100%，>=60%得80%，>=40%得60%，<40%得0%",
            "aggregation": "每项指标等分子项3分；指标分相加得到子项得分；携程计入总分，去哪儿仅展示",
        },
        "records": rows,
    }


__all__ = [
    "DEFAULT_MYSQL_TABLES",
    "build_flow_item",
    "load_database_dataset",
    "load_mysql_dsn_dataset",
    "rank_score_level",
    "ratio_score_level",
]

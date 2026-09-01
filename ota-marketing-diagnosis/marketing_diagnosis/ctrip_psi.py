from __future__ import annotations

import json
import os
from typing import Any

from marketing_diagnosis import db_loader as base
from marketing_diagnosis import ctrip_competition as previous


DEFAULT_MYSQL_TABLES = {
    **previous.DEFAULT_MYSQL_TABLES,
    "ctrip_psi_score": "ctrip_ota_psi_score",
    "ctrip_psi_metric": "ctrip_ota_psi_metric",
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

METRIC_SPECS = (
    ("historical_room_nights", "经营产能", "历史间夜量", "间夜"),
    ("historical_gmv", "经营产能", "历史营业额", "元"),
    ("historical_deal_rate", "经营产能", "历史成交率", "%"),
    ("instant_confirm_order_rate", "房源保障", "即时确认订单占比", "%"),
    ("consumer_value", "房源保障", "消费者实惠分", "指数"),
    ("room_status_good_rate", "房源保障", "房态良好度", "%"),
    ("review_competitiveness", "客户服务", "点评竞争指数", "指数"),
    ("information_completeness", "客户服务", "信息完整度", "%"),
    ("cancellation_rate", "客户服务", "可取消率", "%"),
)


def _text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).strip().replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
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


def _latest_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    return dict(max(enumerate(rows), key=lambda item: _order_key(item[1], item[0]))[1])


def _latest_metric_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, tuple[tuple[str, ...], dict[str, Any]]] = {}
    for index, row in enumerate(rows):
        code = _text(row.get("metric_code"))
        if not code:
            continue
        order = _order_key(row, index)
        current = selected.get(code)
        if current is None or order >= current[0]:
            selected[code] = (order, dict(row))
    order_index = {code: index for index, (code, _, _, _) in enumerate(METRIC_SPECS)}
    output = [value[1] for value in selected.values()]
    output.sort(key=lambda row: order_index.get(_text(row.get("metric_code")), 999))
    return output


def _load_psi_score(
    cursor,
    table: str,
    limit: int,
    hotel_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    columns, schema_error = base._table_columns(cursor, table)
    if schema_error:
        return [], {"table": table, "rows": 0, "status": "error", "error": schema_error}
    if not ({"psi_total_score", "score_psi"} & columns):
        return [], {
            "table": table,
            "rows": 0,
            "status": "error",
            "error": "required column missing: psi_total_score or score_psi",
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
    latest = _latest_row(rows)
    output = [latest] if latest else []
    return output, {
        **diag,
        "rows_read": len(rows),
        "rows_used": len(output),
        "selection_rule": "latest PSI summary row",
    }


def _load_psi_metrics(
    cursor,
    table: str,
    limit: int,
    hotel_id: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    columns, schema_error = base._table_columns(cursor, table)
    if schema_error:
        return [], {"table": table, "rows": 0, "status": "error", "error": schema_error}
    if "metric_code" not in columns:
        return [], {
            "table": table,
            "rows": 0,
            "status": "error",
            "error": "required column missing: metric_code",
            "table_columns": sorted(columns),
        }
    order_candidates = tuple(
        [f"{name} DESC" for name in _ORDER_COLUMNS if name in columns]
        + ["metric_code ASC"]
    )
    rows, diag = base._profiled_fetch(
        cursor,
        table,
        max(limit, 10000),
        hotel_id=hotel_id,
        order_candidates=order_candidates,
    )
    latest = _latest_metric_rows(rows)
    return latest, {
        **diag,
        "rows_read": len(rows),
        "rows_used": len(latest),
        "selection_rule": "latest row per metric_code",
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
    dataset = previous.load_mysql_dsn_dataset(
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
        dataset.setdefault("ctrip_psi_score", [])
        dataset.setdefault("ctrip_psi_metric", [])
        return dataset

    ctrip_id = ctrip_hotel_id or hotel_id
    with base._connect_mysql(dsn) as conn:
        with conn.cursor() as cursor:
            score_rows, score_diag = _load_psi_score(
                cursor,
                table_map["ctrip_psi_score"],
                limit,
                ctrip_id,
            )
            metric_rows, metric_diag = _load_psi_metrics(
                cursor,
                table_map["ctrip_psi_metric"],
                limit,
                ctrip_id,
            )

    dataset["ctrip_psi_score"] = base._tag_rows(score_rows, table_map["ctrip_psi_score"])
    dataset["ctrip_psi_metric"] = base._tag_rows(metric_rows, table_map["ctrip_psi_metric"])

    diagnostics = dataset.get("__source_diagnostics__") or []
    if diagnostics and isinstance(diagnostics[0], dict):
        diagnostic = diagnostics[0]
        diagnostic.setdefault("tables", {}).update(
            {
                "ctrip_psi_score": score_diag,
                "ctrip_psi_metric": metric_diag,
            }
        )
        diagnostic.setdefault("transformations", []).extend(
            [
                {
                    "section": "ctrip_psi_score",
                    "rows": len(score_rows),
                    "rule": "latest PSI summary row",
                },
                {
                    "section": "ctrip_psi_metric",
                    "rows": len(metric_rows),
                    "rule": "latest row per metric_code",
                },
            ]
        )
    return dataset


def load_database_dataset(config_path):
    config = base._load_json(config_path)
    kind = str(config.get("kind") or config.get("type") or "sqlite").lower()
    if kind not in {"mysql", "mysql+pymysql"}:
        return previous.load_database_dataset(config_path)
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


def score_psi(total_score: Any) -> float | None:
    score = _number(total_score)
    if score is None:
        return None
    if score >= 5.5:
        return 8.0
    if score >= 5.0:
        return 6.4
    if score >= 4.5:
        return 4.8
    return 0.0


def _unit(raw: Any, fallback: str) -> str:
    aliases = {
        "room_night": "间夜",
        "room_nights": "间夜",
        "cny": "元",
        "rmb": "元",
        "%": "%",
        "percent": "%",
        "index": "指数",
    }
    text = _text(raw)
    return aliases.get(text.lower(), text or fallback)


def _history(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(row) if isinstance(row, dict) else {"value": row} for row in value]
    if isinstance(value, dict):
        return [dict(value)]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return [{"value": value.strip()}]
        return _history(parsed)
    return []


def build_psi_item(sections: dict[str, Any]) -> dict[str, Any]:
    score_rows = [
        dict(row)
        for row in sections.get("ctrip_psi_score") or []
        if isinstance(row, dict)
    ]
    metric_rows = [
        dict(row)
        for row in sections.get("ctrip_psi_metric") or []
        if isinstance(row, dict)
    ]
    summary = _latest_row(score_rows) or {}
    metric_map = {
        _text(row.get("metric_code")): row
        for row in _latest_metric_rows(metric_rows)
        if _text(row.get("metric_code"))
    }

    total_score = _number(_first(summary, "psi_total_score", "score_psi"))
    item_score = score_psi(total_score)
    metrics: list[dict[str, Any]] = []
    for code, group, default_name, default_unit in METRIC_SPECS:
        row = dict(metric_map.get(code) or {})
        metrics.append(
            {
                "metric_code": code,
                "metric_group": group,
                "metric_name": _text(row.get("metric_name")) or default_name,
                "metric_value": _number(row.get("metric_value")),
                "unit": _unit(row.get("metric_unit") or row.get("unit"), default_unit),
                "weight_pct": _number(row.get("weight_pct")),
                "psi_score": _number(row.get("psi_score")),
                "competition_rank": _text(row.get("competition_rank")),
                "score_gap": _number(row.get("score_gap")),
                "score_gap_unit": _unit(row.get("score_gap_unit"), ""),
                "period_start_date": _text(row.get("period_start_date"))[:10],
                "period_end_date": _text(row.get("period_end_date"))[:10],
                "business_date": _text(row.get("business_date"))[:10],
                "snapshot_time": _text(row.get("snapshot_time")),
                "connected": bool(row),
            }
        )

    has_data = total_score is not None or any(metric["connected"] for metric in metrics)
    item = {
        "standard_item_id": 6,
        "item_name": "PSI 服务质量分",
        "participates_in_score": True,
        "full_score": 8,
        "item_score": item_score,
        "data_status": "success" if has_data else "missing",
        "source": "ctrip_ota_psi_score、ctrip_ota_psi_metric",
        "source_path": "携程 eBooking -> 工具中心 / PSI 服务质量分",
        "psi_total_score": total_score,
        "score_psi": total_score,
        "psi_basic_score": _number(summary.get("psi_basic_score")),
        "psi_basic_score_max": _number(summary.get("psi_basic_score_max")),
        "psi_reward_score": _number(summary.get("psi_reward_score")),
        "psi_reward_score_max": _number(summary.get("psi_reward_score_max")),
        "psi_deduction_score": _number(summary.get("psi_deduction_score")),
        "service_deduction_score": _number(summary.get("service_deduction_score")),
        "integrity_deduction_score": _number(summary.get("integrity_deduction_score")),
        "financial_deduction_score": _number(summary.get("financial_deduction_score")),
        "psi_rank": _number(summary.get("psi_rank")),
        "psi_competition_circle_count": _number(summary.get("psi_competition_circle_count")),
        "psi_history": _history(summary.get("psi_history")),
        "metrics": metrics,
        "fields": [
            {"label": "PSI 服务质量总分", "value": total_score},
            {"label": "基础分", "value": _number(summary.get("psi_basic_score"))},
            {"label": "奖励分", "value": _number(summary.get("psi_reward_score"))},
            {"label": "总扣分", "value": _number(summary.get("psi_deduction_score"))},
            {"label": "竞争圈排名", "value": _number(summary.get("psi_rank"))},
        ],
        "score_rule": "PSI>=5.5：8分；5.0<=PSI<5.5：6.4分；4.5<=PSI<5.0：4.8分；PSI<4.5：0分",
        "scoring_note": "九项PSI子指标仅用于诊断解释，不重复拆分计分。",
        "records": score_rows + metric_rows,
    }
    return item


__all__ = [
    "DEFAULT_MYSQL_TABLES",
    "METRIC_SPECS",
    "build_psi_item",
    "load_database_dataset",
    "load_mysql_dsn_dataset",
    "score_psi",
]

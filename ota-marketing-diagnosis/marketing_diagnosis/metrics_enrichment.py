from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(str(value).replace(",", ""))
        return None if number != number else number
    except (TypeError, ValueError):
        return None


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b


def _date_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else text


def _parse_date(value: Any) -> dt.date | None:
    text = _date_text(value)
    if not text or text in {"0000-00-00", "unknown", "累计", "快照"}:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return dt.datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return None


def _row_date(row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = _date_text(row.get(key))
        if value:
            return value
    return None


def _period(rows: list[dict[str, Any]], keys: tuple[str, ...], grain: str, label: str) -> dict[str, Any]:
    dates = sorted({d for row in rows for d in [_row_date(row, keys)] if d})
    return {
        "label": label,
        "grain": grain,
        "start": dates[0] if dates else None,
        "end": dates[-1] if dates else None,
        "row_count": len(rows),
        "date_fields": list(keys),
        "has_explicit_date": bool(dates),
        "note": _period_note(grain, bool(dates)),
    }


def _snapshot_period(rows: list[dict[str, Any]], keys: tuple[str, ...], label: str, cumulative: bool = False) -> dict[str, Any]:
    dates = sorted({d for row in rows for d in [_row_date(row, keys)] if d})
    return {
        "label": label,
        "grain": "snapshot",
        "start": "累计" if cumulative else (dates[0] if dates else None),
        "end": dates[-1] if dates else ("快照" if cumulative else None),
        "row_count": len(rows),
        "date_fields": list(keys),
        "has_explicit_date": bool(dates),
        "note": "累计快照口径，不代表报告请求周期" if cumulative else _period_note("snapshot", bool(dates)),
    }


def _period_note(grain: str, has_date: bool) -> str:
    if grain == "daily":
        return "日粒度，按日期聚合/对比" if has_date else "日粒度字段未明确，按当前行聚合"
    if grain == "monthly":
        return "月粒度，用于趋势观察" if has_date else "月粒度字段未明确"
    if grain == "snapshot":
        return "快照口径，代表最新采集状态" if has_date else "快照口径但缺少快照时间"
    if grain == "event":
        return "事件日期口径，用于未来需求判断" if has_date else "事件日期未明确"
    return "按可用字段聚合"


def _exposure_value(row: dict[str, Any]) -> tuple[float | None, float | None, float | None, str]:
    exposure = _num(row.get("exposure"))
    exposure_people = (
        _num(row.get("exposure_people"))
        or _num(row.get("exposure_users"))
        or _num(row.get("exposure_uv"))
        or _num(row.get("曝光人数"))
    )
    if exposure is not None:
        return exposure, exposure_people, exposure, "exposure"
    if exposure_people is not None:
        return None, exposure_people, exposure_people, "exposure_people_fallback"
    return None, None, None, "missing"


def _aggregate_funnel(rows: list[dict[str, Any]]) -> dict[str, Any]:
    exposure = 0.0
    exposure_people = 0.0
    effective_exposure = 0.0
    exposure_seen = exposure_people_seen = effective_seen = False
    source_counter: dict[str, int] = defaultdict(int)
    views = paid_orders = sales_revenue = sold_room_nights = 0.0
    for row in rows:
        exp, people, effective, source = _exposure_value(row)
        source_counter[source] += 1
        if exp is not None:
            exposure += exp
            exposure_seen = True
        if people is not None:
            exposure_people += people
            exposure_people_seen = True
        if effective is not None:
            effective_exposure += effective
            effective_seen = True
        views += _num(row.get("views")) or _num(row.get("visitors")) or 0.0
        paid_orders += _num(row.get("paid_orders")) or 0.0
        sales_revenue += _num(row.get("sales_revenue")) or 0.0
        sold_room_nights += _num(row.get("sold_room_nights")) or 0.0
    main_source = "exposure_people_fallback" if source_counter.get("exposure_people_fallback") and not exposure_seen else "exposure" if exposure_seen else "missing"
    return {
        "exposure": _round(exposure) if exposure_seen else None,
        "exposure_people": _round(exposure_people) if exposure_people_seen else None,
        "effective_exposure": _round(effective_exposure) if effective_seen else None,
        "exposure_used_source": main_source,
        "exposure_note": "曝光量缺失时，暂用曝光人数作为曝光口径计算一转。" if main_source == "exposure_people_fallback" else "优先使用曝光量；曝光人数仅作为辅助展示。",
        "views": _round(views) if views else None,
        "paid_orders": _round(paid_orders) if paid_orders else None,
        "sales_revenue": _round(sales_revenue) if sales_revenue else None,
        "sold_room_nights": _round(sold_room_nights) if sold_room_nights else None,
        "exposure_to_view_rate": _round(_safe_div(views, effective_exposure if effective_seen else None), 4),
        "payment_conversion_rate": _round(_safe_div(paid_orders, views), 4),
        "avg_order_value": _round(_safe_div(sales_revenue, paid_orders)),
        "revenue_per_view": _round(_safe_div(sales_revenue, views), 4),
        "row_count": len(rows),
    }


def _funnel_by_platform(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("platform") or "unknown")].append(row)
    return [{"platform": platform, **_aggregate_funnel(items)} for platform, items in sorted(groups.items())]


def _enrich_funnel(metrics: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    funnel = metrics.get("ota_funnel") or {}
    if not isinstance(funnel, dict):
        return
    recomputed = _aggregate_funnel(rows)
    for key, value in recomputed.items():
        if value is not None or key in {"exposure_used_source", "exposure_note"}:
            funnel[key] = value
    period = _period(rows, ("business_date", "snapshot_time"), "daily", "OTA流量漏斗")
    funnel["data_period"] = period
    period_types: dict[str, int] = defaultdict(int)
    for row in rows:
        period_types[str(row.get("period_type") or "未标注")] += 1
    funnel["period_type_breakdown"] = dict(sorted(period_types.items()))
    dates = sorted({d for row in rows for d in [_row_date(row, ("business_date", "snapshot_time"))] if d})
    day_items = []
    if dates:
        latest = dates[-1]
        previous = dates[-2] if len(dates) >= 2 else None
        for label, day in (("最新日", latest), ("上一日", previous)):
            if not day:
                continue
            day_rows = [row for row in rows if _row_date(row, ("business_date", "snapshot_time")) == day]
            day_items.append({"label": label, "business_date": day, **_aggregate_funnel(day_rows), "by_platform": _funnel_by_platform(day_rows)})
        funnel["latest_business_date"] = latest
        funnel["previous_business_date"] = previous
    else:
        funnel["latest_business_date"] = None
        funnel["previous_business_date"] = None
    funnel["latest_previous_comparison"] = day_items
    by_platform = _funnel_by_platform(rows)
    total_orders = sum(_num(item.get("paid_orders")) or 0 for item in by_platform)
    total_revenue = sum(_num(item.get("sales_revenue")) or 0 for item in by_platform)
    total_effective = sum(_num(item.get("effective_exposure")) or 0 for item in by_platform)
    total_views = sum(_num(item.get("views")) or 0 for item in by_platform)
    for item in by_platform:
        item["exposure_share"] = _round(_safe_div(_num(item.get("effective_exposure")), total_effective), 4)
        item["view_share"] = _round(_safe_div(_num(item.get("views")), total_views), 4)
        item["order_share"] = _round(_safe_div(_num(item.get("paid_orders")), total_orders), 4)
        item["revenue_share"] = _round(_safe_div(_num(item.get("sales_revenue")), total_revenue), 4)
    if by_platform:
        funnel["by_platform"] = by_platform


def _review_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"review_count": 0, "rating_avg": None, "negative_review_count": 0, "negative_review_rate": None, "unreplied_review_count": 0}
    ratings = [_num(row.get("rating")) for row in rows if _num(row.get("rating")) is not None]
    total = len(rows)
    negative = [row for row in rows if row.get("is_negative") is True or (_num(row.get("rating")) is not None and (_num(row.get("rating")) or 0) < 4)]
    unreplied = sum(1 for row in rows if row.get("is_replied") is False)
    return {
        "review_count": total,
        "rating_avg": _round(sum(ratings) / len(ratings), 2) if ratings else None,
        "negative_review_count": len(negative),
        "negative_review_rate": _round(_safe_div(len(negative), total), 4),
        "unreplied_review_count": unreplied,
    }


def _review_by_platform(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("platform") or "unknown")].append(row)
    return [{"platform": platform, **_review_summary(items)} for platform, items in sorted(groups.items())]


def _overview_snapshot(overview_rows: list[dict[str, Any]], base_rep: dict[str, Any]) -> dict[str, Any]:
    period = _snapshot_period(overview_rows, ("snapshot_time", "business_date"), "口碑概览", cumulative=True)
    if overview_rows:
        by_platform = base_rep.get("by_platform") or []
        return {
            **period,
            "review_count": base_rep.get("review_count"),
            "rating_avg": base_rep.get("rating_avg"),
            "negative_review_count": base_rep.get("negative_review_count"),
            "negative_review_rate": base_rep.get("negative_review_rate"),
            "unreplied_review_count": base_rep.get("unreplied_review_count"),
            "by_platform": by_platform,
            "source_note": "来自平台评价概览，通常是累计快照，不代表近30天或近90天明细。",
        }
    return {
        **period,
        "review_count": None,
        "rating_avg": None,
        "negative_review_count": None,
        "negative_review_rate": None,
        "unreplied_review_count": None,
        "by_platform": [],
        "source_note": "未接入评价概览。",
    }


def _date_window_summary(dated: list[tuple[dict[str, Any], dt.date]], days: int) -> dict[str, Any]:
    if not dated:
        return {"start": None, "end": None, "review_count": 0, "by_platform": []}
    latest = max(day for _, day in dated)
    start = latest - dt.timedelta(days=days - 1)
    rows = [row for row, day in dated if day >= start]
    return {"start": start.isoformat(), "end": latest.isoformat(), **_review_summary(rows), "by_platform": _review_by_platform(rows), "source_note": f"来自已采评论明细的近{days}天窗口。"}


def _enrich_reputation(metrics: dict[str, Any], rows: list[dict[str, Any]], overview_rows: list[dict[str, Any]]) -> None:
    rep = metrics.get("reputation") or {}
    if not isinstance(rep, dict):
        return
    rep["overview_snapshot"] = _overview_snapshot(overview_rows, rep)
    rep["data_period"] = rep["overview_snapshot"]
    dated = [(row, _parse_date(row.get("review_date") or row.get("stay_date"))) for row in rows]
    dated = [(row, day) for row, day in dated if day]
    if dated:
        all_rows = [row for row, _ in dated]
        rep["detail_all"] = {"start": min(day for _, day in dated).isoformat(), "end": max(day for _, day in dated).isoformat(), **_review_summary(all_rows), "by_platform": _review_by_platform(all_rows), "source_note": "来自已采评论明细，不等同于累计概览。"}
    else:
        rep["detail_all"] = {"start": None, "end": None, "review_count": 0, "by_platform": [], "source_note": "未接入评论明细或明细缺少日期。"}
    rep["recent_30d"] = _date_window_summary(dated, 30)
    rep["recent_90d"] = _date_window_summary(dated, 90)
    overview_count = _num(rep.get("overview_snapshot", {}).get("review_count")) or 0
    detail_count = _num(rep.get("detail_all", {}).get("review_count")) or 0
    rep["coverage_note"] = "评论明细覆盖少于概览累计数，近30天/近90天只代表已采明细。" if overview_count and detail_count and detail_count < overview_count else "评论明细和概览口径需分开看。"


def _event_suggestions(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["当前未接入周边活动，暂不能用活动辅助判断需求。"]
    upcoming = [row for row in rows if (_num(row.get("countdown_days")) or 9999) <= 60]
    suggestions: list[str] = []
    if upcoming:
        nearest = min(upcoming, key=lambda row: _num(row.get("countdown_days")) or 9999)
        suggestions.append(f"未来60天有{len(upcoming)}个周边活动，最近活动为{nearest.get('event_name')}，距今{nearest.get('countdown_days')}天，可用于远期价和套餐设计。")
    else:
        suggestions.append("未来60天暂无明确周边活动，价格动作应更多依赖PMS趋势和OTA转化。")
    close_events = [row for row in rows if (_num(row.get("distance_km")) is not None and (_num(row.get("distance_km")) or 999) <= 5)]
    if close_events:
        suggestions.append(f"5公里内活动数为{len(close_events)}个，建议检查活动日期前后曝光、搜索词和房型库存。")
    suggestions.append("活动只作为需求辅助信号，不能替代订单、出租率和竞对价格数据。")
    return suggestions


def _enrich_events(metrics: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    events = metrics.get("nearby_events") or {}
    if not isinstance(events, dict):
        return
    events["data_period"] = _period(rows, ("event_start_date", "event_end_date", "snapshot_time"), "event", "周边活动")
    events["ai_context"] = {"suggestions": _event_suggestions(rows), "event_names": [row.get("event_name") for row in rows[:20] if row.get("event_name")]}


def build_time_context(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = [("PMS经营", "operating"), ("OTA流量漏斗", "ota_funnel"), ("价格房型", "price_ladder"), ("推广活动", "promotion"), ("口碑评价", "reputation"), ("周边活动", "nearby_events"), ("竞品价格", "competitors")]
    out = []
    for label, key in mapping:
        item = metrics.get(key) or {}
        period = item.get("data_period") or {}
        if key == "operating" and not period:
            period = {"label": label, "grain": "daily", "start": item.get("period_start"), "end": item.get("period_end"), "row_count": item.get("history_days"), "note": "PMS日粒度汇总"}
            item["data_period"] = period
        out.append({"module": label, **period})
    return out


def enrich_metrics(metrics: dict[str, Any], sections: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    if not metrics:
        return []
    if metrics.get("operating"):
        metrics["operating"]["data_period"] = {"label": "PMS经营", "grain": "daily", "start": metrics["operating"].get("period_start"), "end": metrics["operating"].get("period_end"), "row_count": metrics["operating"].get("history_days"), "note": "所选周期内PMS日粒度聚合；月度趋势单独使用月粒度。"}
    if metrics.get("price_ladder"):
        metrics["price_ladder"]["data_period"] = _period(sections.get("products", []), ("business_date", "snapshot_time"), "snapshot", "价格房型")
    if metrics.get("promotion"):
        metrics["promotion"]["data_period"] = _period(sections.get("promotions", []) + sections.get("promotion_products", []), ("snapshot_time", "business_date"), "snapshot", "推广活动")
    if metrics.get("competitors"):
        metrics["competitors"]["data_period"] = _period(sections.get("competitors", []), ("business_date", "snapshot_time"), "snapshot", "竞品价格")
    _enrich_funnel(metrics, sections.get("ota_funnel", []))
    _enrich_reputation(metrics, sections.get("reviews", []), sections.get("review_overviews", []))
    _enrich_events(metrics, sections.get("nearby_events", []))
    return build_time_context(metrics)

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any, Mapping, Sequence

from runtime.s09_traffic_conversion_real import MEITUAN_TABLE, S09DataGap, build_daily_platform


SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8))
MEITUAN_HOURLY_TABLE = "meituan_ota_business_metrics_hourly"
HOURLY_REQUIRED_CODES = {"INTENTION_UV", "PAY_ORDER_CNT"}


def _number(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any, business_date: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=value.tzinfo or SHANGHAI_TZ).astimezone(SHANGHAI_TZ)
    text = str(value or "").strip()
    if not text:
        return None
    numeric = _number(value)
    if numeric is not None and 0 <= numeric <= 23:
        text = f"{str(business_date)[:10]} {int(numeric):02d}:00:00"
    elif ":" in text and len(text) <= 8:
        text = f"{str(business_date)[:10]} {text}"
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or SHANGHAI_TZ).astimezone(SHANGHAI_TZ)


def _pct(value: Any) -> str:
    number = _number(value)
    return "—" if number is None else f"{number * 100:.1f}%"


def _hourly_rate(value: Any, unit: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number / 100 if str(unit or "").strip().lower() in {"%", "pct", "percent"} or number > 1 else number


def _num(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    return str(int(number)) if number.is_integer() else f"{number:.1f}"


def _target_dates(as_of: dt.datetime, days: int, checkpoint_hour: int) -> list[dt.date]:
    local = as_of.astimezone(SHANGHAI_TZ)
    end = local.date() if local.hour >= checkpoint_hour else local.date() - dt.timedelta(days=1)
    return [end - dt.timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _daily_target_dates(as_of: dt.datetime, days: int) -> list[dt.date]:
    end = as_of.astimezone(SHANGHAI_TZ).date()
    return [end - dt.timedelta(days=offset) for offset in range(days - 1, -1, -1)]


def _select_checkpoint_batches(
    rows: Sequence[Mapping[str, Any]],
    *,
    dates: Sequence[dt.date],
    checkpoint_hour: int,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    cutoff_by_date = {
        day.isoformat(): dt.datetime.combine(day, dt.time(checkpoint_hour), SHANGHAI_TZ)
        for day in dates
    }
    batches: defaultdict[tuple[str, dt.datetime], list[dict[str, Any]]] = defaultdict(list)
    for source in rows:
        row = dict(source)
        day = str(row.get("business_date") or "")[:10]
        observed = _timestamp(row.get("snapshot_hour"), day)
        if day not in cutoff_by_date or observed != cutoff_by_date[day]:
            continue
        batches[(day, observed)].append(row)
    selected: dict[str, list[dict[str, Any]]] = {}
    gaps: dict[str, str] = {}
    for day in dates:
        key = day.isoformat()
        candidates = [
            (observed, values)
            for (batch_day, observed), values in batches.items()
            if batch_day == key and HOURLY_REQUIRED_CODES.issubset(
                {str(item.get("metric_code") or "") for item in values}
            )
        ]
        if not candidates:
            gaps[key] = f"未采集到 {checkpoint_hour:02d}:00 的完整浏览与支付小时快照"
            continue
        observed, values = max(candidates, key=lambda item: item[0])
        for value in values:
            value["checkpoint_observed_at"] = observed.isoformat(timespec="minutes")
        selected[key] = values
    return selected, gaps


def _build_hourly_meituan_platform(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_code = {str(row.get("metric_code") or ""): row for row in rows}
    browse_row = by_code.get("INTENTION_UV") or {}
    pay_row = by_code.get("PAY_ORDER_CNT") or {}
    source_second_row = by_code.get("PAY_ORDER_CNT_UV") or {}
    browse = _number(browse_row.get("metric_value"))
    pay = _number(pay_row.get("metric_value"))
    derived_second = pay / browse if browse and pay is not None else None
    source_second = _hourly_rate(source_second_row.get("metric_value"), source_second_row.get("metric_unit"))
    gaps = []
    if browse is None:
        gaps.append("缺少浏览人数")
    if pay is None:
        gaps.append("缺少支付订单数")
    if derived_second is None:
        gaps.append("无法计算浏览→支付转化率")
    if source_second is not None and derived_second is not None and abs(source_second - derived_second) > 0.01:
        gaps.append("来源支付转化率与派生值不一致")
    return {
        "browse_uv": browse,
        "pay_orders": pay,
        "browse_to_pay_ratio": derived_second,
        "source_browse_to_pay_ratio": source_second,
        "data_gaps": gaps,
    }


def build_s09_checkpoint_report(
    *,
    hotel_id: str,
    as_of: dt.datetime,
    source: Any,
    days: int = 7,
    checkpoint_hour: int = 19,
) -> dict[str, Any]:
    if not 2 <= days <= 31 or not 0 <= checkpoint_hour <= 23:
        raise S09DataGap("invalid_s09_checkpoint_request")
    dates = _target_dates(as_of, days, checkpoint_hour)
    rows = source.hourly_metric_rows(
        MEITUAN_HOURLY_TABLE,
        hotel_id=hotel_id,
        start_date=dates[0],
        end_date=dates[-1],
        as_of=as_of,
    )
    selected, missing = _select_checkpoint_batches(rows, dates=dates, checkpoint_hour=checkpoint_hour)
    entries: list[dict[str, Any]] = []
    for day in dates:
        key = day.isoformat()
        values = selected.get(key)
        if not values:
            continue
        hourly = _build_hourly_meituan_platform(values)
        entries.append(
            {
                "business_date": key,
                "observed_at": values[0].get("checkpoint_observed_at"),
                "stages": hourly,
                "data_gaps": hourly.get("data_gaps") or [],
            }
        )
    return {
        "status": "ok" if entries else "data_gap",
        "skill_id": "S9",
        "intent": "traffic_conversion",
        "query_mode": "historical_checkpoint",
        "hotel_id": hotel_id,
        "as_of_datetime": as_of.isoformat(timespec="seconds"),
        "window_days": days,
        "checkpoint_hour": checkpoint_hour,
        "entries": entries,
        "missing_dates": missing,
        "data_source_type": "real_database" if entries else "unavailable",
        "business_result_generated": bool(entries),
        "approval_data_allowed": False,
        "live_allowed": False,
    }


def _select_daily_batches(
    rows: Sequence[Mapping[str, Any]],
    *,
    dates: Sequence[dt.date],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    required = {"FLOW_EXPOSURE_UV", "FLOW_INTENTION_UV", "FLOW_PAY_ORDER_CNT"}
    batches: defaultdict[tuple[str, dt.datetime], list[dict[str, Any]]] = defaultdict(list)
    allowed_days = {day.isoformat() for day in dates}
    for source in rows:
        row = dict(source)
        day = str(row.get("business_date") or "")[:10]
        observed = _timestamp(row.get("snapshot_time"), day)
        if day in allowed_days and observed is not None:
            batches[(day, observed)].append(row)
    selected: dict[str, list[dict[str, Any]]] = {}
    gaps: dict[str, str] = {}
    for day in dates:
        key = day.isoformat()
        candidates = [
            (observed, values)
            for (batch_day, observed), values in batches.items()
            if batch_day == key and required.issubset({str(item.get("metric_code") or "") for item in values})
        ]
        if not candidates:
            gaps[key] = "没有包含曝光、浏览和支付三项指标的同批次快照"
            continue
        observed, values = max(candidates, key=lambda item: item[0])
        for value in values:
            value["daily_observed_at"] = observed.isoformat(timespec="minutes")
        selected[key] = values
    return selected, gaps


def build_s09_daily_history_report(
    *,
    hotel_id: str,
    as_of: dt.datetime,
    source: Any,
    days: int = 7,
) -> dict[str, Any]:
    if not 2 <= days <= 31:
        raise S09DataGap("invalid_s09_history_request")
    dates = _daily_target_dates(as_of, days)
    rows = source.daily_metric_rows(
        MEITUAN_TABLE,
        hotel_id=hotel_id,
        start_date=dates[0],
        end_date=dates[-1],
        as_of=as_of,
    )
    selected, missing = _select_daily_batches(rows, dates=dates)
    entries: list[dict[str, Any]] = []
    today = as_of.astimezone(SHANGHAI_TZ).date().isoformat()
    for day in dates:
        key = day.isoformat()
        values = selected.get(key)
        if not values:
            continue
        daily = build_daily_platform("meituan", values)
        entries.append(
            {
                "business_date": key,
                "observed_at": values[0].get("daily_observed_at"),
                "is_intraday": key == today,
                "stages": daily.get("stages") or {},
                "first_stage_quality": daily.get("first_stage_quality"),
                "second_stage_quality": daily.get("second_stage_quality"),
                "data_gaps": daily.get("data_gaps") or [],
            }
        )
    return {
        "status": "ok" if entries else "data_gap",
        "skill_id": "S9",
        "intent": "traffic_conversion",
        "query_mode": "daily_history",
        "hotel_id": hotel_id,
        "as_of_datetime": as_of.isoformat(timespec="seconds"),
        "window_days": days,
        "entries": entries,
        "missing_dates": missing,
        "data_source_type": "real_database" if entries else "unavailable",
        "business_result_generated": bool(entries),
        "approval_data_allowed": False,
        "live_allowed": False,
    }


def render_s09_checkpoint_report(report: Mapping[str, Any]) -> str:
    days = int(report.get("window_days") or 0)
    hour = int(report.get("checkpoint_hour") or 0)
    entries = list(report.get("entries") or [])
    if not entries:
        return f"📊 S9 最近{days}天截至{hour:02d}:00流量与转化\n没有可用的同一时点小时快照，未改用日级数据替代。"
    lines = [
        f"📊 S9 最近{days}天截至{hour:02d}:00流量与转化｜美团",
        "口径：浏览/意向 UV → 支付订单；每个日期仅取指定时点的精确小时快照，不与日级数据混用。",
    ]
    for item in entries:
        stages = item.get("stages") or {}
        observed = str(item.get("observed_at") or "")[11:16]
        lines.append(
            f"{str(item.get('business_date') or '')[5:]}｜观测 {observed}"
            f"｜浏览/意向 {_num(stages.get('browse_uv'))}"
            f"｜支付 {_num(stages.get('pay_orders'))}"
            f"｜浏览→支付 {_pct(stages.get('browse_to_pay_ratio'))}"
        )
    first, last = entries[0].get("stages") or {}, entries[-1].get("stages") or {}
    first_browse, last_browse = _number(first.get("browse_uv")), _number(last.get("browse_uv"))
    if first_browse and last_browse is not None:
        change = (last_browse - first_browse) / first_browse
        lines.append(f"趋势：浏览/意向 {_num(first_browse)} → {_num(last_browse)}（{change * 100:+.1f}%）；仅比较同一时点快照。")
    missing = report.get("missing_dates") or {}
    if missing:
        lines.append("数据缺口：" + "；".join(f"{day[5:]} {reason}" for day, reason in missing.items()))
    lines.extend([
        "边界：当天尚未到指定时点时不纳入本窗口；样本不足时只展示数据，不做经营归因或自动动作。",
        "本次仅分析，不创建调价或推广任务。",
    ])
    return "\n".join(lines)


def render_s09_daily_history_report(report: Mapping[str, Any]) -> str:
    days = int(report.get("window_days") or 0)
    entries = list(report.get("entries") or [])
    if not entries:
        return f"📊 S9 最近{days}天每日流量与转化｜美团\n没有可用的同批次日级快照，未混用不同指标版本。"
    lines = [
        f"📊 S9 最近{days}天每日流量与转化｜美团",
        "口径：曝光 UV → 浏览/意向 UV → 支付订单；每个日期只使用包含三项核心指标的同一快照批次。",
    ]
    for item in entries:
        stages = item.get("stages") or {}
        suffix = "（日内累计，未日结）" if item.get("is_intraday") else ""
        lines.append(
            f"{str(item.get('business_date') or '')[5:]}{suffix}"
            f"｜曝光 {_num(stages.get('exposure_uv'))}"
            f"｜浏览/意向 {_num(stages.get('browse_uv'))}"
            f"｜支付 {_num(stages.get('pay_orders'))}"
            f"｜一转 {_pct(stages.get('exposure_to_browse_ratio'))}"
            f"｜二转 {_pct(stages.get('browse_to_pay_ratio'))}"
        )
    complete = [item for item in entries if not item.get("is_intraday")]
    if len(complete) >= 2:
        first, last = complete[0].get("stages") or {}, complete[-1].get("stages") or {}
        before, after = _number(first.get("browse_uv")), _number(last.get("browse_uv"))
        if before and after is not None:
            lines.append(f"已完成日趋势：浏览/意向 {_num(before)} → {_num(after)}（{(after - before) / before * 100:+.1f}%）。")
    missing = report.get("missing_dates") or {}
    if missing:
        lines.append("数据缺口：" + "；".join(f"{day[5:]} {reason}" for day, reason in missing.items()))
    lines.extend([
        "边界：当日数据为日内累计，不与已完成日直接做强弱结论；如需固定时点可说“最近7天截至20点的浏览人数和转化率”。",
        "本次仅分析，不创建调价或推广任务。",
    ])
    return "\n".join(lines)

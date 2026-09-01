from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

_CHECKPOINTS = (9, 12, 14, 16, 18, 20, 22)

_STATUS_LABELS = {
    "severe_slow": "严重滞后",
    "significant_slow": "明显滞后",
    "slow": "略慢",
    "normal": "正常",
    "fast": "略快",
    "significant_fast": "明显超前",
    "unavailable": "暂不可判断",
}
_MATURITY_LABELS = {
    "strong": "高",
    "stable": "较高",
    "temporary": "一般",
    "weak": "偏低",
    "trend_only": "仅作趋势参考",
    "unavailable": "不可用",
    None: "未评估",
}
_COMBINED_LABELS = {
    "genuine_sales_lag": "容量节奏和参考完成节奏都落后，属于真实销售滞后",
    "ambitious_target_gap": "参考最终已售量偏高，当前容量销售节奏本身并不慢",
    "conservative_target_on_track": "参考最终已售量较保守，虽达到参考进度，但容量销售节奏偏慢",
    "on_track_or_ahead": "两种口径均正常或超前",
    "partial_single_line": "当前只有一条基准可用，不能形成双线结论",
}
_STRUCTURE_LABELS = {
    "broad_based_slowdown": "多数房型普遍滞后",
    "room_type_structural_lag": "重要房型存在结构性滞后",
    "mix_offset_detected": "快慢房型相互抵消，全店平均掩盖了结构差异",
}
_TIER_LABELS = {
    "P0_previous_year_approved_window": "上一年同期批准窗口",
    "P1_season_holiday_weekday": "同季节、同节假日、同星期",
    "P2_season_holiday_week_type": "同季节、同节假日、同工作日类型",
    "P3_season_holiday": "同季节、同节假日",
    "P4_same_weekday": "同星期",
    "P5_same_week_type": "同工作日类型",
    "P5_cold_start": "冷启动近似样本",
}
_UNAVAILABLE_LABELS = {
    "market_orders_baseline": "市场总订单基准",
    "hotel_market_share_baseline": "本店市场份额基准",
    "stable_market_browse_pay_conversion_baseline": "稳定的市场浏览到支付转化基准",
    "stable_lead_price_rank_baseline": "稳定的引流价排名基准",
}


def _num(value: Any, digits: int = 1, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "暂不可用"
    if abs(number - round(number)) < 1e-9:
        return f"{int(round(number))}{suffix}"
    return f"{number:.{digits}f}{suffix}"


def _pct(value: Any, digits: int = 0) -> str:
    try:
        return f"{float(value) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "暂不可用"


def _pp(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "暂不可用"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.1f}个百分点"


def _money(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "暂不可用"
    return f"¥{number:,.0f}"


def _summary_value(distribution: Mapping[str, Any] | None, key: str = "median") -> Any:
    return (distribution or {}).get(key)


def _band(distribution: Mapping[str, Any] | None) -> str:
    distribution = distribution or {}
    p25 = distribution.get("p25")
    p80 = distribution.get("p80")
    if p25 is None or p80 is None:
        return "区间不足"
    return f"常见区间 {_pct(p25)}–{_pct(p80)}"


def _point(points: Sequence[Mapping[str, Any]], hour: int) -> Mapping[str, Any] | None:
    exact = next((item for item in points if item.get("hour") == hour), None)
    if exact:
        return exact
    earlier = [item for item in points if isinstance(item.get("hour"), int) and item["hour"] <= hour]
    return max(earlier, key=lambda item: item["hour"]) if earlier else None


def _as_of_hour(value: Any) -> int:
    text = str(value or "")
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).hour
    except ValueError:
        return 23


def _target_label(source: Any) -> str:
    source_text = str(source or "historical_inferred_target")
    if source_text in {"manual_approved", "explicit_target", "approved_target"}:
        return "今日批准目标已售房量"
    return "历史同类日参考最终已售房量"


def _target_source_note(source: Any) -> str:
    source_text = str(source or "historical_inferred_target")
    if source_text in {"manual_approved", "explicit_target", "approved_target"}:
        return "人工批准目标"
    return "根据历史同类日最终已售房量中位数推算，并非人工下达目标"


def _coverage(points: Sequence[Mapping[str, Any]]) -> tuple[list[int], list[int]]:
    observed: list[int] = []
    missing: list[int] = []
    for hour in range(24):
        point = next((item for item in points if item.get("hour") == hour), None)
        counts = [
            int(((point or {}).get("capacity") or {}).get("sample_count") or 0),
            int(((point or {}).get("target_completion") or {}).get("sample_count") or 0),
        ]
        (observed if max(counts) > 0 else missing).append(hour)
    return observed, missing


def _metric_median(platform: Mapping[str, Any], key: str, *, percent: bool = False) -> str:
    value = (((platform.get("baselines") or {}).get(key)) or {}).get("median")
    return _pct(value, 1) if percent else _num(value)


def build_s15_user_message(payload: Mapping[str, Any]) -> str:
    if payload.get("status") != "ok":
        return "S15 销售基准暂不可用。当前缺少可复现的历史分时批次或完整房型范围，请先检查分时采集和房型覆盖。"

    hotel = payload.get("hotel") or {}
    rooms = payload.get("room_types") or {}
    points = hotel.get("hourly_points") or []
    source = payload.get("active_target_source") or payload.get("target_source") or "historical_inferred_target"
    target = hotel.get("effective_target_room_nights")
    revenue = _summary_value(hotel.get("historical_revenue_target"))
    selected_dates = payload.get("selected_dates") or []
    tier = _TIER_LABELS.get(str(payload.get("selected_tier")), "历史同类日")
    observed, missing = _coverage(points)

    lines = [
        f"S15 销售基准（{payload.get('target_date') or payload.get('business_date') or '-'}）",
        f"参考口径：{_target_label(source)} {_num(target, suffix='间')}；{_target_source_note(source)}。",
        f"历史参考收入：{_money(revenue)}；日期匹配：{tier}；选中 {len(selected_dates)} 个历史日期。",
        f"分时覆盖：24小时中 {len(observed)} 个时点有样本。缺失时点只标记缺口，不插值、不补零。",
        "",
        "一、全店两条销售节奏基准",
        "容量节奏＝承诺已售房量÷可售总房量；参考完成节奏＝承诺已售房量÷历史同类日最终已售房量。",
    ]
    for hour in _CHECKPOINTS:
        point = next((item for item in points if item.get("hour") == hour), None)
        if not point:
            continue
        capacity = point.get("capacity") or {}
        completion = point.get("target_completion") or {}
        expected = None
        if target is not None and completion.get("median") is not None:
            expected = float(target) * float(completion["median"])
        count = max(int(capacity.get("sample_count") or 0), int(completion.get("sample_count") or 0))
        maturity = _MATURITY_LABELS.get(point.get("maturity"), str(point.get("maturity") or "未评估"))
        lines.append(
            f"- {hour:02d}时：容量节奏 {_pct(capacity.get('median'))}（{_band(capacity)}）；"
            f"参考完成节奏 {_pct(completion.get('median'))}（{_band(completion)}）；"
            f"折算应售 {_num(expected, suffix='间')}；样本 {count} 天，成熟度{maturity}。"
        )

    lines.extend(["", "二、房型基准（当前时点摘要）"])
    current_hour = _as_of_hour(payload.get("as_of_datetime"))
    if rooms:
        for room_id, room in sorted(rooms.items(), key=lambda item: str(item[0])):
            room_points = room.get("hourly_points") or []
            point = _point(room_points, current_hour) or {}
            capacity = point.get("capacity") or {}
            completion = point.get("target_completion") or {}
            room_target = room.get("effective_target_room_nights")
            price = room.get("price_baseline") or {}
            room_name = room.get("room_type_name") or room.get("room_type_id") or room_id
            lines.append(
                f"- {room_name}：参考最终已售 {_num(room_target, suffix='间')}；"
                f"{current_hour:02d}时容量节奏 {_pct(capacity.get('median'))}；"
                f"参考完成节奏 {_pct(completion.get('median'))}；"
                f"历史成交价中位 {_money(price.get('median'))}。"
            )
    else:
        lines.append("- 暂无可用的 canonical 房型基准。")

    ota = payload.get("ota_baselines") or {}
    mt = ota.get("meituan") or {}
    ct = ota.get("ctrip") or {}
    lines.extend(
        [
            "",
            "三、平台流量与转化基准",
            f"- 美团：浏览人数中位 {_metric_median(mt, 'browse_uv')}；曝光到浏览 {_metric_median(mt, 'first_conversion', percent=True)}；浏览到支付 {_metric_median(mt, 'second_conversion', percent=True)}。",
            f"- 携程：详情访客中位 {_metric_median(ct, 'detail_visitor_count')}；列表曝光到详情 {_metric_median(ct, 'list_to_detail_ratio', percent=True)}；详情到提交 {_metric_median(ct, 'detail_to_submit_ratio', percent=True)}。",
        ]
    )

    unavailable = payload.get("unavailable_baseline_families") or {}
    if unavailable:
        labels = [_UNAVAILABLE_LABELS.get(key, key) for key in unavailable]
        lines.extend(["", "四、当前无法形成稳定基准", "- " + "、".join(labels) + "。缺少真实同范围分母时不会反推或编造。"])

    if missing:
        compact = ", ".join(f"{hour:02d}" for hour in missing)
        lines.extend(["", f"数据提醒：缺失小时为 {compact} 时；已有时点的成熟度独立判断，不能用日级长历史替代小时覆盖。"])
    return "\n".join(lines)


def _line_text(label: str, line: Mapping[str, Any], *, reference_label: str) -> str:
    status = _STATUS_LABELS.get(str(line.get("status")), str(line.get("status") or "暂不可判断"))
    return (
        f"- {label}：当前 {_pct(line.get('actual_progress'), 1)}；{reference_label} {_pct(line.get('baseline_median'), 1)}"
        f"（常见区间 {_pct(line.get('baseline_p25'), 1)}–{_pct(line.get('baseline_p80'), 1)}）；"
        f"偏差 {_pp(line.get('delta_pp'))}；折算应售 {_num(line.get('expected_sold'), suffix='间')}；"
        f"当前比参考 {_num(line.get('room_gap'), suffix='间')}；判定为{status}。"
    )


def build_s16_user_message(report: Mapping[str, Any]) -> str:
    if report.get("status") not in {"ok", "partial"}:
        reason = str(report.get("reason") or "当前事实或S15基准不可用")
        labels = {
            "future_stay_date_requires_lead_time_baseline": "未来入住日需要提前期基准，不能套用入住日当天分时曲线",
            "historical_current_fact_requires_hourly_replay": "历史日期需要使用当时的小时快照回放",
            "s15_baseline_unavailable": "S15基准暂不可用",
            "checkpoint_gap_exceeds_limit": "当前事实快照距离请求时间过久",
        }
        return f"S16 销售进度暂不可判断：{labels.get(reason, reason)}。"

    hotel = report.get("hotel_result") or {}
    capacity = hotel.get("capacity_line") or {}
    target_line = hotel.get("target_line") or {}
    target_source = report.get("target_source") or "historical_inferred_target"
    target_label = "批准目标完成节奏" if _target_source_note(target_source) == "人工批准目标" else "历史参考最终已售完成节奏"
    actual = hotel.get("committed_sold")
    total = hotel.get("total_rooms")
    target = hotel.get("effective_target_room_nights")
    combined = _COMBINED_LABELS.get(str(hotel.get("combined_diagnosis")), str(hotel.get("combined_diagnosis") or "暂不可判断"))
    gap_minutes = report.get("checkpoint_gap_minutes")

    lines = [
        f"S16 销售进度（{report.get('target_date') or '-'}，截至 {str(report.get('as_of_datetime') or '-')[-8:-3]}）",
        f"当前承诺已售房量：{_num(actual, suffix='间')}；可售总房量：{_num(total, suffix='间')}；{_target_label(target_source)}：{_num(target, suffix='间')}。",
        "承诺已售是销售承诺口径，不等同于物理在住房；订单数无法由房量直接换算。",
        "",
        "一、全店双线判断",
        _line_text("容量销售节奏", capacity, reference_label="历史同类日正常容量节奏"),
        _line_text(target_label, target_line, reference_label="历史同类日同时点完成节奏"),
        f"- 距离参考最终已售量：{_num(target_line.get('remaining_target_gap'), suffix='间')}；综合判断：{combined}。",
        "",
        "二、房型双线",
    ]

    room_results = report.get("room_type_results") or []
    if room_results:
        for room in room_results:
            room_name = room.get("room_type_name") or room.get("room_type_id") or "未知房型"
            cap = room.get("capacity_line") or {}
            tgt = room.get("target_line") or {}
            cap_status = _STATUS_LABELS.get(str(cap.get("status")), "暂不可判断")
            tgt_status = _STATUS_LABELS.get(str(tgt.get("status")), "暂不可判断")
            lines.append(
                f"- {room_name}：已售 {_num(room.get('committed_sold'), suffix='间')}/{_num(room.get('total_rooms'), suffix='间')}；"
                f"容量线{cap_status}（{_pp(cap.get('delta_pp'))}）；"
                f"参考完成线{tgt_status}（{_pp(tgt.get('delta_pp'))}，检查点差 {_num(tgt.get('room_gap'), suffix='间')}，最终参考差 {_num(tgt.get('remaining_target_gap'), suffix='间')}）；"
                f"成熟度{_MATURITY_LABELS.get(room.get('maturity'), str(room.get('maturity') or '未评估'))}。"
            )
    else:
        lines.append("- 当前没有可用的完整房型结果。")

    structure = report.get("structure_summary") or {}
    labels = [_STRUCTURE_LABELS.get(str(item), str(item)) for item in structure.get("labels") or []]
    lines.extend(
        [
            "",
            "三、房型结构",
            f"- 滞后房型 {structure.get('slow_room_type_count', 0)} 个；超前房型 {structure.get('fast_room_type_count', 0)} 个；"
            f"滞后房型占参考最终已售量 {_pct(structure.get('slow_target_share'), 1)}。",
            f"- 结构判断：{'；'.join(labels) if labels else '未发现需要单独标记的结构性异常'}。",
        ]
    )
    if gap_minutes not in (None, 0):
        lines.append(f"数据时效：使用的完整房型批次距请求时点约 {gap_minutes} 分钟。")
    if report.get("status") == "partial":
        missing = report.get("missing_room_type_ids") or []
        lines.append(f"数据提醒：当前房型范围不完整，缺失 {', '.join(map(str, missing)) or '部分房型'}；全店与房型合计不作强行对账。")
    lines.append("本结果只说明销售节奏和结构，不据此直接推断必然满房，也不直接生成调价或推广动作。")
    return "\n".join(lines)


def attach_s15_user_view(payload: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    message = build_s15_user_message(result)
    result.update(
        {
            "summary": message,
            "user_message": message,
            "business_view_version": "s15.zh-CN.v2",
            "target_business_term": _target_label(result.get("active_target_source")),
            "order_count_available": False,
            "order_count_unavailable_reason": "订单数不能由已售房量或间夜按1比1换算",
        }
    )
    return result


def attach_s16_user_view(report: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(report)
    message = build_s16_user_message(result)
    result.update(
        {
            "summary": message,
            "user_message": message,
            "business_view_version": "s16.zh-CN.v2",
            "order_count_available": False,
            "order_count_unavailable_reason": "订单数不能由承诺已售房量按1比1换算",
        }
    )
    return result

from __future__ import annotations

from collections import defaultdict
from statistics import median
from typing import Any, Mapping, Sequence

_VERSION = "s15-s16-template-advisory-minfix.v1"
_INSTALLED = False


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _num(value: Any, digits: int = 1) -> str:
    number = _number(value)
    if number is None:
        return "—"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _percent_value(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    display = number * 100 if abs(number) <= 1 else number
    return f"{display:.1f}%"


def _metric_value(value: Any, unit: Any) -> str:
    number = _number(value)
    if number is None:
        return "—"
    normalized = str(unit or "").strip().lower()
    if normalized in {"%", "ratio", "percent", "percentage"}:
        return _percent_value(number)
    if normalized in {"cny", "元", "currency", "rmb"}:
        return f"¥{number:,.0f}"
    unit_labels = {
        "person": "人",
        "人": "人",
        "order": "单",
        "orders": "单",
        "单": "单",
        "room_night": "间夜",
        "间夜": "间夜",
        "count": "次",
        "次": "次",
        "uv": "人",
    }
    return f"{_num(number)}{unit_labels.get(normalized, str(unit or ''))}"


def _rank(value: Any, total: Any = None) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    if "/" in text:
        return text
    rank = _number(value)
    count = _number(total)
    if rank is None:
        return None
    return f"{int(rank)}/{int(count)}" if count else str(int(rank))


def _append_peer_context(lines: list[str], payload: Mapping[str, Any]) -> None:
    context = payload.get("peer_demand_proxy") or {}
    points = context.get("points") or []
    visible = [point for point in points if _number(point.get("hotel_value")) is not None]
    if not visible:
        return
    period_start = next((str(p.get("period_start_date")) for p in visible if p.get("period_start_date")), "")
    period_end = next((str(p.get("period_end_date")) for p in visible if p.get("period_end_date")), "")
    title = "【同行需求代理】"
    if period_start or period_end:
        title += f"（{period_start or '—'} 至 {period_end or '—'}）"
    lines.extend(["", title])
    for point in visible:
        name = point.get("metric_name") or point.get("metric_code") or "指标"
        unit = point.get("metric_unit")
        parts = [f"本店 {_metric_value(point.get('hotel_value'), unit)}"]
        if _number(point.get("competitor_avg")) is not None:
            parts.append(f"竞对均值 {_metric_value(point.get('competitor_avg'), unit)}")
        rank = _rank(point.get("competitor_rank"), point.get("competition_circle_hotel_count"))
        if rank:
            parts.append(f"排名 {rank}")
        lines.append(f"• {name}  " + "  ｜  ".join(parts))
    lines.append("说明  该组数据只作为同行需求代理，不据此反推市场总订单或本店市场份额。")


def _latest_row(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return max(rows, key=lambda row: str(row.get("snapshot_time") or "")) if rows else None


def _append_rolling_context(lines: list[str], payload: Mapping[str, Any]) -> None:
    rolling = payload.get("rolling_30d_context") or {}
    blocks: list[str] = []
    for platform, label in (("meituan", "美团"), ("ctrip", "携程")):
        row = _latest_row(rolling.get(platform) or [])
        if not row:
            continue
        period = f"{str(row.get('period_start_date') or '')[:10]} 至 {str(row.get('period_end_date') or '')[:10]}"
        values: list[str] = []
        if platform == "meituan":
            fields = (
                ("exposure_uv", "曝光", "人"),
                ("browse_uv", "浏览", "人"),
                ("pay_order_count", "支付", "单"),
            )
            rates = (
                ("exposure_to_browse_rate_pct", "曝光→浏览"),
                ("browse_to_pay_rate_pct", "浏览→支付"),
            )
            peer_rates = (
                ("peer_exposure_to_browse_rate_pct", "同行曝光→浏览"),
                ("peer_browse_to_pay_rate_pct", "同行浏览→支付"),
            )
            ranks = (
                ("exposure_peer_rank", "曝光排名"),
                ("browse_peer_rank", "浏览排名"),
                ("pay_order_peer_rank", "支付排名"),
                ("exposure_to_browse_peer_rank", "曝光转化排名"),
                ("browse_to_pay_peer_rank", "支付转化排名"),
            )
        else:
            fields = (
                ("app_visitors", "APP访客", "人"),
                ("list_exposure", "列表曝光", "次"),
                ("detail_exposure", "详情曝光", "次"),
                ("order_filling_count", "填写订单", "单"),
                ("order_submit_count", "提交订单", "单"),
            )
            rates = (
                ("exposure_to_detail_rate_pct", "列表→详情"),
                ("detail_to_order_rate_pct", "详情→填写"),
                ("order_to_submit_rate_pct", "填写→提交"),
            )
            peer_rates = (
                ("peer_exposure_to_detail_rate_pct", "同行列表→详情"),
                ("peer_detail_to_order_rate_pct", "同行详情→填写"),
                ("peer_order_to_submit_rate_pct", "同行填写→提交"),
            )
            ranks = (
                ("list_exposure_peer_rank", "列表曝光排名"),
                ("detail_exposure_peer_rank", "详情曝光排名"),
                ("order_filling_peer_rank", "填写订单排名"),
                ("exposure_to_detail_rate_peer_rank", "列表转化排名"),
                ("detail_to_order_rate_peer_rank", "详情转化排名"),
            )
        for key, name, unit in fields:
            if _number(row.get(key)) is not None:
                values.append(f"{name} {_metric_value(row.get(key), unit)}")
        for key, name in rates:
            if _number(row.get(key)) is not None:
                values.append(f"{name} {_percent_value(row.get(key))}")
        comparison = [f"{name} {_percent_value(row.get(key))}" for key, name in peer_rates if _number(row.get(key)) is not None]
        rank_values = [f"{name} {row.get(key)}" for key, name in ranks if row.get(key) not in (None, "")]
        block = f"• {label}（{period}）\n  本店  " + "  ｜  ".join(values)
        if comparison:
            block += "\n  同行  " + "  ｜  ".join(comparison)
        if rank_values:
            block += "\n  排名  " + "  ｜  ".join(rank_values)
        blocks.append(block)
    if blocks:
        lines.extend(["", "【30日滚动背景】", *blocks])
        lines.append("说明  这是单一滚动窗口背景，不拆成逐日历史样本。")


def _append_booking_context(lines: list[str], payload: Mapping[str, Any]) -> None:
    context = payload.get("gross_booking_created_curve_context") or {}
    points = context.get("points") or []
    if not points:
        return
    dates = {str(point.get("stay_date") or "")[:10] for point in points if point.get("stay_date")}
    hours = {int(point.get("booking_hour")) for point in points if _number(point.get("booking_hour")) is not None}
    by_hour: dict[int, list[float]] = defaultdict(list)
    for point in points:
        hour = _number(point.get("booking_hour"))
        rooms = _number(point.get("gross_created_rooms"))
        if hour is not None and rooms is not None:
            by_hour[int(hour)].append(rooms)
    peaks = sorted(
        ((hour, median(values)) for hour, values in by_hour.items() if values),
        key=lambda item: item[1],
        reverse=True,
    )[:3]
    peak_text = "、".join(f"{hour:02d}时中位{_num(value)}间" for hour, value in peaks)
    lines.extend(["", "【订单创建曲线背景】"])
    lines.append(f"覆盖 {len(dates)}个入住日、{len(hours)}个创建小时" + (f"；相对活跃时段：{peak_text}" if peak_text else "") + "。")
    lines.append("说明  仅作诊断参考，订单创建量不等于承诺已售，且未验证取消时间线。")


def _append_hour_distribution(lines: list[str], payload: Mapping[str, Any]) -> None:
    context = payload.get("gross_order_hour_distribution_context") or {}
    points = context.get("points") or []
    visible = [p for p in points if _number(p.get("rate_pct")) is not None]
    if not visible:
        return
    top = sorted(visible, key=lambda p: float(p.get("rate_pct") or 0), reverse=True)[:5]
    lines.extend(["", "【平台订单时段分布】"])
    lines.append("  ｜  ".join(f"{p.get('bucket_label')} {_percent_value(p.get('rate_pct'))}" for p in top))
    lines.append("说明  只反映平台订单时段分布，不替代入住日小时销售节奏。")


def _append_unavailable(lines: list[str], payload: Mapping[str, Any]) -> None:
    families = payload.get("unavailable_baseline_families") or {}
    labels = {
        "market_orders_baseline": "市场总订单基线",
        "hotel_market_share_baseline": "本店市场份额基线",
        "stable_market_browse_pay_conversion_baseline": "稳定市场浏览→支付转化",
        "stable_lead_price_rank_baseline": "稳定引流价排名",
    }
    visible = [labels.get(str(key), str(key)) for key, reason in families.items() if reason]
    gaps = payload.get("data_gaps") or []
    if not visible and not gaps:
        return
    lines.extend(["", "【数据边界】"])
    if visible:
        lines.append("未形成稳定基准  " + "、".join(visible) + "；不补造。")
    if gaps:
        readable = []
        for gap in gaps:
            text = str(gap)
            if text.startswith("room_daily:"):
                readable.append("房型日终数据查询失败，房型参考终值/完成线可能缺失")
            elif text.startswith("hotel_daily_total:"):
                readable.append("酒店日终总计查询失败，全店参考完成线可能缺失")
            elif text.startswith("ota_business_metrics:"):
                readable.append("OTA日级指标查询失败")
            else:
                readable.append(text)
        lines.append("数据缺口  " + "；".join(dict.fromkeys(readable)) + "。")


def append_complete_s15_families(text: str, payload: Mapping[str, Any]) -> str:
    lines: list[str] = []
    _append_peer_context(lines, payload)
    _append_rolling_context(lines, payload)
    _append_booking_context(lines, payload)
    _append_hour_distribution(lines, payload)
    _append_unavailable(lines, payload)
    if not lines:
        return text
    marker = "\n\n口径说明"
    block = "\n".join(lines)
    if marker in text:
        return text.replace(marker, "\n" + block + marker, 1)
    return text + "\n" + block


def advisory_output_contract(result: Mapping[str, Any]) -> dict[str, Any]:
    intent = str(result.get("intent") or "")
    required = ["全店小时节奏", "房型基准", "平台流量与转化"] if intent == "sales_baseline_demo" else ["全店双线", "房型双线", "结构汇总"]
    if intent == "sales_baseline_demo":
        required.extend(["同行需求代理", "30日滚动背景", "数据边界"])
    return {
        "mode": "authoritative_facts_plus_advisory_analysis",
        "facts_are_authoritative": True,
        "ai_analysis_allowed": True,
        "maximum_runtime_tool_calls": 1,
        "additional_database_queries_allowed": False,
        "must_preserve_authoritative_text": True,
        "must_preserve_all_available_sections": True,
        "required_sections_when_available": required,
        "advisory_analysis_allowed": [
            "晚间剩余需求推断",
            "调价建议",
            "推广建议",
        ],
        "advisory_requirements": [
            "必须明确标注为推断或建议",
            "必须说明依据和数据成熟度",
            "不得把建议表述为已执行动作",
            "不得自动创建调价或推广任务",
            "涉及价格时必须走S5候选和S6 dry-run后续流程",
        ],
        "forbidden": [
            "删除或压缩runtime已提供的基准线族",
            "修改事实数字、日期、单位、房型或样本数",
            "把历史累计应售直接当作未来剩余需求",
            "声称已自动调价、已投放推广或已执行任何写操作",
        ],
        "contract_version": _VERSION,
    }


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s15_s16_ai_analysis_patch, s15_s16_presentation_completeness_patch
    from runtime.sales_progress import presentation

    previous_s15 = presentation.build_s15_user_message

    def expanded_s15(payload: Mapping[str, Any]) -> str:
        return append_complete_s15_families(previous_s15(payload), payload)

    presentation.build_s15_user_message = expanded_s15
    s15_s16_presentation_completeness_patch.direct_output_contract = advisory_output_contract
    s15_s16_ai_analysis_patch.build_ai_response_contract = advisory_output_contract

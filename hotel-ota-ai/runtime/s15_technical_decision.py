from __future__ import annotations

from typing import Any, Mapping

from runtime.s15_technical_sources import (
    AD_OPEN_SALES_SLOW_PP,
    SHARE_WEAK_PP,
    _n,
)


def _diagnose_and_actions(
    analysis: dict[str, Any],
) -> tuple[list[str], list[dict[str, Any]]]:
    diagnosis: list[str] = []
    actions: list[dict[str, Any]] = []
    sales = analysis.get("sales") or {}
    market = analysis.get("market") or {}
    share = analysis.get("market_share") or {}
    browse = analysis.get("browse") or {}
    first = analysis.get("first_conversion") or {}
    second = analysis.get("second_conversion") or {}
    price = analysis.get("price") or {}
    ad = analysis.get("ad_context") or {}

    sales_status = str(sales.get("status") or "unavailable")
    sales_slow = sales_status in {
        "slow",
        "significant_slow",
        "severe_slow",
    }
    sales_fast = sales_status in {"fast", "significant_fast"}
    market_status = str(market.get("status") or "unavailable")
    share_delta = _n(share.get("delta_pp"))
    share_weak = (
        share_delta is not None and share_delta <= SHARE_WEAK_PP
    )
    browse_weak = str(browse.get("status")) == "weak"
    first_weak = str(first.get("status")) == "weak"
    second_weak = bool(second.get("is_weak"))

    if sales_status == "unavailable":
        diagnosis.append("sales_progress_unavailable")
        actions.append(
            {
                "action_type": "no_action",
                "reason": "sales_progress_unavailable",
                "auto_executable": False,
            }
        )
        return diagnosis, actions

    if not sales_slow:
        diagnosis.append("sales_on_track_or_ahead")
        remaining_ratio = _n(sales.get("remaining_inventory_ratio"))
        if (
            sales_fast
            and bool(ad.get("ad_running"))
            and remaining_ratio is not None
            and remaining_ratio <= 0.20
        ):
            actions.append(
                {
                    "action_type": "suggest_disable_ad_slot",
                    "reason": "sales_fast_and_inventory_tight",
                    "observe_minutes": 60,
                    "auto_executable": False,
                    "requires_manual_confirmation": True,
                    "requires_followup_skill": "S8",
                }
            )
        else:
            actions.append(
                {
                    "action_type": "no_action",
                    "reason": "sales_not_slow",
                    "auto_executable": False,
                }
            )
        return diagnosis, actions

    diagnosis.append("sales_progress_slow")
    if market_status == "cold" and not share_weak:
        diagnosis.append("market_cold_share_not_weak")
        actions.append(
            {
                "action_type": "conservative_inventory_management",
                "reason": "market_cold_share_not_weak",
                "auto_executable": False,
                "requires_manual_confirmation": True,
            }
        )
        return diagnosis, actions

    if share_weak:
        diagnosis.append("market_share_declining")
    if browse_weak:
        diagnosis.append("traffic_insufficient")
        sales_delta = _n(sales.get("sales_progress_delta_pp"))
        if (
            sales_delta is not None
            and sales_delta <= AD_OPEN_SALES_SLOW_PP
            and not second_weak
            and market_status not in {"cold", "unavailable"}
        ):
            actions.append(
                {
                    "action_type": "suggest_enable_ad_slot",
                    "reason": (
                        "sales_slow_browse_weak_conversion_not_weak_"
                        "market_not_cold"
                    ),
                    "observe_minutes": 60,
                    "auto_executable": False,
                    "requires_manual_confirmation": True,
                    "requires_followup_skill": "S8",
                }
            )
        else:
            actions.append(
                {
                    "action_type": "investigate_traffic_before_spend",
                    "reason": (
                        "browse_weak_but_conversion_or_market_not_qualified"
                    ),
                    "auto_executable": False,
                }
            )
        return diagnosis, actions

    if first_weak:
        diagnosis.append("entry_attractiveness_weak")
        actions.append(
            {
                "action_type": "optimize_entry_display",
                "reason": "first_conversion_weak",
                "auto_executable": False,
                "requires_manual_confirmation": True,
            }
        )
        return diagnosis, actions

    if second_weak:
        diagnosis.append("detail_page_conversion_weak")
        high_rooms = list(price.get("high_room_type_ids") or [])
        if high_rooms:
            diagnosis.append("specific_room_prices_high")
            actions.append(
                {
                    "action_type": "suggest_room_price_reduction",
                    "target_room_type_ids": high_rooms,
                    "suggested_change_pct_range": [-8, -5],
                    "observe_minutes": 90,
                    "reason": (
                        "sales_slow_browse_normal_second_conversion_"
                        "weak_price_high"
                    ),
                    "auto_executable": False,
                    "requires_manual_confirmation": True,
                    "requires_followup_skill": "S5",
                    "requires_price_guard": True,
                }
            )
        else:
            actions.append(
                {
                    "action_type": "investigate_detail_conversion",
                    "reason": (
                        "second_conversion_weak_without_price_high_evidence"
                    ),
                    "auto_executable": False,
                }
            )
        return diagnosis, actions

    diagnosis.append("no_single_root_cause_confirmed")
    actions.append(
        {
            "action_type": "continue_observation",
            "reason": (
                "sales_slow_but_market_funnel_price_evidence_not_conclusive"
            ),
            "observe_minutes": 60,
            "auto_executable": False,
        }
    )
    return diagnosis, actions


def _fmt_num(value: Any, digits: int = 1) -> str:
    number = _n(value)
    if number is None:
        return "—"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _fmt_pct(value: Any, digits: int = 1) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.{digits}f}%"


def _fmt_pp(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"{number:+.1f}pp"


def render_s15_analysis(payload: Mapping[str, Any]) -> str:
    analysis = payload.get("operating_analysis") or {}
    if not analysis:
        return ""
    sales = analysis.get("sales") or {}
    market = analysis.get("market") or {}
    share = analysis.get("market_share") or {}
    browse = analysis.get("browse") or {}
    first = analysis.get("first_conversion") or {}
    second = analysis.get("second_conversion") or {}
    price = analysis.get("price") or {}
    labels = {
        "severe_slow": "严重偏慢",
        "significant_slow": "明显偏慢",
        "slow": "偏慢",
        "normal": "正常",
        "fast": "偏快",
        "significant_fast": "明显偏快",
        "cold": "偏冷",
        "hot": "偏热",
        "weak": "偏弱",
        "soft": "略弱",
        "strong": "偏强",
        "sample_insufficient": "样本不足",
        "unavailable": "暂不可判断",
    }
    lines = [
        "【S15 基准线经营判断】",
        (
            "结论顺序：销售进度 → 大盘 → 估算份额 → 浏览 → "
            "一转 → 二转 → 房型价格 → 动作。"
        ),
        (
            "• 销售进度："
            f"{labels.get(str(sales.get('status')), sales.get('status') or '暂不可判断')}，"
            f"偏差 {_fmt_pp(sales.get('sales_progress_delta_pp'))}；"
            f"当前承诺已售 {_fmt_num(sales.get('committed_sold'))}/"
            f"{_fmt_num(sales.get('total_rooms'))} 间。"
        ),
        (
            "• 大盘："
            f"{labels.get(str(market.get('status')), market.get('status') or '暂不可判断')}；"
            f"估算订单 {_fmt_num(market.get('estimated_market_orders'))}，"
            "历史估算基准 "
            f"{_fmt_num(market.get('baseline_estimated_market_orders'))}，"
            f"热度比 {_fmt_num(market.get('market_heat_ratio'), 2)}。"
        ),
        (
            "• 本店份额：当前估算 "
            f"{_fmt_pct(share.get('current_estimated_market_share'))}，"
            "历史估算 "
            f"{_fmt_pct(share.get('baseline_estimated_market_share'))}，"
            f"变化 {_fmt_pp(share.get('delta_pp'))}。"
        ),
        (
            "• 浏览："
            f"{labels.get(str(browse.get('status')), browse.get('status') or '暂不可判断')}；"
            f"当前 {_fmt_num(browse.get('current'))}，"
            f"日级基准 {_fmt_num(browse.get('baseline_median'))}，"
            f"比值 {_fmt_num(browse.get('ratio'), 2)}。"
        ),
        (
            "• 一转："
            f"{labels.get(str(first.get('status')), first.get('status') or '暂不可判断')}；"
            f"当前 {_fmt_pct(first.get('current'))}，"
            f"日级基准 {_fmt_pct(first.get('baseline_median'))}。"
        ),
        (
            "• 二转："
            f"{'偏弱' if second.get('is_weak') else labels.get(str(second.get('status')), second.get('status') or '暂不可判断')}；"
            f"当前 {_fmt_pct(second.get('current'))}，"
            f"自身P25 {_fmt_pct(second.get('baseline_p25'))}，"
            "同行30日指数 "
            f"{_fmt_num(second.get('conversion_index_vs_market'), 2)}。"
        ),
        (
            f"• 价格：{len(price.get('high_room_type_ids') or [])} 个房型"
            "高于历史正常价，"
            f"{len(price.get('low_room_type_ids') or [])} 个房型"
            "低于历史正常价。"
        ),
    ]
    diagnosis_labels = {
        "sales_progress_unavailable": "销售进度暂不可判断",
        "sales_on_track_or_ahead": "销售进度正常或偏快",
        "sales_progress_slow": "销售进度偏慢",
        "market_cold_share_not_weak": (
            "主要是市场偏冷，本店份额未明显走弱"
        ),
        "market_share_declining": "本店估算份额下降",
        "traffic_insufficient": "主要问题位于流量不足",
        "entry_attractiveness_weak": "入口吸引力偏弱",
        "detail_page_conversion_weak": "详情页成交承接偏弱",
        "specific_room_prices_high": "部分具体房型价格偏高",
        "no_single_root_cause_confirmed": "现有证据未锁定单一根因",
    }
    diagnoses = [
        diagnosis_labels.get(str(code), str(code))
        for code in analysis.get("diagnosis") or []
    ]
    if diagnoses:
        lines.append("• 综合归因：" + "；".join(diagnoses) + "。")
    action_labels = {
        "no_action": "暂不动作",
        "suggest_enable_ad_slot": "建议开启广告位",
        "suggest_disable_ad_slot": "建议关闭广告位",
        "conservative_inventory_management": "建议保守清库存",
        "investigate_traffic_before_spend": "先排查流量与转化再增加投放",
        "optimize_entry_display": "建议优化列表入口与引流承接",
        "suggest_room_price_reduction": "建议由S5评估具体房型降价",
        "investigate_detail_conversion": "建议排查详情页成交承接",
        "continue_observation": "继续观察",
    }
    for action in analysis.get("actions") or []:
        label = action_labels.get(
            str(action.get("action_type")),
            str(action.get("action_type")),
        )
        targets = action.get("target_room_type_ids") or []
        suffix = (
            f"，房型 {', '.join(map(str, targets))}" if targets else ""
        )
        observe = action.get("observe_minutes")
        if observe:
            suffix += f"，观察 {observe} 分钟"
        lines.append(
            f"• 建议：{label}{suffix}；仅生成建议，不直接执行。"
        )
    lines.append(
        "口径边界：美团经营指标为日级数据，不生成小时浏览/一转/二转"
        "基准；大盘和份额均为估算值并明确标记。"
    )
    return "\n".join(lines)


def _strict_s16_boundary(text: str) -> str:
    replacements = (
        (
            "建议边界  可基于当前节奏、剩余可售、历史 pickup 和数据成熟度给出晚间需求、调价或推广建议；建议不等于自动执行，执行仍需对应能力、护栏和审批流程。",
            "结论边界  S16只判断全店销售进度与房型结构；不分析大盘、份额、浏览、一转、二转和价格，也不生成调价或推广动作。",
        ),
        (
            "本结果只说明销售节奏和结构，不据此直接推断必然满房，也不直接生成调价或推广动作。",
            "结论边界：本结果只判断全店销售进度和房型结构，不分析经营根因，不生成调价或推广动作。",
        ),
    )
    result = str(text)
    for old, new in replacements:
        result = result.replace(old, new)
    if "结论边界" not in result:
        result += (
            "\n结论边界：S16只判断全店销售进度和房型结构，不分析大盘、"
            "份额、流量、转化和价格，不生成动作。"
        )
    return result

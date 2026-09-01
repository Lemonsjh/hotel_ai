from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


BLOCKER_LABELS = {
    "data_not_fresh_for_target": "数据业务日或新鲜度不满足",
    "room_type_transaction_price_reference_missing": "缺少统一房型成交历史价格",
    "baseline_maturity_not_limited_preview": "S15 成熟度不足人工预览",
    "candidate_not_reference_only": "候选状态不适用人工预览",
    "product_not_sellable": "商品不可售",
    "room_type_sales_progress_missing": "缺少房型销售进度",
    "room_type_inventory_scope_invalid": "房型库存范围不足",
    "current_price_invalid": "当前价格无效",
    "room_type_inventory_not_tight_for_raise": "剩余库存未达到涨价条件",
    "market_not_cold_evidence_missing": "大盘热度未达到市场不冷门槛",
    "room_type_inventory_not_loose_for_decrease": "剩余库存未达到降价条件",
    "traffic_not_healthy_for_decrease": "流量未达到降价条件",
    "second_conversion_not_weak": "二转强样本未触发偏弱条件",
    "second_conversion_strong_sample_not_triggered": "二转强样本未触发偏弱条件",
    "second_conversion_data_insufficient": "二转数据不足，暂不将价格作为降价依据",
    "current_price_not_high_vs_room_type_history": "当前价未显著高于房型历史成交价",
    "room_type_sales_progress_within_hold_band": "房型销售进度处于维持区间",
    "exact_hour_grid_evidence_missing": "缺少精确同小时网格证据",
    "global_hour_grid_below_formal_threshold": "全局小时网格覆盖率不足",
    "decision_hour_evidence_missing": "缺少当前决策小时精确样本",
    "decision_hour_maturity_below_formal_threshold": "当前决策小时成熟度不足",
    "decision_hour_evidence_insufficient_for_preview": "当前决策小时证据不足人工预览",
}

IGNORED_BLOCKERS = {
    "price_guard_invalid",
    "no_raise_price_headroom",
    "no_decrease_price_headroom",
}

TIME_EVIDENCE_CODES = {
    "exact_hour_grid_evidence_missing",
    "global_hour_grid_below_formal_threshold",
    "decision_hour_evidence_missing",
    "decision_hour_maturity_below_formal_threshold",
    "decision_hour_evidence_insufficient_for_preview",
}

BLOCKED_REASON_LABELS = {
    "s15_time_evidence_not_formal": "S15 时间证据不足正式调价",
    "strong_pricing_rule_not_satisfied": "强调价条件未同时满足",
    "pricing_rule_not_satisfied": "调价条件未同时满足",
    "data_not_fresh_for_target": "数据业务日或新鲜度不满足",
}

NET_REVENUE_REASON_LABELS = {
    "ota_sale_price_invalid": "商品原卖价无效",
    "commission_rate_missing_or_invalid": "佣金率缺失或无效",
    "activity_summary_source_unavailable": "活动汇总数据不可用",
    "activity_product_detail_source_unavailable": "活动商品明细不可用",
    "activity_product_detail_rows_missing": "活动商品明细缺失",
    "activity_time_context_invalid": "活动有效时间上下文无效",
    "active_activity_factor_unavailable": "有效活动缺少可解析折扣系数",
    "activity_factor_invalid": "活动折扣系数无效",
}

MARKET_LABELS = {
    "cold": "偏冷",
    "normal": "接近历史基线",
    "hot": "高于历史基线",
    "period_not_comparable": "当前时段不可比",
    "unavailable": "暂无",
}

TRAFFIC_LABELS = {
    "healthy": "健康",
    "weak": "偏弱",
    "cold": "偏弱",
    "unavailable": "暂无",
}

FORMAL_MATURITIES = {"temporary", "stable", "strong"}


def _value(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, float):
        return (
            str(int(value))
            if value.is_integer()
            else f"{value:.2f}".rstrip("0").rstrip(".")
        )
    return str(value)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money2(value: Any) -> str:
    number = _decimal(value)
    if number is None:
        return "¥-"
    rounded = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"¥{rounded:,.2f}"


def _factor(value: Any, digits: int = 4) -> str:
    number = _decimal(value)
    if number is None:
        return "-"
    quantum = Decimal("1").scaleb(-digits)
    rounded = number.quantize(quantum, rounding=ROUND_HALF_UP)
    return f"{rounded:.{digits}f}"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def _pp(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if abs(number) < 0.005:
        return "持平"
    return f"{number:+.2f}pp"


def _eligibility_label(value: Any) -> str:
    return {
        "eligible_for_s6_dry_run": "可进入 S6 dry-run",
        "manual_preview_only": "仅人工预览，不进入 S6",
        "preview_only_default_guard": "仅收益参考",
        "preview_only_strong_rule_not_satisfied": "仅收益参考",
        "blocked": "已阻断",
    }.get(str(value or ""), "仅收益参考")


def _coverage(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _time_evidence_line(
    grid: dict[str, Any],
    decision: dict[str, Any],
) -> str:
    if not grid and not decision:
        return (
            "S15 小时证据：confidence=weak（暂无可用精确小时证据）；"
            "仅用于解释证据强度，不决定 S5 涨价、降价或 HOLD。"
        )

    global_coverage = _coverage(grid.get("exact_coverage_ratio"))
    decision_coverage = _coverage(decision.get("exact_coverage_ratio"))
    try:
        decision_count = int(decision.get("exact_sample_count") or 0)
    except (TypeError, ValueError):
        decision_count = 0
    maturity = str(
        decision.get("maturity")
        or grid.get("maturity")
        or ""
    ).strip().lower()

    if global_coverage >= 0.40 and maturity in FORMAL_MATURITIES:
        confidence = "formal"
    elif (
        decision.get("status") == "ok"
        and decision_count >= 3
        and decision_coverage >= 0.40
    ):
        confidence = "limited"
    else:
        confidence = "weak"
    return (
        f"S15 小时证据：confidence={confidence}；"
        "仅用于解释证据强度，不决定 S5 涨价、降价或 HOLD。"
    )


def _compact_product_name(item: dict[str, Any]) -> str:
    product_id = str(item.get("ota_product_id") or "").strip()
    ota_room_type_name = str(item.get("ota_room_type_name") or "").strip()
    room_type_name = str(item.get("room_type_name") or "").strip()
    name = ota_room_type_name or room_type_name or str(item.get("ota_product_name") or "").strip() or product_id or "-"
    # Prefer the platform mapping name.  The canonical/PMS name is only a
    # fallback; package/marketing suffixes are trimmed only from product text.
    compact = name if ota_room_type_name or room_type_name else re.split(r"\s*(?:-|—|–|｜|\||（|【)", name, maxsplit=1)[0].strip()
    compact = compact or name
    return (
        f"{compact}\uff08OTA \u5546\u54c1 ID {product_id}\uff09"
        if product_id
        else compact
    )


def _display_price(item: dict[str, Any]) -> tuple[Any, str]:
    if item.get("limited_evidence_preview"):
        return item.get("manual_preview_price"), "人工预览"
    return (
        item.get("execution_price")
        or item.get("candidate_price")
        or item.get("current_price")
    ), "候选"


def _prices_differ(left: Any, right: Any) -> bool:
    left_value = _decimal(left)
    right_value = _decimal(right)
    return (
        left_value is not None
        and right_value is not None
        and left_value != right_value
    )


def _net_revenue_line(
    item: dict[str, Any],
    *,
    display_price: Any,
) -> str | None:
    channel = str(item.get("channel") or "").strip().lower()
    if channel not in {"meituan", "美团", "mt"}:
        return None

    status = item.get("s5_net_revenue_calculation_status")
    if status != "ok":
        reason = str(
            item.get("s5_net_revenue_calculation_reason")
            or item.get("s5_activity_evidence_reason")
            or "evidence_unavailable"
        )
        label = NET_REVENUE_REASON_LABELS.get(reason, "证据不足")
        return f"- 收益：暂不可计算（{label}）。"

    current_revenue = (
        item.get("estimated_hotel_revenue_exact")
        or item.get("estimated_hotel_revenue")
    )
    proposed_revenue = (
        item.get("proposed_estimated_hotel_revenue_exact")
        or item.get("proposed_estimated_hotel_revenue")
    )
    commission = (
        item.get("commission_rate_exact")
        or item.get("commission_rate")
    )
    combined_factor = (
        item.get("combined_activity_factor_exact")
        or item.get("combined_activity_factor")
    )

    if (
        _prices_differ(item.get("current_price"), display_price)
        and proposed_revenue not in (None, "")
    ):
        revenue_text = (
            f"当前约 {_money2(current_revenue)}/间，"
            f"候选价下约 {_money2(proposed_revenue)}/间"
        )
    else:
        revenue_text = f"预计约 {_money2(current_revenue)}/间"

    details: list[str] = []
    if commission not in (None, ""):
        details.append(f"佣金 {_pct(commission)}")
    if combined_factor not in (None, ""):
        details.append(f"活动综合系数 {_factor(combined_factor)}")
    suffix = f"（{'，'.join(details)}）" if details else ""
    return f"- 收益：{revenue_text}{suffix}。"


def _signal_line(item: dict[str, Any]) -> str:
    market_status = str(item.get("market_status") or "").strip().lower()
    market = MARKET_LABELS.get(
        market_status,
        _value(item.get("market_status")),
    )
    if item.get("market_not_cold") is False and market_status == "cold":
        market = f"{market}，未达市场不冷门槛"

    traffic_status = str(item.get("traffic_status") or "").strip().lower()
    traffic = TRAFFIC_LABELS.get(
        traffic_status,
        _value(item.get("traffic_status")),
    )

    signals = [f"市场 {market}", f"流量 {traffic}"]
    if item.get("second_conversion_weak") is True:
        signals.append("二转偏弱")
    elif item.get("second_conversion_weak_signal") is True:
        signals.append("二转偏弱信号（仅观察）")
    if item.get("price_high") is True:
        signals.append("当前价偏高")
    return "- 判断：" + "；".join(signals) + "。"


def _headline_signal_lines(candidates: list[dict[str, Any]]) -> list[str]:
    """Return the decision signals once, before the product-level evidence."""
    item = candidates[0] if candidates else {}
    traffic_status = str(item.get("traffic_status") or "").strip().lower()
    traffic = TRAFFIC_LABELS.get(traffic_status, _value(item.get("traffic_status")))
    if traffic_status == "healthy":
        traffic_line = "- 流量：健康。"
    elif traffic_status in {"weak", "cold"}:
        traffic_line = "- 流量：偏弱（不满足降价所需的流量健康条件）。"
    else:
        traffic_line = f"- 流量：{traffic or '暂不可判断'}。"

    if item.get("second_conversion_weak") is True:
        conversion_line = "- 二转：偏弱（样本已达到正式判断门槛）。"
    elif item.get("second_conversion_weak_signal") is True:
        conversion_line = "- 二转：存在偏弱信号（样本未达到正式门槛，仅作观察）。"
    elif item.get("second_conversion_sample_valid") is True:
        conversion_line = "- 二转：样本充足，未触发偏弱条件。"
    else:
        conversion_line = "- 二转：样本不足，暂不判断强弱。"
    return [traffic_line, conversion_line]


def _candidate_time_evidence_line(item: dict[str, Any]) -> str | None:
    confidence = str(item.get("s15_time_evidence_confidence") or "").strip()
    if not confidence:
        return None
    return (
        f"- 小时证据：confidence={confidence}；"
        "仅作证据强度标记，不改变本商品业务触发结果。"
    )


def _reason_labels(item: dict[str, Any]) -> list[str]:
    if item.get("strong_pricing_rule_status") == "triggered":
        action = str(item.get("price_action") or item.get("action_type") or "")
        if action in {"increase", "raise_price"}:
            return ["业务涨价条件已触发"]
        if action in {"decrease", "lower_room_price"}:
            return ["业务降价条件已触发"]
        return ["业务调价条件已触发"]

    labels: list[str] = []
    for value in item.get("limited_preview_blockers") or []:
        code = str(value)
        if code in IGNORED_BLOCKERS or code in TIME_EVIDENCE_CODES:
            continue
        label = BLOCKER_LABELS.get(code)
        if label and label not in labels:
            labels.append(label)

    if not labels and item.get("blocked_reason"):
        reason = str(item.get("blocked_reason"))
        if reason not in TIME_EVIDENCE_CODES and reason != "s15_time_evidence_not_formal":
            labels.append(
                BLOCKED_REASON_LABELS.get(
                    reason,
                    "其他正式调价条件未满足",
                )
            )

    if not labels:
        if item.get("limited_evidence_preview"):
            labels.append("当前仅达到人工预览条件")
        elif item.get("reference_only"):
            labels.append("当前仅作收益参考")
        else:
            labels.append("未形成正式调价")
    return labels


def _peer_summary(candidates: list[dict[str, Any]]) -> str | None:
    for item in candidates:
        peer = item.get("peer_price_evidence") or {}
        if not peer:
            continue
        own = peer.get("own_value")
        average = peer.get("peer_average")
        index = peer.get("lead_price_index") or peer.get("peer_index")
        if own in (None, "") and average in (None, ""):
            continue
        try:
            gap = float(peer.get("lead_price_gap_pct"))
        except (TypeError, ValueError):
            try:
                gap = (float(own) - float(average)) / float(average)
            except (TypeError, ValueError, ZeroDivisionError):
                gap = None
        try:
            index_text = f"{float(index):.2f} 倍"
        except (TypeError, ValueError):
            index_text = None
        gap_text = None
        if gap is not None:
            relation = "高于" if gap > 0 else "低于" if gap < 0 else "与同行持平"
            gap_text = (
                "与同行持平"
                if gap == 0
                else f"本店{relation}同行约 {abs(gap) * 100:.1f}%"
            )
        platform = {"meituan": "美团", "ctrip": "携程"}.get(
            str(item.get("channel") or "").lower(), "OTA"
        )
        period = []
        if peer.get("business_date"):
            period.append(f"业务日：{peer['business_date']}")
        if peer.get("snapshot_time"):
            period.append(f"抓取：{peer['snapshot_time']}")
        comparison = "｜".join(
            value
            for value in (
                gap_text,
                index_text,
            )
            if value
        )
        lines = [
            f"- {platform}酒店级引流价（仅作市场背景）：本店 {_money2(own)}｜"
            f"同行均值 {_money2(average)}"
            + (f"｜{comparison}" if comparison else "")
            + "。",
            "  口径：酒店整体最低展示价，不代表具体房型或竞店商品价，不能单独作为调价依据。",
        ]
        if period:
            lines.append(f"  {'｜'.join(period)}。")
        return "\n".join(lines)
    return None


def _quality_scope(flags: Any) -> str | None:
    values = set(str(item) for item in (flags or []))
    labels: list[str] = []
    mapping = (
        (
            "excluded_unsupported_product_type:hour_room",
            "已排除钟点房",
        ),
        (
            "excluded_unsupported_product_type:super_deal",
            "已排除超级团购",
        ),
        (
            "excluded_room_type_no_sellable_inventory",
            "已排除无可售库存房型",
        ),
    )
    for code, label in mapping:
        if code in values:
            labels.append(label)
    if not labels:
        return None
    return "- 数据范围：" + "；".join(labels) + "。"


def render_s5_real_reply(result: dict[str, Any]) -> str:
    grid = result.get("s15_hour_grid_health") or {}
    decision = result.get("s15_decision_hour_evidence") or {}
    candidates = [
        item
        for item in (result.get("candidates") or [])[:5]
        if isinstance(item, dict)
    ]

    lines = [
        "S5 收益候选（真实数据只读）",
        f"目标入住日：{_value(result.get('target_stay_date'))}｜"
        f"计算时点：{_value(result.get('as_of_time'))}",
        f"候选 {result.get('candidate_count') or 0} 个｜"
        f"可进入 S6 dry-run {result.get('eligible_for_s6_count') or 0} 个。",
        "当前经营信号",
        *_headline_signal_lines(candidates),
    ]

    preview_count = result.get("limited_evidence_preview_count") or 0
    if preview_count:
        lines.append(
            f"其中 {preview_count} 个为人工预览，"
            f"单次幅度不超过 "
            f"{_pct(result.get('limited_preview_max_change_pct'))}。"
        )

    if not candidates:
        lines.append(
            f"未形成商品候选：{_value(result.get('blocked_reason'))}。"
        )

    for item in candidates:
        display_price, target_label = _display_price(item)
        lines.extend(
            [
                f"\n{_value(item.get('channel'))}｜"
                f"{_compact_product_name(item)}",
                f"- 价格：当前 {_money2(item.get('current_price'))} → "
                f"{target_label} {_money2(display_price)}"
                f"（{_pct(item.get('actual_change_pct'))}）；"
                f"{_eligibility_label(item.get('eligibility'))}。",
            ]
        )

        revenue_line = _net_revenue_line(
            item,
            display_price=display_price,
        )
        if revenue_line:
            lines.append(revenue_line)

        lines.extend(
            [
                f"- 房型：销售进度 "
                f"{_pp(item.get('sales_progress_delta_pp'))}，"
                f"剩余库存 {_pct(item.get('remaining_room_ratio'))}；"
                f"历史中位 {_money2(item.get('baseline_price_median'))}，"
                f"P20 {_money2(item.get('baseline_price_p20'))}。",
                _signal_line(item),
            ]
        )
        time_line = _candidate_time_evidence_line(item)
        if time_line:
            lines.append(time_line)
        lines.append("- 原因：" + "；".join(_reason_labels(item)) + "。")

    lines.append("\n边界")
    ready_confirmations = [
        item for item in candidates
        if isinstance(item, dict) and item.get("s6_confirmation_command")
    ]
    if ready_confirmations:
        lines.append("- 可直接执行：以下建议已生成确认令牌；确认后由 S6 二次校验并写入调价任务。")
        for item in ready_confirmations:
            lines.append(
                f"  - {_compact_product_name(item)}：回复「{item['s6_confirmation_command']}」"
                f"（有效至 {item.get('s6_confirmation_expires_at') or '-'}）。"
            )
    peer_line = _peer_summary(candidates)
    if peer_line:
        lines.append(peer_line)

    scope_line = _quality_scope(result.get("quality_flags"))
    if scope_line:
        lines.append(scope_line)

    lines.extend(
        [
            "- 价格基准：统一房型成交历史价格；"
            "不要求同一 OTA 商品连续历史价格。",
            "- 证据说明：" + _time_evidence_line(grid, decision),
            "- 收益口径：商品原卖价 ×（1−佣金率）"
            "× 全部有效活动系数连乘；不含用户券，仅供运营查看，"
            "不参与调价写入或审批。",
            "- S5 业务触发由销售进度、库存、市场、流量、二转和价格条件决定；"
            "S15 精确小时网格和当前决策小时样本只标记证据置信度，"
            "不作为 S5 涨价、降价或 HOLD 的硬门槛。",
            "- S5 只生成调价建议，不创建审批、不写调价任务、不执行渠道调价；"
            "已触发的涨/降价建议交给 S6 做执行安全重校验。",
        ]
    )
    return "\n".join(lines)

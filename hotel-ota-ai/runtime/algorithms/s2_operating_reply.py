from __future__ import annotations

from typing import Any


def _value(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def _platform_name(platform: str) -> str:
    return {"meituan": "美团", "ctrip": "携程"}.get(platform, platform)


def _empty_view_line(label: str, view: dict[str, Any]) -> str:
    if view.get("status") == "no_records":
        return f"- {label}：来源已查询，当前范围无记录。"
    flags = "；".join(map(str, view.get("quality_flags") or [])) or "来源不可用"
    return f"- {label}：未形成可用结果（{flags}）。"


def _pct(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except (TypeError, ValueError):
        return "-"


def _short_business_date(value: Any) -> str:
    text = str(value or "")[:10]
    try:
        _, month, day = text.split("-", 2)
        return f"{int(month)}/{int(day)}"
    except (TypeError, ValueError):
        return ""


def render_s2_operating_reply(views: dict[str, Any]) -> str:
    """Render six evidence panels without diagnostic or action language."""
    core = views.get("core_operating") or {}
    room_types = (views.get("room_type_status") or {}).get("items") or []
    flow = views.get("flow_conversion") or {}
    market = views.get("market_competition") or {}
    price = views.get("price_and_lead") or {}
    promotion = views.get("promotion_activity") or {}
    lines = [
        "S2 经营运行快照（真实数据只读）",
        f"数据状态：{_value(core.get('status'))}｜入住营业日 {_value(core.get('business_date'))}｜PMS 快照 {_value(core.get('snapshot_time'))}",
        "\n一、经营总览（PMS）",
        f"- 总房 {_value(core.get('total_rooms'))}，可售 {_value(core.get('available_rooms'))}，基础承诺已售 {_value(core.get('base_committed_sold_rooms'))}，超售 {_value(core.get('overbooking_rooms'))}，承诺已售 {_value(core.get('committed_sold_rooms'))}。",
        f"- 承诺出租率 {_pct(core.get('committed_occupancy_rate'))}；物理在住 {_value(core.get('physical_occupied_rooms'))}，物理入住率 {_pct(core.get('physical_occupancy_rate'))}。",
        f"- PMS 快照房费收入 ¥{_value(core.get('room_revenue'))}，ADR ¥{_value(core.get('adr'))}，RevPAR ¥{_value(core.get('revpar'))}。",
        "\n二、房型房态（同一 PMS 快照；承诺已售/总房）",
    ]
    for item in room_types[:4]:
        lines.append(
            f"- {_value(item.get('room_type_name') or item.get('room_type_id'))}："
            f"承诺已售 {_value(item.get('committed_sold_rooms'))}/{_value(item.get('total_rooms'))}，"
            f"可售 {_value(item.get('available_rooms'))}，超售 {_value(item.get('overbooking_rooms'))}，"
            f"物理在住 {_value(item.get('physical_occupied_rooms'))}。"
        )
    if len(room_types) > 4:
        lines.append(f"- 其余 {len(room_types) - 4} 个房型未在本卡片展开。")

    flow_date = flow.get("business_date")
    if not flow_date and flow.get("platforms"):
        flow_date = next(
            (
                item.get("business_date")
                for item in flow["platforms"].values()
                if isinstance(item, dict) and item.get("business_date")
            ),
            None,
        )
    flow_date_label = _short_business_date(flow_date)
    flow_heading = (
        f"\n三、流量转化（{flow_date_label} 今日数据）"
        if flow_date_label
        else "\n三、流量转化（今日数据）"
    )
    lines.append(flow_heading)
    if flow.get("platforms"):
        for platform, item in flow["platforms"].items():
            metrics = item.get("metrics") or []
            sample = "；".join(
                f"{_value(metric.get('metric_name') or metric.get('metric_code'))}={_value(metric.get('metric_value'))} {_value(metric.get('metric_unit'))}"
                for metric in metrics
            ) or "无可展示指标"
            flags = item.get("quality_flags") or []
            suffix = f"；质量标记 {'、'.join(map(str, flags))}" if flags else ""
            lines.append(
                f"- {_platform_name(platform)}：{_value(item.get('metric_count'))} 条指标，"
                f"业务日 {_value(item.get('business_date'))}，抓取 {_value(item.get('snapshot_time'))}；{sample}{suffix}。"
            )
    elif flow.get("status") == "no_records":
        lines.append(
            f"- 美团：{_value(flow.get('business_date'))} 当日未查询到流量转化记录；"
            "未使用其他业务日数据。"
        )
    else:
        lines.append(_empty_view_line("流量转化", flow))

    lines.append("\n四、市场竞态（仅同行可比指标与月度流失背景）")
    if market.get("platforms"):
        for platform, item in market["platforms"].items():
            if item.get("status") != "ok":
                lines.append(_empty_view_line(f"{_platform_name(platform)}市场竞态", item))
                continue
            loss = item.get("loss_context") or {}
            lines.append(
                f"- {_platform_name(platform)}：同行可比指标 {len(item.get('peer_aggregate') or [])} 项；"
                f"月度流失订单 {_value(loss.get('loss_order_count'))}，竞争圈 {len(item.get('competition_circles') or [])} 个；"
                f"流失窗口 {_value(loss.get('period_start_date'))} 至 {_value(loss.get('period_end_date'))}，"
                f"抓取 {_value(loss.get('snapshot_time'))}。"
            )
    else:
        lines.append(_empty_view_line("市场竞态", market))

    lines.append("\n五、价格与引流（本店商品与酒店级同行可比指标）")
    if price.get("platforms"):
        for platform, item in price["platforms"].items():
            products = item.get("products") or []
            lead = item.get("lead_price") or {}
            sellable = sum(1 for product in products if product.get("product_state") == "sellable")
            lead_text = (
                f"引流指标 {_value(lead.get('own_value'))} / 同行均值 {_value(lead.get('peer_average'))}，"
                f"价格指数 {_value(lead.get('lead_price_index'))}，差 {_pct(lead.get('lead_price_gap_pct'))}，"
                f"排名 {_value(lead.get('rank_position'))}/{_value(lead.get('peer_count'))}"
                if lead else f"引流指标未形成可用结果（{'；'.join(map(str, item.get('quality_flags') or [])) or 'source_missing'}）"
            )
            lines.append(
                f"- {_platform_name(platform)}：自有商品 {len(products)} 个、可售 {sellable} 个；"
                f"{lead_text}。"
            )
    else:
        lines.append(_empty_view_line("价格与引流", price))

    lines.append("\n六、推广活动状态（仅本店）")
    if promotion.get("platforms"):
        for platform, item in promotion["platforms"].items():
            product_count = _value(item.get("activity_product_count"))
            if item.get("activity_product_count_is_lower_bound"):
                product_count = f"至少 {product_count}"
            lines.append(
                f"- {_platform_name(platform)}：活动 {_value(item.get('activity_count'))} 个，活动商品 {product_count} 个，"
                f"已映射房型 {_value(item.get('canonical_room_type_count'))} 个，待映射 {_value(item.get('mapping_missing_count'))} 行；"
                f"状态 {_value('、'.join(item.get('activity_statuses') or []))}，抓取 {_value(item.get('snapshot_time'))}。"
            )
    else:
        lines.append(_empty_view_line("推广活动", promotion))

    flags = views.get("quality_flags") or []
    lines.extend(
        [
            "\n数据质量与边界",
            f"- {'；'.join(map(str, flags)) if flags else '无额外质量标记。'}",
            "- S2 只描述当前运行事实，不判断根因、不生成收益或渠道动作；S14/S5/S6/S8/S13 分别处理诊断、候选或任务。",
        ]
    )
    return "\n".join(lines)

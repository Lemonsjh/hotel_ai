from __future__ import annotations

from collections import defaultdict
from typing import Any


def _display(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def _window(item: dict[str, Any]) -> str:
    if item.get("period_start_date") or item.get("period_end_date"):
        return f"窗口 {_display(item.get('period_start_date'))} 至 {_display(item.get('period_end_date'))}"
    return f"业务日 {_display(item.get('business_date'))}"


def _peer_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- 同行聚合：来源无可用指标。"]
    lines = ["- 同行聚合（仅酒店级/指标级比较，不代表房型竞品价）："]
    for item in items[:3]:
        metric_name = _display(item.get("metric_name") or item.get("metric_code"))
        metric_code = _display(item.get("metric_code"))
        metric_label = metric_name if metric_name == metric_code else f"{metric_name}（{metric_code}）"
        rank = ""
        if item.get("rank_position") is not None:
            rank = f"；来源排名 {_display(item.get('rank_position'))}/{_display(item.get('peer_count'))}"
        lines.append(
            f"  - {metric_label}：本店 {_display(item.get('own_value'))}，"
            f"同行均值 {_display(item.get('peer_average'))}，单位 {_display(item.get('metric_unit'))}；{_window(item)}{rank}"
        )
    snapshots = [item.get("snapshot_time") for item in items if item.get("snapshot_time")]
    if snapshots:
        lines.append(f"  - 同行指标抓取时间：{_display(max(snapshots, key=str))}")
    if len(items) > 3:
        lines.append(f"  - 其余 {len(items) - 3} 条同行指标未在本卡片展开。")
    return lines


def _product_lines(items: list[dict[str, Any]]) -> list[str]:
    sellable = sum(1 for item in items if item.get("product_state") == "sellable")
    lines = [f"- 自有商品（仅本店）：共 {len(items)} 个，其中可售 {sellable} 个；价格为来源观察业务日，并非竞品目标入住日。"]
    for item in items[:3]:
        lines.append(
            f"  - {_display(item.get('ota_product_name') or item.get('ota_product_id'))}：¥{_display(item.get('price'))}，"
            f"状态 {_display(item.get('product_state'))}，业务日 {_display(item.get('price_business_date'))}"
        )
    if len(items) > 3:
        lines.append(f"  - 其余 {len(items) - 3} 个商品未在本卡片展开。")
    return lines


def _ranking_lines(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return []
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        grouped[str(item.get("ranking_type") or "").strip().lower()].append(item)
    for group in grouped.values():
        group.sort(key=lambda item: item.get("rank_position") if item.get("rank_position") is not None else float("inf"))

    def values(group: list[dict[str, Any]], limit: int = 5) -> str:
        entries = []
        for item in group[:limit]:
            name = _display(item.get("rank_item_name"))
            value = _display(item.get("rank_item_value"))
            entries.append(name if value == "-" else f"{name} {value}")
        return "、".join(entries)

    lines: list[str] = []
    display_groups = (
        ("positive_impression", "好评印象", "来源 Top"),
        ("peer_score", "竞争圈酒店评分排名", "美团来源榜单"),
    )
    for key, title, qualifier in display_groups:
        group = grouped.pop(key, [])
        if not group:
            continue
        if key == "peer_score":
            lines.append(f"- {title}（{qualifier}）：")
            for item in group[:5]:
                prefix = f"{_display(item.get('rank_position'))}. " if item.get("rank_position") is not None else ""
                lines.append(f"  - {prefix}{_display(item.get('rank_item_name'))}：{_display(item.get('rank_item_value'))}")
        else:
            lines.append(f"- {title}（{qualifier}）：{values(group)}。")
        if len(group) > 5:
            lines.append(f"  - 其余 {len(group) - 5} 条未在本卡片展开。")
    return lines


def _loss_lines(item: dict[str, Any] | None) -> list[str]:
    if not item:
        return ["- 月度流失背景：来源缺失或无记录，未形成流失结论。"]
    return [
        f"- 月度流失背景（非实时商品比价；窗口 {_display(item.get('period_start_date'))} 至 {_display(item.get('period_end_date'))}）："
        f"流失订单 {_display(item.get('loss_order_count'))}，竞店 {_display(item.get('competitor_count'))} 家，"
        f"最低价范围 {_display(item.get('competitor_lowest_price_range'))}。"
    ]


def _circle_lines(context: dict[str, Any] | None) -> list[str]:
    circles = (context or {}).get("circles") or []
    if not circles:
        return []
    lines = ["- 美团竞争圈与订单流失（月度流失背景，非实时竞品商品价）："]
    for item in circles[:2]:
        price_range = item.get("competitor_lowest_price_range") or ["-", "-"]
        lines.append(
            f"  - {_display(item.get('competition_circle_name'))}：竞店 {_display(item.get('competitor_count'))} 家，"
            f"流失订单 {_display(item.get('loss_order_count'))}，流失金额 ¥{_display(item.get('loss_order_amount'))}，"
            f"竞店最低价 {_display(price_range[0])}–{_display(price_range[-1])}；"
            f"窗口 {_display(item.get('period_start_date'))} 至 {_display(item.get('period_end_date'))}"
        )
    if len(circles) > 2:
        lines.append(f"  - 其余 {len(circles) - 2} 个竞争圈未在本卡片展开。")
    return lines


def render_s7_competition_reply(context: dict[str, Any]) -> str:
    """Render the fixed, evidence-only Feishu reply template for S7."""
    lines = [
        "S7 竞态监控｜真实数据只读",
        f"数据状态：{_display(context.get('status'))}｜业务日 {_display(context.get('data_business_date'))}｜抓取 {_display(context.get('data_snapshot_time'))}",
        "\n一、结论边界",
        "- 仅按标注的可比等级展示事实；没有精确竞品商品记录时，不输出房型竞品价差。",
        "- 同行聚合只表达酒店级或同指标相对位置；来源排名保留原始方向，不推断排名优劣。",
    ]
    for platform, item in (context.get("platforms") or {}).items():
        name = {"meituan": "美团", "ctrip": "携程"}.get(platform, platform)
        lines.append(f"\n二、{name}")
        lines.extend(_peer_lines(item.get("peer_aggregate") or []))
        lines.extend(_product_lines(item.get("own_products") or []))
        activity = item.get("activity_context") or {}
        if activity.get("activity_count") or activity.get("activity_product_count"):
            lines.append(
                f"- 活动/权益（仅本店）：活动 {_display(activity.get('activity_count') or 0)} 个，"
                f"商品 {_display(activity.get('activity_product_count') or 0)} 个，"
                f"已映射统一房型 {_display(activity.get('canonical_room_type_count') or 0)} 个，待映射 {_display(activity.get('mapping_missing_count') or 0)} 行。"
            )
        lines.extend(_ranking_lines(item.get("review_rankings") or []))
        lines.extend(_loss_lines(item.get("loss_context")))
        if platform == "meituan":
            lines.extend(_circle_lines(item.get("competition_circle_context")))
    flags = context.get("quality_flags") or []
    lines.extend(["\n三、数据质量与行动限制", f"- 数据质量：{'；'.join(map(str, flags)) if flags else '无额外标记。'}", "- 本次不创建调价或推广任务；S7 仅可作为后续收益评估的证据输入。"])
    return "\n".join(lines)

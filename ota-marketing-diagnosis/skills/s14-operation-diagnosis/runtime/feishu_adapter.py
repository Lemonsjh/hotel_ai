from __future__ import annotations

from typing import Any

from marketing_diagnosis.channel_score_totals import ctrip_direct_total, meituan_direct_total


STATUS_TEXT = {
    "success": "已形成结果",
    "zero": "真实为0",
    "missing": "数据未取到",
    "error": "查询失败",
    "pending_rule": "规则待确认",
    "manual_pending": "待人工录入",
}


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(str(value).replace(",", "").rstrip("%"))
        return None if number != number else number
    except (TypeError, ValueError):
        return None


def _fmt_num(value: Any, digits: int = 1, missing: str = "暂无数据") -> str:
    number = _num(value)
    if number is None:
        return missing
    return f"{number:,.{digits}f}"


def _fmt_count(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "暂无数据"
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.2f}"


def _money(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "暂无数据"
    return f"¥{number:,.2f}"


def _pct(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "暂无数据"
    if abs(number) <= 1:
        number *= 100
    return f"{number:.2f}%"


def _platform_zh(value: Any) -> str:
    text = str(value or "multi").lower()
    return {
        "multi": "多渠道",
        "meituan": "美团",
        "ctrip": "携程",
        "fliggy": "飞猪",
    }.get(text, _text(value) or "多渠道")


def _source_zh(value: Any) -> str:
    text = str(value or "").lower()
    if "excel" in text:
        return "Excel"
    if "mysql" in text or "database" in text or "数据库" in text:
        return "数据库"
    return _text(value) or "未标注"


def _hotel_label(result: dict[str, Any]) -> str:
    hotel_id = result.get("hotel_id") or "puyue"
    hotel_name = result.get("hotel_name") or ("璞悦" if hotel_id == "puyue" else hotel_id)
    return f"{hotel_name}（{hotel_id}）"


def _period_label(result: dict[str, Any]) -> str:
    start = result.get("period_start") or "未标注"
    end = result.get("period_end") or "未标注"
    return f"{start} 至 {end}"


def _visual(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("visual_diagnosis")
    return value if isinstance(value, dict) else {}


def _items(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _visual(result).get("items") or []
    return [row for row in rows if isinstance(row, dict)]


def _item_map(result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    output: dict[int, dict[str, Any]] = {}
    for item in _items(result):
        try:
            output[int(item.get("standard_item_id") or 0)] = item
        except (TypeError, ValueError):
            continue
    return output


def _base_label(value: Any) -> str:
    text = str(value or "").strip()
    return text.split("（取值日：", 1)[0].strip()


def _field_value(item: dict[str, Any], *aliases: str) -> Any:
    expected = {str(alias).strip().lower() for alias in aliases}
    for field in item.get("fields") or []:
        label = _base_label(field.get("label")).lower()
        if label in expected:
            return field.get("value")
    return None


def _score_text(item: dict[str, Any]) -> str:
    if not item.get("participates_in_score"):
        return "仅展示"
    score = _num(item.get("item_score"))
    base = _num(item.get("base_score")) or 0
    score_text = "待计算" if score is None else f"{score:g}"
    return f"{score_text}/{base:g}"


def _status_text(item: dict[str, Any]) -> str:
    status = str(item.get("data_status") or "missing")
    return STATUS_TEXT.get(status, status)


def _overview_lines(result: dict[str, Any]) -> list[str]:
    meituan_total = meituan_direct_total(result)
    lines = [f"- 总得分：{meituan_total:g}/100"]

    ctrip = result.get("ctrip_summary")
    if isinstance(ctrip, dict) and int(_num(ctrip.get("connected_items")) or 0) > 0:
        total = ctrip_direct_total(result)
        connected = int(_num(ctrip.get("connected_items")) or 0)
        scored = int(_num(ctrip.get("scored_items")) or 0)
        total_text = "待计算" if total is None else f"{total:g}"
        lines.append(
            f"- 携程得分：{total_text}/100｜已接入 {connected} 项｜已计分 {scored} 项"
        )
    return lines


def _room_type_line(item: dict[str, Any]) -> str:
    active = _field_value(item, "全部在售房型数", "在售房型数", "房型数")
    low = _field_value(item, "低效房型数")
    ratio = _field_value(item, "低效房型占比")
    return (
        f"- 02 低效房型：在售 {_fmt_count(active)}｜低效 {_fmt_count(low)}｜"
        f"占比 {_pct(ratio)}｜得分 {_score_text(item)}"
    )


def _flow_line(item: dict[str, Any]) -> str:
    exposure = _field_value(item, "曝光人数")
    views = _field_value(item, "浏览人数")
    orders = _field_value(item, "支付订单数")
    payment_rate = _field_value(item, "浏览-支付转化率")
    return (
        f"- 04 流量：曝光 {_fmt_count(exposure)}｜浏览 {_fmt_count(views)}｜"
        f"支付订单 {_fmt_count(orders)}｜二转 {_pct(payment_rate)}｜得分 {_score_text(item)}"
    )


def _promotion_line(item: dict[str, Any]) -> str:
    status = _field_value(item, "推广状态")
    spend = _field_value(item, "近30天推广投入")
    booking = _field_value(item, "预订订单金额（元）")
    roi = _field_value(item, "ROI")
    return (
        f"- 09 推广：状态 {_text(status) or '暂无数据'}｜投入 {_money(spend)}｜"
        f"预订订单金额 {_money(booking)}｜ROI {_fmt_num(roi, 2)}｜得分 {_score_text(item)}"
    )


def _reputation_line(item: dict[str, Any]) -> str:
    rating = _field_value(item, "美团评分", "meituan评分")
    review_count = _field_value(item, "美团点评条数", "meituan点评条数")
    yesterday = _field_value(item, "昨日新增点评数")
    unreplied = _field_value(item, "美团未回复点评数", "meituan未回复点评数")
    return (
        f"- 13 口碑：美团评分 {_fmt_num(rating, 2)}｜点评 {_fmt_count(review_count)}｜"
        f"昨日新增 {_fmt_count(yesterday)}｜未回复 {_fmt_count(unreplied)}｜得分 {_score_text(item)}"
    )


def _report_metric_lines(result: dict[str, Any]) -> list[str]:
    items = _item_map(result)
    lines: list[str] = []
    if 2 in items:
        lines.append(_room_type_line(items[2]))
    if 4 in items:
        lines.append(_flow_line(items[4]))
    if 9 in items:
        lines.append(_promotion_line(items[9]))
    if 13 in items:
        lines.append(_reputation_line(items[13]))
    return lines or ["- 报告暂无可展示的核心诊断数据。"]


def _attention_lines(result: dict[str, Any], limit: int = 5) -> list[str]:
    candidates = [
        item
        for item in _items(result)
        if item.get("participates_in_score")
    ]

    def order_key(item: dict[str, Any]) -> tuple[float, int]:
        ratio = _num(item.get("score_ratio"))
        try:
            number = int(item.get("standard_item_id") or 0)
        except (TypeError, ValueError):
            number = 0
        return (ratio if ratio is not None else -1.0, number)

    lines: list[str] = []
    for item in sorted(candidates, key=order_key)[:limit]:
        try:
            number = int(item.get("standard_item_id") or 0)
        except (TypeError, ValueError):
            number = 0
        lines.append(
            f"- {number:02d} {item.get('item_name') or '未命名项目'}："
            f"{_score_text(item)}｜{_status_text(item)}"
        )
    return lines or ["- 暂无评分项目。"]


def build_feishu_reply(result: dict[str, Any]) -> str:
    report_url = _text(result.get("report_url", ""))
    lines = [
        f"🎯 S14 OTA营销诊断报告 — {_hotel_label(result)}",
        (
            f"来源：{_source_zh(result.get('data_source'))}｜"
            f"渠道：{_platform_zh(result.get('platform'))}｜"
            f"周期：{_period_label(result)}"
        ),
        "",
        "📊 报告概览：",
        *_overview_lines(result),
        "",
        "📌 报告核心数据：",
        *_report_metric_lines(result),
        "",
        "⚠️ 重点关注（与报告评分一致）：",
        *_attention_lines(result),
        "",
        f"📄 完整报告：{report_url}" if report_url else "📄 完整报告：未生成公开链接",
    ]
    return "\n".join(lines)


def build_feishu_card_reply(result: dict[str, Any]) -> dict[str, Any]:
    report_url = _text(result.get("report_url", ""))
    overview = "\n".join(_overview_lines(result))
    metrics = "\n".join(_report_metric_lines(result))
    attention = "\n".join(_attention_lines(result))
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**酒店：** {_hotel_label(result)}\n"
                    f"**来源：** {_source_zh(result.get('data_source'))}\n"
                    f"**渠道：** {_platform_zh(result.get('platform'))}\n"
                    f"**周期：** {_period_label(result)}"
                ),
            },
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**报告概览**\n{overview}"},
        },
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**报告核心数据**\n{metrics}"},
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**重点关注（与报告评分一致）**\n{attention}",
            },
        },
    ]
    if report_url:
        elements.append(
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打开 HTML 报告"},
                        "type": "primary",
                        "url": report_url,
                    }
                ],
            }
        )
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": "S14 OTA营销诊断报告",
                },
            },
            "elements": elements,
        },
    }


__all__ = [
    "build_feishu_card_reply",
    "build_feishu_reply",
]

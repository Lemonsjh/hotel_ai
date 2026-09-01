from __future__ import annotations

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


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "是", "有", "团购", "钟点", "hour", "group"}


def _room_type(row: dict[str, Any]) -> str:
    value = row.get("room_type_name") or row.get("room_type") or row.get("房型") or row.get("room_name")
    if value:
        return str(value).strip()
    product = str(row.get("product_name") or "").strip()
    return product[:30] if product else "未标注房型"


def _platform(row: dict[str, Any]) -> str:
    return str(row.get("platform") or "unknown").strip() or "unknown"


def _price(row: dict[str, Any]) -> float | None:
    return _num(row.get("final_price")) or _num(row.get("activity_price")) or _num(row.get("listed_price"))


def _exposure(row: dict[str, Any]) -> float | None:
    return _num(row.get("effective_exposure")) or _num(row.get("exposure")) or _num(row.get("exposure_people"))


def _add_num(bucket: dict[str, Any], key: str, value: Any) -> None:
    number = _num(value)
    if number is not None:
        bucket[key] = bucket.get(key, 0.0) + number


def _score_role(item: dict[str, Any]) -> tuple[str, str]:
    order_share = _num(item.get("order_share")) or 0
    revenue_share = _num(item.get("revenue_share")) or 0
    conversion = _num(item.get("payment_conversion_rate"))
    min_price = _num(item.get("min_price"))
    avg_price = _num(item.get("avg_price"))
    price_span = _num(item.get("price_span"))
    orders = _num(item.get("paid_orders")) or 0
    views = _num(item.get("views")) or 0

    if order_share >= 0.3 or revenue_share >= 0.3:
        return "主力房型", "订单或收入贡献较高，重点保障库存、价格稳定和页面卖点。"
    if views >= 100 and (conversion is not None and conversion < 0.04):
        return "高浏览低转化", "浏览不低但支付转化偏弱，优先检查价格、图片、权益、退改和评价露出。"
    if orders == 0 and views > 0:
        return "有浏览无成交", "存在承接断点，建议复核房型展示、价格梯度和库存可售状态。"
    if price_span is not None and price_span >= 120:
        return "价格跨度大", "同房型价格跨度较大，需检查团购、钟点房、活动价和全日房是否互相冲突。"
    if min_price is not None and avg_price is not None and min_price < avg_price * 0.75:
        return "引流价突出", "低价入口明显，需确认是否带来有效订单而不是只拉低价格感知。"
    if item.get("product_count") and not item.get("paid_orders"):
        return "待补销售", "已有商品价格信息，但缺少房型级销售数据。"
    return "观察房型", "建议持续观察销售、单价、转化和竞对价差。"


def _summarize_rows(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["当前缺少房型级商品或销售数据，暂不能判断具体房型表现。"]
    main = [x for x in items if x.get("role") == "主力房型"]
    low_conversion = [x for x in items if x.get("role") in {"高浏览低转化", "有浏览无成交"}]
    wide = [x for x in items if x.get("role") == "价格跨度大"]
    notes: list[str] = []
    if main:
        notes.append("主力房型：" + "、".join(x.get("room_type_name") or "未标注" for x in main[:3]) + "，建议优先保障库存和价格稳定。")
    if low_conversion:
        notes.append("转化承接偏弱房型：" + "、".join(x.get("room_type_name") or "未标注" for x in low_conversion[:3]) + "，建议先查首图、权益、评论和价格承接。")
    if wide:
        notes.append("价格跨度较大房型：" + "、".join(x.get("room_type_name") or "未标注" for x in wide[:3]) + "，建议复核活动价、团购价、钟点房价和全日房价。")
    if not notes:
        notes.append("当前房型价格和销售未触发明显异常，建议继续补齐房型级订单、间夜和收入数据。")
    return notes


def build_room_type_metrics(sections: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    products = sections.get("products") or []
    funnel = sections.get("ota_funnel") or []
    competitors = sections.get("competitors") or []
    promotion_products = sections.get("promotion_products") or []

    buckets: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {
        "platform": None,
        "room_type_name": None,
        "product_count": 0,
        "product_names": set(),
        "prices": [],
        "listed_prices": [],
        "group_buy_count": 0,
        "hour_room_count": 0,
        "activity_product_count": 0,
        "exposure": 0.0,
        "views": 0.0,
        "paid_orders": 0.0,
        "sales_revenue": 0.0,
        "sold_room_nights": 0.0,
        "competitor_prices": [],
    })

    for row in products:
        platform, room = _platform(row), _room_type(row)
        key = (platform, room)
        item = buckets[key]
        item["platform"] = platform
        item["room_type_name"] = room
        item["product_count"] += 1
        if row.get("product_name"):
            item["product_names"].add(str(row.get("product_name")))
        price = _price(row)
        listed = _num(row.get("listed_price"))
        if price is not None:
            item["prices"].append(price)
        if listed is not None:
            item["listed_prices"].append(listed)
        if _as_bool(row.get("is_group_buy") or row.get("group_buy")):
            item["group_buy_count"] += 1
        if _as_bool(row.get("is_hour_room") or row.get("hour_room")):
            item["hour_room_count"] += 1

    for row in promotion_products:
        platform, room = _platform(row), _room_type(row)
        item = buckets[(platform, room)]
        item["platform"] = platform
        item["room_type_name"] = room
        item["activity_product_count"] += 1

    for row in funnel:
        room = _room_type(row)
        if room == "未标注房型":
            continue
        platform = _platform(row)
        item = buckets[(platform, room)]
        item["platform"] = platform
        item["room_type_name"] = room
        _add_num(item, "exposure", _exposure(row))
        _add_num(item, "views", _num(row.get("views")) or _num(row.get("visitors")))
        _add_num(item, "paid_orders", row.get("paid_orders"))
        _add_num(item, "sales_revenue", row.get("sales_revenue"))
        _add_num(item, "sold_room_nights", row.get("sold_room_nights"))

    for row in competitors:
        room = _room_type(row)
        if room == "未标注房型":
            continue
        platform = _platform(row)
        item = buckets[(platform, room)]
        item["platform"] = platform
        item["room_type_name"] = room
        price = _num(row.get("price"))
        if price is not None:
            item["competitor_prices"].append(price)

    rows: list[dict[str, Any]] = []
    total_orders = sum(_num(x.get("paid_orders")) or 0 for x in buckets.values())
    total_revenue = sum(_num(x.get("sales_revenue")) or 0 for x in buckets.values())
    total_views = sum(_num(x.get("views")) or 0 for x in buckets.values())

    for item in buckets.values():
        prices = item.pop("prices")
        listed_prices = item.pop("listed_prices")
        competitor_prices = item.pop("competitor_prices")
        product_names = sorted(item.pop("product_names"))[:5]
        min_price = min(prices) if prices else None
        max_price = max(prices) if prices else None
        avg_price = sum(prices) / len(prices) if prices else None
        listed_avg = sum(listed_prices) / len(listed_prices) if listed_prices else None
        competitor_avg = sum(competitor_prices) / len(competitor_prices) if competitor_prices else None
        item.update({
            "product_names": product_names,
            "min_price": _round(min_price),
            "max_price": _round(max_price),
            "avg_price": _round(avg_price),
            "listed_avg_price": _round(listed_avg),
            "price_span": _round(max_price - min_price) if min_price is not None and max_price is not None else None,
            "competitor_avg_price": _round(competitor_avg),
            "own_vs_competitor_gap": _round(min_price - competitor_avg) if min_price is not None and competitor_avg is not None else None,
            "payment_conversion_rate": _round(_safe_div(_num(item.get("paid_orders")), _num(item.get("views"))), 4),
            "exposure_to_view_rate": _round(_safe_div(_num(item.get("views")), _num(item.get("exposure"))), 4),
            "avg_order_value": _round(_safe_div(_num(item.get("sales_revenue")), _num(item.get("paid_orders")))),
            "sales_adr": _round(_safe_div(_num(item.get("sales_revenue")), _num(item.get("sold_room_nights")))),
            "order_share": _round(_safe_div(_num(item.get("paid_orders")), total_orders), 4),
            "revenue_share": _round(_safe_div(_num(item.get("sales_revenue")), total_revenue), 4),
            "view_share": _round(_safe_div(_num(item.get("views")), total_views), 4),
        })
        role, suggestion = _score_role(item)
        item["role"] = role
        item["suggestion"] = suggestion
        rows.append(dict(item))

    rows.sort(key=lambda x: (_num(x.get("sales_revenue")) or 0, _num(x.get("paid_orders")) or 0, _num(x.get("product_count")) or 0), reverse=True)
    has_sales = any((_num(x.get("paid_orders")) or 0) > 0 or (_num(x.get("sales_revenue")) or 0) > 0 for x in rows)
    return {
        "status": "ok" if rows else "data_gap",
        "room_type_count": len(rows),
        "has_room_type_sales": has_sales,
        "items": rows,
        "summary": _summarize_rows(rows),
        "missing_note": "已读取房型级销售数据。" if has_sales else "当前主要来自商品价格/活动/竞品，缺少房型级订单、间夜或收入时，销售贡献只能作为待补数据。",
    }

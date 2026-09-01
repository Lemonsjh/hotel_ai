from __future__ import annotations

import datetime as dt
import math
from typing import Any

SECTIONS = [
    "hotel_daily",
    "hotel_monthly",
    "hotel_performance_daily",
    "room_type_performance_daily",
    "ota_funnel",
    "products",
    "promotions",
    "promotion_products",
    "reviews",
    "review_overviews",
    "review_rankings",
    "nearby_events",
    "competitors",
    # S14 可视化规则手册专用数据集。保留数据库原字段，由
    # visual_diagnosis.py 统一计算，避免把“缺失”误判成真实 0。
    "exposure_daily",
    "user_source_monthly",
    "promotion_finance",
    "promotion_revenue",
    "order_loss_monthly",
    "joined_rights",
    "promotion_status",
    "video_upload_status",
    "scan_orders",
]

OPTIONAL_SECTIONS = {
    "hotel_monthly", "hotel_performance_daily", "room_type_performance_daily", "promotions", "promotion_products", "review_overviews",
    "review_rankings", "nearby_events", "competitors", "exposure_daily",
    "user_source_monthly", "promotion_finance", "promotion_revenue",
    "order_loss_monthly", "joined_rights", "promotion_status",
    "video_upload_status",
    "scan_orders",
}

SHEET_NAMES = {
    "hotel_daily": {"hotel_daily", "daily", "酒店日报", "每日经营", "经营日报", "jy01", "rs01", "jy01_hotel_statistics_daily", "rs01_room_revenue_daily"},
    "hotel_monthly": {"hotel_monthly", "monthly", "月度经营", "jy03", "jy03_hotel_statistics_month"},
    "hotel_performance_daily": {"hotel_performance_daily", "jl02", "jl02_hotel_performance_daily"},
    "room_type_performance_daily": {"room_type_performance_daily", "jl01", "jl01_room_type_performance_daily"},
    "ota_funnel": {"ota_funnel", "funnel", "OTA漏斗", "流量漏斗", "ota_business_metrics", "meituan_ota_business_metrics", "ctrip_ota_business_metrics"},
    "products": {"products", "商品", "商品价格", "goods_price_mapping", "ota_goods_price_mapping"},
    "promotions": {"promotions", "promotion", "活动", "促销", "ota_promotion_activity"},
    "promotion_products": {"promotion_products", "activity_product_detail", "活动商品", "ota_activity_product_detail"},
    "reviews": {"reviews", "review", "评论", "口碑", "review_detail", "ota_review_detail"},
    "review_overviews": {"review_overviews", "review_overview", "评价概览", "ota_review_overview"},
    "review_rankings": {"review_rankings", "review_ranking", "评价标签", "ota_review_ranking"},
    "nearby_events": {"nearby_events", "nearby_event", "周边活动", "ota_nearby_event"},
    "competitors": {"competitors", "competition", "竞品", "竞品数据"},
    "exposure_daily": {"exposure_daily", "meituan_ota_exposure_source_daily"},
    "user_source_monthly": {"user_source_monthly", "meituan_ota_user_source_monthly"},
    "promotion_finance": {"promotion_finance", "meituan_ota_promotion_finance_detail"},
    "promotion_revenue": {"promotion_revenue", "推广订单金额"},
    "order_loss_monthly": {"order_loss_monthly", "meituan_ota_order_loss_monthly"},
    "joined_rights": {"joined_rights", "meituan_ota_joined_rights"},
    "promotion_status": {"promotion_status", "meituan_ota_promotion_status"},
    "video_upload_status": {"video_upload_status", "meituan_ota_video_upload_status"},
}

FIELD_MAP = {
    "hotel_daily": {
        "日期": "business_date", "营业日期": "business_date", "date": "business_date", "data_date": "business_date",
        "总房量": "room_count", "房间数": "room_count", "available_room_nights": "room_count",
        "间夜": "room_nights", "售出间夜": "room_nights", "sold_room_nights": "room_nights", "sold_rooms": "sold_rooms",
        "收入": "room_revenue", "房费收入": "room_revenue", "room_fee": "room_revenue", "revenue": "room_revenue",
        "出租率": "occupancy_rate", "入住率": "occupancy_rate", "occupancy": "occupancy_rate",
        "平均房价": "adr", "room_daily_price": "adr", "rack_rate": "rack_rate",
    },
    "hotel_monthly": {
        "period_month": "period_month", "月份": "period_month", "month": "period_month",
        "room_count": "room_count", "room_nights": "room_nights", "room_revenue": "room_revenue",
        "maintain_rooms": "maintain_rooms", "occupancy_rate": "occupancy_rate", "adr": "adr", "revpar": "revpar",
    },
    "hotel_performance_daily": {},
    "room_type_performance_daily": {},
    "ota_funnel": {
        "日期": "business_date", "平台": "platform", "渠道": "platform", "channel_source": "platform", "source_platform": "platform",
        "stats_period_type": "period_type", "period_days": "period_days",
        "曝光": "exposure", "曝光人数": "exposure", "曝光量": "exposure", "peer_exposure": "peer_exposure",
        "浏览": "views", "浏览人数": "views", "浏览量": "views", "访客": "visitors", "UV": "visitors", "peer_views": "peer_views",
        "支付订单": "paid_orders", "订单数": "paid_orders", "支付订单数": "paid_orders", "orders": "paid_orders",
        "销售间夜": "sold_room_nights", "销售均价": "sale_adr", "销售额": "sales_revenue", "入住间夜": "checkin_room_nights", "满房率": "full_occupancy_rate",
        "引流价": "entry_price", "评价分": "rating_score", "信息分": "content_score", "HOS分": "hos_score",
        "支付转化率": "payment_conversion_rate", "转化率": "payment_conversion_rate", "浏览-支付转化率": "payment_conversion_rate",
        "曝光-浏览转化率": "exposure_to_view_rate",
        "同行平均转化率": "peer_avg_conversion_rate", "商圈平均转化率": "peer_avg_conversion_rate", "peer_payment_conversion_rate": "peer_avg_conversion_rate",
        "排名": "peer_rank", "商圈排名": "peer_rank", "competitor_rank": "peer_rank",
    },
    "products": {
        "平台": "platform", "渠道": "platform", "channel_source": "platform", "source_platform": "platform",
        "房型": "room_type_name", "source_room_type_name": "room_type_name", "room_type_id": "room_type_id", "ota_room_type_id": "ota_room_type_id",
        "商品名": "product_name", "商品名称": "product_name", "ota_product_name": "product_name", "source_product_name": "product_name",
        "商品类型": "product_type", "rate_plan_name": "product_type", "ota_product_id": "ota_product_id",
        "挂牌价": "listed_price", "门市价": "listed_price", "ota_sale_price": "listed_price", "current_sale_price": "listed_price",
        "活动价": "activity_price", "团购价": "activity_price", "到手价": "final_price", "售卖价": "final_price", "target_sale_price": "final_price",
        "commission_rate": "commission_rate", "是否钟点房": "is_hour_room", "钟点房": "is_hour_room", "是否团购": "is_group_buy", "团购": "is_group_buy", "is_super_deal": "is_group_buy",
    },
    "promotions": {
        "channel_source": "platform", "activity_source_type": "activity_source_type", "activity_id": "activity_id", "activity_name": "activity_name",
        "activity_status": "activity_status", "activity_time_range": "activity_time_range", "activity_rule_labels": "activity_rule_labels",
        "activity_room_type_count": "activity_room_type_count", "activity_room_type_summary": "activity_room_type_summary",
    },
    "promotion_products": {
        "channel_source": "platform", "activity_source_type": "activity_source_type", "activity_id": "activity_id", "activity_name": "activity_name",
        "ota_room_type_id": "ota_room_type_id", "room_type_name": "room_type_name", "room_type_id": "room_type_id", "remaining_inventory": "remaining_inventory",
    },
    "reviews": {
        "平台": "platform", "渠道": "platform", "channel_source": "platform",
        "评论日期": "review_date", "日期": "review_date", "review_time": "review_date", "stay_date": "stay_date",
        "评分": "rating", "星级": "rating", "review_score": "rating", "review_score_max": "rating_max",
        "评论": "review_text", "评论内容": "review_text", "评价内容": "review_text", "review_content": "review_text",
        "是否差评": "is_negative", "差评": "is_negative", "is_negative_review": "is_negative",
        "is_replied": "is_replied", "merchant_reply_time": "merchant_reply_time", "hygiene_score": "hygiene_score", "facility_score": "facility_score", "location_score": "location_score", "service_score": "service_score",
        "关键词": "keywords", "rank_item_name": "keywords",
    },
    "review_overviews": {
        "channel_source": "platform", "review_score": "rating_avg", "review_score_max": "rating_max",
        "environment_score": "environment_score", "facility_score": "facility_score", "service_score": "service_score", "hygiene_score": "hygiene_score",
        "total_review_count": "review_count", "unreplied_review_count": "unreplied_review_count", "negative_review_count": "negative_review_count",
    },
    "review_rankings": {
        "channel_source": "platform", "ranking_type": "ranking_type", "ranking_position": "ranking_position", "rank_item_name": "rank_item_name", "rank_item_value": "rank_item_value",
    },
    "nearby_events": {
        "channel_source": "platform", "event_id": "event_id", "event_class_id": "event_class_id", "event_name": "event_name",
        "event_start_date": "event_start_date", "event_end_date": "event_end_date", "event_address": "event_address", "distance_km": "distance_km", "countdown_days": "countdown_days",
    },
    "competitors": {
        "日期": "business_date", "竞品": "competitor_name", "竞品名称": "competitor_name",
        "房型": "room_type_name", "价格": "price", "售卖价": "price", "peer_average": "price",
        "排名": "rank", "competitor_rank": "rank", "距离": "distance", "活动标签": "promotion_tag",
    },
    "exposure_daily": {},
    "user_source_monthly": {},
    "promotion_finance": {},
    "promotion_revenue": {},
    "order_loss_monthly": {},
    "joined_rights": {},
    "promotion_status": {},
    "video_upload_status": {},
}

REQUIRED = {
    "hotel_daily": {"business_date", "room_count", "room_nights"},
    "hotel_monthly": set(),
    "hotel_performance_daily": set(),
    "room_type_performance_daily": set(),
    "ota_funnel": {"platform", "views", "paid_orders"},
    "products": {"product_name", "listed_price"},
    "promotions": set(),
    "promotion_products": set(),
    "reviews": set(),
    "review_overviews": set(),
    "review_rankings": set(),
    "nearby_events": set(),
    "competitors": set(),
    "exposure_daily": set(),
    "user_source_monthly": set(),
    "promotion_finance": set(),
    "promotion_revenue": set(),
    "order_loss_monthly": set(),
    "joined_rights": set(),
    "promotion_status": set(),
    "video_upload_status": set(),
}

NUMBER_FIELDS = {
    "room_count", "room_nights", "room_revenue", "maintain_rooms", "adr", "revpar", "occupancy_rate", "sold_rooms", "remaining_rooms", "orders_today",
    "exposure", "peer_exposure", "views", "peer_views", "visitors", "paid_orders", "sold_room_nights", "sale_adr", "sales_revenue", "checkin_room_nights", "full_occupancy_rate",
    "payment_conversion_rate", "exposure_to_view_rate", "peer_avg_conversion_rate", "peer_rank", "entry_price", "rating_score", "content_score", "hos_score", "period_days",
    "listed_price", "activity_price", "final_price", "commission_rate", "rating", "rating_avg", "rating_max", "review_count", "unreplied_review_count", "negative_review_count",
    "environment_score", "facility_score", "service_score", "hygiene_score", "ranking_position", "rank_item_value", "activity_room_type_count", "distance_km", "countdown_days",
    "price", "rank",
    "total_exposure", "non_ad_exposure", "ad_exposure", "ad_exposure_ratio_pct",
    "local_user_pct", "nonlocal_user_pct", "new_user_pct", "returning_user_pct",
    "transaction_amount", "amount", "room_revenue", "competitor_loss_order_count",
    "competitor_loss_amount", "total_review_count", "unreplied_review_count",
    "uploaded_count", "required_count",
    "value_day", "value_month", "value_year",
}

BOOL_FIELDS = {"is_hour_room", "is_group_buy", "is_negative", "is_replied"}
DATE_FIELDS = {"business_date", "review_date", "stay_date", "event_start_date", "event_end_date"}
MASK_FIELDS = {"contact", "order_id", "room_no", "guest_name", "reviewer_name_masked"}
META_SECTIONS = {"__source_diagnostics__"}


def section_for_sheet(name: str) -> str | None:
    value = str(name or "").strip()
    lower = value.lower()
    for section, aliases in SHEET_NAMES.items():
        if value in aliases or lower in {x.lower() for x in aliases}:
            return section
    return None


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        percent = "%" in text
        text = text.replace("%", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        return number / 100 if percent else number
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _boolean(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "是", "有", "团购", "钟点", "已回复", "进行中"}:
        return True
    if text in {"0", "false", "no", "n", "否", "无", "未回复", "结束"}:
        return False
    return None


def _date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).strip()
    return text[:10] if len(text) >= 10 else text


def _canonical_key(section: str, key: str) -> str:
    raw = str(key or "").strip()
    return FIELD_MAP.get(section, {}).get(raw, raw)


def normalize_section(section: str, rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    source_tables: set[str] = set()
    for row in rows or []:
        item: dict[str, Any] = {}
        for raw_key, value in row.items():
            key = _canonical_key(section, str(raw_key))
            if not key:
                continue
            seen.add(key)
            if key == "source_table" or key == "__source_table":
                if value:
                    source_tables.add(str(value))
                item["source_table"] = value
            elif key in MASK_FIELDS:
                item[key] = "***" if value not in (None, "") else ""
            elif key in NUMBER_FIELDS:
                item[key] = _number(value)
            elif key in BOOL_FIELDS:
                item[key] = _boolean(value)
            elif key in DATE_FIELDS:
                item[key] = _date(value)
            else:
                item[key] = value
        if any(v not in (None, "") for v in item.values()):
            out.append(item)
    if not out and section in OPTIONAL_SECTIONS:
        missing: list[str] = []
    else:
        missing = sorted(REQUIRED.get(section, set()) - seen)
    return out, {"section": section, "row_count": len(out), "missing_fields": missing, "source_tables": sorted(source_tables), "seen_fields": sorted(seen), "status": "ok" if not missing else "data_gap"}


def normalize_dataset(raw: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    sections: dict[str, list[dict[str, Any]]] = {}
    diagnostics: dict[str, Any] = {}
    for section in SECTIONS:
        rows, diag = normalize_section(section, raw.get(section, []))
        sections[section] = rows
        diagnostics[section] = diag
    source_diagnostics = raw.get("__source_diagnostics__") or []
    missing = {k: v["missing_fields"] for k, v in diagnostics.items() if v["missing_fields"]}
    empty_sections = {k: v["row_count"] for k, v in diagnostics.items() if v["row_count"] == 0 and k not in OPTIONAL_SECTIONS}
    return {"status": "ok" if not missing and not empty_sections else "partial", "sections": sections, "diagnostics": diagnostics, "source_diagnostics": source_diagnostics, "missing_fields": missing, "empty_sections": empty_sections}

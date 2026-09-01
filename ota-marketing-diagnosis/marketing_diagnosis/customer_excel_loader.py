from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


IMPORT_HEADER = "是否导入"
MODULE_HEADER = "系统模块（勿改）"
YES_VALUES = {"是", "yes", "y", "true", "1", "导入"}

PLATFORM_VALUES = {
    "美团": "meituan",
    "美团酒店": "meituan",
    "meituan": "meituan",
    "携程": "ctrip",
    "ctrip": "ctrip",
    "飞猪": "fliggy",
    "fliggy": "fliggy",
    "去哪儿": "qunar",
    "qunar": "qunar",
    "抖音": "douyin",
    "douyin": "douyin",
}

REVIEW_PLATFORM_VALUES = {
    "美团": "meituan",
    "meituan": "meituan",
    "大众点评": "dianping",
    "点评": "dianping",
    "dianping": "dianping",
    "携程": "ctrip",
    "ctrip": "ctrip",
    "飞猪": "fliggy",
    "fliggy": "fliggy",
    "去哪儿": "qunar",
    "qunar": "qunar",
}

STATUS_VALUES = {
    "已开通": "OPEN",
    "已报名": "OPEN",
    "已生效": "OPEN",
    "是": "OPEN",
    "open": "OPEN",
    "未开通": "CLOSED",
    "未报名": "CLOSED",
    "未生效": "CLOSED",
    "否": "CLOSED",
    "closed": "CLOSED",
    "不确定": "PENDING",
    "待确认": "PENDING",
    "pending": "PENDING",
}

MODULE_FIELD_MAP: dict[str, dict[str, str]] = {
    "basic_info": {
        "酒店ID": "hotel_id",
        "酒店名称": "hotel_name",
        "诊断开始日期": "period_start",
        "诊断结束日期": "period_end",
    },
    "hotel_daily": {
        "酒店ID": "hotel_id",
        "酒店名称": "hotel_name",
        "业务日期": "business_date",
        "总房量": "room_count",
        "售出间夜": "room_nights",
        "房费收入": "room_revenue",
        "平均房价": "adr",
        "出租率": "occupancy_rate",
        "快照时间": "snapshot_time",
    },
    "hotel_performance_daily": {
        "酒店ID": "hotel_id",
        "酒店名称": "hotel_name",
        "业务日期": "business_date",
        "指标名称": "metric_name",
        "当日值": "value_day",
        "本月值": "value_month",
        "本年值": "value_year",
        "快照时间": "snapshot_time",
    },
    "room_type_performance_daily": {
        "酒店ID": "hotel_id",
        "业务日期": "business_date",
        "房型ID": "room_type_id",
        "房型名称": "room_type_name",
        "指标名称": "metric_name",
        "当日值": "value_day",
        "近30天值": "value_month",
        "本年值": "value_year",
        "快照时间": "snapshot_time",
    },
    "products": {
        "酒店ID": "hotel_id",
        "快照时间": "snapshot_time",
        "平台": "platform",
        "商品ID": "ota_product_id",
        "商品名称": "product_name",
        "房型ID": "room_type_id",
        "房型名称": "room_type_name",
        "挂牌价": "listed_price",
        "售卖价": "final_price",
    },
    "exposure_daily": {
        "酒店ID": "hotel_id",
        "业务日期": "business_date",
        "整体曝光": "total_exposure",
        "非广告曝光": "non_ad_exposure",
        "广告曝光": "ad_exposure",
        "广告曝光占比": "ad_exposure_ratio_pct",
        "快照时间": "snapshot_time",
    },
    "ota_funnel": {
        "酒店ID": "hotel_id",
        "业务日期": "business_date",
        "平台": "platform",
        "统计周期": "period_type",
        "曝光人数": "exposure",
        "同行曝光": "peer_exposure",
        "曝光排名": "exposure_rank",
        "浏览人数": "views",
        "同行浏览": "peer_views",
        "浏览排名": "views_rank",
        "支付订单": "paid_orders",
        "同行订单": "peer_paid_orders",
        "订单排名": "paid_orders_rank",
        "曝光-浏览转化率": "exposure_to_view_rate",
        "同行曝光-浏览转化率": "peer_exposure_to_view_rate",
        "转化率排名": "exposure_to_view_rate_rank",
        "浏览-支付转化率": "payment_conversion_rate",
        "同行浏览-支付转化率": "peer_payment_conversion_rate",
        "支付转化排名": "payment_conversion_rate_rank",
        "HOS分": "hos_score",
        "HOS排名": "hos_score_rank",
        "信息分": "content_score",
        "快照时间": "snapshot_time",
    },
    "user_source_monthly": {
        "酒店ID": "hotel_id",
        "统计月份": "period_month",
        "本地占比": "local_user_pct",
        "异地占比": "nonlocal_user_pct",
        "新客占比": "new_user_pct",
        "老客占比": "returning_user_pct",
        "快照时间": "snapshot_time",
    },
    "promotion_finance": {
        "酒店ID": "hotel_id",
        "交易时间": "transaction_time",
        "交易类型": "transaction_type",
        "交易金额": "transaction_amount",
        "快照时间": "snapshot_time",
    },
    "promotion_revenue": {
        "酒店ID": "hotel_id",
        "统计月份": "period_month",
        "维度类型": "dimension_type",
        "维度名称": "dimension_name",
        "房费收入": "room_revenue",
        "快照时间": "snapshot_time",
    },
    "order_loss_monthly": {
        "酒店ID": "hotel_id",
        "统计月份": "period_month",
        "竞对酒店名称": "competitor_hotel_name",
        "流失订单数": "competitor_loss_order_count",
        "流失金额": "competitor_loss_amount",
        "流失房型": "lost_room_types_text",
        "关注状态": "follow_status",
        "快照时间": "snapshot_time",
    },
    "review_overviews": {
        "酒店ID": "hotel_id",
        "点评平台": "review_platform",
        "点评评分": "review_score",
        "点评总数": "total_review_count",
        "未回复点评数": "unreplied_review_count",
        "差评数": "negative_review_count",
        "快照时间": "snapshot_time",
    },
    "joined_rights": {
        "酒店ID": "hotel_id",
        "酒店名称": "hotel_name",
        "权益名称": "right_name",
        "有效房型范围": "effective_room_scope",
        "热门商圈词命中": "hot_business_area_hit",
        "快照时间": "snapshot_time",
    },
    "promotion_status": {
        "酒店ID": "hotel_id",
        "配置项名称": "promotion_name",
        "开通状态": "status",
        "报名状态": "enroll_status",
        "生效状态": "effective_status",
        "快照时间": "snapshot_time",
    },
    "video_upload_status": {
        "酒店ID": "hotel_id",
        "视频类型": "video_type",
        "已上传数量": "uploaded_count",
        "需上传数量": "required_count",
        "快照时间": "snapshot_time",
    },
    "manual_inputs": {
        "酒店ID": "hotel_id",
        "挂冠类型": "crown_type",
        "录入人": "operator",
        "录入时间": "recorded_at",
    },
    "scan_orders": {
        "酒店ID": "hotel_id",
        "扫码时间": "scan_time",
        "订单ID": "order_id",
        "扫码订单数量": "order_count",
    },
    "nearby_events": {
        "酒店ID": "hotel_id",
        "活动名称": "event_name",
        "开始日期": "event_start_date",
        "结束日期": "event_end_date",
        "活动地址": "event_address",
        "距离公里": "distance_km",
        "活动类型": "event_type",
        "预计需求": "expected_demand",
    },
    "competitors": {
        "酒店ID": "hotel_id",
        "业务日期": "business_date",
        "平台": "platform",
        "竞品名称": "competitor_name",
        "房型名称": "room_type_name",
        "价格": "price",
        "排名": "rank",
        "评分": "rating",
        "已售房量": "sold_rooms",
        "活动标签": "promotion_tag",
    },
}

RANK_FIELDS = {
    "exposure_rank",
    "views_rank",
    "paid_orders_rank",
    "exposure_to_view_rate_rank",
    "payment_conversion_rate_rank",
    "hos_score_rank",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_imported(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).lower() in YES_VALUES


def _iso_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = _text(value)
    return text[:10] if len(text) >= 10 else text


def _rank(value: Any) -> Any:
    if value in (None, ""):
        return value
    if isinstance(value, (int, float)):
        return value
    match = re.search(r"-?\d+(?:\.\d+)?", _text(value))
    if not match:
        return value
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


def _percentage_points(value: Any) -> Any:
    if value in (None, ""):
        return value
    try:
        number = float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return value
    return number * 100 if abs(number) <= 1 else number


def _normalize_value(module: str, key: str, value: Any, record: dict[str, Any]) -> Any:
    if value in (None, ""):
        return value
    if key == "platform":
        return PLATFORM_VALUES.get(_text(value).lower(), PLATFORM_VALUES.get(_text(value), _text(value).lower()))
    if key == "review_platform":
        return REVIEW_PLATFORM_VALUES.get(_text(value).lower(), REVIEW_PLATFORM_VALUES.get(_text(value), _text(value).lower()))
    if key in {"status", "enroll_status", "effective_status"}:
        text = _text(value)
        return STATUS_VALUES.get(text.lower(), STATUS_VALUES.get(text, text.upper()))
    if key in RANK_FIELDS:
        return _rank(value)
    if key == "follow_status":
        text = _text(value).lower()
        if text in {"1", "是", "已关注", "true", "yes"}:
            return 1
        if text in {"0", "否", "未关注", "false", "no"}:
            return 0
    if module in {"hotel_performance_daily", "room_type_performance_daily"} and key in {"value_day", "value_month", "value_year"}:
        metric = _text(record.get("指标名称")).lower()
        if metric in {"出租率", "入住率", "occupancy", "occupancy_rate"}:
            return _percentage_points(value)
    return value


def is_customer_excel_template(workbook: Any) -> bool:
    """Return True only for the compact Chinese customer template."""
    for sheet in workbook.worksheets:
        for row_number, raw in enumerate(sheet.iter_rows(values_only=True), start=1):
            values = {_text(value) for value in raw if value not in (None, "")}
            if IMPORT_HEADER in values and MODULE_HEADER in values:
                return True
            if row_number >= 80:
                break
    return False


def load_customer_excel_workbook(workbook: Any) -> dict[str, list[dict[str, Any]]]:
    """Parse multi-block Chinese sheets into the existing internal dataset shape.

    Only rows whose ``是否导入`` value is affirmative are included. The function
    does not query a database and does not know anything about Feishu.
    """
    dataset: dict[str, list[dict[str, Any]]] = {}
    context: dict[str, Any] = {}
    imported_rows = 0
    skipped_rows = 0
    unsupported_modules: set[str] = set()

    for sheet in workbook.worksheets:
        headers: list[str] | None = None
        for raw in sheet.iter_rows(values_only=True):
            values = list(raw)
            text_values = [_text(value) for value in values]
            if IMPORT_HEADER in text_values and MODULE_HEADER in text_values:
                headers = text_values
                continue
            if not headers:
                continue

            record = {
                headers[index]: value
                for index, value in enumerate(values)
                if index < len(headers) and headers[index]
            }
            if not _is_imported(record.get(IMPORT_HEADER)):
                if any(value not in (None, "") for value in record.values()):
                    skipped_rows += 1
                continue

            module = _text(record.get(MODULE_HEADER))
            field_map = MODULE_FIELD_MAP.get(module)
            if not module or not field_map:
                if module:
                    unsupported_modules.add(module)
                continue

            converted: dict[str, Any] = {}
            for source_name, target_name in field_map.items():
                value = record.get(source_name)
                if value in (None, ""):
                    continue
                converted[target_name] = _normalize_value(module, target_name, value, record)

            if module == "basic_info":
                if converted.get("hotel_id"):
                    context["hotel_id"] = converted["hotel_id"]
                if converted.get("hotel_name"):
                    context["hotel_name"] = converted["hotel_name"]
                if converted.get("period_start"):
                    context["period_start"] = _iso_date(converted["period_start"])
                if converted.get("period_end"):
                    context["period_end"] = _iso_date(converted["period_end"])
                imported_rows += 1
                continue

            if module == "hotel_performance_daily":
                converted.setdefault("room_type_id", "")
            converted.setdefault("source_table", f"Excel：{sheet.title}/{module}")
            if any(value not in (None, "") for key, value in converted.items() if key != "source_table"):
                dataset.setdefault(module, []).append(converted)
                imported_rows += 1

    dataset["__excel_context__"] = context  # consumed only by excel_upload mode
    dataset["__source_diagnostics__"] = [{
        "loader": "customer_excel_v1",
        "status": "ok",
        "imported_rows": imported_rows,
        "skipped_rows": skipped_rows,
        "unsupported_modules": sorted(unsupported_modules),
    }]
    return dataset

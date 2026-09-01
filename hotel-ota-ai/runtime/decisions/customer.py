from __future__ import annotations

import argparse
from typing import Any

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit
from runtime.contracts import standard_envelope


CHANNEL_LABELS = {
    "meituan": "美团",
    "fliggy": "飞猪",
    "unknown": "未知",
}
LEAD_BUCKET_LABELS = {
    "same_day": "当天预订",
    "1_3_days": "提前1–3天",
    "4_7_days": "提前4–7天",
    "8_14_days": "提前8–14天",
    "15_30_days": "提前15–30天",
    "31_plus_days": "提前31天以上",
    "invalid_negative_or_missing": "时间异常或缺失",
}
STAY_BUCKET_LABELS = {
    "same_day_or_day_use": "同日正时长/钟点",
    "1_night": "1晚",
    "2_nights": "2晚",
    "3_4_nights": "3–4晚",
    "5_7_nights": "5–7晚",
    "8_plus_nights": "8晚以上",
    "invalid_nonpositive_duration": "时长无效",
}


def _display_number(value: Any, *, decimals: int = 2) -> str:
    if value is None:
        return "不可用"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")


def _display_percent(value: Any) -> str:
    if value is None:
        return "不可用"
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return str(value)


def _distribution_text(
    cells: list[dict[str, Any]],
    *,
    name_field: str = "name",
    value_field: str = "value",
    labels: dict[str, str] | None = None,
    suffix: str,
) -> str:
    rendered: list[str] = []
    for cell in cells:
        raw_name = str(cell.get(name_field) or "unknown")
        name = (labels or {}).get(raw_name, raw_name)
        value = _display_number(cell.get(value_field))
        share = cell.get("share")
        rendered.append(f"{name} {value}{suffix}" + (f"（{_display_percent(share)}）" if share is not None else ""))
    return "、".join(rendered)


def render_s17_summary(payload: dict[str, Any]) -> str:
    populations = payload.get("populations") if isinstance(payload.get("populations"), dict) else {}
    booking = populations.get("pms_booking_created") if isinstance(populations.get("pms_booking_created"), dict) else {}
    arrival = populations.get("pms_arrival_cohort") if isinstance(populations.get("pms_arrival_cohort"), dict) else {}
    realized = populations.get("realized_stay") if isinstance(populations.get("realized_stay"), dict) else {}
    extension = populations.get("extension_reconciliation") if isinstance(populations.get("extension_reconciliation"), dict) else {}

    lines = [
        (
            "S17 客户与订单结构分析"
            f"（窗口 {payload.get('window_start') or '未知'} 至 {payload.get('window_end') or '未知'}；"
            f"截至 {payload.get('as_of_datetime') or '未知'}）"
        )
    ]

    if booking:
        created = booking.get("created_order_count")
        booked_rooms = booking.get("booked_rooms")
        cancelled = booking.get("current_cancelled_orders")
        non_cancelled = booking.get("current_non_cancelled_orders")
        if non_cancelled is None and created is not None and cancelled is not None:
            try:
                non_cancelled = int(created) - int(cancelled)
            except (TypeError, ValueError):
                non_cancelled = None
        lines.append(
            "订单总览："
            f"{_display_number(created)} 单，{_display_number(booked_rooms)} 间预订房；"
            f"当前取消 {_display_number(cancelled)} 单（{_display_percent(booking.get('current_cancelled_share'))}），"
            f"当前非取消 {_display_number(non_cancelled)} 单。"
        )

        guest_cells = booking.get("guest_source_order_distribution") or []
        if guest_cells:
            lines.append(
                "预订客源分类（guest_source，不是渠道）："
                + _distribution_text(guest_cells, suffix="单")
                + "。"
            )

        channel_status = booking.get("booking_channel_status")
        channel_cells = booking.get("booking_channel_order_distribution") or []
        if channel_status == "unavailable":
            lines.append("预订渠道：暂不可用，正式字段映射缺少 member_level/booking_product_tag。")
        elif channel_cells:
            channel_text = _distribution_text(channel_cells, labels=CHANNEL_LABELS, suffix="单")
            unknown_orders = booking.get("booking_channel_unknown_orders")
            if unknown_orders:
                channel_text += f"、未知 {_display_number(unknown_orders)}单"
            lines.append("预订渠道（由产品标签批准字典派生）：" + channel_text + "。")

        lead_cells = booking.get("lead_time_buckets") or []
        if lead_cells:
            lines.append(
                "预订提前期："
                + _distribution_text(lead_cells, labels=LEAD_BUCKET_LABELS, suffix="单")
                + f"；平均提前期 {_display_number(booking.get('average_lead_time_days'))} 天。"
            )

        if arrival:
            lines.append(
                "到店 cohort（按 arrival_time）："
                f"{_display_number(arrival.get('arrival_order_count'))} 单，"
                f"{_display_number(arrival.get('booked_rooms'))} 间预订房；"
                f"当前非取消 {_display_number(arrival.get('current_non_cancelled_orders'))} 单。"
            )

        stay_source = arrival or booking
        stay_cells = stay_source.get("stay_duration_buckets") or []
        if stay_cells:
            prefix = "到店 cohort 入住时长结构：" if arrival else "入住时长结构："
            lines.append(
                prefix
                + _distribution_text(stay_cells, labels=STAY_BUCKET_LABELS, suffix="单")
                + f"；过夜订单中的长住占比 {_display_percent(stay_source.get('long_stay_share'))}。"
            )

        booking_room_types = booking.get("room_type_room_distribution") or []
        if booking_room_types:
            lines.append(
                "预订房型："
                + _distribution_text(booking_room_types, suffix="间预订房")
                + "。"
            )
        elif booking.get("unmapped_count"):
            lines.append(
                f"预订房型：canonical room_type_id 缺失 {_display_number(booking.get('unmapped_count'))} 条，"
                "不能按名称补齐。"
            )

    if realized:
        lines.append(
            "实际入住实现（RS01）："
            f"实现间夜 {_display_number(realized.get('realized_room_nights'))}，"
            f"批准房费科目金额 {_display_number(realized.get('realized_room_fee'))} 元，"
            f"ADR {_display_number(realized.get('realized_adr'))} 元/间夜。"
        )
        source_cells = realized.get("source_distribution") or []
        if source_cells:
            lines.append(
                "实际客源结构（RS01 customer_source）："
                + _distribution_text(
                    source_cells,
                    name_field="customer_source",
                    value_field="realized_room_nights",
                    suffix="间夜",
                )
                + "。"
            )
        realized_room_types = realized.get("room_type_distribution") or []
        if realized_room_types:
            lines.append(
                "实际入住房型："
                + _distribution_text(
                    realized_room_types,
                    name_field="room_type_name",
                    value_field="realized_room_nights",
                    suffix="间夜",
                )
                + "。"
            )
        excluded = realized.get("excluded_unapproved_charge_record_count")
        if excluded:
            lines.append(
                "房费科目核查：已排除 "
                f"{_display_number(excluded)} 条未批准科目，金额 {_display_number(realized.get('excluded_unapproved_charge_amount'))} 元。"
            )

    if extension:
        lines.append(
            "续住核查（JD04，独立口径）："
            f"当前有效续住记录 {_display_number(extension.get('active_extension_records'))} 条，"
            f"累计延长 {_display_number(extension.get('extended_hours'))} 小时。"
        )

    data_gaps = [str(item) for item in (payload.get("data_gaps") or []) if item]
    if data_gaps:
        lines.append("数据缺口：" + "、".join(dict.fromkeys(data_gaps)) + "。")

    lines.append(
        "边界：订单、预订房数、实现间夜、收入和续住是不同 population；"
        "不得相加为客户总数，不生成客户画像，不据此推断酒店类型或创建定向动作。"
    )
    return "\n".join(lines)


def customer_analysis(args: argparse.Namespace) -> None:
    if not database_source_enabled():
        emit(
            standard_envelope(
                status="data_gap",
                skill_id="S17",
                summary="客户与订单结构分析需要只读数据库聚合；当前数据库来源未启用。",
                evidence={"blocked_reason": "database_source_disabled", "direct_action_allowed": False},
                recommendations=["请先启用只读数据库来源并确认 S17 exact hotel_id 表映射。"],
                risk_level="medium",
            )
        )
        return

    result = database_template_result(
        "customer_order_analysis",
        args.hotel_id,
        period_start=getattr(args, "period_start", None),
        period_end=getattr(args, "period_end", None),
        as_of_time=getattr(args, "as_of_time", None),
        minimum_cohort_size=getattr(args, "minimum_cohort_size", None),
        max_output_cells=getattr(args, "max_output_cells", None),
        contact_lookup_value=getattr(args, "contact_lookup_value", None),
    )
    if result.get("status") != "ok":
        emit(
            standard_envelope(
                status="data_gap",
                skill_id="S17",
                summary="客户与订单结构分析无法读取受控聚合。",
                evidence={
                    "database_result_status": result.get("status"),
                    "reason": result.get("reason"),
                    "direct_action_allowed": False,
                },
                recommendations=["请检查 S17 数据表、字段映射、只读账号和隐私策略。"],
                risk_level="medium",
            )
        )
        return

    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    populations = payload.get("populations") if isinstance(payload.get("populations"), dict) else {}
    booking = populations.get("pms_booking_created") if isinstance(populations.get("pms_booking_created"), dict) else {}
    contact_proxy = booking.get("contact_proxy") if isinstance(booking.get("contact_proxy"), dict) else {}
    lookup = contact_proxy.get("exact_lookup")
    if getattr(args, "contact_lookup_value", None):
        if contact_proxy.get("status") != "ok":
            status = "data_gap"
            if contact_proxy.get("reason") == "contact_semantic_unavailable_or_masked":
                summary = "联系人订单数代理不可用：当前联系方式字段为脱敏值或字段语义不适用。"
            else:
                summary = "联系人订单数代理不可用：酒店域 HMAC 未配置。"
        else:
            status = "ok"
            lookup = lookup or {
                "all_order_count": 0,
                "non_cancelled_order_count": 0,
                "checked_in_or_stayed_order_count": 0,
                "contact_semantics": "booking_contact_value",
            }
            summary = (
                f"该预订联系人值在可观察历史内关联订单 {lookup['all_order_count']} 笔，"
                f"其中非取消 {lookup['non_cancelled_order_count']} 笔、"
                f"已入住状态 {lookup['checked_in_or_stayed_order_count']} 笔。"
            )
        evidence = {
            "contact_lookup": lookup,
            "history_window": {"start": payload.get("window_start"), "end": payload.get("window_end")},
            "contact_semantics": "booking_contact_value",
            "raw_contact_included": False,
            "direct_action_allowed": False,
        }
    else:
        status = payload.get("status") or "data_gap"
        summary = render_s17_summary(payload)
        evidence = payload
    emit(
        standard_envelope(
            status=status,
            skill_id="S17",
            summary=summary,
            evidence=evidence,
            recommendations=["依据可见聚合核查订单、房型、客源、收入及数据缺口；代理指标不代表实际入住人。"],
            actions=[],
            risk_level="medium" if payload.get("data_gaps") else "low",
        )
    )

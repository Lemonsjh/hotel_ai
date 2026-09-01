from __future__ import annotations

from typing import Any


NOT_COMPUTABLE = "not_computable"
RAW_ITEM_FIELDS = (
    "plan_id",
    "plan_name",
    "launch_id",
    "launch_name",
    "promotion_name",
    "period_start_date",
    "period_end_date",
    "snapshot_time",
    "spend_amount",
    "cash_spend_amount",
    "exposure_count",
    "click_count",
    "booking_order_count",
    "room_night_count",
    "booking_order_amount",
    "click_rate_pct",
    "cost_per_click",
)


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rounded(value: float, digits: int = 4) -> float:
    return round(value, digits)


def _ratio(
    numerator: Any,
    denominator: Any,
    *,
    multiplier: float = 1.0,
) -> float | str:
    numerator_value = _number(numerator)
    denominator_value = _number(denominator)
    if numerator_value is None or denominator_value in (None, 0):
        return NOT_COMPUTABLE
    return _rounded(numerator_value / denominator_value * multiplier)


def _difference(left: Any, right: Any) -> float | str:
    left_value = _number(left)
    right_value = _number(right)
    if left_value is None or right_value is None:
        return NOT_COMPUTABLE
    return _rounded(left_value - right_value)


def _display_item(row: dict[str, Any]) -> dict[str, Any]:
    item = {
        field: row.get(field)
        for field in RAW_ITEM_FIELDS
        if field in row
    }
    spend = row.get("spend_amount")
    cash_spend = row.get("cash_spend_amount")
    order_amount = row.get("booking_order_amount")
    order_count = row.get("booking_order_count")
    room_nights = row.get("room_night_count")
    clicks = row.get("click_count")

    item.update(
        {
            "cost_per_booking": _ratio(spend, order_count),
            "cost_per_room_night": _ratio(spend, room_nights),
            "average_booking_order_amount": _ratio(order_amount, order_count),
            "promotion_adr": _ratio(order_amount, room_nights),
            "roas": _ratio(order_amount, spend),
            "promotion_amount_after_spend": _difference(order_amount, spend),
            "cash_roas": _ratio(order_amount, cash_spend),
            "booking_conversion_rate_pct": _ratio(
                order_count,
                clicks,
                multiplier=100.0,
            ),
        }
    )
    return item


def build_s8_promotion_display(source_result: dict[str, Any]) -> dict[str, Any]:
    """Build a display-only S8 payload from the fixed Meituan source result."""

    payload = (
        source_result.get("payload")
        if isinstance(source_result.get("payload"), dict)
        else {}
    )
    rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
    items = [
        _display_item(row)
        for row in rows
        if isinstance(row, dict)
    ]
    period_starts = [
        str(item["period_start_date"])
        for item in items
        if item.get("period_start_date") not in (None, "")
    ]
    period_ends = [
        str(item["period_end_date"])
        for item in items
        if item.get("period_end_date") not in (None, "")
    ]

    return {
        "status": source_result.get("status") or "data_gap",
        "reason": source_result.get("reason"),
        "source_status": payload.get("source_status") or "unavailable",
        "source_table": payload.get("source_table"),
        "data_business_date": payload.get("data_business_date"),
        "data_snapshot_time": payload.get("data_snapshot_time"),
        "period_start_date": min(period_starts) if period_starts else None,
        "period_end_date": max(period_ends) if period_ends else None,
        "item_count": len(items),
        "items": items,
    }

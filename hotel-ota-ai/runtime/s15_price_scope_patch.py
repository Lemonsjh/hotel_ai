from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping, Sequence

VERSION = "s15-price-scope.v1"
_INSTALLED = False


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(left: Any, right: Any) -> float | None:
    left_value = _n(left)
    right_value = _n(right)
    if left_value is None or right_value in (None, 0):
        return None
    return left_value / right_value


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _scope(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("product_scope") or "").strip()
    if explicit:
        return explicit
    if _truthy(row.get("is_hour_room")):
        return "hour_room"
    if _truthy(row.get("is_super_deal")):
        return "super_deal"
    return "normal_full_day"


def _status(price: float | None, average: float | None) -> tuple[str, float | None]:
    ratio = _ratio(price, average)
    if ratio is None:
        return "unavailable", None
    if ratio >= 1.08:
        return "high", ratio
    if ratio <= 0.95:
        return "low", ratio
    return "normal", ratio


def analyze_price_scopes(
    payload: Mapping[str, Any],
    current_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in current_rows:
        row = dict(source)
        room_id = str(row.get("room_type_id") or "").strip()
        price = _n(row.get("ota_sale_price"))
        if not room_id or price is None or price <= 0:
            continue
        row["product_scope"] = _scope(row)
        row["ota_sale_price"] = price
        grouped[room_id].append(row)

    rooms = payload.get("room_types") or {}
    room_results: list[dict[str, Any]] = []
    high_ids: list[str] = []
    low_ids: list[str] = []
    for room_id in sorted(set(map(str, rooms.keys())) | set(grouped.keys())):
        room = rooms.get(room_id) or {}
        baseline = room.get("price_baseline") or {}
        average = _n(baseline.get("weighted_avg"))
        median = _n(baseline.get("median"))
        p20 = _n(baseline.get("p20"))
        p80 = _n(baseline.get("p80"))
        products: list[dict[str, Any]] = []
        by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in grouped.get(room_id, []):
            scope = str(row.get("product_scope"))
            by_scope[scope].append(row)
            product_status, product_ratio = _status(
                _n(row.get("ota_sale_price")), average
            )
            products.append(
                {
                    "ota_product_id": row.get("ota_product_id"),
                    "ota_product_name": row.get("ota_product_name"),
                    "rate_plan_name": row.get("rate_plan_name"),
                    "product_scope": scope,
                    "current_price": _n(row.get("ota_sale_price")),
                    "price_ratio_vs_avg": product_ratio,
                    "price_status": product_status,
                    "mapping_status": row.get("mapping_status"),
                    "mapping_active": bool(row.get("mapping_active")),
                    "price_editable_flag": row.get("price_editable_flag"),
                }
            )
        for values in by_scope.values():
            values.sort(
                key=lambda item: (
                    float(item.get("ota_sale_price") or 0),
                    str(item.get("ota_product_id") or ""),
                )
            )

        normal = (by_scope.get("normal_full_day") or [None])[0]
        super_deal = (by_scope.get("super_deal") or [None])[0]
        hour_room = (by_scope.get("hour_room") or [None])[0]
        comparable = normal or super_deal
        comparison_scope = (
            "normal_full_day"
            if normal is not None
            else "super_deal_reference_only"
            if super_deal is not None
            else "unavailable"
        )
        current_price = _n((comparable or {}).get("ota_sale_price"))
        price_status, ratio_avg = _status(current_price, average)
        action_eligible = normal is not None
        near_p20 = bool(
            p20 is not None
            and current_price is not None
            and current_price <= p20 * 1.02
        )
        near_p80 = bool(
            p80 is not None
            and current_price is not None
            and current_price >= p80 * 0.98
        )
        result = {
            "room_type_id": room_id,
            "room_type_name": room.get("room_type_name")
            or (comparable or {}).get("room_type_name")
            or room_id,
            "current_price": current_price,
            "comparison_scope": comparison_scope,
            "ota_product_id": (comparable or {}).get("ota_product_id"),
            "ota_product_name": (comparable or {}).get("ota_product_name"),
            "baseline_avg": average,
            "baseline_median": median,
            "baseline_p20": p20,
            "baseline_p80": p80,
            "price_ratio_vs_avg": ratio_avg,
            "price_status": price_status,
            "near_p20_floor": near_p20,
            "near_p80_ceiling": near_p80,
            "action_eligible": action_eligible,
            "normal_full_day_current_price": _n(
                (normal or {}).get("ota_sale_price")
            ),
            "normal_full_day_product_id": (normal or {}).get("ota_product_id"),
            "super_deal_current_price": _n(
                (super_deal or {}).get("ota_sale_price")
            ),
            "super_deal_product_id": (super_deal or {}).get("ota_product_id"),
            "hour_room_current_price": _n(
                (hour_room or {}).get("ota_sale_price")
            ),
            "hour_room_product_id": (hour_room or {}).get("ota_product_id"),
            "product_results": sorted(
                products,
                key=lambda item: (
                    item["product_scope"],
                    float(item.get("current_price") or 0),
                    str(item.get("ota_product_id") or ""),
                ),
            ),
        }
        room_results.append(result)
        if action_eligible and price_status == "high" and not near_p20:
            high_ids.append(room_id)
        if action_eligible and price_status == "low":
            low_ids.append(room_id)

    return {
        "status": "available" if any(
            row.get("product_results") for row in room_results
        ) else "unavailable",
        "grain": "exact_meituan_product_scopes_to_canonical_room_type",
        "comparison_rule": (
            "normal_full_day_first; super_deal_reference_only; "
            "hour_room_excluded_from_full_day_comparison"
        ),
        "room_results": room_results,
        "high_room_type_ids": high_ids,
        "low_room_type_ids": low_ids,
    }


def _money(value: Any) -> str:
    value = _n(value)
    return "—" if value is None else f"¥{value:,.0f}"


def _append_product_scope_details(
    base_text: str, payload: Mapping[str, Any]
) -> str:
    analysis = payload.get("operating_analysis") or {}
    price = analysis.get("price") or {}
    rows = price.get("room_results") or []
    if not rows:
        return base_text
    lines = [
        "",
        "附：美团商品价格口径拆分",
        "普通全天房用于与 PMS 历史成交价做经营参考；超级团购单列；钟点房仅展示，不参与全天房价格判断。",
    ]
    for row in rows:
        lines.append(
            f"- {row.get('room_type_name') or row.get('room_type_id')}："
            f"普通全天房 {_money(row.get('normal_full_day_current_price'))}；"
            f"超级团购 {_money(row.get('super_deal_current_price'))}；"
            f"钟点房 {_money(row.get('hour_room_current_price'))}；"
            f"比较口径 {row.get('comparison_scope') or 'unavailable'}。"
        )
    return base_text + "\n" + "\n".join(lines)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import (
        s15_technical_analysis,
        s15_technical_sources,
        s15_s16_complete_output_patch,
    )
    from runtime.sales_progress import presentation

    s15_technical_sources._price_analysis = analyze_price_scopes
    s15_technical_analysis._price_analysis = analyze_price_scopes

    previous = s15_s16_complete_output_patch.s15_message
    if not getattr(previous, "_S15_PRICE_SCOPE_V1", False):
        def s15_message(payload: Mapping[str, Any]) -> str:
            return _append_product_scope_details(previous(payload), payload)

        s15_message._S15_PRICE_SCOPE_V1 = True  # type: ignore[attr-defined]
        s15_s16_complete_output_patch.s15_message = s15_message
        presentation.build_s15_user_message = s15_message

from __future__ import annotations

from typing import Any

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import now_local
from runtime.control_plane import resolve_price_guard_policy


def _text(value: Any) -> str:
    return str(value or "").strip()


def _has_price(value: Any) -> bool:
    try:
        return float(value) >= 0
    except (TypeError, ValueError):
        return False


def _explicitly_not_editable(value: Any) -> bool:
    return value is False or str(value or "").strip().lower() in {"0", "false", "no", "n"}


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) == 1.0
    return _text(value).lower() in {"1", "true", "yes", "y"}


def _excluded_product_type(item: dict[str, Any]) -> str | None:
    name = _text(item.get("ota_product_name")).lower()
    if _truthy(item.get("is_hour_room")) or any(
        token in name for token in ("钟点", "小时", "hour")
    ):
        return "hour_room"
    if _truthy(item.get("is_super_deal")) or any(
        token in name for token in ("超级团购", "super deal")
    ):
        return "super_deal"
    return None


def _closed_room_types(result: dict[str, Any], *, target_date: str) -> set[str]:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    if result.get("status") != "ok" or payload.get("source_status") not in {None, "ok"}:
        return set()
    closed: set[str] = set()
    for room in payload.get("room_type_forecasts") or []:
        if not isinstance(room, dict):
            continue
        stay_date = _text(room.get("stay_date") or room.get("business_date"))[:10]
        if stay_date and stay_date != target_date:
            continue
        room_type_id = _text(room.get("room_type_id"))
        try:
            available_rooms = float(room.get("available_rooms"))
        except (TypeError, ValueError):
            continue
        if room_type_id and available_rooms <= 0:
            closed.add(room_type_id)
    return closed


def _product_state(item: dict[str, Any]) -> tuple[str, str]:
    if not _text(item.get("ota_product_id")):
        return "view_only", "ota_product_id_missing"
    if not _has_price(item.get("current_price")):
        return "view_only", "current_price_missing"
    if _explicitly_not_editable(item.get("price_editable_flag")):
        return "view_only", "platform_price_not_editable"
    if "ota_room_type_mapping_incomplete" in set(item.get("row_risk_flags") or []):
        return "view_only", "room_type_mapping_pending"
    return "eligible_for_price_request", "product_ready_for_price_request"


def list_priceable_products(
    *,
    hotel_id: str,
    control_db_path: str,
    as_of_time: str | None = None,
    source_platform: str | None = None,
) -> dict[str, Any]:
    """List OTA products for viewing; guard state controls eligibility, never visibility."""
    requested_platform = _text(source_platform).lower() or None
    if not database_source_enabled():
        return {
            "status": "data_gap",
            "hotel_id": hotel_id,
            "products": [],
            "blocked_reason": "database_source_disabled",
            "summary": "OTA 商品数据源未启用，无法查询当前商品和价格。",
        }
    result = database_template_result(
        "ota_price_mapping",
        hotel_id,
        as_of_time=as_of_time,
        source_platform=requested_platform,
    )
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    source_status = payload.get("source_status")
    if result.get("status") != "ok" or source_status not in {None, "ok"}:
        return {
            "status": "data_gap",
            "hotel_id": hotel_id,
            "products": [],
            "blocked_reason": source_status or result.get("reason") or "ota_price_mapping_unavailable",
            "data_source_type": result.get("data_source_type"),
            "freshness_status": payload.get("freshness_status"),
            "risk_flags": payload.get("risk_flags") or result.get("risk_flags") or [],
            "summary": "OTA 商品映射不可用，未展示任何推测商品。",
        }

    at_time = as_of_time or now_local()
    target_date = _text(at_time)[:10]
    operating_result = database_template_result(
        "operating_snapshot", hotel_id, date=target_date, as_of_time=at_time
    )
    closed_room_types = _closed_room_types(operating_result, target_date=target_date)
    products = []
    excluded_types: list[str] = []
    excluded_sold_out_product_count = 0
    excluded_sold_out_room_types: set[str] = set()
    for item in payload.get("price_snapshots") or []:
        channel = _text(item.get("channel")).lower()
        if requested_platform and channel != requested_platform:
            continue
        excluded_type = _excluded_product_type(item)
        if excluded_type:
            excluded_types.append(excluded_type)
            continue
        room_type_id = _text(item.get("room_type_id"))
        if room_type_id in closed_room_types:
            excluded_sold_out_product_count += 1
            excluded_sold_out_room_types.add(room_type_id)
            continue
        product_id = _text(item.get("ota_product_id"))
        policy = resolve_price_guard_policy(
            control_db_path,
            hotel_id=hotel_id,
            room_type_id=room_type_id,
            channel_source=channel,
            ota_product_id=product_id,
            at_time=at_time,
        )
        state, reason = _product_state(item)
        products.append(
            {
                "channel": channel or "unknown",
                "ota_product_id": product_id or None,
                "ota_product_name": item.get("ota_product_name") or None,
                "current_price": item.get("current_price"),
                "room_type_id": room_type_id or None,
                "room_type_name": item.get("room_type_name") or None,
                "product_state": state,
                "price_request_eligible": state == "eligible_for_price_request",
                "state_reason": reason,
                "price_guard_source": policy.get("source"),
                "price_guard_policy_id": policy.get("policy_id"),
                "price_floor": policy.get("floor_price"),
                "price_ceiling": policy.get("ceiling_price"),
                "snapshot_time": item.get("snapshot_time"),
            }
        )
    products.sort(key=lambda item: (item["channel"], _text(item.get("ota_product_name")), _text(item.get("ota_product_id"))))
    eligible_count = sum(1 for item in products if item["price_request_eligible"])
    return {
        "status": "ok",
        "hotel_id": hotel_id,
        "source_platform": requested_platform,
        "products": products,
        "product_count": len(products),
        "eligible_product_count": eligible_count,
        "view_only_product_count": len(products) - eligible_count,
        "excluded_unsupported_product_count": len(excluded_types),
        "excluded_unsupported_product_types": sorted(set(excluded_types)),
        "excluded_sold_out_product_count": excluded_sold_out_product_count,
        "excluded_sold_out_room_type_count": len(excluded_sold_out_room_types),
        "room_inventory_source_status": (
            (operating_result.get("payload") or {}).get("source_status")
            if isinstance(operating_result.get("payload"), dict)
            else operating_result.get("reason")
        ),
        "data_source_type": result.get("data_source_type") or "mysql_db",
        "freshness_status": payload.get("freshness_status"),
        "data_snapshot_time": payload.get("data_snapshot_time"),
        "risk_flags": payload.get("risk_flags") or result.get("risk_flags") or [],
        "summary": "仅展示可售的普通全天房 OTA 商品名称和当前价格；钟点房、超级团购、售完或关房房型均不进入调价清单。",
        "live_allowed": False,
        "formal_approval_created": False,
        "live_execution_count": 0,
    }

from __future__ import annotations

import hashlib
import json
from typing import Any


PRICE_EXECUTION_FIELDS = (
    "hotel_id",
    "price_guard_policy_id",
    "guard_version",
    "room_type_id",
    "channel",
    "ota_product_id",
    "normal_price",
    "old_price",
    "execution_price",
    "candidate_price",
    "floor_price",
    "ceiling_price",
    "max_increase_pct",
    "max_decrease_pct",
    "min_increase_pct",
    "min_decrease_pct",
    "begin_date",
    "end_date",
    "freshness_status",
)


def _normalize_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, int):
        return value
    if value in (None, ""):
        return None
    return value


def canonical_payload(payload: dict[str, Any], fields: tuple[str, ...] = PRICE_EXECUTION_FIELDS) -> dict[str, Any]:
    data = dict(payload)
    if data.get("normal_price") in (None, "") and data.get("execution_price") not in (None, ""):
        data["normal_price"] = data.get("execution_price")
    if data.get("execution_price") in (None, "") and data.get("normal_price") not in (None, ""):
        data["execution_price"] = data.get("normal_price")
    return {field: _normalize_value(data.get(field)) for field in fields if field in data or field in PRICE_EXECUTION_FIELDS}


def payload_hash(payload: dict[str, Any], fields: tuple[str, ...] = PRICE_EXECUTION_FIELDS) -> str:
    canonical = canonical_payload(payload, fields)
    blob = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def price_execution_payload(
    *,
    hotel_id: Any = None,
    room_type_id: Any,
    channel: Any,
    normal_price: Any,
    ota_product_id: Any = None,
    old_price: Any = None,
    price_guard_policy_id: Any = None,
    begin_date: Any,
    end_date: Any,
    floor_price: Any = None,
    ceiling_price: Any = None,
    max_increase_pct: Any = None,
    max_decrease_pct: Any = None,
    min_increase_pct: Any = None,
    min_decrease_pct: Any = None,
    freshness_status: Any = None,
    guard_version: Any = None,
) -> dict[str, Any]:
    return {
        "hotel_id": hotel_id,
        "price_guard_policy_id": price_guard_policy_id,
        "guard_version": guard_version,
        "room_type_id": room_type_id,
        "channel": channel,
        "ota_product_id": ota_product_id,
        "normal_price": normal_price,
        "old_price": old_price,
        "execution_price": normal_price,
        "begin_date": begin_date,
        "end_date": end_date,
        "floor_price": floor_price,
        "ceiling_price": ceiling_price,
        "max_increase_pct": max_increase_pct,
        "max_decrease_pct": max_decrease_pct,
        "min_increase_pct": min_increase_pct,
        "min_decrease_pct": min_decrease_pct,
        "freshness_status": freshness_status,
    }


def price_execution_payload_hash(payload: dict[str, Any]) -> str:
    return payload_hash(payload, PRICE_EXECUTION_FIELDS)

from __future__ import annotations

from typing import Any


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate_room_type_inventory(room_types_fact: dict[str, Any]) -> dict[str, Any]:
    rows = []
    missing: list[str] = []
    for room in room_types_fact.get("room_types") or []:
        room_id = str(room.get("room_type_id") or room.get("room_type_name") or "unknown")
        required_missing = [field for field in ("inventory", "sold_rooms") if room.get(field) in (None, "")]
        missing.extend(f"{room_id}.{field}" for field in required_missing)
        total = _number(room.get("inventory"))
        sold = _number(room.get("sold_rooms"))
        stayover = _number(room.get("stayover_rooms") or room.get("stayover_count"))
        maintenance = _number(room.get("maintenance_rooms"))
        reserved = _number(room.get("reserved_rooms"))
        offline_hold = _number(room.get("offline_hold_rooms"))
        expected_checkout = _number(room.get("expected_checkout_sellable"))
        sellable = max(total - sold - stayover - maintenance - reserved - offline_hold + expected_checkout, 0)
        rows.append(
            {
                "room_type_id": room_id,
                "room_type_name": room.get("room_type_name") or room_id,
                "total_inventory": total,
                "sold_rooms": sold,
                "stayover_rooms": stayover,
                "maintenance_rooms": maintenance,
                "reserved_rooms": reserved,
                "offline_hold_rooms": offline_hold,
                "expected_checkout_sellable": expected_checkout,
                "room_type_sellable_inventory": sellable,
                "inventory_pressure": round(sold / total, 4) if total else None,
            }
        )
    total_inventory = sum(_number(row["total_inventory"]) for row in rows)
    total_sellable = sum(_number(row["room_type_sellable_inventory"]) for row in rows)
    total_sold = sum(_number(row["sold_rooms"]) for row in rows)
    return {
        "status": "ok" if not missing else "partial",
        "algorithm": "room_type_sellable_inventory_v1",
        "formula": "total - sold - stayover - maintenance - reserved - offline_hold + expected_checkout_sellable",
        "room_type_inventory": rows,
        "total_inventory": total_inventory,
        "sold_rooms": total_sold,
        "sellable_inventory": total_sellable,
        "inventory_pressure": round(total_sold / total_inventory, 4) if total_inventory else None,
        "missing_fields": sorted(set(missing)),
    }

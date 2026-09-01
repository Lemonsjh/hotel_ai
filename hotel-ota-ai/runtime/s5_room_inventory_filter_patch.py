from __future__ import annotations

import sys
from typing import Any, Mapping


_INSTALLED = False
VERSION = "s5-room-inventory-filter.v1"


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _payload(result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    nested = result.get("payload")
    return dict(nested) if isinstance(nested, Mapping) else dict(result)


def no_sellable_room_types(
    operating_result: Mapping[str, Any] | None,
    *,
    target_stay_date: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Return room types whose PMS forecast has no sellable inventory."""

    payload = _payload(operating_result)
    rows = payload.get("room_type_forecasts") or []
    if not isinstance(rows, list):
        return {}

    result: dict[str, dict[str, Any]] = {}
    fallback_date = (
        _text(target_stay_date)
        or _text(payload.get("stay_date"))
        or _text(payload.get("business_date"))
        or _text(payload.get("data_business_date"))
    )[:10]
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        room_type_id = _text(row.get("room_type_id"))
        available_rooms = _n(row.get("available_rooms"))
        if not room_type_id or available_rooms is None or available_rooms > 0:
            continue
        result[room_type_id] = {
            "room_type_id": room_type_id,
            "room_type_name": row.get("room_type_name"),
            "stay_date": (
                _text(row.get("stay_date"))
                or _text(row.get("business_date"))
                or fallback_date
            )[:10],
            "total_rooms": _n(row.get("total_rooms")),
            "available_rooms": available_rooms,
            "reason": "room_type_no_sellable_inventory",
        }
    return result


def filter_s5_candidates_by_room_inventory(
    result: Mapping[str, Any],
    *,
    operating_result: Mapping[str, Any] | None,
    target_stay_date: str | None = None,
    requested_ota_product_id: str | None = None,
) -> dict[str, Any]:
    """Remove products mapped to room types with available_rooms <= 0."""

    copied = dict(result)
    closed_room_types = no_sellable_room_types(
        operating_result,
        target_stay_date=target_stay_date,
    )
    candidates = [
        dict(item)
        for item in (copied.get("candidates") or [])
        if isinstance(item, Mapping)
    ]

    kept: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    affected_room_type_ids: set[str] = set()
    for candidate in candidates:
        room_type_id = _text(candidate.get("room_type_id"))
        if room_type_id and room_type_id in closed_room_types:
            excluded.append(candidate)
            affected_room_type_ids.add(room_type_id)
            continue
        kept.append(candidate)

    copied["candidates"] = kept
    copied["candidate_count"] = len(kept)
    copied["eligible_for_s6_count"] = sum(
        bool(item.get("auto_execution_eligible"))
        or item.get("eligibility") == "eligible_for_s6_dry_run"
        for item in kept
    )
    copied.update(
        {
            "s5_room_inventory_filter_version": VERSION,
            "excluded_no_inventory_product_count": len(excluded),
            "excluded_no_inventory_room_type_count": len(affected_room_type_ids),
            "excluded_no_inventory_room_types": [
                closed_room_types[room_type_id]
                for room_type_id in sorted(affected_room_type_ids)
            ],
        }
    )

    if excluded:
        quality_flags = [str(item) for item in (copied.get("quality_flags") or [])]
        flag = "excluded_room_type_no_sellable_inventory"
        if flag not in quality_flags:
            quality_flags.append(flag)
        copied["quality_flags"] = quality_flags

        requested = _text(requested_ota_product_id)
        if requested and any(
            _text(item.get("ota_product_id")) == requested for item in excluded
        ):
            copied["requested_product_excluded_reason"] = (
                "room_type_no_sellable_inventory"
            )
        if not kept:
            copied["blocked_reason"] = (
                "all_matching_products_excluded_no_sellable_inventory"
            )

    return copied


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.algorithms import s5_real_candidates as s5_module

    previous_build = s5_module.build_s5_real_candidates
    if getattr(previous_build, "_S5_ROOM_INVENTORY_FILTER_V1", False):
        return

    def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
        original_query = kwargs.get("query")
        if not callable(original_query):
            return previous_build(*args, **kwargs)

        captured_operating: dict[str, Any] = {}

        def captured_query(
            template: str,
            hotel_id: str,
            **query_kwargs: Any,
        ) -> dict[str, Any]:
            query_result = original_query(template, hotel_id, **query_kwargs)
            if template == "operating_snapshot" and isinstance(
                query_result, Mapping
            ):
                captured_operating.update(dict(query_result))
            return query_result

        patched_kwargs = dict(kwargs)
        patched_kwargs["query"] = captured_query
        result = previous_build(*args, **patched_kwargs)
        return filter_s5_candidates_by_room_inventory(
            result,
            operating_result=captured_operating,
            target_stay_date=kwargs.get("target_stay_date"),
            requested_ota_product_id=kwargs.get("ota_product_id"),
        )

    build_s5_real_candidates._S5_ROOM_INVENTORY_FILTER_V1 = True  # type: ignore[attr-defined]
    s5_module.build_s5_real_candidates = build_s5_real_candidates

    router = sys.modules.get("runtime.feishu_command_router")
    if router is not None and hasattr(router, "build_s5_real_candidates"):
        router.build_s5_real_candidates = build_s5_real_candidates

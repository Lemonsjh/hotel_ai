from __future__ import annotations

import sys
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Mapping


_INSTALLED = False
VERSION = "s5-limited-preview.v2"
LIMITED_PREVIEW_MAX_CHANGE_PCT = 0.03
LIMITED_BASELINE_MATURITY = {
    "weak",
    "trend_only",
    "limited",
    "partial",
    "early",
    "insufficient",
}


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _baseline_package(s15_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(s15_result, Mapping):
        return {}
    payload = _mapping(s15_result.get("baseline")) or dict(s15_result)
    return _mapping(payload.get("baseline_package")) or payload


def _room_reference(
    s15_result: Mapping[str, Any] | None,
    room_type_id: str,
) -> dict[str, Any]:
    package = _baseline_package(s15_result)
    references = package.get("room_type_transaction_references") or []
    if isinstance(references, list):
        for item in references:
            if isinstance(item, Mapping) and _text(item.get("room_type_id")) == room_type_id:
                return dict(item)

    rooms = _mapping(package.get("room_types"))
    room = _mapping(rooms.get(room_type_id))
    return _mapping(room.get("price_baseline")) or room


def _baseline_maturity(s15_result: Mapping[str, Any] | None) -> str:
    package = _baseline_package(s15_result)
    payload = _mapping((s15_result or {}).get("baseline"))
    hotel = _mapping(package.get("hotel")) or _mapping(payload.get("hotel"))
    health = _mapping(hotel.get("baseline_health"))
    return _text(
        package.get("sample_maturity")
        or payload.get("sample_maturity")
        or health.get("object_maturity")
        or health.get("sample_maturity")
    ).lower()


def _baseline_reference_available(reference: Mapping[str, Any]) -> bool:
    return any(
        _n(reference.get(field)) not in (None, 0)
        for field in ("median", "weighted_avg", "avg", "p20")
    )


def _fresh_for_target(result: Mapping[str, Any]) -> bool:
    target_date = _text(result.get("target_stay_date"))[:10]
    business_date = _text(
        result.get("data_business_date")
        or result.get("business_date")
    )[:10]
    return bool(
        target_date
        and business_date == target_date
        and _text(result.get("freshness_status")).lower() == "fresh"
    )


def _money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _money_down(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_FLOOR))


def _preview_direction(candidate: Mapping[str, Any]) -> str | None:
    delta_pp = _n(candidate.get("sales_progress_delta_pp"))
    total_rooms = _n(candidate.get("total_rooms"))
    remaining_ratio = _n(candidate.get("remaining_room_ratio"))
    current_price = _n(candidate.get("current_price"))
    if (
        delta_pp is None
        or total_rooms is None
        or total_rooms <= 0
        or remaining_ratio is None
        or current_price in (None, 0)
        or not candidate.get("product_sellable")
        or not candidate.get("guard_valid")
    ):
        return None

    ceiling = _n(candidate.get("effective_price_ceiling"))
    if (
        delta_pp >= 8
        and remaining_ratio <= 0.30
        and candidate.get("market_not_cold") is True
        and ceiling is not None
        and current_price < ceiling
    ):
        return "increase"

    floor = _n(candidate.get("effective_price_floor"))
    if (
        delta_pp <= -8
        and remaining_ratio >= 0.50
        and _text(candidate.get("traffic_status")).lower() == "healthy"
        and candidate.get("second_conversion_weak") is True
        and candidate.get("price_high") is True
        and floor is not None
        and current_price > floor
    ):
        return "decrease"
    return None


def _apply_limited_preview(
    candidate: dict[str, Any],
    *,
    direction: str,
) -> None:
    """Legacy compatibility helper; v2 no longer calls it automatically."""

    current_price = float(candidate["current_price"])
    if direction == "increase":
        ceiling = float(candidate["effective_price_ceiling"])
        target = _money_down(
            min(ceiling, current_price * (1.0 + LIMITED_PREVIEW_MAX_CHANGE_PCT))
        )
    else:
        floor = float(candidate["effective_price_floor"])
        target = _money(
            max(floor, current_price * (1.0 - LIMITED_PREVIEW_MAX_CHANGE_PCT))
        )

    if target == current_price:
        return
    change = round((target - current_price) / current_price, 4)
    candidate.update(
        {
            "limited_evidence_preview": True,
            "limited_preview_version": VERSION,
            "preview_direction": direction,
            "manual_preview_price": target,
            "manual_preview_change_pct": change,
            "candidate_price": target,
            "conservative_price": target,
            "execution_price": current_price,
            "actual_change_pct": change,
            "configured_change_pct": LIMITED_PREVIEW_MAX_CHANGE_PCT,
            "price_action": "hold",
            "action_type": "manual_price_preview",
            "eligibility": "manual_preview_only",
            "blocked_reason": "limited_s15_evidence_preview_only",
            "auto_execution_eligible": False,
            "approval_required": False,
            "handoff_to": None,
            "requires_s6_revalidation": False,
            "reference_only": True,
            "risk_level": "medium",
            "decision_strength": "limited_evidence_preview",
            "price_comparison_basis": (
                candidate.get("price_comparison_basis")
                or "room_type_transaction_history_fallback"
            ),
        }
    )


def apply_limited_evidence_previews(
    result: Mapping[str, Any],
    *,
    s15_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Preserve S5 business decisions; S15 maturity no longer creates prices."""

    del s15_result
    copied = dict(result)
    candidates = [
        dict(item)
        for item in (copied.get("candidates") or [])
        if isinstance(item, Mapping)
    ]

    candidates.sort(
        key=lambda item: (
            item.get("strong_pricing_rule_status") != "triggered",
            not bool(item.get("limited_evidence_preview")),
            _text(item.get("ota_product_name")),
        )
    )
    copied["candidates"] = candidates
    copied["limited_evidence_preview_count"] = sum(
        bool(item.get("limited_evidence_preview")) for item in candidates
    )
    copied["s5_limited_preview_version"] = VERSION
    copied["s5_limited_preview_generation_enabled"] = False
    copied["limited_preview_max_change_pct"] = LIMITED_PREVIEW_MAX_CHANGE_PCT
    copied["eligible_for_s6_count"] = sum(
        bool(item.get("auto_execution_eligible"))
        and item.get("eligibility") == "eligible_for_s6_dry_run"
        for item in candidates
    )
    return copied


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.algorithms import s5_real_candidates as s5_module

    previous_build = s5_module.build_s5_real_candidates
    if getattr(previous_build, "_S5_LIMITED_PREVIEW_V2", False):
        return

    def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = previous_build(*args, **kwargs)
        return apply_limited_evidence_previews(
            result,
            s15_result=kwargs.get("s15_result"),
        )

    build_s5_real_candidates._S5_LIMITED_PREVIEW_V2 = True  # type: ignore[attr-defined]
    s5_module.build_s5_real_candidates = build_s5_real_candidates

    router = sys.modules.get("runtime.feishu_command_router")
    if router is not None and hasattr(router, "build_s5_real_candidates"):
        router.build_s5_real_candidates = build_s5_real_candidates

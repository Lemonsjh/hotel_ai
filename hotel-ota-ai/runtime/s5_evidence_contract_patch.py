from __future__ import annotations

import sys
from collections import Counter
from typing import Any, Mapping

from runtime.s5_limited_preview_patch import (
    LIMITED_BASELINE_MATURITY,
    _baseline_maturity,
    _baseline_reference_available,
    _fresh_for_target,
    _room_reference,
)


_INSTALLED = False
VERSION = "s5-evidence-contract.v1"
PRICE_REFERENCE_SCOPE = "unified_room_type_transaction_history"


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _preview_blockers(
    candidate: Mapping[str, Any],
    *,
    result: Mapping[str, Any],
    s15_result: Mapping[str, Any] | None,
) -> list[str]:
    if candidate.get("strong_pricing_rule_status") == "triggered":
        return []
    if candidate.get("limited_evidence_preview"):
        return []

    blockers: list[str] = []
    if not _fresh_for_target(result):
        blockers.append("data_not_fresh_for_target")

    reference = _room_reference(
        s15_result,
        _text(candidate.get("room_type_id")),
    )
    if not _baseline_reference_available(reference):
        blockers.append("room_type_transaction_price_reference_missing")

    maturity = _baseline_maturity(s15_result)
    if maturity and maturity not in LIMITED_BASELINE_MATURITY:
        blockers.append("baseline_maturity_not_limited_preview")

    if not candidate.get("reference_only"):
        blockers.append("candidate_not_reference_only")
    if not candidate.get("product_sellable"):
        blockers.append("product_not_sellable")
    if not candidate.get("guard_valid"):
        blockers.append("price_guard_invalid")

    delta_pp = _n(candidate.get("sales_progress_delta_pp"))
    total_rooms = _n(candidate.get("total_rooms"))
    remaining_ratio = _n(candidate.get("remaining_room_ratio"))
    current_price = _n(candidate.get("current_price"))
    if delta_pp is None:
        blockers.append("room_type_sales_progress_missing")
    if total_rooms is None or total_rooms <= 0 or remaining_ratio is None:
        blockers.append("room_type_inventory_scope_invalid")
    if current_price in (None, 0):
        blockers.append("current_price_invalid")

    if delta_pp is not None and remaining_ratio is not None and current_price not in (None, 0):
        if delta_pp >= 8:
            if remaining_ratio > 0.30:
                blockers.append("room_type_inventory_not_tight_for_raise")
            if candidate.get("market_not_cold") is not True:
                blockers.append("market_not_cold_evidence_missing")
            ceiling = _n(candidate.get("effective_price_ceiling"))
            if ceiling is None or current_price >= ceiling:
                blockers.append("no_raise_price_headroom")
        elif delta_pp <= -8:
            if remaining_ratio < 0.50:
                blockers.append("room_type_inventory_not_loose_for_decrease")
            if _text(candidate.get("traffic_status")).lower() != "healthy":
                blockers.append("traffic_not_healthy_for_decrease")
            if (
                candidate.get("second_conversion_evidence_available") is False
                or candidate.get("second_conversion_sample_valid") is not True
            ):
                blockers.append("second_conversion_data_insufficient")
            elif candidate.get("second_conversion_weak") is not True:
                blockers.append("second_conversion_strong_sample_not_triggered")
            if candidate.get("price_high") is not True:
                blockers.append("current_price_not_high_vs_room_type_history")
            floor = _n(candidate.get("effective_price_floor"))
            if floor is None or current_price <= floor:
                blockers.append("no_decrease_price_headroom")
        else:
            blockers.append("room_type_sales_progress_within_hold_band")

    return list(dict.fromkeys(blockers))


def attach_s5_evidence_contract(
    result: Mapping[str, Any],
    *,
    s15_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    copied = dict(result)
    candidates = [
        dict(item)
        for item in (copied.get("candidates") or [])
        if isinstance(item, Mapping)
    ]
    blocker_counts: Counter[str] = Counter()

    for candidate in candidates:
        candidate["price_reference_scope"] = PRICE_REFERENCE_SCOPE
        candidate["same_ota_product_history_required"] = False
        blockers = _preview_blockers(
            candidate,
            result=copied,
            s15_result=s15_result,
        )
        candidate["limited_preview_blockers"] = blockers
        candidate["limited_preview_evidence_complete"] = not blockers
        blocker_counts.update(blockers)

    copied["candidates"] = candidates
    copied["s5_evidence_contract_version"] = VERSION
    copied["price_reference_scope"] = PRICE_REFERENCE_SCOPE
    copied["same_ota_product_history_required"] = False
    copied["limited_preview_blocker_counts"] = dict(sorted(blocker_counts.items()))
    return copied


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.algorithms import s5_real_candidates as s5_module

    previous_build = s5_module.build_s5_real_candidates
    if getattr(previous_build, "_S5_EVIDENCE_CONTRACT_V1", False):
        return

    def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = previous_build(*args, **kwargs)
        return attach_s5_evidence_contract(
            result,
            s15_result=kwargs.get("s15_result"),
        )

    build_s5_real_candidates._S5_EVIDENCE_CONTRACT_V1 = True  # type: ignore[attr-defined]
    s5_module.build_s5_real_candidates = build_s5_real_candidates

    router = sys.modules.get("runtime.feishu_command_router")
    if router is not None and hasattr(router, "build_s5_real_candidates"):
        router.build_s5_real_candidates = build_s5_real_candidates

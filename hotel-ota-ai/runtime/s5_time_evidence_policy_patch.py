from __future__ import annotations

import sys
from typing import Any, Mapping

from runtime.sales_progress.hour_grid_evidence import (
    FORMAL_DECISION_MATURITIES,
    FORMAL_GLOBAL_MIN_COVERAGE,
    PREVIEW_DECISION_MATURITIES,
)
from runtime.s5_limited_preview_patch import LIMITED_PREVIEW_MAX_CHANGE_PCT


_INSTALLED = False
VERSION = "s5-time-evidence-policy.v3"

S15_ADVISORY_CODES = {
    "baseline_maturity_not_limited_preview",
    "exact_hour_grid_evidence_missing",
    "global_hour_grid_below_formal_threshold",
    "decision_hour_evidence_missing",
    "decision_hour_maturity_below_formal_threshold",
    "decision_hour_evidence_insufficient_for_preview",
    "s15_time_evidence_not_formal",
}

S5_PRICING_TRIGGER_BASIS = [
    "sales_progress",
    "inventory",
    "market",
    "traffic",
    "second_conversion",
    "price",
]


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _baseline_package(s15_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(s15_result, Mapping):
        return {}
    payload = _mapping(s15_result.get("baseline")) or dict(s15_result)
    return _mapping(payload.get("baseline_package")) or payload


def _global_health(package: Mapping[str, Any]) -> dict[str, Any]:
    return _mapping(package.get("hour_grid_health"))


def _room_decision_evidence(
    package: Mapping[str, Any],
    room_type_id: str,
) -> dict[str, Any]:
    rooms = _mapping(package.get("room_types"))
    room = _mapping(rooms.get(room_type_id))
    direct = _mapping(room.get("decision_hour_evidence"))
    if direct:
        return direct
    by_room = _mapping(package.get("room_type_decision_hour_evidence"))
    direct = _mapping(by_room.get(room_type_id))
    return direct or _mapping(package.get("decision_hour_evidence"))


def formal_time_evidence_sufficient(
    global_health: Mapping[str, Any],
    decision_evidence: Mapping[str, Any],
) -> bool:
    global_coverage = _n(global_health.get("exact_coverage_ratio"))
    decision_maturity = _text(decision_evidence.get("maturity")).lower()
    return bool(
        global_health.get("status") == "ok"
        and global_coverage is not None
        and global_coverage >= FORMAL_GLOBAL_MIN_COVERAGE
        and decision_evidence.get("status") == "ok"
        and decision_maturity in FORMAL_DECISION_MATURITIES
    )


def limited_preview_time_evidence_sufficient(
    decision_evidence: Mapping[str, Any],
) -> bool:
    sample_count = _n(decision_evidence.get("exact_sample_count"))
    coverage = _n(decision_evidence.get("exact_coverage_ratio"))
    maturity = _text(decision_evidence.get("maturity")).lower()
    return bool(
        decision_evidence.get("status") == "ok"
        and sample_count is not None
        and sample_count >= 3
        and coverage is not None
        and coverage >= 0.40
        and maturity in PREVIEW_DECISION_MATURITIES
    )


def _reset_to_hold(candidate: dict[str, Any], reason: str) -> None:
    """Legacy compatibility helper; v3 never calls it from the time policy."""

    current_price = _n(candidate.get("current_price"))
    for field in (
        "manual_preview_price",
        "manual_preview_change_pct",
        "limited_evidence_preview",
        "limited_preview_version",
        "preview_direction",
    ):
        candidate.pop(field, None)
    candidate.update(
        {
            "price_action": "hold",
            "candidate_price": current_price,
            "conservative_price": current_price,
            "execution_price": current_price,
            "actual_change_pct": 0.0,
            "configured_change_pct": 0.0,
            "action_type": "hold",
            "auto_execution_eligible": False,
            "approval_required": False,
            "handoff_to": None,
            "requires_s6_revalidation": False,
            "eligibility": "preview_only_strong_rule_not_satisfied",
            "blocked_reason": reason,
            "reference_only": True,
            "candidate_strength": "partial",
        }
    )


def _time_blockers(
    global_health: Mapping[str, Any],
    decision_evidence: Mapping[str, Any],
) -> list[str]:
    """Return evidence-quality flags, not S5 pricing blockers."""

    flags: list[str] = []
    global_coverage = _n(global_health.get("exact_coverage_ratio"))
    if global_health.get("status") != "ok" or global_coverage is None:
        flags.append("exact_hour_grid_evidence_missing")
    elif global_coverage < FORMAL_GLOBAL_MIN_COVERAGE:
        flags.append("global_hour_grid_below_formal_threshold")

    if decision_evidence.get("status") != "ok":
        flags.append("decision_hour_evidence_missing")
    else:
        maturity = _text(decision_evidence.get("maturity")).lower()
        if maturity not in FORMAL_DECISION_MATURITIES:
            flags.append("decision_hour_maturity_below_formal_threshold")
        if not limited_preview_time_evidence_sufficient(decision_evidence):
            flags.append("decision_hour_evidence_insufficient_for_preview")
    return flags


def _time_confidence(*, formal_ok: bool, limited_ok: bool) -> str:
    if formal_ok:
        return "formal"
    if limited_ok:
        return "limited"
    return "weak"


def _sanitize_legacy_s15_causality(
    candidate: dict[str, Any],
    *,
    quality_flags: list[str],
) -> list[str]:
    """Move legacy S15 causal fields into advisory quality metadata.

    Older S5 layers used S15 maturity/time evidence in ``limited_preview_blockers``
    and ``blocked_reason``. Leaving those values in causal fields lets downstream
    renderers or agents incorrectly explain a HOLD as caused by S15. V3 removes
    those codes from causal fields while preserving them as quality evidence.
    """

    migrated: list[str] = []
    business_blockers: list[str] = []
    for value in candidate.get("limited_preview_blockers") or []:
        code = _text(value)
        if not code:
            continue
        if code in S15_ADVISORY_CODES:
            migrated.append(code)
        else:
            business_blockers.append(code)
    candidate["limited_preview_blockers"] = business_blockers

    blocked_reason = _text(candidate.get("blocked_reason"))
    if blocked_reason in S15_ADVISORY_CODES:
        migrated.append(blocked_reason)
        if candidate.get("strong_pricing_rule_status") == "triggered":
            candidate.pop("blocked_reason", None)
        else:
            candidate["blocked_reason"] = "strong_pricing_rule_not_satisfied"

    return list(dict.fromkeys([*migrated, *quality_flags]))


def _rebuild_decision_ref(
    candidate: dict[str, Any],
    *,
    result: Mapping[str, Any],
) -> None:
    """Legacy hook retained for patches that replace this function."""

    from runtime.algorithms.revenue_decision_engine import build_s5_decision_ref

    candidate["decision_ref"] = build_s5_decision_ref(
        candidate,
        freshness_status=result.get("freshness_status"),
        business_date=result.get("target_stay_date"),
        hotel_id=result.get("hotel_id"),
        guard_version=str(
            candidate.get("price_guard_policy_version")
            or "s5-time-evidence-policy-v3"
        ),
        price_guard_policy_id=candidate.get("price_guard_policy_id"),
    )


def apply_s5_time_evidence_policy(
    result: Mapping[str, Any],
    *,
    s15_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Attach S15 hour evidence without changing the S5 business decision.

    Sales progress, inventory, market, traffic, conversion and price evidence
    decide HOLD / raise / lower. Hour-grid evidence only describes confidence;
    execution safety remains an S6 responsibility.
    """

    copied = dict(result)
    package = _baseline_package(s15_result)
    global_health = _global_health(package)
    candidates = [
        dict(item)
        for item in (copied.get("candidates") or [])
        if isinstance(item, Mapping)
    ]

    for candidate in candidates:
        room_type_id = _text(candidate.get("room_type_id"))
        decision = _room_decision_evidence(package, room_type_id)
        formal_ok = formal_time_evidence_sufficient(global_health, decision)
        limited_ok = limited_preview_time_evidence_sufficient(decision)
        quality_flags = _sanitize_legacy_s15_causality(
            candidate,
            quality_flags=_time_blockers(global_health, decision),
        )
        candidate.update(
            {
                "s15_hour_grid_health": dict(global_health),
                "s15_decision_hour_evidence": dict(decision),
                "formal_time_evidence_sufficient": formal_ok,
                "limited_preview_time_evidence_sufficient": limited_ok,
                "s15_time_evidence_advisory_only": True,
                "s15_time_evidence_role": "confidence_only",
                "s15_time_evidence_can_block_s5": False,
                "s15_time_evidence_confidence": _time_confidence(
                    formal_ok=formal_ok,
                    limited_ok=limited_ok,
                ),
                "s15_time_evidence_quality_flags": quality_flags,
                "s5_pricing_trigger_basis": list(S5_PRICING_TRIGGER_BASIS),
            }
        )

    copied["candidates"] = candidates
    copied["s5_time_evidence_policy_version"] = VERSION
    copied["s5_time_evidence_advisory_only"] = True
    copied["s15_time_evidence_role"] = "confidence_only"
    copied["s15_time_evidence_can_block_s5"] = False
    copied["s5_pricing_trigger_basis"] = list(S5_PRICING_TRIGGER_BASIS)
    copied["s15_hour_grid_health"] = dict(global_health)
    copied["s15_decision_hour_evidence"] = _mapping(
        package.get("decision_hour_evidence")
    )
    copied["formal_global_hour_grid_min_coverage"] = (
        FORMAL_GLOBAL_MIN_COVERAGE
    )
    copied["formal_decision_hour_maturities"] = sorted(
        FORMAL_DECISION_MATURITIES
    )
    copied["limited_preview_decision_hour_maturities"] = sorted(
        PREVIEW_DECISION_MATURITIES
    )
    copied["limited_evidence_preview_count"] = sum(
        bool(item.get("limited_evidence_preview")) for item in candidates
    )
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
    if getattr(previous_build, "_S5_TIME_EVIDENCE_POLICY_V3", False):
        return

    def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = previous_build(*args, **kwargs)
        return apply_s5_time_evidence_policy(
            result,
            s15_result=kwargs.get("s15_result"),
        )

    build_s5_real_candidates._S5_TIME_EVIDENCE_POLICY_V3 = True  # type: ignore[attr-defined]
    s5_module.build_s5_real_candidates = build_s5_real_candidates

    router = sys.modules.get("runtime.feishu_command_router")
    if router is not None and hasattr(router, "build_s5_real_candidates"):
        router.build_s5_real_candidates = build_s5_real_candidates

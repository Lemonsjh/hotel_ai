from __future__ import annotations

import copy
import sys
from collections import Counter
from typing import Any, Mapping


_INSTALLED = False
VERSION = "s5-no-price-guard.v1"
SINGLE_CHANGE_HARD_CAP = 0.10
_ORIGINAL_PRODUCT_EVIDENCE: Any = None

_GUARD_BLOCKERS = {
    "price_guard_invalid",
    "price_guard_not_configured",
    "price_guard_incomplete",
    "active_price_guard_policy_required_before_s6",
    "no_raise_price_headroom",
    "no_decrease_price_headroom",
    "raise_target_clamped_to_current_price",
    "lower_target_clamped_to_current_price",
}
_GUARD_FIELDS = {
    "price_guard_source",
    "price_guard_policy_id",
    "price_guard_policy_version",
    "price_guard_policy_state",
    "price_guard_status",
    "guard_version",
    "guard_valid",
    "configured_floor_price",
    "configured_ceiling_price",
    "configured_price_floor",
    "configured_price_ceiling",
    "effective_price_floor",
    "effective_price_ceiling",
    "floor_price",
    "ceiling_price",
    "max_single_change_pct",
    "max_increase_pct",
    "max_decrease_pct",
    "min_increase_pct",
    "min_decrease_pct",
}
_GUARD_TOP_LEVEL_FIELDS = {
    "price_guard_statuses",
    "price_guard_summary",
    "price_guard_policy",
    "pending_configuration_requests",
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


def _is_guard_marker(value: Any) -> bool:
    text = _text(value).lower()
    return bool(
        text in _GUARD_BLOCKERS
        or "price_guard" in text
        or "guard_preview" in text
        or "default_guard" in text
        or "mapping_and_guard" in text
        or "effective_price_floor_respected" in text
        or "护栏" in text
    )


def _no_price_guard_policy(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Supply algorithm movement limits without reading guard storage."""

    return {
        "source": "s5_no_price_guard",
        "policy_id": None,
        "version": VERSION,
        "policy_state": "not_used",
        "floor_price": None,
        "ceiling_price": None,
        "max_increase_pct": SINGLE_CHANGE_HARD_CAP,
        "max_decrease_pct": SINGLE_CHANGE_HARD_CAP,
        "min_increase_pct": 0.0,
        "min_decrease_pct": 0.0,
    }


def _product_evidence_without_guard(
    candidate: Mapping[str, Any],
    product_row: Mapping[str, Any],
    s15_result: Mapping[str, Any] | None,
    s16_result: Mapping[str, Any] | None,
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    """Keep historical-price evidence, but replace guard bounds with algo cap."""

    if _ORIGINAL_PRODUCT_EVIDENCE is None:
        raise RuntimeError("s5 original product evidence is unavailable")
    evidence = dict(
        _ORIGINAL_PRODUCT_EVIDENCE(
            candidate,
            product_row,
            s15_result,
            s16_result,
            thresholds,
        )
    )
    current_price = _n(candidate.get("current_price")) or 0.0
    configured_cap = _n(thresholds.get("single_change_hard_cap"))
    hard_cap = min(
        max(configured_cap or SINGLE_CHANGE_HARD_CAP, 0.0),
        SINGLE_CHANGE_HARD_CAP,
    )
    p80_raw = _n(evidence.get("baseline_price_p80_raw_equivalent"))
    estimated_net = _n(evidence.get("estimated_activity_net_price"))
    p80_net_ceiling = _n(evidence.get("raise_net_revenue_ceiling"))
    effective_ceiling = round(current_price * (1.0 + hard_cap), 2)
    if p80_raw is not None:
        effective_ceiling = min(effective_ceiling, p80_raw * 0.98)
    evidence.update(
        {
            # Compatibility values used only by the existing strong-rule
            # arithmetic. They are algorithm limits, not price guards.
            "configured_price_floor": None,
            "configured_price_ceiling": None,
            "effective_price_floor": 0.0,
            "effective_price_ceiling": effective_ceiling,
            "raise_price_has_headroom": bool(
                estimated_net is not None
                and p80_net_ceiling is not None
                and estimated_net < p80_net_ceiling
            ),
            "guard_valid": True,
            "product_healthy": bool(
                evidence.get("product_sellable")
                and evidence.get("mapping_valid")
            ),
            "price_guard_applied": False,
            "pricing_bound_source": (
                "algorithm_single_change_hard_cap_only"
            ),
            "algorithm_single_change_hard_cap": hard_cap,
        }
    )
    return evidence


def _decision_ref_without_guard(
    candidate: dict[str, Any],
    *,
    result: Mapping[str, Any],
    hotel_id: str | None = None,
    target_stay_date: str | None = None,
) -> None:
    from runtime.safety.payload_hash import payload_hash

    resolved_hotel_id = _text(hotel_id or result.get("hotel_id")) or None
    resolved_target_stay_date = (
        _text(target_stay_date or result.get("target_stay_date"))[:10]
        or None
    )
    payload = {
        "hotel_id": resolved_hotel_id,
        "room_type_id": candidate.get("room_type_id"),
        "channel": candidate.get("channel"),
        "ota_product_id": candidate.get("ota_product_id"),
        "old_price": candidate.get("current_price"),
        "candidate_price": candidate.get("candidate_price"),
        "execution_price": candidate.get("execution_price"),
        "single_change_hard_cap": SINGLE_CHANGE_HARD_CAP,
        "begin_date": resolved_target_stay_date,
        "end_date": resolved_target_stay_date,
        "freshness_status": result.get("freshness_status"),
        "pricing_rule_version": VERSION,
    }
    output_hash = payload_hash(payload, tuple(payload))
    room_id = _text(candidate.get("room_type_id")) or "room"
    candidate["decision_ref"] = {
        "decision_id": f"s5-{room_id.lower()}-{output_hash[:12]}",
        "output_hash": output_hash,
        **payload,
    }


def _without_guard_fields(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in values.items()
        if key not in _GUARD_FIELDS
        and not key.startswith("price_guard_")
        and not _is_guard_marker(key)
    }


def _scrub_trace(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    result = _without_guard_fields(value)
    result["price_bound_adjusted"] = False
    result["pricing_bound_source"] = (
        "algorithm_single_change_hard_cap_only"
    )
    return result


def scrub_candidate_guard_references(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    copied = copy.deepcopy(dict(candidate))
    for key in list(copied):
        if key in _GUARD_FIELDS or key.startswith("price_guard_"):
            copied.pop(key, None)

    for field in (
        "limited_preview_blockers",
        "blocked_reasons",
        "missing_rule_evidence",
        "reason_codes",
    ):
        values = copied.get(field)
        if isinstance(values, list):
            copied[field] = [
                item for item in values if not _is_guard_marker(item)
            ]

    quality = copied.get("quality_flags")
    if isinstance(quality, list):
        copied["quality_flags"] = [
            item for item in quality if not _is_guard_marker(item)
        ]

    if copied.get("eligibility") == "preview_only_default_guard":
        copied["eligibility"] = "preview_only_strong_rule_not_satisfied"
    if _is_guard_marker(copied.get("blocked_reason")):
        copied["blocked_reason"] = "strong_pricing_rule_not_satisfied"
    if copied.get("candidate_strength") == "partial" and (
        copied.get("strong_pricing_rule_status") == "triggered"
        and copied.get("formal_time_evidence_sufficient") is True
    ):
        copied["candidate_strength"] = "full"

    if isinstance(copied.get("calculation_trace"), Mapping):
        copied["calculation_trace"] = _scrub_trace(
            copied["calculation_trace"]
        )
    if isinstance(copied.get("decision_ref"), Mapping):
        copied["decision_ref"] = _without_guard_fields(
            copied["decision_ref"]
        )

    copied["pricing_bound_source"] = (
        "algorithm_single_change_hard_cap_only"
    )
    copied["algorithm_single_change_hard_cap"] = (
        SINGLE_CHANGE_HARD_CAP
    )
    copied["limited_preview_evidence_complete"] = not bool(
        copied.get("limited_preview_blockers")
    )
    return copied


def scrub_s5_result_guard_references(
    result: Mapping[str, Any],
) -> dict[str, Any]:
    copied = copy.deepcopy(dict(result))
    for key in list(copied):
        if key in _GUARD_TOP_LEVEL_FIELDS or key.startswith("price_guard_"):
            copied.pop(key, None)

    candidates = [
        scrub_candidate_guard_references(item)
        for item in copied.get("candidates") or []
        if isinstance(item, Mapping)
    ]
    copied["candidates"] = candidates

    quality = copied.get("quality_flags")
    if isinstance(quality, list):
        copied["quality_flags"] = [
            item for item in quality if not _is_guard_marker(item)
        ]

    counts: Counter[str] = Counter()
    for candidate in candidates:
        counts.update(candidate.get("limited_preview_blockers") or [])
    copied["limited_preview_blocker_counts"] = dict(sorted(counts.items()))
    copied["eligible_for_s6_count"] = sum(
        bool(item.get("auto_execution_eligible"))
        and item.get("eligibility") == "eligible_for_s6_dry_run"
        for item in candidates
    )
    copied["limited_evidence_preview_count"] = sum(
        bool(item.get("limited_evidence_preview"))
        for item in candidates
    )
    copied["s5_pricing_bound_source"] = (
        "algorithm_single_change_hard_cap_only"
    )
    copied["s5_algorithm_single_change_hard_cap"] = (
        SINGLE_CHANGE_HARD_CAP
    )
    copied["s5_no_price_guard_version"] = VERSION
    return copied


def _render_without_guard(previous: Any, result: Mapping[str, Any]) -> str:
    text = previous(scrub_s5_result_guard_references(result))
    output: list[str] = []
    for line in str(text).splitlines():
        stripped = line.strip()
        if stripped.startswith("- 护栏：") or stripped.startswith("护栏："):
            continue
        line = line.replace(
            "参与调价写入、价格护栏或审批",
            "参与调价写入或审批",
        ).replace(
            "参与调价写入 / 护栏 / 审批",
            "参与调价写入或审批",
        )
        output.append(line)
    return "\n".join(output)


def install() -> None:
    global _INSTALLED, _ORIGINAL_PRODUCT_EVIDENCE
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s5_strong_pricing_rules_patch as strong
    from runtime import s5_time_evidence_policy_patch as time_policy
    from runtime.algorithms import s5_real_candidates as s5_candidates
    from runtime.algorithms import s5_real_reply as s5_reply

    if _ORIGINAL_PRODUCT_EVIDENCE is None:
        _ORIGINAL_PRODUCT_EVIDENCE = strong._product_evidence
    strong._product_evidence = _product_evidence_without_guard
    strong._rebuild_decision_ref = _decision_ref_without_guard
    time_policy._rebuild_decision_ref = _decision_ref_without_guard

    previous_build = s5_candidates.build_s5_real_candidates
    if not getattr(previous_build, "_S5_NO_PRICE_GUARD_V1", False):
        def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
            call_kwargs = dict(kwargs)
            call_kwargs["resolve_guard"] = _no_price_guard_policy
            built = previous_build(*args, **call_kwargs)
            return scrub_s5_result_guard_references(built)

        build_s5_real_candidates._S5_NO_PRICE_GUARD_V1 = True  # type: ignore[attr-defined]
        s5_candidates.build_s5_real_candidates = build_s5_real_candidates

        router = sys.modules.get("runtime.feishu_command_router")
        if router is not None and hasattr(router, "build_s5_real_candidates"):
            router.build_s5_real_candidates = build_s5_real_candidates

    previous_render = s5_reply.render_s5_real_reply
    if not getattr(previous_render, "_S5_NO_PRICE_GUARD_V1", False):
        def render_s5_real_reply(result: dict[str, Any]) -> str:
            return _render_without_guard(previous_render, result)

        render_s5_real_reply._S5_NO_PRICE_GUARD_V1 = True  # type: ignore[attr-defined]
        s5_reply.render_s5_real_reply = render_s5_real_reply

        renderer = sys.modules.get("runtime.feishu_output_renderer")
        if renderer is not None and hasattr(renderer, "render_s5_real_reply"):
            renderer.render_s5_real_reply = render_s5_real_reply

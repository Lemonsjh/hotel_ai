from __future__ import annotations

import sys
from collections import Counter
from typing import Any, Mapping


_INSTALLED = False
VERSION = "s5-market-heat-contract.v2"
FORMULA = "market_orders / baseline_market_orders"
DEFAULT_NOT_COLD_THRESHOLD = 0.90
DEFAULT_HOT_THRESHOLD = 1.10
_MARKET_BLOCKERS = {
    "market_not_cold_evidence_missing",
    "market_heat_evidence_missing",
    "market_heat_below_not_cold_threshold",
    "market_heat_period_not_comparable",
}


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _n(value)
        if number is not None:
            return number
    return None


def _explicit_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "allowed"}:
        return True
    if text in {"0", "false", "no", "n", "blocked", "not_allowed"}:
        return False
    return None


def _dynamic(s16_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(s16_result, Mapping):
        return {}
    nested = s16_result.get("dynamic_diagnosis")
    return _mapping(nested) or dict(s16_result)


def _comparison_allowed(
    source: Mapping[str, Any],
) -> tuple[bool, str | None]:
    allowed = _explicit_bool(source.get("comparison_allowed"))
    status = str(source.get("status") or "").strip().lower()
    if allowed is False or status in {
        "period_not_comparable",
        "not_comparable",
        "time_basis_mismatch",
    }:
        return False, "market_period_not_comparable"
    return True, None


def _recomputed_market_evidence(
    s16_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the only S5 market-heat contract.

    S5 never infers market heat from a prose/status label. It requires a
    current or projected market-order numerator, a positive historical
    market-order baseline, and an upstream comparable-period signal before
    division.
    """

    dynamic = _dynamic(s16_result)
    market = _mapping(dynamic.get("market"))
    proxy = _mapping(dynamic.get("meituan_market_proxy"))
    projection = _mapping(proxy.get("market_projection"))

    current_orders = _first_number(
        market.get("market_orders"),
        market.get("current_market_orders"),
        market.get("current_estimated_market_orders"),
        market.get("estimated_market_orders"),
    )
    projected_orders = _first_number(
        projection.get("market_orders"),
        projection.get("projected_market_orders"),
        projection.get("estimated_market_orders"),
    )
    current_allowed, current_reason = _comparison_allowed(market)
    projection_allowed, projection_reason = _comparison_allowed(projection)

    if current_orders is not None and current_allowed:
        market_orders = current_orders
        evidence_source = market
        comparison_allowed = True
        comparison_reason = None
        market_orders_basis = "current_market_orders"
    elif projected_orders is not None and projection_allowed:
        market_orders = projected_orders
        evidence_source = projection
        comparison_allowed = True
        comparison_reason = None
        market_orders_basis = "market_projection"
    elif current_orders is not None:
        market_orders = current_orders
        evidence_source = market
        comparison_allowed = False
        comparison_reason = current_reason or "market_period_not_comparable"
        market_orders_basis = "current_market_orders"
    else:
        market_orders = projected_orders
        evidence_source = projection
        comparison_allowed = projection_allowed
        comparison_reason = projection_reason
        market_orders_basis = "market_projection"

    baseline_market_orders = _first_number(
        market.get("baseline_market_orders"),
        market.get("baseline_median"),
        market.get("historical_market_orders"),
        projection.get("baseline_market_orders"),
        projection.get("baseline_median"),
        projection.get("history_median"),
    )

    common = {
        "market_heat_contract_version": VERSION,
        "market_heat_formula": FORMULA,
        "market_orders": market_orders,
        "baseline_market_orders": baseline_market_orders,
        "market_orders_basis": market_orders_basis,
        "market_comparison_allowed": comparison_allowed,
        "market_comparison_basis": evidence_source.get("comparison_basis"),
        "market_evidence_source": "s16_market_orders_vs_baseline_market_orders",
    }
    if market_orders is None:
        return {
            **common,
            "market_heat_ratio": None,
            "market_status": "unavailable",
            "market_heat_calculation_status": "unavailable",
            "market_heat_calculation_reason": "market_orders_missing",
        }
    if baseline_market_orders is None:
        return {
            **common,
            "market_heat_ratio": None,
            "market_status": "unavailable",
            "market_heat_calculation_status": "unavailable",
            "market_heat_calculation_reason": "baseline_market_orders_missing",
        }
    if baseline_market_orders <= 0:
        return {
            **common,
            "market_heat_ratio": None,
            "market_status": "unavailable",
            "market_heat_calculation_status": "unavailable",
            "market_heat_calculation_reason": "baseline_market_orders_non_positive",
        }
    if not comparison_allowed:
        return {
            **common,
            "market_heat_ratio": None,
            "market_status": "period_not_comparable",
            "market_heat_calculation_status": "unavailable",
            "market_heat_calculation_reason": (
                comparison_reason or "market_period_not_comparable"
            ),
        }

    ratio = market_orders / baseline_market_orders
    status = (
        "cold"
        if ratio < DEFAULT_NOT_COLD_THRESHOLD
        else "hot"
        if ratio >= DEFAULT_HOT_THRESHOLD
        else "normal"
    )
    position = (
        "below_history"
        if ratio < DEFAULT_NOT_COLD_THRESHOLD
        else "above_history"
        if ratio >= DEFAULT_HOT_THRESHOLD
        else "near_history"
    )
    return {
        **common,
        "market_heat_ratio": ratio,
        "market_status": status,
        "market_heat_position": position,
        "market_heat_calculation_status": "ok",
        "market_heat_calculation_reason": None,
    }


def deterministic_market_evidence(
    s16_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Consume S16's comparable market conclusion without recomputation."""

    from runtime.s5_s16_market_heat_sync_patch import (
        s5_market_evidence_from_s16,
    )

    return s5_market_evidence_from_s16(s16_result)


def _market_threshold() -> float:
    try:
        from runtime import s5_strong_pricing_rules_patch as strong

        return float(
            strong._thresholds().get(
                "market_not_cold_ratio", DEFAULT_NOT_COLD_THRESHOLD
            )
        )
    except Exception:
        return DEFAULT_NOT_COLD_THRESHOLD


def _finalize_market_fields(
    evidence: Mapping[str, Any],
    *,
    threshold: float,
) -> dict[str, Any]:
    result = dict(evidence)
    ratio = _n(result.get("market_heat_ratio"))
    result["market_not_cold_threshold"] = threshold
    result["market_not_cold"] = bool(
        result.get("market_heat_calculation_status") == "ok"
        and ratio is not None
        and ratio >= threshold
    )
    return result


def _replace_market_blocker(
    blockers: list[str],
    candidate: Mapping[str, Any],
) -> list[str]:
    had_market_blocker = any(
        str(blocker) in _MARKET_BLOCKERS for blocker in blockers
    )
    result = [
        str(blocker)
        for blocker in blockers
        if str(blocker) not in _MARKET_BLOCKERS
    ]
    if not had_market_blocker:
        return list(dict.fromkeys(result))

    reason = str(candidate.get("market_heat_calculation_reason") or "")
    if reason == "market_period_not_comparable":
        result.append("market_heat_period_not_comparable")
    elif candidate.get("market_heat_calculation_status") != "ok":
        result.append("market_heat_evidence_missing")
    elif candidate.get("market_not_cold") is not True:
        result.append("market_heat_below_not_cold_threshold")
    return list(dict.fromkeys(result))


def _refresh_candidate_market_blockers(candidate: dict[str, Any]) -> None:
    blockers = candidate.get("limited_preview_blockers")
    if not isinstance(blockers, list):
        return
    refreshed = _replace_market_blocker(blockers, candidate)
    candidate["limited_preview_blockers"] = refreshed
    candidate["limited_preview_evidence_complete"] = not refreshed


def _refresh_blocker_summary(
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> None:
    counts: Counter[str] = Counter()
    for candidate in candidates:
        _refresh_candidate_market_blockers(candidate)
        counts.update(
            str(item)
            for item in (candidate.get("limited_preview_blockers") or [])
        )
    result["limited_preview_blocker_counts"] = dict(sorted(counts.items()))


def _fmt_number(value: Any) -> str:
    number = _n(value)
    if number is None:
        return "-"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _market_order_label(evidence: Mapping[str, Any]) -> str:
    if evidence.get("market_orders_basis") == "market_projection":
        return "预计全天大盘订单"
    return "当前大盘订单"


def _recomputed_market_line(result: Mapping[str, Any]) -> str:
    evidence = _mapping(result.get("s5_market_heat"))
    if not evidence:
        candidates = result.get("candidates") or []
        if (
            isinstance(candidates, list)
            and candidates
            and isinstance(candidates[0], Mapping)
        ):
            evidence = dict(candidates[0])

    threshold = _n(evidence.get("market_not_cold_threshold"))
    if threshold is None:
        threshold = DEFAULT_NOT_COLD_THRESHOLD
    order_label = _market_order_label(evidence)
    if evidence.get("market_heat_calculation_status") != "ok":
        reason = str(
            evidence.get("market_heat_calculation_reason")
            or "market_heat_evidence_missing"
        )
        if reason == "market_period_not_comparable":
            return (
                "大盘热度：暂不可用于定价（"
                f"{order_label} {_fmt_number(evidence.get('market_orders'))} "
                "与历史基线订单 "
                f"{_fmt_number(evidence.get('baseline_market_orders'))} "
                "的时间口径不可比）；当前值不判定为大盘偏冷。"
            )
        labels = {
            "market_orders_missing": "缺少当前或预计大盘订单",
            "baseline_market_orders_missing": "缺少历史基线订单",
            "baseline_market_orders_non_positive": "历史基线订单必须大于 0",
        }
        return (
            "大盘热度：不可计算（"
            f"{labels.get(reason, reason)}）；这是数据缺失，不等同于大盘偏冷。"
        )

    ratio = _n(evidence.get("market_heat_ratio"))
    status_label = {
        "cold": "低于历史基线",
        "normal": "接近历史基线",
        "hot": "高于历史基线",
    }.get(str(evidence.get("market_status") or ""), "-")
    return (
        f"大盘热度：{ratio:.2f}（{order_label} "
        f"{_fmt_number(evidence.get('market_orders'))} ÷ 历史基线订单 "
        f"{_fmt_number(evidence.get('baseline_market_orders'))}）；"
        f"状态：{status_label}；市场不冷："
        f"{'是' if evidence.get('market_not_cold') else '否'}"
        f"（门槛 ≥{threshold:.2f}）。"
    )


def _market_line(result: Mapping[str, Any]) -> str:
    from runtime.s5_s16_market_heat_sync_patch import s5_market_line

    return s5_market_line(result)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s5_evidence_contract_patch as evidence_module
    from runtime import s5_strong_pricing_rules_patch as strong_module
    from runtime.algorithms import s5_real_candidates as s5_module
    from runtime.algorithms import s5_real_reply as reply_module

    # The strong-rule evaluator resolves this module global at call time, so
    # replacing it makes formal decisions and limited previews share the same
    # comparable-period market contract.
    strong_module._market_evidence = deterministic_market_evidence

    previous_blockers = evidence_module._preview_blockers
    if not getattr(previous_blockers, "_S5_MARKET_HEAT_CONTRACT_V2", False):

        def preview_blockers(*args: Any, **kwargs: Any) -> list[str]:
            candidate = args[0] if args else kwargs.get("candidate") or {}
            blockers = previous_blockers(*args, **kwargs)
            return _replace_market_blocker(blockers, candidate)

        preview_blockers._S5_MARKET_HEAT_CONTRACT_V2 = True  # type: ignore[attr-defined]
        evidence_module._preview_blockers = preview_blockers

    previous_build = s5_module.build_s5_real_candidates
    if not getattr(previous_build, "_S5_MARKET_HEAT_CONTRACT_V2", False):

        def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
            result = previous_build(*args, **kwargs)
            threshold = _market_threshold()
            market = _finalize_market_fields(
                deterministic_market_evidence(kwargs.get("s16_result")),
                threshold=threshold,
            )
            copied = dict(result)
            candidates = [
                dict(item)
                for item in (copied.get("candidates") or [])
                if isinstance(item, Mapping)
            ]
            for candidate in candidates:
                candidate.update(market)
            copied["candidates"] = candidates
            _refresh_blocker_summary(copied, candidates)
            copied["s5_market_heat"] = market
            copied["s5_market_heat_contract_version"] = VERSION
            copied["s5_market_heat_formula"] = FORMULA
            return copied

        build_s5_real_candidates._S5_MARKET_HEAT_CONTRACT_V2 = True  # type: ignore[attr-defined]
        s5_module.build_s5_real_candidates = build_s5_real_candidates

        router = sys.modules.get("runtime.feishu_command_router")
        if router is not None and hasattr(router, "build_s5_real_candidates"):
            router.build_s5_real_candidates = build_s5_real_candidates

    reply_module.BLOCKER_LABELS.update(
        {
            "market_heat_evidence_missing": "缺少当前大盘订单或历史基线订单",
            "market_heat_below_not_cold_threshold": "大盘热度低于市场不冷门槛",
            "market_heat_period_not_comparable": "当前大盘订单与历史基线时间口径不可比",
        }
    )
    previous_render = reply_module.render_s5_real_reply
    if not getattr(previous_render, "_S5_MARKET_HEAT_CONTRACT_V2", False):

        def render_s5_real_reply(result: dict[str, Any]) -> str:
            text = previous_render(result)
            line = _market_line(result)
            rows = text.splitlines()
            insert_at = next(
                (
                    index + 1
                    for index, value in enumerate(rows)
                    if value.strip() == "当前经营信号"
                ),
                min(4, len(rows)),
            )
            rows.insert(insert_at, line)
            return "\n".join(rows)

        render_s5_real_reply._S5_MARKET_HEAT_CONTRACT_V2 = True  # type: ignore[attr-defined]
        reply_module.render_s5_real_reply = render_s5_real_reply

        output_renderer = sys.modules.get("runtime.feishu_output_renderer")
        if output_renderer is not None and hasattr(
            output_renderer, "render_s5_real_reply"
        ):
            output_renderer.render_s5_real_reply = render_s5_real_reply

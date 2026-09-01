from __future__ import annotations

import sys
from typing import Any, Mapping


_INSTALLED = False
VERSION = "s5-s16-linear-market-heat-sync.v1"
PROJECTION_METHOD = "linear_day_pace_reference"
COMPARISON_BASIS = "linear_projected_full_day_vs_historical_full_day"
PROJECTION_FORMULA = (
    "(current_market_orders / elapsed_day_fraction) "
    "/ historical_full_day_market_orders"
)
DAILY_FORMULA = (
    "completed_daily_market_orders / historical_full_day_market_orders"
)
DEFAULT_NOT_COLD_THRESHOLD = 0.90
DEFAULT_HOT_THRESHOLD = 1.10
MIN_ELAPSED_DAY_FRACTION = 0.35


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
    if text in {
        "0",
        "false",
        "no",
        "n",
        "blocked",
        "not_allowed",
    }:
        return False
    return None


def _status_from_ratio(ratio: float) -> str:
    if ratio < DEFAULT_NOT_COLD_THRESHOLD:
        return "cold"
    if ratio >= DEFAULT_HOT_THRESHOLD:
        return "hot"
    return "normal"


def _position_from_status(status: str) -> str:
    return {
        "cold": "below_history",
        "normal": "near_history",
        "hot": "above_history",
    }.get(status, "unavailable")


def _legacy_projection_status(ratio: float) -> str:
    if ratio >= 1.05:
        return "likely_above_history"
    if ratio >= 0.95:
        return "near_history"
    return "likely_below_history"


def _projection_unavailable(
    *,
    reason: str,
    current_market_orders: float | None,
    baseline_market_orders: float | None,
    elapsed_day_fraction: float | None,
) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "market_status": "unavailable",
        "projected_full_day": None,
        "projected_market_orders": None,
        "projected_ratio_vs_history": None,
        "projected_market_heat_ratio": None,
        "market_heat_ratio": None,
        "current_market_orders": current_market_orders,
        "baseline_market_orders": baseline_market_orders,
        "elapsed_day_fraction": elapsed_day_fraction,
        "comparison_allowed": False,
        "comparison_basis": COMPARISON_BASIS,
        "comparison_reason": reason,
        "projection_method": PROJECTION_METHOD,
        "projection_confidence": "linear_reference",
        "market_orders_basis": "s16_linear_projected_full_day",
        "market_heat_formula": PROJECTION_FORMULA,
        "market_heat_calculation_status": "unavailable",
        "market_heat_calculation_reason": reason,
        "market_not_cold_threshold": DEFAULT_NOT_COLD_THRESHOLD,
        "market_not_cold": False,
        "linear_projection_only": True,
        "contract_version": VERSION,
    }


def build_linear_market_projection(
    current: Any,
    baseline: Any,
    elapsed: float | None,
) -> dict[str, Any]:
    """Build S16's comparable full-day linear market-heat projection."""

    current_value = _n(current)
    baseline_value = _n(baseline)
    elapsed_value = _n(elapsed)

    if current_value is None:
        return _projection_unavailable(
            reason="current_market_orders_missing",
            current_market_orders=None,
            baseline_market_orders=baseline_value,
            elapsed_day_fraction=elapsed_value,
        )
    if baseline_value is None:
        return _projection_unavailable(
            reason="historical_full_day_market_orders_missing",
            current_market_orders=current_value,
            baseline_market_orders=None,
            elapsed_day_fraction=elapsed_value,
        )
    if baseline_value <= 0:
        return _projection_unavailable(
            reason="historical_full_day_market_orders_non_positive",
            current_market_orders=current_value,
            baseline_market_orders=baseline_value,
            elapsed_day_fraction=elapsed_value,
        )
    if elapsed_value is None:
        return _projection_unavailable(
            reason="elapsed_day_fraction_unavailable",
            current_market_orders=current_value,
            baseline_market_orders=baseline_value,
            elapsed_day_fraction=None,
        )
    if elapsed_value < MIN_ELAPSED_DAY_FRACTION:
        return _projection_unavailable(
            reason="elapsed_day_fraction_below_projection_floor",
            current_market_orders=current_value,
            baseline_market_orders=baseline_value,
            elapsed_day_fraction=elapsed_value,
        )
    if elapsed_value >= 1:
        return _projection_unavailable(
            reason="elapsed_day_fraction_not_intraday",
            current_market_orders=current_value,
            baseline_market_orders=baseline_value,
            elapsed_day_fraction=elapsed_value,
        )

    projected = current_value / elapsed_value
    ratio = projected / baseline_value
    market_status = _status_from_ratio(ratio)

    return {
        "status": _legacy_projection_status(ratio),
        "market_status": market_status,
        "projected_full_day": projected,
        "projected_market_orders": projected,
        "projected_ratio_vs_history": ratio,
        "projected_market_heat_ratio": ratio,
        "market_heat_ratio": ratio,
        "current_market_orders": current_value,
        "baseline_market_orders": baseline_value,
        "elapsed_day_fraction": elapsed_value,
        "comparison_allowed": True,
        "comparison_basis": COMPARISON_BASIS,
        "comparison_reason": None,
        "projection_method": PROJECTION_METHOD,
        "projection_confidence": "linear_reference",
        "market_orders_basis": "s16_linear_projected_full_day",
        "market_heat_formula": PROJECTION_FORMULA,
        "market_heat_calculation_status": "ok",
        "market_heat_calculation_reason": None,
        "market_not_cold_threshold": DEFAULT_NOT_COLD_THRESHOLD,
        "market_not_cold": ratio >= DEFAULT_NOT_COLD_THRESHOLD,
        "linear_projection_only": True,
        "contract_version": VERSION,
    }


def _dynamic(s16_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(s16_result, Mapping):
        return {}
    nested = s16_result.get("dynamic_diagnosis")
    return _mapping(nested) or dict(s16_result)


def _projection_market_evidence(
    projection: Mapping[str, Any],
    proxy: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not projection:
        return None

    comparison_allowed = _explicit_bool(projection.get("comparison_allowed"))
    calculation_status = str(
        projection.get("market_heat_calculation_status") or ""
    ).strip().lower()
    ratio = _first_number(
        projection.get("projected_market_heat_ratio"),
        projection.get("market_heat_ratio"),
        projection.get("projected_ratio_vs_history"),
    )
    projected_orders = _first_number(
        projection.get("projected_market_orders"),
        projection.get("projected_full_day"),
    )
    baseline_orders = _first_number(
        projection.get("baseline_market_orders"),
        proxy.get("baseline_market_orders"),
    )
    current_orders = _first_number(
        projection.get("current_market_orders"),
        proxy.get("current_estimated_market_orders"),
    )

    if (
        comparison_allowed is not True
        or calculation_status == "unavailable"
        or ratio is None
    ):
        return None

    market_status = str(
        projection.get("market_status") or ""
    ).strip().lower()
    if market_status not in {"cold", "normal", "hot"}:
        market_status = _status_from_ratio(ratio)

    return {
        "market_heat_contract_version": VERSION,
        "market_heat_formula": (
            projection.get("market_heat_formula") or PROJECTION_FORMULA
        ),
        "market_orders": projected_orders,
        "current_market_orders": current_orders,
        "baseline_market_orders": baseline_orders,
        "elapsed_day_fraction": _n(
            projection.get("elapsed_day_fraction")
        ),
        "market_orders_basis": "s16_linear_projected_full_day",
        "market_comparison_allowed": True,
        "market_comparison_basis": (
            projection.get("comparison_basis") or COMPARISON_BASIS
        ),
        "market_projection_method": (
            projection.get("projection_method") or PROJECTION_METHOD
        ),
        "market_projection_confidence": (
            projection.get("projection_confidence")
            or "linear_reference"
        ),
        "market_projection_linear_only": (
            projection.get("linear_projection_only") is not False
        ),
        "market_evidence_source": (
            "s16.meituan_market_proxy.market_projection"
        ),
        "market_heat_ratio": ratio,
        "market_status": market_status,
        "market_heat_position": _position_from_status(market_status),
        "market_heat_calculation_status": "ok",
        "market_heat_calculation_reason": None,
    }


def _completed_daily_market_evidence(
    market: Mapping[str, Any],
) -> dict[str, Any] | None:
    if not market:
        return None
    if _explicit_bool(market.get("comparison_allowed")) is not True:
        return None

    ratio = _n(market.get("market_heat_ratio"))
    if ratio is None:
        return None

    market_status = _status_from_ratio(ratio)
    market_orders = _first_number(
        market.get("market_orders"),
        market.get("current_market_orders"),
        market.get("current_estimated_market_orders"),
        market.get("estimated_market_orders"),
    )
    return {
        "market_heat_contract_version": VERSION,
        "market_heat_formula": DAILY_FORMULA,
        "market_orders": market_orders,
        "current_market_orders": market_orders,
        "baseline_market_orders": _first_number(
            market.get("baseline_market_orders"),
            market.get("baseline_median"),
            market.get("historical_market_orders"),
        ),
        "market_orders_basis": "s16_completed_daily_market",
        "market_comparison_allowed": True,
        "market_comparison_basis": (
            market.get("comparison_basis")
            or "completed_daily_vs_historical_full_day"
        ),
        "market_evidence_source": "s16.dynamic_diagnosis.market",
        "market_heat_ratio": ratio,
        "market_status": market_status,
        "market_heat_position": _position_from_status(market_status),
        "market_heat_calculation_status": "ok",
        "market_heat_calculation_reason": None,
    }


def s5_market_evidence_from_s16(
    s16_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Consume S16's market result without recomputing its heat ratio."""

    dynamic = _dynamic(s16_result)
    market = _mapping(dynamic.get("market"))
    proxy = _mapping(dynamic.get("meituan_market_proxy"))
    projection = _mapping(proxy.get("market_projection"))

    projected = _projection_market_evidence(projection, proxy)
    if projected is not None:
        return projected

    completed = _completed_daily_market_evidence(market)
    if completed is not None:
        return completed

    projection_reason = str(
        projection.get("market_heat_calculation_reason")
        or projection.get("comparison_reason")
        or ""
    ).strip()
    market_reason = str(market.get("status") or "").strip().lower()
    reason = (
        projection_reason
        or (
            "s16_linear_projection_unavailable"
            if market_reason == "period_not_comparable"
            else "s16_market_heat_unavailable"
        )
    )
    return {
        "market_heat_contract_version": VERSION,
        "market_heat_formula": PROJECTION_FORMULA,
        "market_orders": _first_number(
            projection.get("projected_market_orders"),
            projection.get("projected_full_day"),
        ),
        "current_market_orders": _first_number(
            projection.get("current_market_orders"),
            proxy.get("current_estimated_market_orders"),
            market.get("estimated_market_orders"),
        ),
        "baseline_market_orders": _first_number(
            projection.get("baseline_market_orders"),
            proxy.get("baseline_market_orders"),
            market.get("baseline_market_orders"),
            market.get("baseline_median"),
        ),
        "elapsed_day_fraction": _first_number(
            projection.get("elapsed_day_fraction"),
            proxy.get("elapsed_day_fraction"),
        ),
        "market_orders_basis": "s16_linear_projected_full_day",
        "market_comparison_allowed": False,
        "market_comparison_basis": (
            projection.get("comparison_basis") or COMPARISON_BASIS
        ),
        "market_projection_method": (
            projection.get("projection_method") or PROJECTION_METHOD
        ),
        "market_projection_confidence": (
            projection.get("projection_confidence")
            or "linear_reference"
        ),
        "market_projection_linear_only": True,
        "market_evidence_source": (
            "s16.meituan_market_proxy.market_projection"
        ),
        "market_heat_ratio": None,
        "market_status": "unavailable",
        "market_heat_position": "unavailable",
        "market_heat_calculation_status": "unavailable",
        "market_heat_calculation_reason": reason,
    }


def _fmt_number(value: Any) -> str:
    number = _n(value)
    if number is None:
        return "-"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _fmt_percent(value: Any) -> str:
    number = _n(value)
    if number is None:
        return "-"
    return f"{number * 100:.1f}%"


def s5_market_line(result: Mapping[str, Any]) -> str:
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

    if evidence.get("market_heat_calculation_status") != "ok":
        reason = str(
            evidence.get("market_heat_calculation_reason")
            or "s16_market_heat_unavailable"
        )
        labels = {
            "current_market_orders_missing": "缺少当前大盘订单",
            "historical_full_day_market_orders_missing": (
                "缺少历史完整日大盘订单基线"
            ),
            "historical_full_day_market_orders_non_positive": (
                "历史完整日大盘订单基线必须大于 0"
            ),
            "elapsed_day_fraction_unavailable": "当前时间进度不可用",
            "elapsed_day_fraction_below_projection_floor": (
                "当天进度不足 35%，暂不进行线性全天预测"
            ),
            "elapsed_day_fraction_not_intraday": "当前不属于盘中预测时段",
            "s16_linear_projection_unavailable": (
                "S16 线性预计全天大盘订单暂不可用"
            ),
            "s16_market_heat_unavailable": "S16 大盘热度暂不可用",
        }
        return (
            "大盘热度：不可计算（"
            f"{labels.get(reason, reason)}）；"
            "S5 不使用当前累计订单除以历史完整日基线。"
        )

    ratio = _n(evidence.get("market_heat_ratio"))
    status_label = {
        "cold": "低于历史基线",
        "normal": "接近历史基线",
        "hot": "高于历史基线",
    }.get(str(evidence.get("market_status") or ""), "-")
    basis = str(evidence.get("market_orders_basis") or "")

    if basis == "s16_linear_projected_full_day":
        return (
            f"大盘热度：{ratio:.2f}（当前累计大盘订单 "
            f"{_fmt_number(evidence.get('current_market_orders'))}，"
            "经 S16 按已过时间 "
            f"{_fmt_percent(evidence.get('elapsed_day_fraction'))} "
            "线性外推为预计全天 "
            f"{_fmt_number(evidence.get('market_orders'))} ÷ "
            "历史完整日基线订单 "
            f"{_fmt_number(evidence.get('baseline_market_orders'))}）；"
            f"状态：{status_label}；市场不冷："
            f"{'是' if evidence.get('market_not_cold') else '否'}"
            f"（门槛 ≥{threshold:.2f}）；市场证据可比。"
        )

    return (
        f"大盘热度：{ratio:.2f}（S16 完整日大盘订单 "
        f"{_fmt_number(evidence.get('market_orders'))} ÷ "
        "历史完整日基线订单 "
        f"{_fmt_number(evidence.get('baseline_market_orders'))}）；"
        f"状态：{status_label}；市场不冷："
        f"{'是' if evidence.get('market_not_cold') else '否'}"
        f"（门槛 ≥{threshold:.2f}）。"
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s16_meituan_projection_advisory_patch as s16_source
    from runtime import s5_market_heat_contract_patch as s5_target

    s16_source._projection = build_linear_market_projection

    s5_target.VERSION = VERSION
    s5_target.FORMULA = PROJECTION_FORMULA
    s5_target.deterministic_market_evidence = s5_market_evidence_from_s16
    s5_target._market_line = s5_market_line

    strong_module = sys.modules.get("runtime.s5_strong_pricing_rules_patch")
    if strong_module is not None:
        strong_module._market_evidence = s5_market_evidence_from_s16

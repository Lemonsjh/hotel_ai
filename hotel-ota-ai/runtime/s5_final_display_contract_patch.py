from __future__ import annotations

import importlib
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

VERSION = "s5-final-display-contract.v1"
PROJECTION_METHOD = "linear_day_pace_reference"
COMPARISON_BASIS = "s16_linear_projected_close_vs_historical_daily_median"
_INSTALLED = False

_s16_source_at_import = importlib.import_module(
    "runtime.s16_meituan_projection_advisory_patch"
)
_NATIVE_S16_PROJECTION = _s16_source_at_import._projection


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


def _market_status(ratio: float) -> str:
    if ratio < 0.90:
        return "cold"
    if ratio >= 1.10:
        return "hot"
    return "normal"


def _position(status: str) -> str:
    return {
        "cold": "below_history",
        "normal": "near_history",
        "hot": "above_history",
    }.get(status, "unavailable")


def _dynamic(s16_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(s16_result, Mapping):
        return {}
    nested = s16_result.get("dynamic_diagnosis")
    return _mapping(nested) or dict(s16_result)


def s5_market_evidence_from_s16(
    s16_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Consume S16's calculated market heat without recomputing its ratio."""

    dynamic = _dynamic(s16_result)
    proxy = _mapping(dynamic.get("meituan_market_proxy"))
    projection = _mapping(proxy.get("market_projection"))
    market = _mapping(dynamic.get("market"))

    ratio = _first_number(
        projection.get("projected_ratio_vs_history"),
        projection.get("projected_market_heat_ratio"),
        projection.get("market_heat_ratio"),
    )
    projection_status = str(projection.get("status") or "").strip().lower()
    explicitly_blocked = projection.get("comparison_allowed") is False

    if (
        projection
        and ratio is not None
        and projection_status != "unavailable"
        and not explicitly_blocked
    ):
        status = _market_status(ratio)
        linear_only = projection.get("linear_projection_only") is not False
        market_orders_basis = (
            "s16_linear_projected_full_day"
            if linear_only
            else "s16_hourly_completion_projected_full_day"
        )
        market_heat_formula = (
            "S16: (current_cumulative / elapsed_day_fraction) "
            "/ historical_daily_median"
            if linear_only
            else "S16: (current_cumulative / comparable_hourly_completion_ratio) "
            "/ historical_daily_median"
        )
        comparison_basis = (
            COMPARISON_BASIS
            if linear_only
            else "s16_hourly_completion_projected_close_vs_historical_daily_median"
        )
        return {
            "market_heat_contract_version": VERSION,
            "market_heat_formula": market_heat_formula,
            "market_orders": _first_number(
                projection.get("projected_full_day"),
                projection.get("projected_market_orders"),
            ),
            "current_market_orders": _first_number(
                projection.get("current_market_orders"),
                proxy.get("current_estimated_market_orders"),
            ),
            "baseline_market_orders": _first_number(
                projection.get("baseline_market_orders"),
                proxy.get("baseline_market_orders"),
            ),
            "historical_daily_median": _first_number(
                projection.get("baseline_market_orders"),
                proxy.get("baseline_market_orders"),
            ),
            "elapsed_day_fraction": _first_number(
                projection.get("elapsed_day_fraction"),
                proxy.get("elapsed_day_fraction"),
            ),
            "market_orders_basis": market_orders_basis,
            "market_comparison_allowed": True,
            "market_comparison_basis": comparison_basis,
            "market_projection_method": (
                projection.get("projection_method")
                or (
                    PROJECTION_METHOD
                    if linear_only
                    else "hourly_completion_ratio_with_linear_fallback"
                )
            ),
            "market_projection_linear_only": linear_only,
            "market_evidence_source": (
                "s16.meituan_market_proxy.market_projection.direct"
            ),
            "market_heat_ratio": ratio,
            "market_status": status,
            "market_heat_position": _position(status),
            "market_heat_calculation_status": "ok",
            "market_heat_calculation_reason": None,
            "s5_recomputed_market_heat": False,
        }

    completed_ratio = _n(market.get("market_heat_ratio"))
    if completed_ratio is not None and market.get("comparison_allowed") is True:
        status = _market_status(completed_ratio)
        median = _first_number(
            market.get("baseline_median"),
            market.get("baseline_market_orders"),
        )
        current = _first_number(
            market.get("market_orders"),
            market.get("current_market_orders"),
            market.get("estimated_market_orders"),
        )
        return {
            "market_heat_contract_version": VERSION,
            "market_heat_formula": "S16 completed daily market heat",
            "market_orders": current,
            "current_market_orders": current,
            "baseline_market_orders": median,
            "historical_daily_median": median,
            "elapsed_day_fraction": None,
            "market_orders_basis": "s16_completed_daily_market",
            "market_comparison_allowed": True,
            "market_comparison_basis": "s16_completed_daily_vs_historical_daily_median",
            "market_evidence_source": "s16.dynamic_diagnosis.market.direct",
            "market_heat_ratio": completed_ratio,
            "market_status": status,
            "market_heat_position": _position(status),
            "market_heat_calculation_status": "ok",
            "market_heat_calculation_reason": None,
            "s5_recomputed_market_heat": False,
        }

    return {
        "market_heat_contract_version": VERSION,
        "market_heat_formula": (
            "S16: (current_cumulative / elapsed_day_fraction) "
            "/ historical_daily_median"
        ),
        "market_orders": _first_number(
            projection.get("projected_full_day"),
            projection.get("projected_market_orders"),
        ),
        "current_market_orders": _first_number(
            projection.get("current_market_orders"),
            proxy.get("current_estimated_market_orders"),
            market.get("estimated_market_orders"),
        ),
        "baseline_market_orders": _first_number(
            projection.get("baseline_market_orders"),
            proxy.get("baseline_market_orders"),
            market.get("baseline_median"),
        ),
        "historical_daily_median": _first_number(
            projection.get("baseline_market_orders"),
            proxy.get("baseline_market_orders"),
            market.get("baseline_median"),
        ),
        "elapsed_day_fraction": _first_number(
            projection.get("elapsed_day_fraction"),
            proxy.get("elapsed_day_fraction"),
        ),
        "market_orders_basis": "s16_linear_projected_full_day",
        "market_comparison_allowed": False,
        "market_comparison_basis": COMPARISON_BASIS,
        "market_projection_method": PROJECTION_METHOD,
        "market_projection_linear_only": True,
        "market_evidence_source": (
            "s16.meituan_market_proxy.market_projection.direct"
        ),
        "market_heat_ratio": None,
        "market_status": "unavailable",
        "market_heat_position": "unavailable",
        "market_heat_calculation_status": "unavailable",
        "market_heat_calculation_reason": "s16_market_heat_unavailable",
        "s5_recomputed_market_heat": False,
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
    return "-" if number is None else f"{number * 100:.1f}%"


def s5_market_line(result: Mapping[str, Any]) -> str:
    evidence = _mapping(result.get("s5_market_heat"))
    if not evidence:
        candidates = result.get("candidates") or []
        if candidates and isinstance(candidates[0], Mapping):
            evidence = dict(candidates[0])

    if evidence.get("market_heat_calculation_status") != "ok":
        return (
            "大盘热度：S16 当前未形成可用的大盘热度；"
            "S5 不自行重算或替代 S16 结果。"
        )

    ratio = _n(evidence.get("market_heat_ratio"))
    status_label = {
        "cold": "低于历史日度中位",
        "normal": "接近历史日度中位",
        "hot": "高于历史日度中位",
    }.get(str(evidence.get("market_status") or ""), "-")
    threshold = _n(evidence.get("market_not_cold_threshold"))
    threshold = 0.90 if threshold is None else threshold

    if evidence.get("market_orders_basis") == "s16_linear_projected_full_day":
        return (
            f"大盘热度：{ratio:.2f}（直接采用 S16 预计/历史比例；"
            f"当前累计值 {_fmt_number(evidence.get('current_market_orders'))}，"
            f"当天已过时间占比 {_fmt_percent(evidence.get('elapsed_day_fraction'))}，"
            f"线性预计收盘值 {_fmt_number(evidence.get('market_orders'))}，"
            f"历史日度中位 {_fmt_number(evidence.get('historical_daily_median') or evidence.get('baseline_market_orders'))}）；"
            f"状态：{status_label}；市场不冷："
            f"{'是' if evidence.get('market_not_cold') else '否'}"
            f"（门槛 ≥{threshold:.2f}）。"
        )

    if evidence.get("market_orders_basis") == "s16_hourly_completion_projected_full_day":
        return (
            f"大盘热度：{ratio:.2f}（直接采用 S16 预计/历史比例；"
            f"当前累计值 {_fmt_number(evidence.get('current_market_orders'))}，"
            "按可比历史同小时至日终完成率预计收盘值 "
            f"{_fmt_number(evidence.get('market_orders'))}，"
            f"历史日度中位 {_fmt_number(evidence.get('historical_daily_median') or evidence.get('baseline_market_orders'))}）；"
            f"状态：{status_label}；市场不冷："
            f"{'是' if evidence.get('market_not_cold') else '否'}"
            f"（门槛 ≥{threshold:.2f}）。"
        )

    return (
        f"大盘热度：{ratio:.2f}（直接采用 S16 完整日结果；"
        f"当前值 {_fmt_number(evidence.get('market_orders'))}，"
        f"历史日度中位 {_fmt_number(evidence.get('historical_daily_median') or evidence.get('baseline_market_orders'))}）；"
        f"状态：{status_label}；市场不冷："
        f"{'是' if evidence.get('market_not_cold') else '否'}"
        f"（门槛 ≥{threshold:.2f}）。"
    )


def _money(value: Any) -> str:
    number = _n(value)
    return "¥-" if number is None else f"¥{number:,.2f}"


def _rounded_money(value: Any) -> str:
    """Format customer-facing estimated revenue as a whole yuan."""
    if value in (None, ""):
        return "¥-"
    try:
        number = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return "¥-"
    return f"¥{number:,}"


def _pct(value: Any) -> str:
    number = _n(value)
    return "-" if number is None else f"{number * 100:.2f}%"


def _factor(value: Any, digits: int = 2) -> str:
    number = _n(value)
    return "-" if number is None else f"{number:.{digits}f}"


def render_net_revenue_reference_line(
    item: Mapping[str, Any],
    *,
    display_price: Any = None,
) -> str | None:
    del display_price
    channel = str(item.get("channel") or "").strip().lower()
    if channel not in {"meituan", "美团", "mt"}:
        return None

    raw_price = item.get("current_price")
    if item.get("s5_net_revenue_calculation_status") != "ok":
        reason = str(
            item.get("s5_net_revenue_calculation_reason")
            or item.get("s5_activity_evidence_reason")
            or "evidence_unavailable"
        )
        try:
            from runtime.algorithms import s5_real_reply as reply_module

            label = reply_module.NET_REVENUE_REASON_LABELS.get(reason, "证据不足")
        except Exception:
            label = "证据不足"
        return (
            f"- 净收参考：原卖价 {_money(raw_price)} → "
            f"酒店净收参考价暂不可计算（{label}）；不含用户券。"
        )

    net_revenue = (
        item.get("estimated_hotel_revenue_exact")
        or item.get("estimated_hotel_revenue")
    )
    commission = (
        item.get("commission_rate_exact")
        or item.get("commission_rate")
    )
    combined = (
        item.get("combined_activity_factor_exact")
        or item.get("combined_activity_factor")
    )
    activities = item.get("applied_activities") or []
    factors = [
        _factor(
            activity.get("discount_factor_exact")
            if activity.get("discount_factor_exact") not in (None, "")
            else activity.get("discount_factor")
        )
        for activity in activities
        if isinstance(activity, Mapping)
        and (
            activity.get("discount_factor_exact") not in (None, "")
            or activity.get("discount_factor") not in (None, "")
        )
    ]
    if factors:
        factor_text = " × ".join(factors)
        activity_text = (
            f"有效活动系数 {factor_text}"
            f"（综合 {_factor(combined, 4)}）"
        )
    elif _n(combined) not in (None, 1.0):
        activity_text = (
            "有效活动系数明细不可用"
            f"（综合 {_factor(combined, 4)}）"
        )
    else:
        activity_text = "有效活动系数 1.00（无有效活动）"

    return (
        f"- 净收参考：原卖价 {_money(raw_price)} → "
        f"酒店净收参考价 {_money(net_revenue)}；"
        f"佣金 {_pct(commission)}，{activity_text}；不含用户券。"
    )


def render_net_revenue_with_room_history(
    item: Mapping[str, Any], *, display_price: Any = None
) -> str:
    """Render S5 as a net-revenue view, without exposing OTA list prices."""
    del display_price
    net_revenue = _first_number(
        item.get("estimated_hotel_revenue_exact"),
        item.get("estimated_hotel_revenue"),
    )
    if item.get("s5_net_revenue_calculation_status") == "ok" and net_revenue is not None:
        commission = _pct(
            item.get("commission_rate_exact") or item.get("commission_rate")
        )
        factor = _factor(
            item.get("combined_activity_factor_exact")
            or item.get("combined_activity_factor"),
            4,
        )
        member_factor = _factor(
            item.get("member_expected_factor_exact")
            or item.get("member_expected_factor")
            or 0.85,
            2,
        )
        line = (
            f"- \u51c0\u6536\u9884\u4f30\uff1a{_rounded_money(net_revenue)}"
            f"\uff08\u4f63\u91d1 {commission}\uff0c\u6709\u6548\u6d3b\u52a8\u7efc\u5408\u7cfb\u6570 {factor}\uff0c\u4f1a\u5458\u9884\u671f\u7cfb\u6570 {member_factor}\uff1b\u4e0d\u542b\u7528\u6237\u5238\uff09\u3002"
        )
    else:
        line = "- \u51c0\u6536\u9884\u4f30\uff1a\u6682\u4e0d\u53ef\u8ba1\u7b97\uff08\u6e20\u9053\u51c0\u6536\u4f9d\u636e\u4e0d\u8db3\uff09\u3002"
    net_text = _rounded_money(net_revenue) if net_revenue is not None else "\u6682\u4e0d\u53ef\u8ba1\u7b97"
    return (
        f"{line}\n"
        f"- \u6536\u76ca\u53c2\u8003\u4fe1\u53f7\uff1a\u9884\u8ba1\u51c0\u6536 {net_text} vs "
        f"\u623f\u578b\u5386\u53f2\u6210\u4ea4\u4e2d\u4f4d {_money(item.get('baseline_price_median'))}"
        "\uff08\u4ec5\u6536\u76ca\u53c2\u8003\uff0c\u4e0d\u662f\u5546\u54c1\u7ea7\u5386\u53f2\u6bd4\u4ef7\uff09\u3002"
        + _raise_net_revenue_headroom_line(item, current_net_revenue=net_revenue)
        + _proposed_net_revenue_line(item, current_net_revenue=net_revenue)
    )


def _raise_net_revenue_headroom_line(
    item: Mapping[str, Any], *, current_net_revenue: float | None
) -> str:
    if str(item.get("price_action") or item.get("action_type") or "").lower() not in {
        "increase",
        "raise_price",
    }:
        return ""
    ceiling = _first_number(item.get("raise_net_revenue_ceiling"))
    if current_net_revenue is None or ceiling is None:
        return ""
    return (
        f"\n- \u6da8\u4ef7\u7a7a\u95f4\uff1a\u5f53\u524d\u51c0\u6536\u9884\u4f30 {_rounded_money(current_net_revenue)} "
        f"< \u623f\u578b\u5386\u53f2\u6210\u4ea4 P80 \u00d7 98%\uff08{_rounded_money(ceiling)}\uff09\uff1b"
        "\u5b9e\u9645\u6267\u884c\u65f6\u518d\u53cd\u7b97 OTA \u6302\u724c\u4ef7\u3002"
    )


def _proposed_net_revenue_line(
    item: Mapping[str, Any], *, current_net_revenue: float | None
) -> str:
    proposed = _first_number(
        item.get("proposed_estimated_hotel_revenue_exact"),
        item.get("proposed_estimated_hotel_revenue"),
    )
    try:
        change = float(item.get("actual_change_pct"))
    except (TypeError, ValueError):
        return ""
    if proposed is None or current_net_revenue is None or abs(change) < 0.000001:
        return ""
    _money = _rounded_money  # Display-only: proposed net revenue is whole yuan.
    direction = "\u4e0a\u8c03" if change > 0 else "\u4e0b\u8c03"
    return (
        f"\n- \u8c03\u4ef7\u6536\u76ca\u53c2\u8003\uff1a\u9884\u8ba1\u51c0\u6536 {_money(current_net_revenue)} "
        f"\u2192 \u5efa\u8bae\u51c0\u6536 {_money(proposed)}\uff08{direction} {abs(change) * 100:.2f}%\uff09\u3002"
    )


def _relative_market_line(result: Mapping[str, Any]) -> str | None:
    for item in result.get("candidates") or []:
        if not isinstance(item, Mapping):
            continue
        peer = item.get("peer_price_evidence") or {}
        if not isinstance(peer, Mapping):
            continue
        try:
            gap = float(peer.get("lead_price_gap_pct"))
        except (TypeError, ValueError):
            try:
                gap = (
                    float(peer.get("own_value")) - float(peer.get("peer_average"))
                ) / float(peer.get("peer_average"))
            except (TypeError, ValueError, ZeroDivisionError):
                continue
        platform = {"meituan": "\u7f8e\u56e2", "ctrip": "\u643a\u7a0b"}.get(
            str(item.get("channel") or "").lower(), "OTA"
        )
        if gap == 0:
            relation = "\u4e0e\u540c\u884c\u5747\u503c\u6301\u5e73"
        else:
            direction = "\u9ad8\u4e8e" if gap > 0 else "\u4f4e\u4e8e"
            relation = f"\u8f83\u540c\u884c\u5747\u503c{direction} {abs(gap) * 100:.1f}%"
        return (
            f"- \u5e02\u573a\u80cc\u666f\uff08{platform}\u9152\u5e97\u7ea7\u76f8\u5bf9\u4f4d\u7f6e\uff09\uff1a{relation}\uff1b"
            "\u4ec5\u4f5c\u5e02\u573a\u80cc\u666f\uff0c\u4e0d\u4f5c\u4e3a\u5177\u4f53\u5546\u54c1\u8c03\u4ef7\u4f9d\u636e\u3002"
        )
    return None


def render_s5_revenue_only_reply(previous: Any, result: Mapping[str, Any]) -> str:
    """Keep S5 as a revenue view; reserve list prices for explicit S6 actions."""
    market_line = _relative_market_line(result)
    output: list[str] = []
    market_replaced = False
    for line in str(previous(dict(result))).splitlines():
        stripped = line.strip()
        if stripped.startswith("- \u4ef7\u683c\uff1a"):
            continue
        if stripped.startswith("- \u7f8e\u56e2\u9152\u5e97\u7ea7\u5f15\u6d41\u4ef7") or stripped.startswith(
            "- \u643a\u7a0b\u9152\u5e97\u7ea7\u5f15\u6d41\u4ef7"
        ):
            if market_line and not market_replaced:
                output.append(market_line)
                market_replaced = True
            continue
        if stripped.startswith("\u53e3\u5f84\uff1a\u9152\u5e97\u6574\u4f53\u6700\u4f4e\u5c55\u793a\u4ef7"):
            continue
        if stripped.startswith("- \u6536\u76ca\u53e3\u5f84\uff1a"):
            output.append(
                "- \u6536\u76ca\u53e3\u5f84\uff1a\u51c0\u6536\u9884\u4f30\u6309\u6e20\u9053\u4f63\u91d1\u7387\u4e0e\u6709\u6548\u6d3b\u52a8\u7cfb\u6570\u6298\u7b97\uff1b"
                "\u4e0d\u542b\u7528\u6237\u5238\uff0c\u4ec5\u4f9b\u8fd0\u8425\u67e5\u770b\u3002"
            )
            continue
        output.append(line)
    return "\n".join(output)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import (
        s16_meituan_projection_advisory_patch as s16_source,
        s5_market_heat_contract_patch as market_target,
        s5_product_net_revenue_patch as net_revenue,
        s5_strong_pricing_rules_patch as strong_target,
    )
    from runtime.algorithms import s5_real_reply as reply_module

    # The older S5 sync patch replaced S16's private projection function.
    # Restore the S16-native implementation captured before that patch ran.
    s16_source._projection = _NATIVE_S16_PROJECTION

    # Make S5 consume S16's published ratio directly, then ensure the existing
    # S5 market wrapper is active. S5 may classify the ratio against its own
    # gate threshold, but it never rebuilds the ratio itself.
    market_target.VERSION = VERSION
    market_target.FORMULA = (
        "S16 projected_ratio_vs_history = "
        "(current_cumulative / elapsed_day_fraction) / historical_daily_median"
    )
    market_target.deterministic_market_evidence = s5_market_evidence_from_s16
    market_target._market_line = s5_market_line
    strong_target._market_evidence = s5_market_evidence_from_s16
    market_target.install()

    # Existing deterministic net-revenue calculation remains the source of
    # truth; install it explicitly so every real S5 candidate is enriched.
    net_revenue.install()

    # The base S5 renderer calls this helper for every candidate. Replacing the
    # helper keeps all existing S5/S6 decision logic unchanged while enforcing
    # the requested Meituan display contract.
    reply_module._net_revenue_line = render_net_revenue_with_room_history

    previous_render = reply_module.render_s5_real_reply
    if not getattr(previous_render, "_S5_REVENUE_ONLY_DISPLAY_V1", False):
        def render_s5_real_reply(result: dict[str, Any]) -> str:
            return render_s5_revenue_only_reply(previous_render, result)

        render_s5_real_reply._S5_REVENUE_ONLY_DISPLAY_V1 = True  # type: ignore[attr-defined]
        reply_module.render_s5_real_reply = render_s5_real_reply

        try:
            from runtime import feishu_output_renderer

            feishu_output_renderer.render_s5_real_reply = render_s5_real_reply
        except Exception:
            pass

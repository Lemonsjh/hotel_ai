from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

_INSTALLED = False
VERSION = "s09-real-field-rules.v3"
_COUNT_UNITS = {
    "",
    "count",
    "order",
    "orders",
    "person",
    "people",
    "uv",
    "次",
    "单",
    "人",
    "间夜",
    "room_night",
}
_RATE_TOLERANCE = 0.005


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _latest_metric_row(
    rows: Sequence[Mapping[str, Any]],
    code: str,
) -> Mapping[str, Any] | None:
    candidates = [
        row
        for row in rows
        if str(row.get("metric_code") or "") == code
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda row: (
            str(row.get("snapshot_time") or ""),
            int(_n(row.get("id")) or 0),
        ),
    )


def _count_value(row: Mapping[str, Any] | None) -> float | None:
    if not row:
        return None
    unit = str(row.get("metric_unit") or "").strip().lower()
    if unit not in _COUNT_UNITS:
        return None
    return _n(row.get("metric_value"))


def _ratio(numerator: Any, denominator: Any) -> float | None:
    left = _n(numerator)
    right = _n(denominator)
    if left is None or right in (None, 0):
        return None
    return left / right


def _sample_quality(
    *,
    denominator: float | None,
    numerator: float | None,
    stage: str,
) -> str:
    if denominator is None or numerator is None:
        return "unavailable"
    if stage == "first":
        if denominator >= 300 and numerator >= 30:
            return "stable"
        if denominator >= 30:
            return "weak"
        return "trend_only"
    if denominator >= 50 and numerator >= 3:
        return "stable"
    if denominator >= 30 and numerator >= 2:
        return "weak"
    return "trend_only"


def _rate_conflict(
    derived: float | None,
    source: Any,
    *,
    name: str,
) -> str | None:
    source_value = _n(source)
    if derived is None or source_value is None:
        return None
    return (
        f"source_conflict:{name}"
        if abs(derived - source_value) > _RATE_TOLERANCE
        else None
    )


def apply_meituan_metric_fallback(
    result: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    output = dict(result)
    if str(output.get("platform") or "") != "meituan":
        return output

    stages = dict(output.get("stages") or {})
    primary_browse = _n(stages.get("browse_uv"))
    primary_pay = _n(stages.get("pay_orders"))
    backup_browse = _count_value(
        _latest_metric_row(rows, "INTENTION_UV")
    )
    backup_pay = _count_value(
        _latest_metric_row(rows, "PAY_ORDER_CNT")
    )

    browse = primary_browse
    browse_source = (
        "FLOW_INTENTION_UV" if browse is not None else None
    )
    browse_fallback = False
    if browse is None and backup_browse is not None:
        browse = backup_browse
        browse_source = "INTENTION_UV"
        browse_fallback = True

    pay = primary_pay
    pay_source = "FLOW_PAY_ORDER_CNT" if pay is not None else None
    pay_fallback = False
    if pay is None and backup_pay is not None:
        pay = backup_pay
        pay_source = "PAY_ORDER_CNT"
        pay_fallback = True

    exposure = _n(stages.get("exposure_uv"))
    first = _ratio(browse, exposure)
    second = _ratio(pay, browse)

    stages.update(
        {
            "browse_uv": browse,
            "pay_orders": pay,
            "exposure_to_browse_ratio": first,
            "browse_to_pay_ratio": second,
            "browse_uv_source": browse_source,
            "browse_uv_fallback_used": browse_fallback,
            "pay_orders_source": pay_source,
            "pay_orders_fallback_used": pay_fallback,
        }
    )
    output["stages"] = stages
    output["first_stage_quality"] = _sample_quality(
        denominator=exposure,
        numerator=browse,
        stage="first",
    )
    output["second_stage_quality"] = _sample_quality(
        denominator=browse,
        numerator=pay,
        stage="second",
    )

    conflicts = [
        str(item)
        for item in output.get("source_conflicts") or []
        if str(item)
        not in {
            "source_conflict:exposure_to_browse",
            "source_conflict:browse_to_pay",
        }
    ]
    for conflict in (
        _rate_conflict(
            first,
            stages.get("source_exposure_to_browse_ratio"),
            name="exposure_to_browse",
        ),
        _rate_conflict(
            second,
            stages.get("source_browse_to_pay_ratio"),
            name="browse_to_pay",
        ),
    ):
        if conflict:
            conflicts.append(conflict)
    output["source_conflicts"] = sorted(set(conflicts))

    gaps = {
        str(item) for item in output.get("data_gaps") or []
    }
    if browse is not None:
        gaps.discard("missing_metric:FLOW_INTENTION_UV")
        gaps.discard("missing_metric:first_stage")
    if pay is not None:
        gaps.discard("missing_metric:FLOW_PAY_ORDER_CNT")
        gaps.discard("missing_metric:second_stage")
    output["data_gaps"] = sorted(gaps)

    output["metric_fallbacks"] = [
        stage
        for stage, used, value in (
            ("browse", browse_fallback, browse),
            ("pay_orders", pay_fallback, pay),
        )
        if used and value is not None
    ]
    output["metric_fallback_version"] = VERSION
    return output


def build_daily_platform_wrapper(
    previous: Callable[
        [str, Sequence[Mapping[str, Any]]],
        dict[str, Any],
    ],
) -> Callable[
    [str, Sequence[Mapping[str, Any]]],
    dict[str, Any],
]:
    def build_daily_platform(
        platform: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        result = previous(platform, rows)
        if platform != "meituan":
            return result
        return apply_meituan_metric_fallback(result, rows)

    build_daily_platform._S09_METRIC_FALLBACK_V3 = True  # type: ignore[attr-defined]
    return build_daily_platform


def append_fallback_section(
    text: str,
    report: Mapping[str, Any],
) -> str:
    lines: list[str] = []
    labels = {
        "meituan": "美团",
        "dianping": "大众点评",
        "ctrip": "携程",
    }
    for platform, item in (report.get("platforms") or {}).items():
        daily = (item or {}).get("daily") or {}
        used = set(daily.get("metric_fallbacks") or [])
        stages = daily.get("stages") or {}
        notes: list[str] = []
        if "browse" in used:
            notes.append(
                "漏斗浏览为空，已用同次采集的经营浏览补齐"
            )
        if "pay_orders" in used:
            pay = _n(stages.get("pay_orders"))
            browse = _n(stages.get("browse_uv"))
            second = _n(stages.get("browse_to_pay_ratio"))
            detail = (
                f"{pay:g}/{browse:g}，二转 {second * 100:.1f}%"
                if pay is not None
                and browse not in (None, 0)
                and second is not None
                else "已重新计算二转"
            )
            notes.append(
                "漏斗支付订单为空，已用同次采集的经营支付订单补齐"
                f"（{detail}）"
            )
        if notes:
            lines.append(
                f"• {labels.get(platform, platform)}："
                + "；".join(notes)
                + "。"
            )
    if not lines:
        return str(text)
    return (
        str(text).rstrip()
        + "\n\n【数据口径回退】\n"
        + "\n".join(lines)
        + "\n说明：仅在同平台、同业务日的备用经营指标有值时回退，不使用 PMS 或订单明细。"
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s01_s17_exact_route_patch as route
    from runtime import s09_traffic_conversion_real as s09

    previous_build = s09.build_daily_platform
    if not getattr(
        previous_build,
        "_S09_METRIC_FALLBACK_V3",
        False,
    ):
        s09.build_daily_platform = build_daily_platform_wrapper(
            previous_build
        )

    previous_render = s09.render_s09_report
    if not getattr(
        previous_render,
        "_S09_METRIC_FALLBACK_V3",
        False,
    ):
        def render_s09_report(report: Mapping[str, Any]) -> str:
            return append_fallback_section(
                previous_render(report),
                report,
            )

        render_s09_report._S09_METRIC_FALLBACK_V3 = True  # type: ignore[attr-defined]
        s09.render_s09_report = render_s09_report
        route.render_s09_report = render_s09_report

    s09.VERSION = VERSION
    route.build_s09_report = s09.build_s09_report

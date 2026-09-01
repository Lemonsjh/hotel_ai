from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

_INSTALLED = False
_VERSION = "s09-real-field-rules.v2"
_RATE_TOLERANCE = 0.005


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quantile(values: Sequence[float], q: float) -> float | None:
    clean = sorted(float(value) for value in values)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    position = (len(clean) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(clean) - 1)
    weight = position - lower
    return clean[lower] * (1 - weight) + clean[upper] * weight


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _week_type(day: dt.date) -> str:
    return "weekend" if day.weekday() >= 5 else "weekday"


def _history_point(row: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = row.get("daily")
    return nested if isinstance(nested, Mapping) else row


def _select_comparable(
    history: Sequence[Mapping[str, Any]],
    current_date: Any,
) -> tuple[list[Mapping[str, Any]], str]:
    target = _date(current_date)
    if target is None:
        return [], "unavailable"
    candidates: list[Mapping[str, Any]] = []
    for row in history:
        point = _history_point(row)
        day = _date(point.get("business_date"))
        if day is not None and day != target:
            candidates.append(row)
    same_weekday = [
        row
        for row in candidates
        if (_date(_history_point(row).get("business_date")) or target).weekday()
        == target.weekday()
    ]
    if same_weekday:
        return same_weekday, "same_weekday_holiday_registry_unavailable"
    same_type = [
        row
        for row in candidates
        if _week_type(_date(_history_point(row).get("business_date")) or target)
        == _week_type(target)
    ]
    if same_type:
        return same_type, "same_week_type_holiday_registry_unavailable"
    return [], "unavailable"


def _baseline_maturity(count: int, tier: str) -> str:
    if count <= 0:
        return "unavailable"
    if "holiday_registry_unavailable" in tier:
        return "weak" if count >= 3 else "trend_only"
    if count >= 14:
        return "stable"
    if count >= 7:
        return "temporary"
    if count >= 3:
        return "weak"
    return "trend_only"


def _history_baseline(item: Mapping[str, Any]) -> dict[str, Any]:
    daily = item.get("daily") or {}
    comparable, tier = _select_comparable(
        item.get("daily_history") or [],
        daily.get("business_date"),
    )
    algorithm = str(item.get("algorithm_platform") or item.get("platform") or "")
    browse_values: list[float] = []
    first_values: list[float] = []
    second_values: list[float] = []
    dates: list[str] = []
    for row in comparable:
        point = _history_point(row)
        stages = point.get("stages") or {}
        date_text = str(point.get("business_date") or "")[:10]
        if date_text:
            dates.append(date_text)
        if algorithm == "meituan":
            browse = _n(stages.get("browse_uv"))
            first = _n(stages.get("exposure_to_browse_ratio"))
            second = _n(stages.get("browse_to_pay_ratio"))
        else:
            browse = _n(stages.get("detail_visitor_count"))
            first = _n(stages.get("list_to_detail_ratio"))
            second = _n(stages.get("detail_to_submit_ratio"))
        if browse is not None:
            browse_values.append(browse)
        if first is not None:
            first_values.append(first)
        if second is not None:
            second_values.append(second)
    count = len(set(dates))
    return {
        "selected_tier": tier,
        "selected_dates": sorted(set(dates)),
        "sample_count": count,
        "maturity": _baseline_maturity(count, tier),
        "holiday_alignment": (
            "unavailable"
            if "holiday_registry_unavailable" in tier
            else "matched"
        ),
        "browse_median": _quantile(browse_values, 0.5),
        "first_p25": _quantile(first_values, 0.25),
        "first_median": _quantile(first_values, 0.5),
        "second_p25": _quantile(second_values, 0.25),
        "second_median": _quantile(second_values, 0.5),
    }


def _peer_second(item: Mapping[str, Any]) -> float | None:
    algorithm = str(item.get("algorithm_platform") or item.get("platform") or "")
    stages = ((item.get("rolling_30d") or {}).get("stages") or {})
    # Meituan daily and 30-day second stage share browse -> paid orders.
    # Ctrip daily detail -> submit does not share a source definition with
    # 30-day peer detail -> order-filling, so it must not be compared.
    if algorithm == "meituan":
        return _n(stages.get("peer_browse_to_pay_ratio"))
    return None


def _sample_state(item: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    algorithm = str(item.get("algorithm_platform") or item.get("platform") or "")
    stages = ((item.get("daily") or {}).get("stages") or {})
    if algorithm == "meituan":
        first_den = _n(stages.get("exposure_uv"))
        first_num = _n(stages.get("browse_uv"))
        second_den = _n(stages.get("browse_uv"))
        second_num = _n(stages.get("pay_orders"))
    else:
        first_den = _n(stages.get("list_exposure_count"))
        first_num = _n(stages.get("detail_visitor_count"))
        second_den = _n(stages.get("detail_visitor_count"))
        second_num = _n(stages.get("submit_orders"))
    first_strong = bool(
        first_den is not None
        and first_num is not None
        and first_den >= 300
        and first_num >= 30
    )
    second_strong = bool(
        second_den is not None
        and second_num is not None
        and second_den >= 50
        and second_num >= 3
    )
    second_preview = bool(
        not second_strong
        and second_den is not None
        and second_num is not None
        and second_den >= 30
        and second_num >= 2
    )
    return first_strong, second_strong, second_preview


def _has_metric_conflict(item: Mapping[str, Any]) -> bool:
    daily = item.get("daily") or {}
    rolling = item.get("rolling_30d") or {}
    conflicts = list(daily.get("source_conflicts") or []) + list(
        rolling.get("source_conflicts") or []
    )
    return any(
        str(conflict).startswith("source_conflict:")
        for conflict in conflicts
    )


def _status_label(value: str) -> str:
    return {
        "weak": "明显偏弱",
        "weak_signal": "偏弱信号",
        "strong": "表现较强",
        "strong_signal": "较强信号",
        "normal": "正常区间",
        "manual_preview": "人工预览样本",
        "sample_insufficient": "样本不足",
        "baseline_unavailable": "历史基准不足",
        "metric_conflict": "来源率冲突",
    }.get(value, value)


def diagnose_platform(item: Mapping[str, Any]) -> dict[str, Any]:
    algorithm = str(item.get("algorithm_platform") or item.get("platform") or "")
    daily = item.get("daily") or {}
    stages = daily.get("stages") or {}
    baseline = _history_baseline(item)
    first_strong, second_strong, second_preview = _sample_state(item)
    if algorithm == "meituan":
        first = _n(stages.get("exposure_to_browse_ratio"))
        second = _n(stages.get("browse_to_pay_ratio"))
        first_label, second_label = "曝光→浏览", "浏览→支付"
    else:
        first = _n(stages.get("list_to_detail_ratio"))
        second = _n(stages.get("detail_to_submit_ratio"))
        first_label, second_label = "列表曝光→详情访客", "详情访客→提交"
    peer_second = _peer_second(item)
    peer_index = (
        second / peer_second
        if second is not None and peer_second not in (None, 0)
        else None
    )
    maturity = str(baseline.get("maturity") or "unavailable")
    low_baseline = maturity in {"weak", "trend_only", "unavailable"}

    if _has_metric_conflict(item):
        first_status = second_status = "metric_conflict"
    else:
        if not first_strong:
            first_status = "sample_insufficient"
        elif baseline.get("first_p25") is None:
            first_status = "baseline_unavailable"
        elif first is not None and first < baseline["first_p25"]:
            first_status = "weak_signal" if low_baseline else "weak"
        else:
            first_median = _n(baseline.get("first_median"))
            if (
                first is not None
                and first_median is not None
                and first >= first_median
            ):
                first_status = "strong_signal" if low_baseline else "strong"
            else:
                first_status = "normal"

        if baseline.get("second_p25") is None:
            second_status = "baseline_unavailable"
        elif second_strong:
            if (
                second is not None
                and second < baseline["second_p25"]
                and peer_index is not None
                and peer_index < 0.85
            ):
                second_status = "weak_signal" if low_baseline else "weak"
            else:
                second_median = _n(baseline.get("second_median"))
                if (
                    second is not None
                    and second_median is not None
                    and second >= second_median
                    and (peer_index is None or peer_index >= 1.0)
                ):
                    second_status = "strong_signal" if low_baseline else "strong"
                else:
                    second_status = "normal"
        elif second_preview:
            if (
                second is not None
                and second < baseline["second_p25"]
                and peer_index is not None
                and peer_index < 0.85
            ):
                second_status = "weak_signal"
            else:
                second_status = "manual_preview"
        else:
            second_status = "sample_insufficient"

    weak = [
        label
        for label, status in (
            (first_label, first_status),
            (second_label, second_status),
        )
        if status in {"weak", "weak_signal"}
    ]
    if first_status == "metric_conflict":
        conclusion = "来源率与分子分母派生率冲突，暂停强弱判断"
    elif weak:
        conclusion = "主要短板信号：" + "、".join(weak)
    elif first_status == second_status == "sample_insufficient":
        conclusion = "样本不足，仅展示当前事实"
    elif baseline.get("sample_count", 0) < 3:
        conclusion = "同日型历史不足，不生成稳定正常线"
    else:
        conclusion = (
            f"{first_label}{_status_label(first_status)}；"
            f"{second_label}{_status_label(second_status)}"
        )
    suggestions = []
    if first_status in {"weak", "weak_signal"}:
        suggestions.append(
            "建议检查列表主图、标题、引流价和曝光人群匹配；"
            "先核查展示层，不直接归因于房价。"
        )
    if second_status in {"weak", "weak_signal"}:
        suggestions.append(
            "建议检查房型可售、价格权益、取消政策和下单阻力，"
            "再评估推广或价格动作。"
        )
    if first_status == "metric_conflict":
        suggestions.append(
            "建议先核对来源转化率与真实分子分母，"
            "冲突解除前不输出强弱动作建议。"
        )
    if not suggestions:
        suggestions.append(
            "建议继续积累同日型样本；历史成熟度不足时"
            "不因单日波动直接调整预算或价格。"
        )
    return {
        "first_stage_status": first_status,
        "second_stage_status": second_status,
        "first_stage_label": _status_label(first_status),
        "second_stage_label": _status_label(second_status),
        "historical_baseline": baseline,
        "second_conversion_peer": peer_second,
        "second_conversion_peer_index": peer_index,
        "weak_stages": weak,
        "conclusion": conclusion,
        "suggestions": suggestions,
        "policy_version": _VERSION,
    }


def _pct(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.1f}%"


def _num(value: Any) -> str:
    number = _n(value)
    if number is None:
        return "—"
    return (
        str(int(round(number)))
        if abs(number - round(number)) < 1e-9
        else f"{number:.1f}"
    )


def append_baseline_section(text: str, report: Mapping[str, Any]) -> str:
    blocks = ["", "【同日型历史基准与判定】"]
    labels = {
        "meituan": "美团",
        "dianping": "大众点评",
        "ctrip": "携程",
        "qunar": "去哪儿",
        "tongcheng": "同程",
        "zhixing": "智行",
    }
    for platform, item in (report.get("platforms") or {}).items():
        diagnosis = item.get("diagnosis") or {}
        baseline = diagnosis.get("historical_baseline") or {}
        blocks.append(
            f"• {labels.get(platform, platform)}  "
            f"样本 {baseline.get('sample_count', 0)}天 / "
            f"{baseline.get('selected_tier') or 'unavailable'} / "
            f"成熟度 {baseline.get('maturity') or 'unavailable'}"
        )
        blocks.append(
            f"  浏览/详情中位 {_num(baseline.get('browse_median'))}"
            f"  ｜  一转 P25/中位 {_pct(baseline.get('first_p25'))}/"
            f"{_pct(baseline.get('first_median'))}"
            f"  ｜  二转 P25/中位 {_pct(baseline.get('second_p25'))}/"
            f"{_pct(baseline.get('second_median'))}"
        )
        peer_index = diagnosis.get("second_conversion_peer_index")
        blocks.append(
            f"  判定  一转 {diagnosis.get('first_stage_label') or '—'}"
            f"  ｜  二转 {diagnosis.get('second_stage_label') or '—'}"
            + (
                f"  ｜  二转同行指数 {float(peer_index):.2f}"
                if _n(peer_index) is not None
                else ""
            )
        )
    blocks.append(
        "说明  当前纵表未携带法定节假日/调休标签时，仅退化到同星期或"
        "同工作日类型，并降低历史成熟度；不会伪装成完整同日型基准。"
    )
    return str(text).rstrip() + "\n" + "\n".join(blocks)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s01_s17_exact_route_patch as route_patch
    from runtime import s09_traffic_conversion_real as s09

    s09.SOURCE_RATE_TOLERANCE = _RATE_TOLERANCE
    s09.VERSION = _VERSION
    s09.diagnose_platform = diagnose_platform
    previous_render = s09.render_s09_report

    def render_v2(report: Mapping[str, Any]) -> str:
        return append_baseline_section(previous_render(report), report)

    s09.render_s09_report = render_v2
    route_patch.render_s09_report = render_v2
    route_patch.build_s09_report = s09.build_s09_report

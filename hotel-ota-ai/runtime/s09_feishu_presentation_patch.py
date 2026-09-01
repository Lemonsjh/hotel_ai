"""Operator-facing S9 Feishu presentation without changing S9 decisions."""

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping

_INSTALLED = False

_PLATFORM_LABELS = {
    "meituan": "美团",
    "dianping": "大众点评",
    "ctrip": "携程",
    "qunar": "去哪儿",
    "tongcheng": "同程",
    "zhixing": "智行",
}
_PREFERRED_PLATFORMS = tuple(_PLATFORM_LABELS)


def _number(value: Any, digits: int = 1) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.{digits}f}"


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def _date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _as_of_date(report: Mapping[str, Any]) -> dt.date | None:
    return _date(report.get("as_of_datetime"))


def _quality_label(value: Any) -> str:
    return {
        "stable": "样本充足",
        "weak": "样本偏少，仅作观察",
        "trend_only": "样本不足，仅作趋势参考",
        "unavailable": "缺少数据",
    }.get(str(value or ""), "缺少数据")


def _maturity_label(value: Any) -> str:
    return {
        "stable": "样本充足",
        "temporary": "样本有限",
        "weak": "样本较少，仅作观察",
        "trend_only": "样本不足，仅作趋势参考",
        "unavailable": "历史样本不足",
    }.get(str(value or ""), "历史样本不足")


def _missing_labels(algorithm: str, stages: Mapping[str, Any]) -> list[str]:
    if algorithm == "meituan":
        fields = (
            ("exposure_uv", "曝光人数"),
            ("browse_uv", "浏览人数"),
            ("pay_orders", "支付订单数"),
        )
    else:
        fields = (
            ("list_exposure_count", "列表曝光"),
            ("detail_visitor_count", "详情访客"),
            ("submit_orders", "提交订单"),
        )
    return [label for field, label in fields if stages.get(field) in (None, "")]


def _ordered_platforms(report: Mapping[str, Any]) -> list[str]:
    available = report.get("platforms") or {}
    return [
        *[key for key in _PREFERRED_PLATFORMS if key in available],
        *sorted(set(available) - set(_PREFERRED_PLATFORMS)),
    ]


def _rolling_line(algorithm: str, rolling: Mapping[str, Any]) -> str | None:
    if not rolling:
        return None
    stages = rolling.get("stages") or {}
    start = rolling.get("period_start_date") or "—"
    end = rolling.get("period_end_date") or "—"
    if algorithm == "meituan":
        return (
            f"近30日平台参考（{start} 至 {end}）："
            f"本店曝光→浏览 {_percent(stages.get('exposure_to_browse_ratio'))}，"
            f"浏览→支付 {_percent(stages.get('browse_to_pay_ratio'))}；"
            f"同行 {_percent(stages.get('peer_exposure_to_browse_ratio'))} / "
            f"{_percent(stages.get('peer_browse_to_pay_ratio'))}。"
        )
    return (
        f"近30日平台参考（{start} 至 {end}）："
        f"本店列表→详情 {_percent(stages.get('list_to_detail_ratio'))}，"
        f"详情→填写 {_percent(stages.get('detail_to_order_filling_ratio'))}，"
        f"填写→提交 {_percent(stages.get('order_filling_to_submit_ratio'))}。"
    )


def _second_stage_evidence(
    diagnosis: Mapping[str, Any],
    stages: Mapping[str, Any],
    rolling: Mapping[str, Any],
) -> str | None:
    status = str(diagnosis.get("second_stage_status") or "")
    baseline = diagnosis.get("historical_baseline") or {}
    sample_count = int(baseline.get("sample_count") or 0)
    maturity = _maturity_label(baseline.get("maturity"))
    if status in {"weak", "weak_signal"}:
        current = _percent(stages.get("browse_to_pay_ratio"))
        historic = _percent(baseline.get("second_p25"))
        peer = _percent(
            ((rolling.get("stages") or {}).get("peer_browse_to_pay_ratio"))
        )
        peer_index = diagnosis.get("second_conversion_peer_index")
        peer_text = (
            f"，本店约为同行的 {float(peer_index):.2f}"
            if isinstance(peer_index, (int, float))
            else ""
        )
        return (
            f"浏览→支付观察：当日 {current}，低于历史低位 {historic}，"
            f"且低于近30日同行参考 {peer}{peer_text}。"
            f"历史可比样本 {sample_count} 天，{maturity}，仅作观察，不单独触发调价或投放。"
        )
    if status == "sample_insufficient":
        return "浏览→支付：当前样本不足，暂不判断转化强弱。"
    if status == "baseline_unavailable":
        return "浏览→支付：缺少可比历史，暂不判断转化强弱。"
    if status == "metric_conflict":
        return "浏览→支付：来源转化率与漏斗计算不一致，暂不判断转化强弱。"
    return None


def _render_current_platform(
    platform: str,
    item: Mapping[str, Any],
) -> list[str]:
    daily = item.get("daily") or {}
    stages = daily.get("stages") or {}
    rolling = item.get("rolling_30d") or {}
    diagnosis = item.get("diagnosis") or {}
    algorithm = str(item.get("algorithm_platform") or platform)
    title = _PLATFORM_LABELS.get(platform, platform)
    lines = [f"【{title}｜业务日 {daily.get('business_date') or '—'}】"]
    if algorithm == "meituan":
        lines.append(
            f"当日漏斗：曝光 {_number(stages.get('exposure_uv'))} 人 → "
            f"浏览 {_number(stages.get('browse_uv'))} 人 → "
            f"支付 {_number(stages.get('pay_orders'))} 单"
        )
        lines.append(
            f"当日转化：曝光→浏览 {_percent(stages.get('exposure_to_browse_ratio'))}｜"
            f"浏览→支付 {_percent(stages.get('browse_to_pay_ratio'))}"
        )
    else:
        lines.append(
            f"当日漏斗：列表曝光 {_number(stages.get('list_exposure_count'))} 次 → "
            f"详情访客 {_number(stages.get('detail_visitor_count'))} 人 → "
            f"提交 {_number(stages.get('submit_orders'))} 单"
        )
        lines.append(
            f"当日转化：列表曝光→详情访客 {_percent(stages.get('list_to_detail_ratio'))}｜"
            f"详情访客→提交 {_percent(stages.get('detail_to_submit_ratio'))}"
        )
    lines.append(
        f"样本：一转{_quality_label(daily.get('first_stage_quality'))}；"
        f"二转{_quality_label(daily.get('second_stage_quality'))}。"
    )
    rolling_line = _rolling_line(algorithm, rolling)
    if rolling_line:
        lines.append(rolling_line)
    if any(str(item).startswith("source_conflict:") for item in daily.get("source_conflicts") or []):
        lines.append("数据校验：来源转化率与按漏斗计算的结果不一致，本轮仅展示事实。")
    else:
        evidence = _second_stage_evidence(diagnosis, stages, rolling)
        if evidence:
            lines.append(evidence)
        conclusion = str(diagnosis.get("conclusion") or "")
        if conclusion:
            lines.append(f"诊断：{conclusion}。")
        suggestions = [str(value) for value in diagnosis.get("suggestions") or [] if value]
        if suggestions:
            lines.append(f"建议：{suggestions[0]}")
    if daily.get("metric_fallbacks"):
        lines.append("说明：个别漏斗指标已用同平台、同业务日的经营指标补齐。")
    return lines


def render_s09_operator_report(report: Mapping[str, Any]) -> str:
    if report.get("status") == "data_gap":
        return "S9 流量与转化（真实数据只读）\n当前没有可用的平台漏斗数据，暂不作诊断。"
    as_of = str(report.get("as_of_datetime") or "")
    lines = [
        "S9 流量与转化（真实数据只读）",
        f"数据截至：{as_of[0:10]} {as_of[11:16]}".rstrip(),
    ]
    target_date = _as_of_date(report)
    for platform in _ordered_platforms(report):
        item = (report.get("platforms") or {}).get(platform) or {}
        daily = item.get("daily") or {}
        daily_date = _date(daily.get("business_date"))
        algorithm = str(item.get("algorithm_platform") or platform)
        lines.append("")
        if target_date and daily_date and daily_date != target_date:
            missing = _missing_labels(algorithm, daily.get("stages") or {})
            lines.extend([
                f"【{_PLATFORM_LABELS.get(platform, platform)}】",
                f"当日暂无可用流量与转化数据；最近业务日为 {daily_date.isoformat()}，非当前业务日，本轮不作诊断。",
            ])
            if missing:
                lines.append("缺少关键指标：" + "、".join(missing) + "。")
            continue
        lines.extend(_render_current_platform(platform, item))
    if report.get("data_gaps"):
        lines.append("")
        lines.append("其他平台暂无可用数据，本轮未纳入诊断。")
    lines.extend([
        "",
        "边界：流量与转化诊断仅提供经营观察，不自动创建调价或推广任务。",
    ])
    return "\n".join(lines)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from runtime import s01_s17_exact_route_patch as route
    from runtime import s09_traffic_conversion_real as s09

    render_s09_operator_report._S09_OPERATOR_PRESENTATION_V1 = True  # type: ignore[attr-defined]
    s09.render_s09_report = render_s09_operator_report
    route.render_s09_report = render_s09_operator_report
    route.build_s09_report = s09.build_s09_report

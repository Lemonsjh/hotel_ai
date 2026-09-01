from __future__ import annotations

import re
from typing import Any, Mapping

from runtime.algorithms.s08_promotion_display import build_s8_promotion_display
from runtime.algorithms.s10_promotion_roi import build_s10_promotion_roi
from runtime.common import emit, today
from runtime.s10_promotion_source import query_s10_promotion_performance
from runtime.s11_promotion_source import query_s11_promotion_performance


_INSTALLED = False
VERSION = "s11-per-plan-recommendation.v1"
_DEGRADED = {"", "unavailable", "data_gap", "blocked", "error"}
_AHEAD = {"ahead", "fast", "significant_fast"}
_BEHIND = {"behind", "slow", "significant_slow", "severe_slow"}
_CAMPAIGN_ID_SUFFIX = re.compile(r"\s+\S*\d{6,}\S*$")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if value in (None, "", "not_computable"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_ready(source: Mapping[str, Any] | None) -> bool:
    source_map = _mapping(source)
    status = _text(source_map.get("status") or source_map.get("source_status")).lower()
    return status not in _DEGRADED


def _promotion_state(value: Any) -> str:
    raw = _text(value)
    text = raw.lower().replace(" ", "").replace("_", "-")
    if not text:
        return "unknown"
    if any(token in raw for token in ("暂停", "已暂停")) or text in {
        "paused", "pause", "suspended", "stopped-temporarily",
    }:
        return "paused"
    if any(token in raw for token in ("投放中", "进行中", "运行中", "已开启")) or text in {
        "running", "active", "open", "opened", "enabled", "on",
    }:
        return "running"
    if any(token in raw for token in ("已结束", "已关闭", "已终止")) or text in {
        "ended", "closed", "terminated", "finished", "expired",
    }:
        return "ended"
    return "unknown"


def _sales_status(s16_result: Mapping[str, Any] | None) -> str:
    source = _mapping(s16_result)
    dynamic = _mapping(source.get("dynamic_diagnosis"))
    sales = _mapping(dynamic.get("sales"))
    return _text(
        sales.get("status")
        or sales.get("sales_status")
        or source.get("progress_status")
    ).lower()


def _s10_items(s10_result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    source = _mapping(s10_result)
    roi = _mapping(source.get("promotion_roi")) or source
    platforms = _mapping(roi.get("platforms"))
    meituan = _mapping(platforms.get("meituan"))
    return [dict(item) for item in (meituan.get("items") or []) if isinstance(item, Mapping)]


def _s8_rows(s8_result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    source = _mapping(s8_result)
    return [dict(item) for item in (source.get("rows") or []) if isinstance(item, Mapping)]


def _identity(row: Mapping[str, Any]) -> tuple[str, str]:
    return _text(row.get("launch_id")), _text(row.get("plan_id"))


def _match_s10(candidate: Mapping[str, Any], items: list[dict[str, Any]]) -> dict[str, Any] | None:
    launch_id, plan_id = _identity(candidate)
    if launch_id:
        matches = [item for item in items if _text(item.get("launch_id")) == launch_id]
        if len(matches) == 1:
            return matches[0]
    if plan_id:
        matches = [item for item in items if _text(item.get("plan_id")) == plan_id]
        if len(matches) == 1:
            return matches[0]
    return None


def _label(row: Mapping[str, Any]) -> str:
    name = _text(
        row.get("launch_name")
        or row.get("promotion_name")
        or row.get("plan_name")
        or row.get("plan_id")
        or row.get("launch_id")
    )
    return _CAMPAIGN_ID_SUFFIX.sub("", name) or "未命名推广计划"


def _dominated_by_running_plan(
    item: Mapping[str, Any],
    all_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    roas = _number(item.get("observed_roas"))
    cpa = _number(item.get("cpa"))
    if roas is None or cpa is None:
        return None
    current_launch = _text(item.get("launch_id"))
    for other in all_items:
        if _text(other.get("launch_id")) == current_launch:
            continue
        if _promotion_state(other.get("promotion_status")) != "running":
            continue
        other_roas = _number(other.get("observed_roas"))
        other_cpa = _number(other.get("cpa"))
        if other_roas is None or other_cpa is None:
            continue
        if (
            other_roas >= roas
            and other_cpa <= cpa
            and (other_roas > roas or other_cpa < cpa)
        ):
            return other
    return None


def build_per_plan_recommendations(
    *,
    s8_result: Mapping[str, Any] | None,
    s10_result: Mapping[str, Any] | None,
    s15_result: Mapping[str, Any] | None,
    s16_result: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    items = _s10_items(s10_result)
    candidates = _s8_rows(s8_result) or items
    sales_status = _sales_status(s16_result)
    formal_ready = all(
        _source_ready(source)
        for source in (s10_result, s15_result, s16_result)
    )

    recommendations: list[dict[str, Any]] = []
    for candidate in candidates:
        launch_id = _text(candidate.get("launch_id"))
        if not launch_id:
            continue
        item = _match_s10(candidate, items)
        state = _promotion_state((item or {}).get("promotion_status"))
        roas = _number((item or {}).get("observed_roas"))
        cpa = _number((item or {}).get("cpa"))
        suggested_action = "观察"
        reason = "缺少可用于计划级动作判断的完整正式证据。"
        dominated_by: dict[str, Any] | None = None

        if formal_ready and item is not None and _text(item.get("status")).lower() != "data_gap":
            if state == "running":
                if roas is not None and roas <= 1:
                    suggested_action = "暂停"
                    reason = "计划正在投放，S10 观测 ROAS≤1，继续投放缺少效率依据。"
                else:
                    dominated_by = _dominated_by_running_plan(item, items)
                    if sales_status in _AHEAD and dominated_by is not None:
                        suggested_action = "暂停"
                        reason = (
                            "当前销售进度超前，且存在同时投放、ROAS 更高且 CPA 更低的计划；"
                            "该计划在现有可比效率证据下处于严格劣势。"
                        )
                    else:
                        suggested_action = "维持"
                        if sales_status in _BEHIND:
                            reason = "当前销售进度落后，计划仍在投放且未触发低效暂停条件，建议维持并继续观察效果。"
                        elif sales_status in _AHEAD:
                            reason = "当前销售进度超前，但该计划未被其他在投计划同时以更高 ROAS、更低 CPA 严格支配，建议维持而不加投。"
                        else:
                            reason = "计划正在投放，当前正式证据未触发暂停条件，建议维持并继续观察。"
            elif state == "paused":
                if sales_status in _BEHIND and roas is not None and roas > 1:
                    suggested_action = "恢复"
                    reason = "计划当前已暂停；销售进度落后且该计划窗口观测 ROAS>1，具备恢复投放的经营与效率依据。"
                else:
                    suggested_action = "观察"
                    reason = "计划当前已暂停，但尚未同时满足销售落后和窗口观测 ROAS>1 的恢复条件，暂不建议恢复。"
            elif state == "ended":
                suggested_action = "观察"
                reason = "计划状态已结束/关闭，不应把历史绩效直接转换为恢复任务。"
            else:
                suggested_action = "观察"
                reason = "无法确认计划当前是投放中还是已暂停，因此不生成暂停/恢复动作建议。"

        recommendation = {
            "plan_id": candidate.get("plan_id"),
            "plan_name": candidate.get("plan_name"),
            "launch_id": launch_id,
            "launch_name": candidate.get("launch_name"),
            "promotion_name": candidate.get("promotion_name"),
            "source_snapshot_time": candidate.get("snapshot_time") or candidate.get("source_snapshot_time"),
            "promotion_status": (item or {}).get("promotion_status"),
            "current_state": state,
            "suggested_action": suggested_action,
            "observed_roas": (item or {}).get("observed_roas"),
            "cpa": (item or {}).get("cpa"),
            "reason": reason,
            "formal_evidence_complete": formal_ready,
            "write_performed": False,
        }
        if dominated_by is not None:
            recommendation["dominated_by_launch_id"] = dominated_by.get("launch_id")
            recommendation["dominated_by_plan_name"] = dominated_by.get("plan_name")
        recommendations.append(recommendation)

    return recommendations


def _s11_view(source_result: Mapping[str, Any]) -> dict[str, Any]:
    source = _mapping(source_result)
    payload = _mapping(source.get("payload"))
    raw_rows = [dict(item) for item in (payload.get("rows") or []) if isinstance(item, Mapping)]
    display = build_s8_promotion_display(source)
    by_launch = {
        _text(row.get("launch_id")): row
        for row in raw_rows
        if _text(row.get("launch_id"))
    }
    rows: list[dict[str, Any]] = []
    for item in (display.get("items") or []):
        if not isinstance(item, Mapping):
            continue
        copied = dict(item)
        raw = by_launch.get(_text(copied.get("launch_id")), {})
        if raw.get("promotion_status") not in (None, ""):
            copied["promotion_status"] = raw.get("promotion_status")
        copied["deterministic_display_metrics"] = {"roas": copied.get("roas")}
        rows.append(copied)
    result = dict(display)
    result["rows"] = rows
    result["snapshot_policy"] = payload.get("snapshot_policy")
    result["launch_snapshot_times"] = payload.get("launch_snapshot_times") or {}
    return result


def _format_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _state_label(value: str) -> str:
    return {
        "running": "投放中",
        "paused": "已暂停",
        "ended": "已结束/关闭",
        "unknown": "状态未知",
    }.get(value, value)


def _recommendation_lines(plan: Mapping[str, Any]) -> list[str]:
    rows = [
        dict(item)
        for item in (plan.get("per_plan_recommendations") or [])
        if isinstance(item, Mapping)
    ]
    lines: list[str] = []
    for item in rows:
        name = _label(item)
        action = _text(item.get("suggested_action")) or "观察"
        state = _state_label(_text(item.get("current_state")) or "unknown")
        detail = [f"建议{action}", f"状态 {state}"]
        detail.append(_text(item.get("reason")))
        lines.append(f"{name}：" + "｜".join(detail))
    return lines


def _portfolio_summary(plan: Mapping[str, Any]) -> str:
    rows = [
        dict(item)
        for item in (plan.get("per_plan_recommendations") or [])
        if isinstance(item, Mapping)
    ]
    if not rows:
        return ""
    parts = [
        f"{_label(item)}→{_text(item.get('suggested_action')) or '观察'}"
        for item in rows
    ]
    return "分计划建议：" + "；".join(parts) + "。"


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.decisions import promotion as promotion_module
    from runtime import s11_promotion_execution_patch as execution_module
    from runtime import s11_readonly_plan_patch as readonly_module

    previous_build = promotion_module.build_s11_promotion_plan
    if not getattr(previous_build, "_S11_PER_PLAN_V1", False):
        def build_s11_promotion_plan(**kwargs: Any) -> dict[str, Any]:
            result = previous_build(**kwargs)
            plan = _mapping(result.get("promotion_plan"))
            if not plan:
                return result
            recommendations = build_per_plan_recommendations(
                s8_result=kwargs.get("s8_result"),
                s10_result=kwargs.get("s10_result"),
                s15_result=kwargs.get("s15_result"),
                s16_result=kwargs.get("s16_result"),
            )
            plan["per_plan_recommendations"] = recommendations
            plan["recommendation_policy"] = "per_launch_formal_evidence_v1"
            scoped_launch = _text(_mapping(plan.get("plan_scope")).get("launch_id"))
            scoped_plan = _text(_mapping(plan.get("plan_scope")).get("plan_id"))
            if scoped_launch or scoped_plan:
                matches = [
                    item for item in recommendations
                    if (scoped_launch and _text(item.get("launch_id")) == scoped_launch)
                    or (not scoped_launch and scoped_plan and _text(item.get("plan_id")) == scoped_plan)
                ]
                if len(matches) == 1:
                    plan["suggested_action"] = matches[0].get("suggested_action") or "观察"
            result["promotion_plan"] = plan
            return result

        build_s11_promotion_plan._S11_PER_PLAN_V1 = True  # type: ignore[attr-defined]
        promotion_module.build_s11_promotion_plan = build_s11_promotion_plan

    def emit_s11_promotion_suggestion(args: Any) -> None:
        hotel_id = str(args.hotel_id)
        target_date = str(getattr(args, "target_date", None) or getattr(args, "date", None) or today())[:10]
        as_of_time = getattr(args, "as_of_time", None)
        message = str(getattr(args, "message", None) or "")

        s11_source = query_s11_promotion_performance(hotel_id, as_of_time=as_of_time)
        s8_result = _s11_view(s11_source)
        s9_result = promotion_module._s9_result(hotel_id, target_date=target_date, as_of_time=as_of_time)
        performance = query_s10_promotion_performance(
            hotel_id,
            as_of_time=as_of_time,
            meituan_per_launch=True,
        )
        roi = build_s10_promotion_roi(performance_result=performance, as_of_time=as_of_time)
        s10_result = {"status": roi.get("status") or "data_gap", "promotion_roi": roi}
        s15_result = getattr(args, "s15_result", None)
        if not isinstance(s15_result, dict):
            s15_result = {"status": "data_gap", "reason": "s15_result_not_supplied"}
        s16_result = getattr(args, "s16_result", None)
        if not isinstance(s16_result, dict):
            s16_result = {"status": "data_gap", "reason": "s16_result_not_supplied"}

        emit(
            promotion_module.build_s11_promotion_plan(
                hotel_id=hotel_id,
                message=message,
                target_date=target_date,
                as_of_time=as_of_time,
                s8_result=s8_result,
                s9_result=s9_result,
                s10_result=s10_result,
                s16_result=s16_result,
                s15_result=s15_result,
            )
        )

    promotion_module._emit_s11_promotion_suggestion = emit_s11_promotion_suggestion

    def execution_latest_rows(
        hotel_id: str,
        *,
        as_of_time: str | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        result = query_s11_promotion_performance(hotel_id, as_of_time=as_of_time)
        payload = _mapping(result.get("payload"))
        if result.get("status") != "ok":
            raise execution_module.PromotionControlError(
                str(result.get("reason") or "promotion_source_unavailable")
            )
        rows = [dict(row) for row in (payload.get("rows") or []) if isinstance(row, Mapping)]
        if not rows:
            raise execution_module.PromotionControlError("promotion_launch_not_found")
        return rows, payload

    execution_module._latest_rows = execution_latest_rows

    previous_adapt = readonly_module._adapt_s11_promotion_result
    if not getattr(previous_adapt, "_S11_PER_PLAN_V1", False):
        def adapt_s11_promotion_result(result: Mapping[str, Any]) -> dict[str, Any]:
            adapted = previous_adapt(result)
            plan = _mapping(adapted.get("promotion_plan"))
            if not plan:
                return adapted
            lines = _recommendation_lines(plan)
            if lines:
                evidence = _mapping(adapted.get("evidence"))
                evidence["s11_plan_recommendations"] = {
                    "observations": lines,
                    "recommendation_contract": "one recommendation per unique launch_id",
                }
                adapted["evidence"] = evidence
                portfolio = _portfolio_summary(plan)
                if portfolio:
                    adapted["summary"] = portfolio
            return adapted

        adapt_s11_promotion_result._S11_PER_PLAN_V1 = True  # type: ignore[attr-defined]
        readonly_module._adapt_s11_promotion_result = adapt_s11_promotion_result

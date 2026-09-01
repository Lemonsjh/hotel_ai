from __future__ import annotations

import re
from typing import Any, Mapping


VERSION = "s11-readonly-promotion-plan.v3"
SUGGESTED_ACTIONS = ("开启", "恢复", "维持", "观察", "暂停", "关闭")
_DEGRADED_STATUSES = {"", "unavailable", "data_gap", "blocked", "error"}


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


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _rows(source: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    source_map = _mapping(source)
    values = source_map.get("rows") or []
    return [dict(item) for item in values if isinstance(item, Mapping)]


def _requested_action(message: str) -> str | None:
    text = _text(message).lower()
    checks = (
        ("暂停", ("暂停",)),
        ("关闭", ("关闭", "关掉")),
        ("恢复", ("恢复",)),
        ("开启", ("开启", "打开")),
        ("维持", ("维持", "保持")),
        ("观察", ("观察",)),
    )
    for action, tokens in checks:
        if any(token in text for token in tokens):
            return action
    return None


def _manual_money(message: str, label: str) -> dict[str, Any]:
    text = _text(message)
    pattern = re.compile(
        rf"{label}(?:\s*(?:改为|调整为|修改为|设为|调到|改到|为|到))?"
        r"\s*[¥￥]?\s*(\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return {"status": "manual_input_required"}
    return {
        "status": "suggested_manual_input",
        "amount": float(match.group(1)),
        "currency": "CNY",
        "write_performed": False,
    }


def _identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": row.get("plan_id"),
        "plan_name": row.get("plan_name"),
        "launch_id": row.get("launch_id"),
        "launch_name": row.get("launch_name"),
        "promotion_name": row.get("promotion_name"),
    }


def _candidate_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        _text(row.get("plan_id")),
        _text(row.get("launch_id")),
        _text(row.get("promotion_name") or row.get("plan_name") or row.get("launch_name")),
    )


def _s10_candidate_rows(s10_result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    source = _mapping(s10_result)
    roi = _mapping(source.get("promotion_roi")) or source
    platforms = _mapping(roi.get("platforms"))
    meituan = _mapping(platforms.get("meituan"))
    return [dict(item) for item in (meituan.get("items") or []) if isinstance(item, Mapping)]


def _promotion_candidates(
    s8_result: Mapping[str, Any] | None,
    s10_result: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    rows = _rows(s8_result) or _s10_candidate_rows(s10_result)
    for row in rows:
        key = _candidate_key(row)
        if key in seen:
            continue
        seen.add(key)
        candidate = _identity(row)
        candidate["source_snapshot_time"] = row.get("snapshot_time")
        result.append(candidate)
    return result


def _message_matches_candidate(message: str, candidate: Mapping[str, Any]) -> bool:
    text = _text(message).lower()
    if not text:
        return False
    for key in ("plan_id", "plan_name", "launch_id", "launch_name", "promotion_name"):
        value = _text(candidate.get(key)).lower()
        if value and value in text:
            return True
    return False


def _needs_single_object(message: str, action: str | None, budget: Mapping[str, Any], bid: Mapping[str, Any]) -> bool:
    text = _text(message)
    if any(token in text for token in ("这个计划", "该计划", "某计划", "这个投放", "该投放")):
        return True
    if action is not None and any(token in text for token in ("计划", "投放", "广告")):
        return True
    return budget.get("status") != "manual_input_required" or bid.get("status") != "manual_input_required"


def _resolve_scope(
    message: str,
    candidates: list[dict[str, Any]],
    *,
    action: str | None,
    budget: Mapping[str, Any],
    bid: Mapping[str, Any],
) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
    matches = [item for item in candidates if _message_matches_candidate(message, item)]
    if len(matches) == 1:
        return "resolved", matches[0], matches
    if len(matches) > 1:
        return "clarification_required", None, matches

    if _needs_single_object(message, action, budget, bid):
        if len(candidates) == 1:
            return "resolved", candidates[0], candidates
        if len(candidates) > 1:
            return "clarification_required", None, candidates
        return "unresolved", None, []

    return "portfolio", None, candidates


def _source_status(source: Mapping[str, Any] | None) -> str:
    source_map = _mapping(source)
    return _text(source_map.get("status") or source_map.get("source_status") or "unavailable")


def _s9_observation(s9_result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    source = _mapping(s9_result)
    funnel = _mapping(source.get("funnel")) or source
    keys = (
        "exposure_uv",
        "intention_uv",
        "pay_order_count",
        "browse_conversion_rate",
        "pay_conversion_rate",
    )
    values = {key: funnel.get(key) for key in keys if funnel.get(key) not in (None, "")}
    if not values:
        return None
    return {
        "source": "S9",
        "role": "advisory_reference",
        "reference_only": True,
        **values,
    }


def _s10_items(s10_result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    source = _mapping(s10_result)
    roi = _mapping(source.get("promotion_roi")) or source
    platforms = _mapping(roi.get("platforms"))
    meituan = _mapping(platforms.get("meituan"))
    return [dict(item) for item in (meituan.get("items") or []) if isinstance(item, Mapping)]


def _s10_observations(s10_result: Mapping[str, Any] | None, plan_scope: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    plan_id = _text((plan_scope or {}).get("plan_id"))
    launch_id = _text((plan_scope or {}).get("launch_id"))
    for item in _s10_items(s10_result):
        if plan_id and _text(item.get("plan_id")) not in {"", plan_id}:
            continue
        if launch_id and _text(item.get("launch_id")) not in {"", launch_id}:
            continue
        result.append(
            {
                "source": "S10",
                "plan_id": item.get("plan_id"),
                "plan_name": item.get("plan_name"),
                "launch_id": item.get("launch_id"),
                "launch_name": item.get("launch_name"),
                "promotion_name": item.get("promotion_name"),
                "promotion_status": item.get("promotion_status"),
                "period_start_date": item.get("period_start_date"),
                "period_end_date": item.get("period_end_date"),
                "snapshot_time": item.get("snapshot_time"),
                "observed_roas": item.get("observed_roas"),
                "cpa": item.get("cpa"),
                "booking_order_count": item.get("booking_order_count"),
                "spend_amount": item.get("spend_amount"),
            }
        )
    return result


def _s8_observations(s8_result: Mapping[str, Any] | None, plan_scope: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    plan_id = _text((plan_scope or {}).get("plan_id"))
    launch_id = _text((plan_scope or {}).get("launch_id"))
    for row in _rows(s8_result):
        if plan_id and _text(row.get("plan_id")) != plan_id:
            continue
        if launch_id and _text(row.get("launch_id")) != launch_id:
            continue
        metrics = _mapping(row.get("deterministic_display_metrics"))
        result.append(
            {
                "source": "S8",
                **_identity(row),
                "spend_amount": row.get("spend_amount"),
                "booking_order_count": row.get("booking_order_count"),
                "room_night_count": row.get("room_night_count"),
                "roas": metrics.get("roas"),
            }
        )
    return result[:20]


def _s15_observation(s15_result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    source = _mapping(s15_result)
    if not source or _source_status(source) in _DEGRADED_STATUSES:
        return None
    baseline = _mapping(source.get("baseline")) or source
    hotel = _mapping(baseline.get("hotel"))
    target_room_nights = _first_present(
        baseline.get("target_room_nights"),
        baseline.get("daily_target_room_nights"),
        hotel.get("effective_target_room_nights"),
    )
    selected_dates = baseline.get("selected_dates") or []
    sample_count = len(selected_dates) if isinstance(selected_dates, list) and selected_dates else None
    values = {
        "target_room_nights": target_room_nights,
        "sample_count": sample_count,
        "baseline_confidence": _first_present(baseline.get("baseline_confidence"), baseline.get("source_confidence")),
        "operating_evidence": True,
    }
    values = {key: value for key, value in values.items() if value not in (None, "")}
    return {"source": "S15", "role": "operating_evidence", **values}


def _s16_observation(s16_result: Mapping[str, Any] | None) -> dict[str, Any] | None:
    source = _mapping(s16_result)
    dynamic = _mapping(source.get("dynamic_diagnosis"))
    sales = _mapping(dynamic.get("sales"))
    values = {
        "sales_status": _first_present(sales.get("status"), sales.get("sales_status"), source.get("progress_status")),
        "checkpoint_room_gap": _first_present(sales.get("checkpoint_room_gap"), source.get("room_night_gap")),
        "remaining_target_gap": _first_present(sales.get("remaining_target_gap"), source.get("daily_remaining_room_nights")),
        "sales_progress_delta_pp": _first_present(sales.get("sales_progress_delta_pp"), source.get("sales_progress_delta_pp")),
        "actual_room_nights": source.get("actual_room_nights"),
        "checkpoint_target_room_nights": source.get("checkpoint_target_room_nights"),
        "target_room_nights": source.get("target_room_nights"),
    }
    values = {key: value for key, value in values.items() if value not in (None, "")}
    if not values:
        return None
    return {"source": "S16", **values}


def _stop_conditions(s10_result: Mapping[str, Any] | None) -> list[str]:
    result = ["任何预算、出价或计划状态变更都必须由人工在实际渠道后台确认。"]
    if any((_number(item.get("observed_roas")) or 999999) <= 1 for item in _s10_items(s10_result)):
        result.append("S10 观测 ROAS ≤ 1 时停止扩量，并先人工复盘成本与归因口径。")
    return result


def build_s11_promotion_plan(
    *,
    hotel_id: str,
    message: str,
    target_date: str,
    as_of_time: str | None,
    s8_result: Mapping[str, Any] | None,
    s9_result: Mapping[str, Any] | None,
    s10_result: Mapping[str, Any] | None,
    s16_result: Mapping[str, Any] | None,
    s15_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, read-only S11 recommendation plan."""

    action = _requested_action(message)
    budget = _manual_money(message, "预算")
    bid = _manual_money(message, "出价")
    candidates = _promotion_candidates(s8_result, s10_result)
    scope_status, plan_scope, scope_candidates = _resolve_scope(
        message,
        candidates,
        action=action,
        budget=budget,
        bid=bid,
    )

    suggested_action = action or "观察"
    observations: list[dict[str, Any]] = []
    observations.extend(_s8_observations(s8_result, plan_scope))
    s9 = _s9_observation(s9_result)
    if s9:
        observations.append(s9)
    observations.extend(_s10_observations(s10_result, plan_scope))
    s15 = _s15_observation(s15_result)
    if s15:
        observations.append(s15)
    s16 = _s16_observation(s16_result)
    if s16:
        observations.append(s16)

    source_alignment = {
        "hotel_id": hotel_id,
        "channel": "meituan",
        "target_date": target_date,
        "as_of_time": as_of_time,
        "sources": {
            "S8": _source_status(s8_result),
            "S10": _source_status(s10_result),
            "S15": _source_status(s15_result),
            "S16": _source_status(s16_result),
        },
        "reference_sources": {
            "S9": _source_status(s9_result),
        },
        "reference_policy": {
            "S9": "advisory_traffic_context_only_not_a_promotion_gate",
        },
    }
    missing_sources = [key for key, value in source_alignment["sources"].items() if value in _DEGRADED_STATUSES]

    risks = ["S11 输出仅为人工运营建议，不代表渠道中的任何状态已经改变。"]
    if missing_sources:
        risks.append("以下正式经营/推广证据当前不完整：" + "、".join(missing_sources) + "。")
    if scope_status == "clarification_required":
        risks.append("目标计划存在歧义；在人工明确对象前，不应据此执行任何渠道操作。")

    checklist = [
        "人工核对目标酒店、渠道、计划/投放单元和时间窗口。",
        "人工检查活动报名、叠加优惠和其他营销动作是否存在冲突。",
        "人工确认预算和出价后，再自行前往渠道后台操作。",
        "操作后继续观察 S10 推广效果、S15 经营基准和 S16 销售进度；S9 流量漏斗仅作为辅助参考。",
    ]

    plan = {
        "type": "PromotionPlan",
        "version": VERSION,
        "hotel_id": hotel_id,
        "channel": "meituan",
        "window": {"target_date": target_date, "as_of_time": as_of_time},
        "scope_resolution": scope_status,
        "plan_scope": plan_scope,
        "plan_candidates": scope_candidates[:20] if scope_status in {"clarification_required", "unresolved"} else [],
        "suggested_action": suggested_action,
        "suggested_time_window": {
            "status": "manual_input_required",
            "reference_date": target_date,
        },
        "budget": budget,
        "bid": bid,
        "activity_conflict": {
            "status": "manual_input_required",
            "reason": "S11 的正式经营/推广证据为 S8/S10/S15/S16；S9 只作流量参考，活动冲突仍需人工核验。",
        },
        "observation_metrics": observations,
        "stop_conditions": _stop_conditions(s10_result),
        "risks": risks,
        "manual_operation_checklist": checklist,
        "source_alignment": source_alignment,
        "read_only": True,
        "ai_invoked": False,
        "write_performed": False,
    }

    formal_observations = [
        item for item in observations if str(item.get("source") or "").upper() != "S9"
    ]
    if scope_status == "clarification_required":
        status = "clarification_required"
    elif not formal_observations and len(missing_sources) == 4:
        status = "data_gap"
    else:
        status = "suggestion_only"

    return {
        "skill_id": "S11",
        "status": status,
        "promotion_plan": plan,
        "boundary": {
            "mode": "read_only_recommendation_only",
            "allowed_output": "PromotionPlan",
            "side_effects": "none",
        },
        "read_only": True,
        "ai_invoked": False,
        "write_performed": False,
    }

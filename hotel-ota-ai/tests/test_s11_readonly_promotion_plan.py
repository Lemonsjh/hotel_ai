from __future__ import annotations

import json

from runtime.algorithms.s11_promotion_plan import build_s11_promotion_plan
from runtime.s11_readonly_plan_patch import is_s11_readonly_intent


def _s8(*rows):
    return {"status": "ok", "rows": list(rows)}


def _base(**kwargs):
    return build_s11_promotion_plan(
        hotel_id="puyue",
        message=kwargs.pop("message", "推广建议"),
        target_date="2026-08-07",
        as_of_time="2026-08-07T19:00:00+08:00",
        s8_result=kwargs.pop(
            "s8_result",
            _s8({"plan_id": "P1", "plan_name": "夏季推广", "launch_id": "L1", "launch_name": "默认投放"}),
        ),
        s9_result=kwargs.pop("s9_result", {"status": "ok", "funnel": {"exposure_uv": 1000, "intention_uv": 120, "pay_order_count": 8}}),
        s10_result=kwargs.pop("s10_result", {"status": "ok", "promotion_roi": {"platforms": {"meituan": {"items": [{"plan_id": "P1", "observed_roas": 2.1, "cpa": 30}]}}}}),
        s16_result=kwargs.pop("s16_result", {"status": "ok", "dynamic_diagnosis": {"sales": {"status": "slow", "remaining_target_gap": 5}}}),
        **kwargs,
    )


def test_open_plan_is_suggestion_only() -> None:
    result = _base(message="开启这个计划")
    plan = result["promotion_plan"]
    assert result["status"] == "suggestion_only"
    assert plan["suggested_action"] == "开启"
    assert plan["scope_resolution"] == "resolved"
    assert plan["plan_scope"]["plan_id"] == "P1"
    assert result["read_only"] is True
    assert result["ai_invoked"] is False
    assert result["write_performed"] is False


def test_pause_named_plan_never_executes() -> None:
    result = _base(message="暂停夏季推广计划")
    assert result["promotion_plan"]["suggested_action"] == "暂停"
    assert result["promotion_plan"]["plan_scope"]["plan_id"] == "P1"


def test_budget_is_manual_suggestion() -> None:
    result = _base(message="把预算改为 500")
    assert result["promotion_plan"]["budget"] == {
        "status": "suggested_manual_input",
        "amount": 500.0,
        "currency": "CNY",
        "write_performed": False,
    }
    assert result["promotion_plan"]["bid"]["status"] == "manual_input_required"


def test_ambiguous_this_plan_requires_clarification_without_guessing_id() -> None:
    result = _base(
        message="关闭这个计划",
        s8_result=_s8(
            {"plan_id": "P1", "plan_name": "计划甲", "launch_id": "L1"},
            {"plan_id": "P2", "plan_name": "计划乙", "launch_id": "L2"},
        ),
    )
    plan = result["promotion_plan"]
    assert result["status"] == "clarification_required"
    assert plan["scope_resolution"] == "clarification_required"
    assert plan["plan_scope"] is None
    assert {item["plan_id"] for item in plan["plan_candidates"]} == {"P1", "P2"}


def test_output_has_no_request_task_approval_or_execution_state() -> None:
    text = json.dumps(_base(message="开启这个计划"), ensure_ascii=False)
    for forbidden in (
        "REQ-",
        '"request_id"',
        '"task_id"',
        '"approval"',
        '"execution"',
        '"dispatch_status"',
        '"confirmation_command"',
        "已提交",
        "执行中",
    ):
        assert forbidden not in text


def test_intent_rules_treat_action_language_as_s11_but_keep_s8_display_separate() -> None:
    assert is_s11_readonly_intent("开启这个计划") is True
    assert is_s11_readonly_intent("暂停某计划") is True
    assert is_s11_readonly_intent("把预算改为 500") is True
    assert is_s11_readonly_intent("调整出价到 2.5") is True
    assert is_s11_readonly_intent("查看推广通数据") is False

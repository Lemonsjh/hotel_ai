from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from runtime.decisions import promotion


ROOT = Path(__file__).resolve().parents[1]
RULE_PATH = ROOT / "runtime" / "algorithm_rules" / "promotion_execution_rules.yaml"
TABLE_MAPPING_PATH = ROOT / "docs" / "skill_to_table_mapping.md"
COVERAGE_PATH = ROOT / "docs" / "skill_coverage_matrix.md"
TRANSFORM_PATH = ROOT / "docs" / "skill_transform_plan.md"


def _stub_s11_sources(monkeypatch, *, two_plans: bool = False) -> list[dict]:
    emitted: list[dict] = []
    items = [
        {
            "plan_id": "P1",
            "plan_name": "夏季推广",
            "launch_id": "L1",
            "launch_name": "默认投放",
            "promotion_name": "推广通",
            "snapshot_time": "2026-08-07 19:00:00",
            "spend_amount": 100,
            "booking_order_count": 4,
            "room_night_count": 5,
            "roas": 2.1,
        }
    ]
    if two_plans:
        items.append(
            {
                "plan_id": "P2",
                "plan_name": "周末推广",
                "launch_id": "L2",
                "launch_name": "周末投放",
                "promotion_name": "推广通",
                "snapshot_time": "2026-08-07 19:00:00",
                "spend_amount": 80,
                "booking_order_count": 3,
                "room_night_count": 3,
                "roas": 1.8,
            }
        )

    monkeypatch.setattr(
        promotion,
        "query_s8_promotion_display",
        lambda hotel_id, *, as_of_time=None: {"status": "ok", "payload": {"source_status": "ok"}},
    )
    monkeypatch.setattr(
        promotion,
        "build_s8_promotion_display",
        lambda source: {
            "status": "ok",
            "source_status": "ok",
            "data_business_date": "2026-08-07",
            "data_snapshot_time": "2026-08-07 19:00:00",
            "items": items,
        },
    )
    monkeypatch.setattr(
        promotion,
        "_s9_result",
        lambda hotel_id, *, target_date, as_of_time: {
            "status": "ok",
            "funnel": {
                "exposure_uv": 1000,
                "intention_uv": 120,
                "pay_order_count": 8,
                "browse_conversion_rate": 0.12,
                "pay_conversion_rate": 0.0667,
            },
        },
    )
    monkeypatch.setattr(
        promotion,
        "_s10_result",
        lambda hotel_id, *, as_of_time: {
            "status": "ok",
            "promotion_roi": {
                "platforms": {
                    "meituan": {
                        "items": [
                            {
                                "plan_id": "P1",
                                "plan_name": "夏季推广",
                                "observed_roas": 2.1,
                                "cpa": 25,
                                "booking_order_count": 4,
                                "spend_amount": 100,
                            }
                        ]
                    }
                }
            },
        },
    )
    monkeypatch.setattr(promotion, "emit", emitted.append)
    return emitted


def _run_s11(monkeypatch, message: str, *, two_plans: bool = False) -> dict:
    emitted = _stub_s11_sources(monkeypatch, two_plans=two_plans)
    promotion._emit_s11_promotion_suggestion(
        Namespace(
            hotel_id="puyue",
            message=message,
            target_date="2026-08-07",
            as_of_time="2026-08-07T19:00:00+08:00",
            s16_result={
                "status": "ok",
                "dynamic_diagnosis": {
                    "sales": {
                        "status": "slow",
                        "remaining_target_gap": 5,
                        "sales_progress_delta_pp": -8.0,
                    }
                },
            },
        )
    )
    return emitted[0]


def _table_row(text: str, prefix: str) -> str:
    return next(line for line in text.splitlines() if line.startswith(prefix))


def test_s11_runtime_consumes_s8_s9_s10_s16_and_emits_promotion_plan(monkeypatch) -> None:
    result = _run_s11(monkeypatch, "推广建议")
    plan = result["promotion_plan"]

    assert result["skill_id"] == "S11"
    assert result["status"] == "suggestion_only"
    assert plan["type"] == "PromotionPlan"
    assert plan["suggested_action"] == "观察"
    assert plan["source_alignment"]["sources"] == {
        "S8": "ok",
        "S10": "ok",
        "S15": "data_gap",
        "S16": "ok",
    }
    assert plan["source_alignment"]["reference_sources"] == {"S9": "ok"}
    assert {item["source"] for item in plan["observation_metrics"]} == {"S8", "S9", "S10", "S16"}
    assert result["read_only"] is True
    assert result["ai_invoked"] is False
    assert result["write_performed"] is False


def test_approval_language_never_turns_s11_into_execution(monkeypatch) -> None:
    result = _run_s11(monkeypatch, "老板已经批准，直接开启这个计划，预算改为 500")
    plan = result["promotion_plan"]

    assert result["status"] == "suggestion_only"
    assert plan["suggested_action"] == "开启"
    assert plan["budget"] == {
        "status": "suggested_manual_input",
        "amount": 500.0,
        "currency": "CNY",
        "write_performed": False,
    }
    assert result["boundary"] == {
        "mode": "read_only_recommendation_only",
        "allowed_output": "PromotionPlan",
        "side_effects": "none",
    }
    assert result["read_only"] is True
    assert result["ai_invoked"] is False
    assert result["write_performed"] is False

    text = json.dumps(result, ensure_ascii=False)
    for forbidden in (
        "REQ-",
        '"request_id"',
        '"task_id"',
        '"approval_id"',
        '"dispatch_status"',
        '"execution_status"',
        '"confirmation_command"',
        '"promotion_execution_task"',
        '"ota_readback_status"',
        '"api_status"',
        "已提交",
        "执行中",
        "已开启",
        "已暂停",
    ):
        assert forbidden not in text


def test_pause_language_is_still_suggestion_only_after_confirmation_words(monkeypatch) -> None:
    result = _run_s11(monkeypatch, "已经确认并审批通过，暂停这个计划")
    assert result["promotion_plan"]["suggested_action"] == "暂停"
    assert result["promotion_plan"]["plan_scope"]["plan_id"] == "P1"
    assert result["read_only"] is True
    assert result["write_performed"] is False


def test_ambiguous_plan_stops_before_object_specific_action(monkeypatch) -> None:
    result = _run_s11(monkeypatch, "关闭这个计划", two_plans=True)
    plan = result["promotion_plan"]

    assert result["status"] == "clarification_required"
    assert plan["scope_resolution"] == "clarification_required"
    assert plan["plan_scope"] is None
    assert {item["plan_id"] for item in plan["plan_candidates"]} == {"P1", "P2"}
    assert result["write_performed"] is False


def test_s11_algorithm_rule_has_absolute_readonly_boundary() -> None:
    rule = json.loads(RULE_PATH.read_text(encoding="utf-8"))

    assert rule["owner_skill"] == "S11"
    assert "S8/S9/S10/S16" in rule["algorithm"]["objective"]
    assert rule["algorithm"]["thresholds"] == {
        "ai_invoked": False,
        "write_performed": False,
        "live_allowed": False,
        "execution_supported": False,
        "task_creation_supported": False,
        "approval_supported": False,
    }
    forbidden = set(rule["forbidden_actions"])
    for item in (
        "invoke_ai_for_s11_plan",
        "emit_request_id",
        "emit_confirmation_command",
        "create_formal_approval",
        "create_promotion_task",
        "dispatch_promotion_task",
        "execute_promotion_change",
        "write_ota_promotion_state",
        "write_control_plane_promotion_state",
        "simulate_ota_readback_state",
        "guess_ambiguous_plan_id_or_launch_id",
    ):
        assert item in forbidden
    assert rule["runtime_execution_status"] == "read_only_recommendation_path"


def test_s11_docs_match_current_promotion_plan_boundary() -> None:
    mapping_row = _table_row(TABLE_MAPPING_PATH.read_text(encoding="utf-8"), "| S11 |")
    assert "S8/S9/S10/S16" in mapping_row
    assert "PromotionPlan" in mapping_row
    assert "unsupported until separately approved" not in mapping_row
    assert "no AI" in mapping_row
    assert "no approval/task/dispatch/write" in mapping_row

    coverage_row = _table_row(COVERAGE_PATH.read_text(encoding="utf-8"), "| S11 |")
    assert coverage_row == "| S11 | no | yes | no | no | no |"

    transform_row = _table_row(TRANSFORM_PATH.read_text(encoding="utf-8"), "| S11 推广建议书 |")
    assert "S8/S9/S10/S16" in transform_row
    assert "PromotionPlan" in transform_row
    assert "不调用 AI、不审批、不建任务、不派发、不执行、不写状态" in transform_row

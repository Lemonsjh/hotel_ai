from __future__ import annotations

import inspect

from runtime.feishu_command_router import _detect_intent
from runtime.s11_promotion_execution_patch import (
    _write_pending_task,
    enqueue_promotion_control_task,
    promotion_control_action,
    resolve_unique_launch,
)


def _rows() -> list[dict]:
    return [
        {
            "hotel_id": "hotel-a",
            "plan_id": "plan-1",
            "plan_name": "智能计划",
            "launch_id": "090510524719",
            "launch_name": "智能计划",
            "promotion_name": "智能计划",
        },
        {
            "hotel_id": "hotel-a",
            "plan_id": "plan-2",
            "plan_name": "高效计划",
            "launch_id": "041617192624",
            "launch_name": "高效计划",
            "promotion_name": "高效计划",
        },
    ]


def test_only_explicit_positive_pause_recover_commands_enter_execution() -> None:
    assert promotion_control_action("暂停推广 090510524719") == "pause"
    assert promotion_control_action("恢复计划 高效计划") == "recover"
    assert promotion_control_action("是否应该暂停推广 090510524719") is None
    assert promotion_control_action("给我暂停推广的建议") is None
    assert promotion_control_action("不要暂停推广 090510524719") is None
    assert promotion_control_action("不恢复推广 高效计划") is None
    assert promotion_control_action("暂停一下") is None


def test_runtime_routes_only_positive_commands_to_execution() -> None:
    assert _detect_intent("暂停推广 090510524719") == "promotion_control_execute"
    assert _detect_intent("恢复推广 高效计划") == "promotion_control_execute"
    assert _detect_intent("是否应该暂停推广 090510524719") != "promotion_control_execute"
    assert _detect_intent("不要暂停推广 090510524719") != "promotion_control_execute"


def test_name_is_only_lookup_hint_and_resolves_to_unique_launch_id() -> None:
    result = resolve_unique_launch(
        hotel_id="hotel-a",
        message="暂停推广 高效计划",
        rows=_rows(),
    )

    assert result["status"] == "resolved"
    assert result["hotel_id"] == "hotel-a"
    assert result["platform"] == "meituan"
    assert result["launch_id"] == "041617192624"
    assert result["matched_by"] == "source_name_to_launch_id"


def test_plan_id_is_lookup_only_and_maps_to_launch_id() -> None:
    rows = [
        {
            "plan_id": "090510524719",
            "plan_name": "计划一",
            "launch_id": "launch-real-001",
        }
    ]
    result = resolve_unique_launch(
        hotel_id="hotel-a",
        message="暂停推广计划 090510524719",
        rows=rows,
    )

    assert result["status"] == "resolved"
    assert result["plan_id"] == "090510524719"
    assert result["launch_id"] == "launch-real-001"
    assert result["matched_by"] == "plan_id_to_launch_id"


def test_explicit_launch_id_still_has_to_exist_in_hotel_scoped_source() -> None:
    found = resolve_unique_launch(
        hotel_id="hotel-a",
        message="暂停推广 090510524719",
        rows=_rows(),
    )
    missing = resolve_unique_launch(
        hotel_id="hotel-a",
        message="暂停推广 999999999999",
        rows=_rows(),
    )

    assert found["status"] == "resolved"
    assert found["launch_id"] == "090510524719"
    assert missing["status"] == "blocked"
    assert missing["reason"] == "promotion_launch_not_found"


def test_duplicate_name_requires_launch_id_clarification_and_never_writes() -> None:
    duplicate_rows = [
        {"plan_name": "智能计划", "launch_id": "launch-a"},
        {"plan_name": "智能计划", "launch_id": "launch-b"},
    ]
    writes: list[dict] = []

    result = enqueue_promotion_control_task(
        hotel_id="hotel-a",
        message="暂停推广 智能计划",
        action="pause",
        rows=duplicate_rows,
        writer=lambda **kwargs: writes.append(kwargs) or 1,
    )

    assert result["status"] == "clarification_required"
    assert result["reason"] == "promotion_identifier_maps_to_multiple_launch_ids"
    assert {item["launch_id"] for item in result["candidates"]} == {"launch-a", "launch-b"}
    assert result["write_performed"] is False
    assert writes == []


def test_enqueue_passes_verified_hotel_launch_and_allowed_action_only() -> None:
    captured: list[dict] = []

    result = enqueue_promotion_control_task(
        hotel_id="hotel-a",
        message="恢复推广 041617192624",
        action="recover",
        rows=_rows(),
        writer=lambda **kwargs: captured.append(kwargs) or 27,
    )

    assert result["status"] == "pending"
    assert result["task_status"] == "pending"
    assert result["task_id"] == 27
    assert result["platform"] == "meituan"
    assert result["launch_id"] == "041617192624"
    assert captured == [
        {"hotel_id": "hotel-a", "launch_id": "041617192624", "action": "recover"}
    ]


def test_unsupported_action_is_blocked_before_write() -> None:
    writes: list[dict] = []
    result = enqueue_promotion_control_task(
        hotel_id="hotel-a",
        message="关闭推广 090510524719",
        action="close",
        rows=_rows(),
        writer=lambda **kwargs: writes.append(kwargs) or 1,
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "unsupported_promotion_control_action"
    assert result["write_performed"] is False
    assert writes == []


def test_mysql_insert_contract_hardcodes_meituan_and_pending() -> None:
    source = inspect.getsource(_write_pending_task)

    assert "ota_promotion_control_task" in source
    assert "'meituan'" in source
    assert "'pending'" in source
    assert "error_message" in source
    assert "executed_at" in source
    assert "ALLOWED_ACTIONS" in source

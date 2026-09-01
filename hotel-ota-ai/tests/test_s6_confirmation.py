from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from unittest import mock

from runtime.feishu_command_router import (
    _create_s5_candidate_confirmations,
    _detect_intent,
    _s6_current_price_matches,
    _trusted_s6_hotel_name,
    _write_s6_confirmation_fast,
)
from runtime.s6_confirmation import claim_confirmation, create_confirmation, record_rejected_preview
from runtime.storage import connect, init_schema


def _seed_hotel(db_path: str, hotel_id: str, name: str) -> None:
    with connect(db_path) as conn:
        init_schema(conn)
        conn.execute(
            "INSERT INTO hotels (hotel_id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (hotel_id, name, "2026-08-19 00:00:00", "2026-08-19 00:00:00"),
        )


def test_s6_confirmation_token_is_single_use_and_scoped(tmp_path) -> None:
    db_path = str(tmp_path / "control.sqlite")
    created = create_confirmation(
        db_path, hotel_id="hotel-a", chat_id="oc_1", requester_id="user-1",
        payload={"ota_product_id": "p-1", "old_price": 100},
    )
    assert created["status"] == "pending"
    claimed = claim_confirmation(
        db_path, confirmation_id=created["confirmation_id"], hotel_id="hotel-a", chat_id="oc_1", actor_id="owner-1"
    )
    assert claimed["status"] == "claimed"
    repeated = claim_confirmation(
        db_path, confirmation_id=created["confirmation_id"], hotel_id="hotel-a", chat_id="oc_1", actor_id="owner-1"
    )
    assert repeated["reason"] == "s6_confirmation_not_pending"


def test_s6_confirmation_serializes_datetime_payload_as_iso(tmp_path) -> None:
    db_path = str(tmp_path / "control-datetime.sqlite")
    created = create_confirmation(
        db_path,
        hotel_id="hotel-a",
        chat_id="oc_1",
        requester_id="user-1",
        payload={"data_snapshot_time": datetime(2026, 8, 10, 16, 30, 0)},
    )

    assert created["status"] == "pending"
    claimed = claim_confirmation(
        db_path,
        confirmation_id=created["confirmation_id"],
        hotel_id="hotel-a",
        chat_id="oc_1",
        actor_id="user-1",
    )
    assert claimed["payload"]["data_snapshot_time"] == "2026-08-10T16:30:00"


def test_s6_confirmation_explains_latest_rejected_preview_without_token(tmp_path) -> None:
    db_path = str(tmp_path / "control-rejected.sqlite")
    record_rejected_preview(
        db_path,
        hotel_id="hotel-a",
        chat_id="oc_1",
        requester_id="user-1",
        payload={"actual_change_pct": -0.105, "max_decrease_pct": 0.10},
    )

    claimed = claim_confirmation(
        db_path,
        confirmation_id=None,
        hotel_id="hotel-a",
        chat_id="oc_1",
        actor_id="user-1",
    )

    assert claimed["reason"] == "s6_latest_preview_not_confirmable"
    assert claimed["preview"]["actual_change_pct"] == -0.105


def test_s5_triggered_candidate_creates_a_confirmable_s6_token(tmp_path) -> None:
    db_path = str(tmp_path / "control-s5.sqlite")
    _seed_hotel(db_path, "hotel-a", "真实酒店")
    result = {
        "freshness_status": "fresh",
        "target_stay_date": "2026-08-11",
        "candidates": [
            {
                "eligibility": "eligible_for_s6_dry_run",
                "auto_execution_eligible": True,
                "s6_task_mapping_ready": True,
                "hotel_name": "璞悦酒店 Demo",
                "room_type_id": "rt-1",
                "room_type_name": "大床房",
                "channel": "meituan",
                "ota_product_id": "p-1",
                "ota_product_name": "大床房挂牌",
                "current_price": 500,
                "execution_price": 480,
                "target_stay_date": "2026-08-11",
                "price_observation_snapshot_time": "2026-08-11T10:00:00",
                "decision_ref": {"decision_id": "s5-rt-1-abc"},
            },
            {
                "eligibility": "preview_only_strong_rule_not_satisfied",
                "auto_execution_eligible": False,
                "s6_task_mapping_ready": True,
                "ota_product_id": "p-2",
            },
        ],
    }

    _create_s5_candidate_confirmations(
        result,
        hotel_id="hotel-a",
        db_path=db_path,
        chat_id="oc_1",
        requester_id="owner-1",
    )

    candidate = result["candidates"][0]
    assert result["s6_confirmation_ready_count"] == 1
    assert candidate["s6_confirmation_command"].startswith("确认调价 PRC-")
    assert "s6_confirmation_command" not in result["candidates"][1]
    claimed = claim_confirmation(
        db_path,
        confirmation_id=candidate["s6_confirmation_id"],
        hotel_id="hotel-a",
        chat_id="oc_1",
        actor_id="owner-1",
    )
    assert claimed["status"] == "claimed"
    assert claimed["payload"]["target_price"] == 480.0
    assert claimed["payload"]["hotel_name"] == "真实酒店"


def test_s6_task_hotel_name_requires_a_non_demo_control_plane_name(tmp_path) -> None:
    db_path = str(tmp_path / "control-name.sqlite")
    _seed_hotel(db_path, "hotel-a", "璞悦酒店 Demo")

    assert _trusted_s6_hotel_name(db_path, "hotel-a") is None


def test_s6_confirmation_price_query_normalizes_legacy_filters() -> None:
    with mock.patch(
        "runtime.safety._S6_DATABASE_TEMPLATE_RESULT_BASE",
        return_value={
            "payload": {
                "price_snapshots": [
                    {"channel": "meituan", "ota_product_id": "p-1", "current_price": 100}
                ]
            }
        },
    ) as query:
        matched = _s6_current_price_matches(
            hotel_id="hotel-a",
            payload={"channel": "meituan", "ota_product_id": "p-1", "old_price": 100},
        )

    assert matched is True
    assert query.call_count == 1
    args, kwargs = query.call_args
    assert args[:2] == ("ota_price_mapping", "hotel-a")
    assert kwargs["source_platform"] == "meituan"
    assert "channel" not in kwargs
    assert "ota_product_id" not in kwargs


def test_s6_confirmation_intent_is_not_a_menu_command() -> None:
    assert _detect_intent("确认") == "price_execution_confirm"
    assert _detect_intent("确认调价 PRC-ABC123") == "price_execution_confirm"


def test_s6_confirm_execute_phrase_uses_the_confirmation_path() -> None:
    assert _detect_intent("\u786e\u8ba4\u6267\u884c") == "price_execution_confirm"
    assert _detect_intent("\u786e\u8ba4\u6267\u884c\u8c03\u4ef7") == "price_execution_confirm"


def test_s6_confirmation_writes_outbox_without_waiting_for_plugin(tmp_path) -> None:
    db_path = str(tmp_path / "control.sqlite")
    _seed_hotel(db_path, "hotel-a", "真实酒店")
    created = create_confirmation(
        db_path, hotel_id="hotel-a", chat_id="oc_1", requester_id="user-1",
        payload={
            "requester_id": "user-1", "hotel_name": "璞悦酒店 Demo", "room_type_id": "rt-1", "room_type_name": "大床房",
            "channel": "meituan", "ota_product_id": "p-1", "old_price": 100, "target_price": 105,
            "target_stay_date": "2026-08-10", "data_snapshot_time": "2026-08-10T10:00:00",
        },
    )
    with mock.patch(
        "runtime.feishu_command_router.database_template_result",
        side_effect=lambda template, *_args, **_kwargs: (
                {"status": "ok", "payload": {"price_snapshots": [{"hotel_name": "璞悦酒店 Demo", "channel": "meituan", "ota_product_id": "p-1", "current_price": 100, "room_type_id": "rt-1", "snapshot_time": "2026-08-10T10:00:00", "mapping_status": "AUTO", "mapping_active": True, "mapping_resolution_status": "mapped", "source_product_id": "p-1"}]}}
            if template == "ota_price_mapping"
            else {"status": "ok", "payload": {"room_type_forecasts": [{"room_type_id": "rt-1", "available_rooms": 1}]}}
        ),
    ), mock.patch(
        "runtime.feishu_command_router.resolve_price_guard_policy",
        return_value={"source": "default_policy", "version": 1, "max_increase_pct": 0.12, "max_decrease_pct": 0.12},
    ), mock.patch(
        "runtime.feishu_command_router._capture_runtime_emit", return_value={"status": "queued", "execute_status": "PENDING"}
    ) as capture:
        result = _write_s6_confirmation_fast(
            message=f"确认调价 {created['confirmation_id']}", hotel_id="hotel-a", db_path=db_path,
            auth_context={"principal_id": "owner-1", "user_role": "owner"}, auth_config=None,
            chat_id="oc_1", chat_type="group", user_id="user-1", open_id="user-1", union_id=None,
        )
    assert result["status"] == "queued"
    assert result["execute_status"] == "PENDING"
    assert result["plugin_waited"] is False
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT payload_json FROM approvals WHERE approval_id=?",
            (result["approval_id"],),
        ).fetchone()
    approval_payload = json.loads(row[0])
    assert approval_payload["guard_version"] == 1
    assert approval_payload["price_guard_policy_version"] == 1
    assert capture.call_args.args[1].hotel_name == "真实酒店"


def test_s6_batch_confirmation_writes_each_preview_as_an_independent_task(tmp_path) -> None:
    db_path = str(tmp_path / "batch-control.sqlite")
    _seed_hotel(db_path, "hotel-a", "真实酒店")
    items = [
        {"requester_id": "user-1", "room_type_id": "rt-1", "room_type_name": "大床房", "channel": "meituan", "ota_product_id": "p-1", "old_price": 100, "target_price": 105, "target_stay_date": "2026-08-10", "data_snapshot_time": "2026-08-10T10:00:00"},
        {"requester_id": "user-1", "room_type_id": "rt-2", "room_type_name": "双床房", "channel": "meituan", "ota_product_id": "p-2", "old_price": 200, "target_price": 205, "target_stay_date": "2026-08-10", "data_snapshot_time": "2026-08-10T10:00:00"},
    ]
    created = create_confirmation(
        db_path, hotel_id="hotel-a", chat_id="oc_1", requester_id="user-1",
        payload={"requester_id": "user-1", "batch_items": items},
    )
    products = [
        {"channel": "meituan", "ota_product_id": "p-1", "current_price": 100, "room_type_id": "rt-1", "snapshot_time": "2026-08-10T10:00:00", "mapping_status": "AUTO", "mapping_active": True, "mapping_resolution_status": "mapped", "source_product_id": "p-1"},
        {"channel": "meituan", "ota_product_id": "p-2", "current_price": 200, "room_type_id": "rt-2", "snapshot_time": "2026-08-10T10:00:00", "mapping_status": "AUTO", "mapping_active": True, "mapping_resolution_status": "mapped", "source_product_id": "p-2"},
    ]
    with mock.patch(
        "runtime.feishu_command_router.database_template_result",
        side_effect=lambda template, *_args, **_kwargs: (
            {"status": "ok", "payload": {"price_snapshots": products}} if template == "ota_price_mapping"
            else {"status": "ok", "payload": {"room_type_forecasts": [{"room_type_id": "rt-1", "available_rooms": 1}, {"room_type_id": "rt-2", "available_rooms": 1}]}}
        ),
    ), mock.patch(
        "runtime.feishu_command_router.resolve_price_guard_policy",
        return_value={"source": "default_policy", "version": 1, "max_increase_pct": 0.12, "max_decrease_pct": 0.12},
    ), mock.patch(
        "runtime.feishu_command_router._capture_runtime_emit", return_value={"status": "queued", "execute_status": "PENDING"}
    ) as capture:
        result = _write_s6_confirmation_fast(
            message=f"确认调价 {created['confirmation_id']}", hotel_id="hotel-a", db_path=db_path,
            auth_context={"principal_id": "owner-1", "user_role": "owner"}, auth_config=None,
            chat_id="oc_1", chat_type="group", user_id="user-1", open_id="user-1", union_id=None,
        )

    assert result["status"] == "queued"
    assert result["batch_write"] is True
    assert result["task_count"] == 2
    assert capture.call_count == 2

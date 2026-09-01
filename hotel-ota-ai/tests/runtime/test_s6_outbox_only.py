from __future__ import annotations

import argparse
from unittest import mock

from runtime.decisions import pricing


def _dry_run_args() -> argparse.Namespace:
    return argparse.Namespace(
        db=":memory:",
        hotel_id="hotel-a",
        room_type_id="room-a",
        room_type_name="测试房型",
        hotel_name="测试酒店",
        channel="meituan",
        channel_source="meituan",
        ota_product_id="product-a",
        normal_price=200,
        old_price=190,
        begin_date="2026-08-27",
        end_date="2026-08-27",
        approved_by=None,
        approval_id=None,
        approver_role=None,
        requested_by="operator-a",
        auth_source="test",
        user_id=None,
        open_id="operator-a",
        union_id=None,
        chat_id="chat-a",
        chat_type="group",
        user_role="operator",
        auth_config=None,
        activity_discount_factors="0.9",
        pms_price=None,
        dry_run=True,
    )


def test_s6_dry_run_only_previews_outbox_without_channel_credentials() -> None:
    emitted: list[dict] = []
    policy = {
        "source": "default_policy",
        "max_increase_pct": 0.12,
        "max_decrease_pct": 0.15,
        "min_increase_pct": 0.0,
        "min_decrease_pct": 0.0,
        "version": None,
    }
    with (
        mock.patch.object(pricing, "emit", emitted.append),
        mock.patch.object(pricing, "build_auth_context", return_value={"principal_id": "operator-a"}),
        mock.patch.object(pricing, "permission_gate", return_value={"allowed": True}),
        mock.patch.object(pricing, "approval_gate", return_value={"allowed": True}),
        mock.patch.object(pricing, "resolve_price_guard_policy", return_value=policy),
    ):
        pricing.execute_price(_dry_run_args())

    assert len(emitted) == 1
    result = emitted[0]
    assert result["status"] == "dry_run"
    assert result["request"]["adapter_vendor"] == "price_task_outbox"
    assert result["dry_run_preview"]["action"] == "enqueue_price_task"
    assert result["dry_run_preview"]["channel_credentials_checked"] is False
    assert "channelkey" not in str(result).lower()
    assert "app_key" not in str(result).lower()

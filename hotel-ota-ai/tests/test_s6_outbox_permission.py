from runtime.safety.approvals import approval_gate
from runtime.safety.auth import PERMISSIONS_BY_ROLE, permission_gate


def _context(role: str) -> dict:
    return {
        "auth_status": "authorized",
        "permissions": sorted(PERMISSIONS_BY_ROLE[role]),
    }


def test_owner_can_enqueue_an_approved_price_task_without_live_permission() -> None:
    gate = permission_gate(_context("owner"), "enqueue_price_task")

    assert gate["allowed"] is True
    assert gate["required_permission"] == "enqueue_price_task"
    assert permission_gate(_context("owner"), "price_update")["allowed"] is False


def test_operator_can_enqueue_price_task_without_generic_live_permissions() -> None:
    gate = permission_gate(_context("operator"), "enqueue_price_task")

    assert gate["allowed"] is True
    assert gate["required_permission"] == "enqueue_price_task"
    assert permission_gate(_context("operator"), "price_update")["allowed"] is False
    assert permission_gate(_context("operator"), "approve_live_action")["allowed"] is False
    assert permission_gate(_context("operator"), "create_dry_run")["allowed"] is True


def test_operator_can_self_confirm_own_s6_price_execution_with_feishu_executor_id() -> None:
    gate = approval_gate(
        approved_by="principal-operator",
        dry_run=False,
        action_type="price_update",
        approval_id="appr-1",
        approver_role="operator",
        requester_id="principal-operator",
        executor_id="ou_feishu_open_id",
    )

    assert gate["allowed"] is True
    assert gate["approval_required"] is False
    assert gate["reason"] == "operator_self_confirmed_price_execution"


def test_operator_cannot_confirm_another_users_price_preview() -> None:
    gate = approval_gate(
        approved_by="principal-operator-2",
        dry_run=False,
        action_type="price_update",
        approval_id="appr-2",
        approver_role="operator",
        requester_id="principal-operator-1",
        executor_id="ou_operator_2",
    )

    assert gate["allowed"] is False
    assert gate["reason"] == "operator_price_execution_requires_same_requester"


def test_operator_still_cannot_approve_other_live_action_types() -> None:
    gate = approval_gate(
        approved_by="principal-operator",
        dry_run=False,
        action_type="promotion_update",
        approval_id="appr-3",
        approver_role="operator",
        requester_id="principal-operator",
        executor_id="ou_feishu_open_id",
    )

    assert gate["allowed"] is False
    assert gate["reason"] == "promotion_update requires admin_or_owner_approval"

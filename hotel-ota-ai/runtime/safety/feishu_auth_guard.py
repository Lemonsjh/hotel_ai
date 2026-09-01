from __future__ import annotations

import argparse
import json
from typing import Any

from runtime.common import DEFAULT_DB, emit
from runtime.safety.auth import ACTION_TO_PERMISSION, build_auth_context, permission_gate, tenant_scope_gate


DEFAULT_BLOCKED_MESSAGE = (
    "未通过飞书入口鉴权，已阻断本次请求。请确认当前会话已绑定酒店，"
    "且发送人已在角色表/SQLite Active Auth 中配置对应酒店权限。"
)

REASON_MESSAGES = {
    "missing_required_chat_id": "缺少飞书会话 ID，无法确认酒店绑定。",
    "missing_feishu_identity": "缺少飞书用户身份，无法确认成员权限。",
    "chat_not_allowed": "当前会话未在允许列表中。",
    "chat_not_bound_to_hotel": "当前飞书会话尚未绑定酒店。",
    "tenant_scope_mismatch": "请求酒店与当前会话绑定酒店不一致。",
    "tenant_selection_required": "私聊场景需要先指定或选择酒店。",
    "user_not_hotel_member": "发送人不是当前酒店成员。",
    "unknown_tenant": "请求的酒店未登记或未授权。",
    "sqlite_active_auth_unavailable": "SQLite Active Auth 不可用，生产飞书请求已 fail-closed。",
    "sqlite_principal_not_found": "发送人未登记到权限表。",
    "direct_message_policy_denied": "当前配置不允许私聊触发业务能力。",
}


def _redact_identity(value: Any) -> str | None:
    text = str(value or "").strip()
    return "set" if text else None


def _redacted_auth_context(auth_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": auth_context.get("source"),
        "auth_status": auth_context.get("auth_status"),
        "reason": auth_context.get("reason"),
        "user_role": auth_context.get("user_role"),
        "principal_present": bool(auth_context.get("principal_id")),
        "matched_by": auth_context.get("matched_by"),
        "role_map_version": auth_context.get("role_map_version"),
        "auth_backend": auth_context.get("auth_backend"),
        "global_admin": bool(auth_context.get("global_admin")),
        "resolved_hotel_id": auth_context.get("resolved_hotel_id"),
        "authorized_hotel_ids": auth_context.get("authorized_hotel_ids") or [],
        "tenant_status": auth_context.get("tenant_status"),
        "chat_type": auth_context.get("chat_type"),
        "feishu_chat_id": _redact_identity(auth_context.get("feishu_chat_id")),
        "feishu_user_id": _redact_identity(auth_context.get("feishu_user_id")),
        "feishu_open_id": _redact_identity(auth_context.get("feishu_open_id")),
        "feishu_union_id": _redact_identity(auth_context.get("feishu_union_id")),
        "permissions": auth_context.get("permissions") or [],
    }


def _blocked_message(reason: str | None) -> str:
    if reason and reason.startswith("permission_denied:"):
        return "当前角色权限不足，已阻断本次请求。"
    return REASON_MESSAGES.get(reason or "", DEFAULT_BLOCKED_MESSAGE)


def evaluate_feishu_auth_guard(
    *,
    db_path: str | None,
    auth_config: str | None,
    chat_id: str | None,
    chat_type: str | None,
    user_id: str | None,
    open_id: str | None,
    union_id: str | None,
    hotel_id: str | None,
    action: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Optional Feishu authorization preflight and diagnostic helper.

    The primary Feishu authorization path remains feishu-route/runtime auth-check.
    Use this helper when an Agent or operator needs an explicit authorization
    result without triggering downstream business logic.
    """

    auth_context = build_auth_context(
        source="feishu",
        user_id=user_id,
        open_id=open_id,
        union_id=union_id,
        chat_id=chat_id,
        chat_type=chat_type,
        config_path=auth_config,
        auth_db_path=db_path,
        requested_hotel_id=hotel_id,
    )

    resolved_hotel_id = auth_context.get("resolved_hotel_id") or hotel_id
    tenant_gate = tenant_scope_gate(auth_context, resolved_hotel_id)
    if not tenant_gate.get("allowed"):
        reason = str(tenant_gate.get("reason") or auth_context.get("reason") or "tenant_scope_mismatch")
        return {
            "status": "blocked",
            "guard": "feishu_auth_guard",
            "should_continue": False,
            "fail_closed": True,
            "reason": reason,
            "safe_user_message": _blocked_message(reason),
            "required_permission": ACTION_TO_PERMISSION.get(action, action),
            "resolved_hotel_id": auth_context.get("resolved_hotel_id"),
            "auth_context": _redacted_auth_context(auth_context),
        }

    gate = permission_gate(auth_context, action, dry_run=dry_run)
    if not gate.get("allowed"):
        reason = str(auth_context.get("reason") or gate.get("reason") or "permission_denied")
        return {
            "status": "blocked",
            "guard": "feishu_auth_guard",
            "should_continue": False,
            "fail_closed": True,
            "reason": reason,
            "safe_user_message": _blocked_message(reason),
            "required_permission": gate.get("required_permission"),
            "resolved_hotel_id": auth_context.get("resolved_hotel_id"),
            "auth_context": _redacted_auth_context(auth_context),
        }

    return {
        "status": "ok",
        "guard": "feishu_auth_guard",
        "should_continue": True,
        "fail_closed": False,
        "reason": "allowed",
        "required_permission": gate.get("required_permission"),
        "resolved_hotel_id": auth_context.get("resolved_hotel_id"),
        "hotel_id": auth_context.get("resolved_hotel_id"),
        "user_role": auth_context.get("user_role"),
        "auth_backend": auth_context.get("auth_backend"),
        "tenant_status": auth_context.get("tenant_status"),
        "auth_context": _redacted_auth_context(auth_context),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optional Feishu authorization preflight and diagnostic helper.")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--auth-config")
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--chat-type", choices=["group", "p2p"])
    parser.add_argument("--user-id")
    parser.add_argument("--open-id")
    parser.add_argument("--union-id")
    parser.add_argument("--hotel-id")
    parser.add_argument("--action", choices=sorted(ACTION_TO_PERMISSION), default="view_diagnosis")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = evaluate_feishu_auth_guard(
        db_path=args.db,
        auth_config=args.auth_config,
        chat_id=args.chat_id,
        chat_type=args.chat_type,
        user_id=args.user_id,
        open_id=args.open_id,
        union_id=args.union_id,
        hotel_id=args.hotel_id,
        action=args.action,
        dry_run=args.dry_run,
    )
    emit(result)
    # A blocked guard decision is a valid business result, not a shell failure.
    # Downstream Agent/Skill flow must read status/should_continue from JSON.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

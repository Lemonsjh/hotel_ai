from __future__ import annotations

import json
import os
from contextlib import closing
from pathlib import Path
from typing import Any

from runtime.common import now_local
from runtime.storage import connect, init_schema


ROLES = ("admin", "owner", "operator", "frontdesk", "guest")
TENANT_MEMBER_ROLES = ("owner", "operator", "frontdesk")
DIRECT_MESSAGE_POLICIES = {"role_mapped_users_only", "disabled"}

PERMISSIONS_BY_ROLE: dict[str, set[str]] = {
    "admin": {
        "view_diagnosis",
        "view_frontdesk_task",
        "run_recommendation",
        "create_dry_run",
        "create_approval",
        "approve_live_action",
        "execute_live_action",
        "enqueue_price_task",
        "manage_roles",
        "manage_safety_config",
        "view_hotel_controls",
        "request_configuration_change",
        "confirm_configuration_change",
    },
    "owner": {
        "view_diagnosis",
        "view_frontdesk_task",
        "run_recommendation",
        "create_dry_run",
        "create_approval",
        "approve_live_action",
        "enqueue_price_task",
        "view_hotel_controls",
        "request_configuration_change",
        "confirm_configuration_change",
    },
    "operator": {
        "view_diagnosis",
        "view_frontdesk_task",
        "run_recommendation",
        "create_dry_run",
        "create_approval",
        "request_configuration_change",
    },
    "frontdesk": {"view_frontdesk_task"},
    "guest": set(),
}

# A verified member of a hotel-bound Feishu group may inspect that hotel's
# operational data and generate non-executing recommendations without being
# assigned a business role.  This deliberately excludes S6, S13, and every
# action that can create, approve, publish, configure, or queue a change in
# production.
GROUP_MEMBER_READ_PERMISSIONS = {
    "view_diagnosis",
    "view_frontdesk_task",
    "run_recommendation",
    "view_hotel_controls",
}

IDENTITY_KEY_ALIASES: dict[str, tuple[str, ...]] = {
    "open_id": ("open_id", "feishu_open_id"),
    "user_id": ("user_id", "feishu_user_id"),
    "union_id": ("union_id", "feishu_union_id"),
}


def normalize_feishu_chat_id(raw_chat_id: Any) -> str | None:
    """Normalize a Feishu conversation/chat id for auth lookup.

    `user:ou_*` is a send target, not an auth chat id.
    """
    text = str(raw_chat_id or "").strip()
    if not text:
        return None
    if text.startswith("user:"):
        return None
    for prefix in ("chat:", "conversation:"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    return text or None


def resolve_feishu_business_chat_id(raw_chat_id: Any) -> dict[str, Any]:
    """Resolve a Feishu business conversation id without accepting send targets.

    Feishu direct-message send targets such as ``user:ou_*`` are useful for
    message delivery, but they are not business conversation ids and cannot
    prove hotel scope.  Return a structured reason so callers can fail closed
    without leaking the original identifier.
    """

    text = str(raw_chat_id or "").strip()
    if not text:
        return {"status": "invalid_context", "reason": "missing_required_chat_id", "chat_id": None}
    if text.startswith("user:"):
        return {"status": "invalid_context", "reason": "missing_business_chat_id", "chat_id": None}
    chat_id = normalize_feishu_chat_id(text)
    if not chat_id:
        return {"status": "invalid_context", "reason": "missing_required_chat_id", "chat_id": None}
    return {"status": "ok", "reason": "chat_id_resolved", "chat_id": chat_id}


def _nested_get(mapping: Any, path: tuple[str, ...]) -> Any:
    current = mapping
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def resolve_trusted_feishu_chat_context(
    *,
    message_text: str | None = None,
    event: dict[str, Any] | None = None,
    ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a trusted Feishu business chat id from gateway context only.

    User message text is intentionally ignored. A visible ``oc_*`` string in
    the business message is ordinary text and must never become auth context.
    """

    candidates = [
        _nested_get(event, ("message", "chat_id")),
        _nested_get(event, ("message", "conversation_id")),
        _nested_get(event, ("content", "chat_id")),
        _nested_get(event, ("channel", "chat_id")),
        _nested_get(event, ("channel", "conversationId")),
        _nested_get(event, ("conversation", "id")),
        (event or {}).get("conversationId") if isinstance(event, dict) else None,
        (event or {}).get("chatId") if isinstance(event, dict) else None,
        (ctx or {}).get("conversationId") if isinstance(ctx, dict) else None,
        (ctx or {}).get("chatId") if isinstance(ctx, dict) else None,
        (ctx or {}).get("chat_id") if isinstance(ctx, dict) else None,
    ]
    for candidate in candidates:
        resolved = resolve_feishu_business_chat_id(candidate)
        if resolved.get("status") == "ok":
            return {
                "status": "ok",
                "reason": "trusted_chat_id_resolved",
                "chat_id": resolved.get("chat_id"),
                "message_text_used": False,
            }
    return {
        "status": "invalid_context",
        "reason": "missing_trusted_business_chat_id",
        "chat_id": None,
        "message_text_used": False,
    }


def normalize_feishu_conversation_id(raw_id: Any) -> str | None:
    return normalize_feishu_chat_id(raw_id)


def _clean_identity(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _identity_values(user: dict[str, Any]) -> dict[str, set[str]]:
    return {
        canonical: {
            cleaned
            for key in aliases
            for cleaned in [_clean_identity(user.get(key))]
            if cleaned
        }
        for canonical, aliases in IDENTITY_KEY_ALIASES.items()
    }


def _config_version(config: dict[str, Any]) -> int:
    try:
        return int(config.get("version") or 1)
    except (TypeError, ValueError):
        return 0


def validate_auth_config(config: dict[str, Any]) -> list[str]:
    """Validate only public role-map structure; never expose identity values in errors."""
    errors: list[str] = []
    users = config.get("users")
    if not isinstance(users, list):
        return ["users_must_be_list"]

    version = _config_version(config)

    seen: dict[tuple[str, str], int] = {}
    for index, user in enumerate(users):
        if not isinstance(user, dict):
            errors.append("user_must_be_object")
            continue
        if version != 3 and (user.get("role") not in ROLES or user.get("role") == "guest"):
            errors.append("invalid_user_role")
        for canonical, values in _identity_values(user).items():
            for value in values:
                key = (canonical, value)
                if key in seen and seen[key] != index:
                    errors.append("duplicate_canonical_identity")
                seen[key] = index

    if version == 0:
        errors.append("invalid_role_map_version")
    if version == 2:
        group_ids = config.get("allowed_group_chat_ids")
        if not isinstance(group_ids, list):
            errors.append("allowed_group_chat_ids_must_be_list")
        if config.get("direct_message_policy") not in DIRECT_MESSAGE_POLICIES:
            errors.append("invalid_direct_message_policy")
    if version == 3:
        principals: set[str] = set()
        for user in users:
            if not isinstance(user, dict):
                continue
            principal_id = str(user.get("principal_id") or "").strip()
            if not principal_id:
                errors.append("principal_id_required")
            elif principal_id in principals:
                errors.append("duplicate_principal_id")
            else:
                principals.add(principal_id)

        global_admins = config.get("global_admin_principal_ids")
        if not isinstance(global_admins, list):
            errors.append("global_admin_principal_ids_must_be_list")
        else:
            for principal_id in global_admins:
                if principal_id not in principals:
                    errors.append("unknown_global_admin_principal")

        memberships = config.get("hotel_memberships")
        if not isinstance(memberships, list):
            errors.append("hotel_memberships_must_be_list")
        else:
            seen_memberships: set[tuple[str, str]] = set()
            for membership in memberships:
                if not isinstance(membership, dict):
                    errors.append("hotel_membership_must_be_object")
                    continue
                principal_id = str(membership.get("principal_id") or "")
                hotel_id = str(membership.get("hotel_id") or "")
                if principal_id not in principals:
                    errors.append("unknown_membership_principal")
                if not hotel_id:
                    errors.append("membership_hotel_id_required")
                if membership.get("role") not in TENANT_MEMBER_ROLES:
                    errors.append("invalid_membership_role")
                key = (principal_id, hotel_id)
                if key in seen_memberships:
                    errors.append("duplicate_hotel_membership")
                seen_memberships.add(key)

        bindings = config.get("group_chat_bindings")
        if not isinstance(bindings, list):
            errors.append("group_chat_bindings_must_be_list")
        else:
            seen_chats: set[str] = set()
            for binding in bindings:
                if not isinstance(binding, dict):
                    errors.append("group_chat_binding_must_be_object")
                    continue
                chat_id = normalize_feishu_chat_id(binding.get("chat_id")) or ""
                hotel_id = str(binding.get("hotel_id") or "")
                if not chat_id or not hotel_id:
                    errors.append("group_chat_binding_fields_required")
                    continue
                if chat_id in seen_chats:
                    errors.append("duplicate_group_chat_binding")
                seen_chats.add(chat_id)
        if config.get("direct_message_policy") not in DIRECT_MESSAGE_POLICIES:
            errors.append("invalid_direct_message_policy")
    return sorted(set(errors))

ACTION_TO_PERMISSION = {
    "view_diagnosis": "view_diagnosis",
    "view_frontdesk_task": "view_frontdesk_task",
    "run_recommendation": "run_recommendation",
    "create_dry_run": "create_dry_run",
    "create_approval": "create_approval",
    "approve_live_action": "approve_live_action",
    "execute_live_action": "execute_live_action",
    "enqueue_price_task": "enqueue_price_task",
    "manage_roles": "manage_roles",
    "manage_safety_config": "manage_safety_config",
    "view_hotel_controls": "view_hotel_controls",
    "request_configuration_change": "request_configuration_change",
    "confirm_configuration_change": "confirm_configuration_change",
    "price_update": "execute_live_action",
    "quota_update": "execute_live_action",
    "room_quota_update": "execute_live_action",
    "promotion_update": "execute_live_action",
    "review_publish": "execute_live_action",
}

WRITE_ACTIONS = {"price_update", "quota_update", "room_quota_update", "promotion_update", "review_publish"}


def load_auth_config(config_path: str | None = None) -> dict[str, Any]:
    path = config_path or os.environ.get("HOTEL_OTA_AUTH_CONFIG")
    if not path:
        return {"users": [], "allowed_chat_ids": [], "config_source": "missing"}
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {"users": [], "allowed_chat_ids": [], "config_source": path, "load_error": "file_not_found"}
    except json.JSONDecodeError as exc:
        return {"users": [], "allowed_chat_ids": [], "config_source": path, "load_error": f"invalid_json:{exc.msg}"}
    data["config_source"] = path
    return data


def bootstrap_active_auth(db_path: str, *, config_path: str) -> dict[str, Any]:
    """Import V3 bootstrap identities into SQLite without changing the JSON file."""
    config = load_auth_config(config_path)
    identity_owner: dict[tuple[str, str], str] = {}
    for user in config.get("users") or []:
        if not isinstance(user, dict):
            continue
        principal_id = str(user.get("principal_id") or "")
        for canonical, aliases in IDENTITY_KEY_ALIASES.items():
            for key in aliases:
                value = _clean_identity(user.get(key))
                if not value:
                    continue
                identity_key = (canonical, value)
                if identity_key in identity_owner and identity_owner[identity_key] != principal_id:
                    raise ValueError("bootstrap_duplicate_identity")
                identity_owner[identity_key] = principal_id
    if config.get("load_error") or _config_version(config) != 3 or validate_auth_config(config):
        raise ValueError("bootstrap_role_map_invalid")
    timestamp = now_local()
    global_admins = {str(value) for value in config.get("global_admin_principal_ids") or []}
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            for user in config.get("users", []):
                open_id = _clean_identity(user.get("open_id") or user.get("feishu_open_id"))
                user_id = _clean_identity(user.get("user_id") or user.get("feishu_user_id"))
                union_id = _clean_identity(user.get("union_id") or user.get("feishu_union_id"))
                display_name = _clean_identity(user.get("display_name") or user.get("name"))
                alias = _clean_identity(user.get("alias"))
                name_snapshot = _clean_identity(user.get("name_snapshot") or display_name)
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, user_id, union_id, display_name, alias, name_snapshot, is_global_admin, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(principal_id) DO UPDATE SET open_id=excluded.open_id, user_id=excluded.user_id, union_id=excluded.union_id, display_name=excluded.display_name, alias=excluded.alias, name_snapshot=excluded.name_snapshot, is_global_admin=excluded.is_global_admin, updated_at=excluded.updated_at",
                    (user["principal_id"], open_id, user_id, union_id, display_name, alias, name_snapshot, int(user["principal_id"] in global_admins), timestamp, timestamp),
                )
            for membership in config.get("hotel_memberships", []):
                conn.execute(
                    "INSERT INTO hotel_memberships (principal_id, hotel_id, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(principal_id, hotel_id) DO UPDATE SET role=excluded.role, status='active', updated_at=excluded.updated_at",
                    (membership["principal_id"], membership["hotel_id"], membership["role"], timestamp, timestamp),
                )
            for binding in config.get("group_chat_bindings", []):
                chat_type = str(binding.get("chat_type") or "group")
                conn.execute(
                    "INSERT INTO group_chat_bindings (chat_id, hotel_id, created_at, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(chat_id) DO UPDATE SET hotel_id=excluded.hotel_id, status='active', updated_at=excluded.updated_at",
                    (normalize_feishu_chat_id(binding["chat_id"]), binding["hotel_id"], timestamp, timestamp),
                )
                conn.execute(
                    "INSERT INTO chat_bindings (chat_id, chat_type, hotel_id, source, created_at, updated_at) VALUES (?, ?, ?, 'json_bootstrap', ?, ?) ON CONFLICT(chat_id) DO UPDATE SET chat_type=excluded.chat_type, hotel_id=excluded.hotel_id, status='active', source=excluded.source, updated_at=excluded.updated_at",
                    (normalize_feishu_chat_id(binding["chat_id"]), chat_type, binding["hotel_id"], timestamp, timestamp),
                )
            conn.execute(
                "INSERT INTO auth_backend_state (backend_name, status, schema_version, activated_at, updated_at) VALUES ('feishu_active_auth', 'active', 1, ?, ?) ON CONFLICT(backend_name) DO UPDATE SET status='active', schema_version=excluded.schema_version, activated_at=excluded.activated_at, updated_at=excluded.updated_at",
                (timestamp, timestamp),
            )
    return {"status": "ok", "auth_backend": "sqlite_active"}


def _sqlite_auth_context(db_path: str, *, chat_id: str, chat_type: str, user_id: str | None, open_id: str | None, union_id: str | None) -> dict[str, Any]:
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    try:
        with closing(connect(db_path)) as conn:
            state = conn.execute(
                "SELECT status FROM auth_backend_state WHERE backend_name='feishu_active_auth'"
            ).fetchone()
            if not state or state["status"] != "active":
                return {"auth_status": "unavailable", "reason": "sqlite_active_auth_unavailable"}
            binding = conn.execute("SELECT hotel_id, chat_type FROM chat_bindings WHERE chat_id=? AND status='active'", (chat_id,)).fetchone()
            if not binding:
                binding = conn.execute("SELECT hotel_id, 'group' AS chat_type FROM group_chat_bindings WHERE chat_id=? AND status='active'", (chat_id,)).fetchone()
            principal = conn.execute("SELECT * FROM auth_principals WHERE status='active' AND (open_id=? OR user_id=? OR union_id=?) LIMIT 1", (open_id, user_id, union_id)).fetchone()
            # Hotel-bound groups establish tenant scope.  Group members who
            # are not yet role-mapped may read, but remain guests for all
            # state-changing operations.
            if binding and chat_type == "group" and not principal:
                return {
                    "auth_status": "authorized",
                    "reason": "group_member_read_only",
                    "principal_id": None,
                    "user_role": "guest",
                    "global_admin": False,
                    "resolved_hotel_id": binding["hotel_id"],
                    "authorized_hotel_ids": [binding["hotel_id"]],
                    "tenant_status": "group_bound_read_only",
                }
            if not principal:
                return {"auth_status": "unauthorized", "reason": "sqlite_principal_not_found"}
            item = dict(principal)
            if not binding:
                memberships = conn.execute(
                    "SELECT hotel_id FROM hotel_memberships WHERE principal_id=? AND status='active'",
                    (item["principal_id"],),
                ).fetchall()
                return {
                    "auth_status": "unauthorized",
                    "reason": "chat_not_bound_to_hotel",
                    "principal_id": item["principal_id"],
                    "user_role": "admin" if bool(item.get("is_global_admin")) else "guest",
                    "global_admin": bool(item.get("is_global_admin")),
                    "resolved_hotel_id": None,
                    "authorized_hotel_ids": [str(row["hotel_id"]) for row in memberships],
                    "tenant_status": "chat_unbound",
                }
            hotel_id = binding["hotel_id"]
            membership = conn.execute("SELECT role FROM hotel_memberships WHERE principal_id=? AND hotel_id=? AND status='active'", (item["principal_id"], hotel_id)).fetchone()
            if not membership and not bool(item.get("is_global_admin")):
                if chat_type == "group":
                    return {
                        "auth_status": "authorized",
                        "reason": "group_member_read_only",
                        "principal_id": item["principal_id"],
                        "user_role": "guest",
                        "global_admin": False,
                        "resolved_hotel_id": hotel_id,
                        "authorized_hotel_ids": [hotel_id],
                        "tenant_status": "group_bound_read_only",
                    }
                return {
                    "auth_status": "unauthorized",
                    "reason": "user_not_hotel_member",
                    "principal_id": item["principal_id"],
                    "user_role": "guest",
                    "global_admin": False,
                    "resolved_hotel_id": hotel_id,
                    "authorized_hotel_ids": [hotel_id],
                    "tenant_status": "user_not_hotel_member",
                }
            return {
                "auth_status": "authorized",
                "principal_id": item["principal_id"],
                "user_role": "admin" if bool(item.get("is_global_admin")) else membership["role"],
                "global_admin": bool(item.get("is_global_admin")),
                "resolved_hotel_id": hotel_id,
                "authorized_hotel_ids": [hotel_id],
                "tenant_status": "ok",
            }
    except Exception:
        return {"auth_status": "unavailable", "reason": "sqlite_active_auth_unavailable"}
    return {"auth_status": "unauthorized", "reason": "sqlite_direct_message_not_configured"}


def _sqlite_dm_open_id_context(
    db_path: str,
    *,
    user_id: str | None,
    open_id: str | None,
    union_id: str | None,
    requested_hotel_id: str | None,
) -> dict[str, Any]:
    try:
        with closing(connect(db_path)) as conn:
            state = conn.execute(
                "SELECT status FROM auth_backend_state WHERE backend_name='feishu_active_auth'"
            ).fetchone()
            if not state or state["status"] != "active":
                return {"auth_status": "unavailable", "reason": "sqlite_active_auth_unavailable"}
            principal = conn.execute(
                "SELECT * FROM auth_principals WHERE status='active' AND (open_id=? OR user_id=? OR union_id=?) LIMIT 1",
                (open_id, user_id, union_id),
            ).fetchone()
            if not principal:
                return {"auth_status": "unauthorized", "reason": "sqlite_principal_not_found"}
            item = dict(principal)
            memberships = [
                dict(row)
                for row in conn.execute(
                    "SELECT hotel_id, role FROM hotel_memberships WHERE principal_id=? AND status='active'",
                    (item["principal_id"],),
                ).fetchall()
            ]
            authorized_hotel_ids = sorted({str(row["hotel_id"]) for row in memberships if row.get("hotel_id")})
            if not memberships:
                return {
                    "auth_status": "unauthorized",
                    "reason": "direct_message_hotel_membership_missing",
                    "principal_id": item["principal_id"],
                    "user_role": "admin" if bool(item.get("is_global_admin")) else "guest",
                    "global_admin": bool(item.get("is_global_admin")),
                    "resolved_hotel_id": None,
                    "authorized_hotel_ids": [],
                    "tenant_status": "direct_message_unbound",
                }
            selected_hotel_id = requested_hotel_id
            if not selected_hotel_id and len(authorized_hotel_ids) == 1:
                selected_hotel_id = authorized_hotel_ids[0]
            if not selected_hotel_id:
                return {
                    "auth_status": "authorized",
                    "reason": "tenant_selection_required",
                    "principal_id": item["principal_id"],
                    "user_role": "admin" if bool(item.get("is_global_admin")) else "guest",
                    "global_admin": bool(item.get("is_global_admin")),
                    "resolved_hotel_id": None,
                    "authorized_hotel_ids": authorized_hotel_ids,
                    "tenant_status": "tenant_selection_required",
                }
            membership = next((row for row in memberships if str(row.get("hotel_id")) == str(selected_hotel_id)), None)
            if not membership and not bool(item.get("is_global_admin")):
                return {
                    "auth_status": "unauthorized",
                    "reason": "tenant_scope_mismatch",
                    "principal_id": item["principal_id"],
                    "user_role": "guest",
                    "global_admin": False,
                    "resolved_hotel_id": None,
                    "authorized_hotel_ids": authorized_hotel_ids,
                    "tenant_status": "tenant_scope_mismatch",
                }
            role = "admin" if bool(item.get("is_global_admin")) else str(membership.get("role") or "guest")
            return {
                "auth_status": "authorized",
                "reason": "authorized_by_open_id_membership",
                "principal_id": item["principal_id"],
                "user_role": role,
                "global_admin": bool(item.get("is_global_admin")),
                "resolved_hotel_id": str(selected_hotel_id),
                "authorized_hotel_ids": authorized_hotel_ids,
                "tenant_status": "bound_by_open_id",
            }
    except Exception:
        return {"auth_status": "unavailable", "reason": "sqlite_active_auth_unavailable"}


def role_map_migration_preview(config_path: str | None = None) -> dict[str, Any]:
    """Describe a V1-to-V2 role-map migration without exposing or writing identities."""
    config = load_auth_config(config_path)
    if config.get("load_error"):
        return {
            "status": "error",
            "reason": config["load_error"],
            "writes_performed": False,
        }

    errors = validate_auth_config(config)
    users = config.get("users") if isinstance(config.get("users"), list) else []
    source_version = _config_version(config)
    legacy_chat_ids = config.get("allowed_chat_ids") or config.get("groupAllowFrom") or []
    groups = [value for value in legacy_chat_ids if isinstance(value, str) and not value.startswith("user:")]
    direct_entries = [value for value in legacy_chat_ids if isinstance(value, str) and value.startswith("user:")]
    if source_version == 3:
        groups = [entry for entry in config.get("group_chat_bindings", []) if isinstance(entry, dict)]
        direct_entries = []
    role_counts = {role: 0 for role in ROLES if role != "guest"}
    membership_count = 0
    hotel_count = 0
    group_binding_count = 0
    warnings: list[str] = []
    if any(
        isinstance(user, dict)
        and any(str(user.get(key) or "").strip() == "" and key in user for key in ("open_id", "user_id", "union_id", "feishu_open_id", "feishu_user_id", "feishu_union_id"))
        for user in users
    ):
        warnings.append("empty_identity_fields_normalized")
    if source_version == 3:
        global_admins = {
            str(principal_id)
            for principal_id in config.get("global_admin_principal_ids", [])
            if isinstance(principal_id, str) and principal_id
        }
        memberships = [item for item in config.get("hotel_memberships", []) if isinstance(item, dict)]
        bindings = [item for item in config.get("group_chat_bindings", []) if isinstance(item, dict)]
        role_counts["admin"] = len(global_admins)
        for membership in memberships:
            role = membership.get("role")
            if role in role_counts and role != "admin":
                role_counts[role] += 1
        membership_count = len(memberships)
        hotel_count = len({str(item.get("hotel_id")) for item in memberships if item.get("hotel_id")})
        group_binding_count = len(bindings)
        display_names = [
            str(user.get("display_name") or user.get("name") or "").strip()
            for user in users
            if isinstance(user, dict)
        ]
        if any(not value for value in display_names):
            warnings.append("display_name_missing")
        duplicates = {value for value in display_names if value and display_names.count(value) > 1}
        if duplicates:
            warnings.append("display_name_duplicate")
    else:
        role_counts = {role: sum(1 for user in users if isinstance(user, dict) and user.get("role") == role) for role in ROLES if role != "guest"}
    if source_version == 3:
        migration_steps = [
            "Validate the private V3 role map before deployment.",
            "Keep canonical identities and tenant memberships unique.",
            "Do not downgrade a V3 role map to legacy formats.",
        ]
    else:
        migration_steps = [
            "Copy the private role map before editing it.",
            "Assign a unique principal_id to each canonical identity.",
            "Move users into global_admin_principal_ids or hotel_memberships.",
            "Move group chat entries to group_chat_bindings with an explicit hotel_id.",
            "Set direct_message_policy to role_mapped_users_only or disabled.",
            "Validate the copied V3 file before manually switching the server path.",
        ]
    return {
        "status": "invalid_config" if errors else "ok",
        "source_version": source_version,
        "target_version": 3,
        "migration_required": source_version != 3,
        "writes_performed": False,
        "user_count": len(users),
        "allowed_group_chat_count": len(groups),
        "legacy_direct_message_entry_count": len(direct_entries),
        "role_counts": role_counts,
        "membership_count": membership_count,
        "hotel_count": hotel_count,
        "group_binding_count": group_binding_count,
        "validation_errors": errors,
        "warnings": sorted(set(warnings)),
        "migration_steps": migration_steps,
    }


def permissions_for_role(role: str | None) -> list[str]:
    return sorted(PERMISSIONS_BY_ROLE.get(role or "guest", set()))


def _value_matches(user: dict[str, Any], keys: tuple[str, ...], value: str | None) -> bool:
    if not value:
        return False
    return any(str(user.get(key, "")) == value for key in keys if user.get(key))


def _role_match_from_feishu_user(config: dict[str, Any], user_id: str | None, open_id: str | None, union_id: str | None) -> dict[str, Any] | None:
    for user in config.get("users", []):
        if _value_matches(user, ("feishu_user_id", "user_id"), user_id):
            return {"role": user.get("role"), "matched_by": "user_id", "matched_role_name": user.get("name")}
        if _value_matches(user, ("feishu_open_id", "open_id"), open_id):
            return {"role": user.get("role"), "matched_by": "open_id", "matched_role_name": user.get("name")}
        if user_id and user_id.startswith("ou_") and _value_matches(user, ("feishu_open_id", "open_id"), user_id):
            return {
                "role": user.get("role"),
                "matched_by": "open_id_fallback_from_user_id",
                "matched_role_name": user.get("name"),
                "identity_warning": "Received an ou_ Open ID through --user-id. Prefer --open-id for Feishu open_id values.",
            }
        if _value_matches(user, ("feishu_union_id", "union_id"), union_id):
            return {"role": user.get("role"), "matched_by": "union_id", "matched_role_name": user.get("name")}
    return None


def _v3_principal_match(config: dict[str, Any], user_id: str | None, open_id: str | None, union_id: str | None) -> dict[str, Any] | None:
    for user in config.get("users", []):
        if not isinstance(user, dict):
            continue
        if _value_matches(user, ("feishu_user_id", "user_id"), user_id):
            return {"principal_id": user.get("principal_id"), "matched_by": "user_id", "matched_role_name": user.get("name")}
        if _value_matches(user, ("feishu_open_id", "open_id"), open_id):
            return {"principal_id": user.get("principal_id"), "matched_by": "open_id", "matched_role_name": user.get("name")}
        if _value_matches(user, ("feishu_union_id", "union_id"), union_id):
            return {"principal_id": user.get("principal_id"), "matched_by": "union_id", "matched_role_name": user.get("name")}
    return None


def _v3_memberships(config: dict[str, Any], principal_id: str) -> list[dict[str, Any]]:
    return [
        membership
        for membership in config.get("hotel_memberships", [])
        if isinstance(membership, dict) and membership.get("principal_id") == principal_id
    ]


def _v3_group_binding(config: dict[str, Any], chat_id: str) -> dict[str, Any] | None:
    normalized_chat_id = normalize_feishu_chat_id(chat_id)
    return next(
        (
            binding
            for binding in config.get("group_chat_bindings", [])
            if isinstance(binding, dict) and normalize_feishu_chat_id(binding.get("chat_id")) == normalized_chat_id
        ),
        None,
    )


def _resolve_v3_tenant(
    config: dict[str, Any],
    *,
    principal_id: str,
    chat_id: str,
    chat_type: str,
    requested_hotel_id: str | None,
) -> dict[str, Any]:
    global_admin = principal_id in set(config.get("global_admin_principal_ids") or [])
    memberships = _v3_memberships(config, principal_id)
    membership_by_hotel = {str(item.get("hotel_id")): item for item in memberships}
    authorized_hotel_ids = sorted(membership_by_hotel)
    if global_admin:
        authorized_hotel_ids = sorted(
            set(authorized_hotel_ids)
            | {
                str(binding.get("hotel_id"))
                for binding in config.get("group_chat_bindings", [])
                if isinstance(binding, dict) and binding.get("hotel_id")
            }
        )

    if chat_type == "group":
        binding = _v3_group_binding(config, chat_id)
        if not binding:
            return {"allowed": False, "reason": "chat_not_bound_to_hotel", "authorized_hotel_ids": authorized_hotel_ids}
        hotel_id = str(binding["hotel_id"])
        if requested_hotel_id and requested_hotel_id != hotel_id:
            return {"allowed": False, "reason": "tenant_scope_mismatch", "authorized_hotel_ids": authorized_hotel_ids}
        membership = membership_by_hotel.get(hotel_id)
        if not global_admin and not membership:
            return {"allowed": False, "reason": "user_not_hotel_member", "authorized_hotel_ids": authorized_hotel_ids}
        return {
            "allowed": True,
            "role": "admin" if global_admin else membership["role"],
            "resolved_hotel_id": hotel_id,
            "authorized_hotel_ids": authorized_hotel_ids,
            "tenant_status": "resolved",
        }

    if config.get("direct_message_policy") != "role_mapped_users_only":
        return {"allowed": False, "reason": "direct_message_policy_denied", "authorized_hotel_ids": authorized_hotel_ids}
    if not requested_hotel_id:
        return {
            "allowed": True,
            "role": "admin" if global_admin else (memberships[0]["role"] if len(memberships) == 1 else "guest"),
            "resolved_hotel_id": None,
            "authorized_hotel_ids": authorized_hotel_ids,
            "tenant_status": "tenant_selection_required",
        }
    membership = membership_by_hotel.get(requested_hotel_id)
    if not global_admin and not membership:
        return {"allowed": False, "reason": "tenant_scope_mismatch", "authorized_hotel_ids": authorized_hotel_ids}
    if global_admin and requested_hotel_id not in authorized_hotel_ids:
        return {"allowed": False, "reason": "unknown_tenant", "authorized_hotel_ids": authorized_hotel_ids}
    return {
        "allowed": True,
        "role": "admin" if global_admin else membership["role"],
        "resolved_hotel_id": requested_hotel_id,
        "authorized_hotel_ids": authorized_hotel_ids,
        "tenant_status": "resolved",
    }


def _resolved_chat_type(chat_id: str | None, chat_type: str | None) -> str:
    if chat_type in {"group", "p2p"}:
        return chat_type
    if str(chat_id or "").startswith("user:"):
        return "p2p"
    return "group"


def _chat_allowed(config: dict[str, Any], *, chat_id: str, chat_type: str) -> tuple[bool, str]:
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    if config.get("version") == 2:
        if chat_type == "p2p":
            return (
                config.get("direct_message_policy") == "role_mapped_users_only",
                "direct_message_policy_denied",
            )
        allowed_groups = set(config.get("allowed_group_chat_ids") or [])
        return chat_id in allowed_groups, "chat_not_allowed"

    allowed_chat_ids = set(config.get("allowed_chat_ids") or config.get("groupAllowFrom") or [])
    if not allowed_chat_ids:
        return True, "chat_allowed"
    return chat_id in allowed_chat_ids, "chat_not_allowed"


def build_auth_context(
    *,
    source: str = "manual_test",
    user_id: str | None = None,
    open_id: str | None = None,
    union_id: str | None = None,
    chat_id: str | None = None,
    chat_type: str | None = None,
    user_role: str | None = None,
    config_path: str | None = None,
    auth_db_path: str | None = None,
    requested_hotel_id: str | None = None,
) -> dict[str, Any]:
    source = source or "manual_test"
    raw_chat_id = chat_id
    chat_id_error_reason = None
    resolved_chat_type = _resolved_chat_type(raw_chat_id, chat_type)
    if source == "feishu":
        chat_resolution = resolve_feishu_business_chat_id(chat_id)
        chat_id = chat_resolution.get("chat_id")
        if chat_resolution.get("status") != "ok":
            chat_id_error_reason = chat_resolution.get("reason") or "missing_required_chat_id"
    reason = "authorized"
    auth_status = "authorized"
    matched_by = None
    matched_role_name = None
    identity_warning = None
    principal_id = None
    resolved_hotel_id = None
    authorized_hotel_ids: list[str] = []
    tenant_status = "not_configured"
    role_map_version = None

    v3_config = load_auth_config(config_path) if source == "feishu" else {}
    if (
        source == "feishu"
        and (user_id or open_id or union_id)
        and auth_db_path
    ):
        # A Feishu private conversation still has an ``oc_*`` conversation ID.
        # It is not a hotel group binding: p2p authorization must always resolve
        # the sender's active hotel membership from SQLite.
        if resolved_chat_type == "p2p":
            sqlite_context = _sqlite_dm_open_id_context(
                auth_db_path,
                user_id=user_id,
                open_id=open_id,
                union_id=union_id,
                requested_hotel_id=requested_hotel_id,
            )
        elif chat_id:
            sqlite_context = _sqlite_auth_context(
                auth_db_path,
                chat_id=chat_id,
                chat_type=resolved_chat_type,
                user_id=user_id,
                open_id=open_id,
                union_id=union_id,
            )
        else:
            sqlite_context = {"auth_status": "unavailable", "reason": "sqlite_active_auth_unavailable"}
        if sqlite_context.get("auth_status") != "unavailable":
            # SQLite Active Auth is the production authority. JSON is bootstrap-only.
            role = sqlite_context.get("user_role") or "guest"
            return {
                "source": source,
                "auth_status": sqlite_context["auth_status"],
                "reason": sqlite_context.get("reason") or "authorized",
                "user_role": role,
                "matched_by": "sqlite_identity",
                "matched_role_name": None,
                "identity_warning": None,
                "principal_id": sqlite_context.get("principal_id"),
                "role_map_version": 3,
                "auth_backend": "sqlite_active",
                "global_admin": bool(sqlite_context.get("global_admin")),
                "resolved_hotel_id": sqlite_context.get("resolved_hotel_id"),
                "authorized_hotel_ids": sqlite_context.get("authorized_hotel_ids") or [],
                "tenant_status": sqlite_context.get("tenant_status") or "unresolved",
                "feishu_user_id": user_id,
                "feishu_open_id": open_id,
                "feishu_union_id": union_id,
                "feishu_chat_id": chat_id,
                "chat_type": resolved_chat_type,
                "permissions": permissions_for_role(role),
            }
        if _config_version(v3_config) == 3 and auth_db_path:
            emergency_match = _v3_principal_match(v3_config, user_id, open_id, union_id)
            emergency_principal_id = (emergency_match or {}).get("principal_id")
            if emergency_principal_id in set(v3_config.get("global_admin_principal_ids") or []):
                tenant = _resolve_v3_tenant(
                    v3_config,
                    principal_id=str(emergency_principal_id),
                    chat_id=chat_id,
                    chat_type=resolved_chat_type,
                    requested_hotel_id=requested_hotel_id,
                )
                if tenant.get("allowed"):
                    return {
                        "source": source,
                        "auth_status": "authorized",
                        "reason": "sqlite_active_auth_unavailable",
                        "user_role": "admin",
                        "matched_by": "emergency_json_global_admin",
                        "matched_role_name": None,
                        "identity_warning": None,
                        "principal_id": emergency_principal_id,
                        "role_map_version": 3,
                        "auth_backend": "emergency_json_global_admin_readonly",
                        "global_admin": True,
                        "resolved_hotel_id": tenant.get("resolved_hotel_id"),
                        "authorized_hotel_ids": tenant.get("authorized_hotel_ids") or [],
                        "tenant_status": "emergency_readonly",
                        "feishu_user_id": user_id,
                        "feishu_open_id": open_id,
                        "feishu_union_id": union_id,
                        "feishu_chat_id": chat_id,
                        "chat_type": resolved_chat_type,
                        "permissions": ["runtime_status", "view_diagnosis", "view_hotel_controls"],
                    }
            return {
                "source": source,
                "auth_status": "unauthorized",
                "reason": "sqlite_active_auth_unavailable",
                "user_role": "guest",
                "matched_by": None,
                "matched_role_name": None,
                "identity_warning": None,
                "principal_id": None,
                "role_map_version": 3,
                "auth_backend": "sqlite_active_unavailable",
                "global_admin": False,
                "resolved_hotel_id": None,
                "authorized_hotel_ids": [],
                "tenant_status": "unavailable",
                "feishu_user_id": user_id,
                "feishu_open_id": open_id,
                "feishu_union_id": union_id,
                "feishu_chat_id": chat_id,
                "chat_type": resolved_chat_type,
                "permissions": [],
            }

    if source == "feishu":
        if not chat_id:
            role = "guest"
            auth_status = "invalid_context"
            reason = chat_id_error_reason or "missing_required_chat_id"
        elif not (user_id or open_id or union_id):
            role = "guest"
            auth_status = "invalid_context"
            reason = "missing_feishu_identity"
        else:
            config = load_auth_config(config_path)
            if config.get("load_error"):
                role = "guest"
                auth_status = "unauthorized"
                reason = config["load_error"]
            else:
                config_errors = validate_auth_config(config)
                if config_errors:
                    role = "guest"
                    auth_status = "invalid_config"
                    reason = config_errors[0]
                else:
                    role_map_version = _config_version(config)
                    if role_map_version == 3:
                        match = _v3_principal_match(config, user_id, open_id, union_id)
                        if not match:
                            role = "guest"
                            auth_status = "unauthorized"
                            reason = "user_not_in_role_map"
                        else:
                            principal_id = match.get("principal_id")
                            matched_by = match.get("matched_by")
                            matched_role_name = match.get("matched_role_name")
                            tenant = _resolve_v3_tenant(
                                config,
                                principal_id=str(principal_id),
                                chat_id=chat_id,
                                chat_type=resolved_chat_type,
                                requested_hotel_id=requested_hotel_id,
                            )
                            authorized_hotel_ids = list(tenant.get("authorized_hotel_ids") or [])
                            resolved_hotel_id = tenant.get("resolved_hotel_id")
                            tenant_status = tenant.get("tenant_status") or "unresolved"
                            if not tenant.get("allowed"):
                                role = "guest"
                                auth_status = "unauthorized"
                                reason = str(tenant.get("reason") or "tenant_scope_mismatch")
                            else:
                                role = str(tenant.get("role") or "guest")
                    else:
                        allowed, denied_reason = _chat_allowed(config, chat_id=chat_id, chat_type=resolved_chat_type)
                        if not allowed:
                            role = "guest"
                            auth_status = "unauthorized"
                            reason = denied_reason
                        else:
                            match = _role_match_from_feishu_user(config, user_id, open_id, union_id)
                            role = (match or {}).get("role") or "guest"
                            matched_by = (match or {}).get("matched_by")
                            matched_role_name = (match or {}).get("matched_role_name")
                            identity_warning = (match or {}).get("identity_warning")
                        if role == "guest" and auth_status == "authorized":
                            auth_status = "unauthorized"
                            reason = "user_not_in_role_map"
    else:
        if os.environ.get("HOTEL_OTA_REQUIRE_VERIFIED_ROLE") == "1":
            # 生产硬边界:非 feishu 源不得信任自报 --user-role,角色只能来自可信身份解析。
            role = "guest"
            auth_status = "unauthorized"
            reason = "verified_identity_required"
        else:
            role = user_role if user_role in ROLES else "operator"
            if role == "guest":
                auth_status = "unauthorized"
                reason = "guest_role"

    if role not in ROLES:
        role = "guest"
        auth_status = "unauthorized"
        reason = "invalid_role"

    return {
        "source": source,
        "auth_status": auth_status,
        "reason": reason,
        "user_role": role,
        "matched_by": matched_by,
        "matched_role_name": matched_role_name,
        "identity_warning": identity_warning,
        "principal_id": principal_id,
        "role_map_version": role_map_version,
        "auth_backend": "json_bootstrap" if source == "feishu" else "local_role",
        "global_admin": bool(
            source == "feishu"
            and role_map_version == 3
            and principal_id in set((load_auth_config(config_path).get("global_admin_principal_ids") or []))
        ),
        "resolved_hotel_id": resolved_hotel_id,
        "authorized_hotel_ids": authorized_hotel_ids,
        "tenant_status": tenant_status,
        "feishu_user_id": user_id,
        "feishu_open_id": open_id,
        "feishu_union_id": union_id,
        "feishu_chat_id": chat_id,
        "chat_type": _resolved_chat_type(chat_id, chat_type) if source == "feishu" and chat_id else None,
        "permissions": permissions_for_role(role),
    }


def tenant_scope_gate(auth_context: dict[str, Any], hotel_id: str | None) -> dict[str, Any]:
    """Require V3 Feishu requests to use the tenant resolved by trusted context."""
    if auth_context.get("role_map_version") != 3:
        return {"allowed": True, "reason": "legacy_role_map_compatibility"}
    if auth_context.get("auth_status") != "authorized":
        return {"allowed": False, "reason": auth_context.get("reason") or "unauthorized"}
    if auth_context.get("tenant_status") == "tenant_selection_required":
        return {"allowed": False, "reason": "tenant_selection_required"}
    resolved_hotel_id = auth_context.get("resolved_hotel_id")
    if not resolved_hotel_id or hotel_id != resolved_hotel_id:
        return {"allowed": False, "reason": "tenant_scope_mismatch"}
    return {"allowed": True, "reason": "allowed", "hotel_id": resolved_hotel_id}


def required_permission(action: str, *, dry_run: bool = False) -> str:
    if dry_run and action in WRITE_ACTIONS:
        return "create_dry_run"
    return ACTION_TO_PERMISSION.get(action, action)


def permission_gate(auth_context: dict[str, Any], action: str, *, dry_run: bool = False) -> dict[str, Any]:
    permission = required_permission(action, dry_run=dry_run)
    permissions = set(auth_context.get("permissions", []))
    authenticated = auth_context.get("auth_status") == "authorized"
    read_only_group_member = (
        auth_context.get("tenant_status") == "group_bound_read_only"
        and permission in GROUP_MEMBER_READ_PERMISSIONS
    )
    allowed = authenticated and (permission in permissions or read_only_group_member)
    return {
        "allowed": allowed,
        "required_permission": permission,
        "reason": "allowed_read_only" if read_only_group_member else ("allowed" if allowed else f"permission_denied:{permission}"),
        "auth_context": auth_context,
    }

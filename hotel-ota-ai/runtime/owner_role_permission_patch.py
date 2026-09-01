from __future__ import annotations

import uuid
from contextlib import closing
from typing import Any


_INSTALLED = False
VERSION = "owner-hotel-role-management.v3"


def _display_name(conn: Any, principal_id: str | None) -> str | None:
    if not principal_id:
        return None
    row = conn.execute(
        "SELECT display_name, alias, name_snapshot FROM auth_principals WHERE principal_id=? LIMIT 1",
        (principal_id,),
    ).fetchone()
    if not row:
        return None
    for key in ("display_name", "alias", "name_snapshot"):
        value = str(row[key] or "").strip()
        if value:
            return value
    return None


def _identity_facts(
    conn: Any,
    *,
    requester_principal_id: str | None,
    requester_role: str | None,
    target_principal_id: str | None,
    target_role: str | None,
    approver_principal_id: str | None = None,
    approver_role: str | None = None,
) -> dict[str, Any]:
    return {
        "identity_source": "sqlite_active_auth",
        "requester": {
            "display_name": _display_name(conn, requester_principal_id),
            "role": requester_role,
        },
        "target": {
            "display_name": _display_name(conn, target_principal_id),
            "role": target_role,
        },
        "approver": (
            {
                "display_name": _display_name(conn, approver_principal_id),
                "role": approver_role,
            }
            if approver_principal_id
            else None
        ),
    }


def _confirmation_policy(requester_role: str | None) -> str:
    return (
        "requester_admin_may_confirm"
        if requester_role == "admin"
        else "requester_owner_may_confirm"
    )


def _enrich_role_result(
    db_path: str,
    result: dict[str, Any],
    *,
    actor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_id = str(result.get("request_id") or "")
    if not request_id:
        return result

    from runtime.storage import connect, init_schema

    try:
        with closing(connect(db_path)) as conn:
            init_schema(conn)
            row = conn.execute(
                "SELECT * FROM role_change_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if not row:
                return result
            request = dict(row)
            membership = conn.execute(
                "SELECT role FROM hotel_memberships WHERE principal_id=? AND hotel_id=? AND status='active'",
                (request["target_principal_id"], request["hotel_id"]),
            ).fetchone()
            approver_principal_id = request.get("approver_principal_id")
            approver_role = request.get("approver_role")
            if result.get("status") == "confirmed" and actor:
                approver_principal_id = approver_principal_id or actor.get("principal_id")
                approver_role = approver_role or actor.get("role")
            facts = _identity_facts(
                conn,
                requester_principal_id=request.get("requester_principal_id"),
                requester_role=request.get("requester_role"),
                target_principal_id=request.get("target_principal_id"),
                target_role=str(membership["role"]) if membership else None,
                approver_principal_id=approver_principal_id,
                approver_role=approver_role,
            )
    except Exception:
        return result

    enriched = dict(result)
    enriched["role_change_identity"] = facts
    enriched["identity_source"] = "sqlite_active_auth"
    if request.get("requester_role") == "owner":
        enriched["self_confirmation_allowed"] = True
        enriched["confirmation_policy"] = "requester_owner_may_confirm"
    if result.get("status") == "confirmed":
        enriched["self_confirmed"] = bool(
            approver_principal_id
            and approver_principal_id == request.get("requester_principal_id")
        )
    return enriched


def _create_owner_direct_replacement(
    control_plane: Any,
    *,
    db_path: str,
    hotel_id: str,
    chat_id: str,
    requester: dict[str, Any],
    target_principal_id: str,
    requested_role: str,
    operation: str,
    now: str | None,
) -> dict[str, Any] | None:
    """Create the missing one-step transition from another owner to a lower hotel role."""
    requester_role = str(requester.get("role") or "")
    if (
        requester_role not in {"owner", "admin"}
        or operation != "grant"
        or requested_role not in {"operator", "frontdesk"}
        or str(requester.get("principal_id") or "") == target_principal_id
    ):
        return None

    from runtime.storage import connect, init_schema

    normalized_chat_id = control_plane.normalize_feishu_chat_id(chat_id) or ""
    timestamp = control_plane._timestamp(now)
    expires_at = (
        control_plane.datetime.fromisoformat(timestamp)
        + control_plane.timedelta(minutes=control_plane._chat_request_ttl_minutes())
    ).isoformat(timespec="seconds")

    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            binding = conn.execute(
                "SELECT hotel_id FROM group_chat_bindings WHERE chat_id=? AND status='active'",
                (normalized_chat_id,),
            ).fetchone()
            if not binding or str(binding["hotel_id"]) != hotel_id:
                return {"status": "blocked", "reason": "chat_not_bound_to_hotel"}
            target = conn.execute(
                "SELECT principal_id FROM auth_principals WHERE principal_id=?",
                (target_principal_id,),
            ).fetchone()
            if not target:
                return {"status": "blocked", "reason": "role_membership_target_not_found"}
            membership = conn.execute(
                "SELECT role FROM hotel_memberships WHERE principal_id=? AND hotel_id=? AND status='active'",
                (target_principal_id, hotel_id),
            ).fetchone()
            if not membership or str(membership["role"]) != "owner":
                return None

            request_id = f"ROLE-{uuid.uuid4().hex[:16].upper()}"
            payload_hash = control_plane._hash(
                control_plane._canonical_json(
                    {
                        "principal_id": target_principal_id,
                        "role": requested_role,
                        "operation": operation,
                    }
                )
            )
            conn.execute(
                """
                INSERT INTO role_change_requests
                  (request_id, hotel_id, target_principal_id, requested_role, operation,
                   payload_hash, expires_at, status, requester_principal_id, requester_role,
                   request_chat_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_confirmation', ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    hotel_id,
                    target_principal_id,
                    requested_role,
                    operation,
                    payload_hash,
                    expires_at,
                    requester.get("principal_id"),
                    requester_role,
                    control_plane._chat_hash(normalized_chat_id),
                    timestamp,
                    timestamp,
                ),
            )
            control_plane._append_audit_event(
                conn,
                hotel_id=hotel_id,
                request_id=request_id,
                actor=requester,
                action="role_change_requested",
                payload_hash=payload_hash,
                created_at=timestamp,
            )
            facts = _identity_facts(
                conn,
                requester_principal_id=requester.get("principal_id"),
                requester_role=requester_role,
                target_principal_id=target_principal_id,
                target_role="owner",
            )

    return {
        "status": "pending_confirmation",
        "request_id": request_id,
        "hotel_id": hotel_id,
        "requested_role": requested_role,
        "operation": operation,
        "previous_role": "owner",
        "direct_role_replacement": True,
        "confirmation_command": f"确认 {request_id}",
        "self_confirmation_allowed": True,
        "confirmation_policy": _confirmation_policy(requester_role),
        "role_change_identity": facts,
        "identity_source": "sqlite_active_auth",
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def _confirm_owner_direct_replacement(
    control_plane: Any,
    *,
    db_path: str,
    request_id: str,
    actor: dict[str, Any],
    chat_id: str,
    requested_role: str | None,
    now: str | None,
) -> dict[str, Any] | None:
    """Confirm owner/admin -> operator/frontdesk while keeping the normal tenant/auth guards."""
    from runtime.storage import connect, init_schema

    normalized_chat_id = control_plane.normalize_feishu_chat_id(chat_id) or ""
    timestamp = control_plane._timestamp(now)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            row = conn.execute(
                "SELECT * FROM role_change_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if not row:
                return None
            request = dict(row)
            membership = conn.execute(
                "SELECT role FROM hotel_memberships WHERE principal_id=? AND hotel_id=? AND status='active'",
                (request["target_principal_id"], request["hotel_id"]),
            ).fetchone()
            is_direct_replacement = (
                request.get("requester_role") in {"owner", "admin"}
                and request.get("operation") == "grant"
                and request.get("requested_role") in {"operator", "frontdesk"}
                and membership is not None
                and str(membership["role"]) == "owner"
            )
            if not is_direct_replacement:
                return None

            if request.get("request_chat_hash") != control_plane._chat_hash(normalized_chat_id):
                return {"status": "blocked", "reason": "role_request_chat_mismatch"}
            if control_plane._is_expired(request["expires_at"], timestamp):
                conn.execute(
                    "UPDATE role_change_requests SET status='expired', updated_at=? WHERE request_id=?",
                    (timestamp, request_id),
                )
                return {"status": "blocked", "reason": "role_request_expired"}
            if request["status"] not in {"pending_owner_approval", "pending_confirmation"}:
                return {"status": "blocked", "reason": "role_request_not_pending"}
            if requested_role is not None and requested_role != request["requested_role"]:
                return {"status": "blocked", "reason": "role_request_role_mismatch"}
            if not control_plane._actor_has_hotel_scope(actor, request["hotel_id"]):
                return {"status": "blocked", "reason": "tenant_scope_mismatch"}
            if str(actor.get("role") or "") != "owner" and not bool(actor.get("global_admin")):
                return {"status": "blocked", "reason": "role_request_requires_owner_confirmation"}
            if str(actor.get("principal_id") or "") == request["target_principal_id"]:
                return {"status": "blocked", "reason": "role_target_cannot_confirm_own_request"}

            conn.execute(
                """
                INSERT INTO hotel_memberships
                  (principal_id, hotel_id, role, status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)
                ON CONFLICT(principal_id, hotel_id)
                DO UPDATE SET role=excluded.role, status='active', updated_at=excluded.updated_at
                """,
                (
                    request["target_principal_id"],
                    request["hotel_id"],
                    request["requested_role"],
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute(
                "UPDATE auth_principals SET status='active', updated_at=? WHERE principal_id=?",
                (timestamp, request["target_principal_id"]),
            )
            conn.execute(
                """
                UPDATE role_change_requests
                SET status='confirmed', approver_principal_id=?, approver_role=?, approved_at=?, updated_at=?
                WHERE request_id=?
                """,
                (
                    actor.get("principal_id"),
                    actor.get("role"),
                    timestamp,
                    timestamp,
                    request_id,
                ),
            )
            control_plane._append_audit_event(
                conn,
                hotel_id=request["hotel_id"],
                request_id=request_id,
                actor=actor,
                action="role_request_confirmed",
                payload_hash=request["payload_hash"],
                created_at=timestamp,
            )
            facts = _identity_facts(
                conn,
                requester_principal_id=request.get("requester_principal_id"),
                requester_role=request.get("requester_role"),
                target_principal_id=request.get("target_principal_id"),
                target_role=request.get("requested_role"),
                approver_principal_id=actor.get("principal_id"),
                approver_role=actor.get("role"),
            )

    return {
        "status": "confirmed",
        "request_id": request_id,
        "hotel_id": request["hotel_id"],
        "role": request["requested_role"],
        "previous_role": "owner",
        "direct_role_replacement": True,
        "self_confirmation_allowed": True,
        "confirmation_policy": _confirmation_policy(request.get("requester_role")),
        "self_confirmed": bool(
            actor.get("principal_id")
            and actor.get("principal_id") == request.get("requester_principal_id")
        ),
        "role_change_identity": facts,
        "identity_source": "sqlite_active_auth",
        "auth_backend": "sqlite_active",
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def install() -> None:
    """Align owner/admin ROLE permission, state transitions, confirmation and identity facts."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.safety import auth
    from runtime import control_plane
    from runtime import feishu_command_router

    auth.PERMISSIONS_BY_ROLE.setdefault("owner", set()).add("manage_roles")
    auth.OWNER_ROLE_PERMISSION_CONTRACT_VERSION = VERSION

    original_create = control_plane.create_chat_role_change_request
    original_confirm = control_plane.confirm_chat_role_change_request

    if not getattr(original_create, "_OWNER_ROLE_MANAGEMENT_V2", False):
        def create_chat_role_change_request(
            db_path: str,
            *,
            hotel_id: str,
            chat_id: str,
            requester: dict[str, Any],
            target_principal_id: str,
            requested_role: str,
            operation: str,
            now: str | None = None,
        ) -> dict[str, Any]:
            result = original_create(
                db_path,
                hotel_id=hotel_id,
                chat_id=chat_id,
                requester=requester,
                target_principal_id=target_principal_id,
                requested_role=requested_role,
                operation=operation,
                now=now,
            )
            if result.get("reason") == "owner_cannot_modify_owner_or_admin_membership":
                replacement = _create_owner_direct_replacement(
                    control_plane,
                    db_path=db_path,
                    hotel_id=hotel_id,
                    chat_id=chat_id,
                    requester=requester,
                    target_principal_id=target_principal_id,
                    requested_role=requested_role,
                    operation=operation,
                    now=now,
                )
                if replacement is not None:
                    return replacement
            return _enrich_role_result(db_path, result, actor=requester)

        create_chat_role_change_request._OWNER_ROLE_MANAGEMENT_V2 = True  # type: ignore[attr-defined]
        control_plane.create_chat_role_change_request = create_chat_role_change_request

    if not getattr(original_confirm, "_OWNER_ROLE_MANAGEMENT_V2", False):
        def confirm_chat_role_change_request(
            db_path: str,
            *,
            request_id: str,
            actor: dict[str, Any],
            chat_id: str,
            requested_role: str | None = None,
            now: str | None = None,
        ) -> dict[str, Any]:
            direct = _confirm_owner_direct_replacement(
                control_plane,
                db_path=db_path,
                request_id=request_id,
                actor=actor,
                chat_id=chat_id,
                requested_role=requested_role,
                now=now,
            )
            if direct is not None:
                return direct
            result = original_confirm(
                db_path,
                request_id=request_id,
                actor=actor,
                chat_id=chat_id,
                requested_role=requested_role,
                now=now,
            )
            return _enrich_role_result(db_path, result, actor=actor)

        confirm_chat_role_change_request._OWNER_ROLE_MANAGEMENT_V2 = True  # type: ignore[attr-defined]
        control_plane.confirm_chat_role_change_request = confirm_chat_role_change_request

    # feishu_command_router imported these functions by value before this patch
    # installs, so rebind both aliases or production can keep calling the stale v1 functions.
    feishu_command_router.create_chat_role_change_request = control_plane.create_chat_role_change_request
    feishu_command_router.confirm_chat_role_change_request = control_plane.confirm_chat_role_change_request


__all__ = ["VERSION", "install"]

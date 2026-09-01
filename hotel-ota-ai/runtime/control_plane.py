from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Any

from runtime.storage import connect, init_schema
from runtime.safety.guards import price_guard
from runtime.safety.payload_hash import price_execution_payload, price_execution_payload_hash
from runtime.safety.auth import normalize_feishu_chat_id


PRICE_GUARD_KIND = "price_guard_policy"
ROLE_MEMBERSHIP_KIND = "role_membership_change"
CHAT_BINDING_KIND = "chat_binding"
CONFIGURATION_KINDS = {PRICE_GUARD_KIND, ROLE_MEMBERSHIP_KIND}
DEFAULT_PRICE_GUARD_POLICY = {
    "floor_price": None,
    "ceiling_price": None,
    "max_increase_pct": 0.12,
    "max_decrease_pct": 0.15,
    "min_increase_pct": 0.01,
    "min_decrease_pct": 0.01,
}
TENANT_MEMBER_ROLES = {"owner", "operator", "frontdesk"}


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _chat_hash(chat_id: str) -> str:
    normalized = normalize_feishu_chat_id(chat_id) or ""
    return _hash(f"feishu-chat:{normalized}")


def _timestamp(value: str | None) -> str:
    return value or datetime.now().isoformat(timespec="seconds")


def _is_expired(expires_at: str, now: str) -> bool:
    return datetime.fromisoformat(now) > datetime.fromisoformat(expires_at)


def _chat_request_ttl_minutes() -> int:
    try:
        return max(int(os.environ.get("HOTEL_OTA_CHAT_REQUEST_TTL_MINUTES", "15")), 1)
    except ValueError:
        return 15


def _actor_value(actor: dict[str, Any], key: str) -> str:
    return str(actor.get(key) or "")


def _owner_membership_change_allowed(actor: dict[str, Any], hotel_id: str, payload: dict[str, Any] | None) -> bool:
    """Permit only an Owner's ordinary-member change in that Owner's hotel."""
    payload = payload or {}
    return (
        _actor_value(actor, "role") == "owner"
        and hotel_id in set(actor.get("hotel_ids") or [])
        and payload.get("role") in TENANT_MEMBER_ROLES
        and bool(payload.get("principal_id"))
        and str(payload.get("principal_id")) != _actor_value(actor, "principal_id")
    )


def _actor_can_request(actor: dict[str, Any], request_kind: str, hotel_id: str, payload: dict[str, Any] | None = None) -> bool:
    role = _actor_value(actor, "role")
    if request_kind == ROLE_MEMBERSHIP_KIND:
        return (bool(actor.get("global_admin")) and role == "admin") or _owner_membership_change_allowed(actor, hotel_id, payload)
    return role in {"admin", "owner"} and (bool(actor.get("global_admin")) or hotel_id in set(actor.get("hotel_ids") or []))


def _actor_can_approve(actor: dict[str, Any], request_kind: str, hotel_id: str, payload: dict[str, Any] | None = None) -> bool:
    return _actor_can_request(actor, request_kind, hotel_id, payload)


def _actor_has_hotel_scope(actor: dict[str, Any], hotel_id: str) -> bool:
    return bool(actor.get("global_admin")) or hotel_id == _actor_value(actor, "resolved_hotel_id") or hotel_id in set(actor.get("hotel_ids") or [])


def _chat_requester_allowed(actor: dict[str, Any], hotel_id: str) -> bool:
    return _actor_value(actor, "role") in {"admin", "owner"} and _actor_has_hotel_scope(actor, hotel_id)


def _chat_confirmer_allowed(actor: dict[str, Any], request: dict[str, Any]) -> bool:
    if not _actor_has_hotel_scope(actor, request["hotel_id"]):
        return False
    actor_role = _actor_value(actor, "role")
    requester_is_operator = request["requester_role"] == "operator"
    if requester_is_operator:
        return bool(actor.get("global_admin")) or actor_role == "owner"
    return bool(actor.get("global_admin")) or (
        actor_role == "owner"
        and _actor_value(actor, "principal_id") == request["requester_principal_id"]
    )


def _chat_binding_actor_allowed(actor: dict[str, Any], hotel_id: str) -> bool:
    return bool(actor.get("global_admin")) or (
        _actor_value(actor, "role") == "owner" and hotel_id in set(actor.get("hotel_ids") or [])
    )


def _validate_request_payload(request_kind: str, payload: dict[str, Any]) -> None:
    if request_kind not in CONFIGURATION_KINDS:
        raise ValueError("unsupported_configuration_request_kind")
    if request_kind == PRICE_GUARD_KIND:
        required = {
            "room_type_id",
            "floor_price",
            "ceiling_price",
            "max_increase_pct",
            "max_decrease_pct",
            "min_increase_pct",
            "min_decrease_pct",
        }
        if any(payload.get(key) in (None, "") for key in required):
            raise ValueError("price_guard_payload_missing_required_fields")
        if float(payload["floor_price"]) > float(payload["ceiling_price"]):
            raise ValueError("price_guard_floor_exceeds_ceiling")
        for key in ("max_increase_pct", "max_decrease_pct", "min_increase_pct", "min_decrease_pct"):
            if not 0 <= float(payload[key]) <= 1:
                raise ValueError("price_guard_invalid_change_limit")
        if float(payload["min_increase_pct"]) > float(payload["max_increase_pct"]):
            raise ValueError("price_guard_increase_min_exceeds_max")
        if float(payload["min_decrease_pct"]) > float(payload["max_decrease_pct"]):
            raise ValueError("price_guard_decrease_min_exceeds_max")
    if request_kind == ROLE_MEMBERSHIP_KIND:
        if payload.get("operation") not in {"grant", "revoke"}:
            raise ValueError("role_membership_invalid_operation")
        if not payload.get("principal_id"):
            raise ValueError("role_membership_principal_required")
        if payload.get("role") not in TENANT_MEMBER_ROLES:
            raise ValueError("role_membership_invalid_role")


def _append_audit_event(
    conn: Any,
    *,
    hotel_id: str,
    request_id: str,
    actor: dict[str, Any],
    action: str,
    payload_hash: str,
    created_at: str,
) -> str:
    previous = conn.execute(
        "SELECT event_hash FROM configuration_audit_events WHERE hotel_id=? ORDER BY rowid DESC LIMIT 1",
        (hotel_id,),
    ).fetchone()
    previous_hash = previous["event_hash"] if previous else ""
    event_id = f"audit-{uuid.uuid4().hex}"
    event_hash = _hash(
        "|".join(
            [hotel_id, request_id, _actor_value(actor, "principal_id"), _actor_value(actor, "role"), action, payload_hash, previous_hash, created_at]
        )
    )
    conn.execute(
        """
        INSERT INTO configuration_audit_events
          (event_id, hotel_id, request_id, actor_principal_id, actor_role, action, payload_hash, previous_event_hash, event_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            hotel_id,
            request_id,
            _actor_value(actor, "principal_id"),
            _actor_value(actor, "role"),
            action,
            payload_hash,
            previous_hash or None,
            event_hash,
            created_at,
        ),
    )
    return event_hash


def create_configuration_request(
    db_path: str,
    *,
    request_kind: str,
    hotel_id: str,
    requester: dict[str, Any],
    payload: dict[str, Any],
    nonce: str,
    expires_at: str,
    role_map: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    _validate_request_payload(request_kind, payload)
    if request_kind == ROLE_MEMBERSHIP_KIND and _actor_value(requester, "role") == "owner":
        if not role_map:
            return {"status": "blocked", "reason": "role_membership_role_map_required"}
        principal_id = str(payload.get("principal_id") or "")
        known_principals = {
            str(item.get("principal_id") or "")
            for item in role_map.get("users") or []
            if isinstance(item, dict) and item.get("principal_id")
        }
        if principal_id not in known_principals:
            return {"status": "blocked", "reason": "role_membership_target_not_found"}
        owner_membership = any(
            isinstance(item, dict)
            and str(item.get("principal_id") or "") == _actor_value(requester, "principal_id")
            and str(item.get("hotel_id") or "") == hotel_id
            and item.get("role") == "owner"
            for item in role_map.get("hotel_memberships") or []
        )
        if not owner_membership:
            return {"status": "blocked", "reason": "owner_not_hotel_member"}
    if not hotel_id or not _actor_can_request(requester, request_kind, hotel_id, payload):
        return {"status": "blocked", "reason": "configuration_request_not_authorized"}
    if not _actor_value(requester, "principal_id") or not nonce:
        return {"status": "blocked", "reason": "configuration_request_identity_or_nonce_missing"}
    timestamp = _timestamp(now)
    if _is_expired(expires_at, timestamp):
        return {"status": "blocked", "reason": "card_nonce_expired"}
    request_id = f"cfg-{uuid.uuid4().hex}"
    payload_json = _canonical_json(payload)
    payload_hash = _hash(payload_json)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO config_change_requests
                  (request_id, request_kind, hotel_id, requester_principal_id, requester_role, payload_json, payload_hash, nonce_hash, expires_at, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    request_id,
                    request_kind,
                    hotel_id,
                    _actor_value(requester, "principal_id"),
                    _actor_value(requester, "role"),
                    payload_json,
                    payload_hash,
                    _hash(nonce),
                    expires_at,
                    timestamp,
                    timestamp,
                ),
            )
            _append_audit_event(
                conn,
                hotel_id=hotel_id,
                request_id=request_id,
                actor=requester,
                action="requested",
                payload_hash=payload_hash,
                created_at=timestamp,
            )
    return {
        "status": "pending",
        "request_id": request_id,
        "request_kind": request_kind,
        "hotel_id": hotel_id,
        "expires_at": expires_at,
        "payload_hash": payload_hash,
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def create_chat_configuration_request(
    db_path: str,
    *,
    request_kind: str,
    hotel_id: str,
    requester: dict[str, Any],
    chat_id: str,
    payload: dict[str, Any],
    expires_at: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Create a sealed chat request; it cannot apply configuration by itself."""
    _validate_request_payload(request_kind, payload)
    if not chat_id or not _actor_value(requester, "principal_id"):
        return {"status": "blocked", "reason": "configuration_request_identity_or_chat_missing"}
    if not _chat_requester_allowed(requester, hotel_id):
        return {"status": "blocked", "reason": "configuration_request_not_authorized"}
    timestamp = _timestamp(now)
    if _is_expired(expires_at, timestamp):
        return {"status": "blocked", "reason": "configuration_request_expired"}

    request_id = f"CFG-{uuid.uuid4().hex[:16].upper()}"
    payload_json = _canonical_json(payload)
    payload_hash = _hash(payload_json)
    status = "pending_owner_approval" if _actor_value(requester, "role") == "operator" else "pending_confirmation"
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO config_change_requests
                  (request_id, request_kind, hotel_id, requester_principal_id, requester_role, payload_json, payload_hash, nonce_hash, request_chat_hash, expires_at, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    request_kind,
                    hotel_id,
                    _actor_value(requester, "principal_id"),
                    _actor_value(requester, "role"),
                    payload_json,
                    payload_hash,
                    _hash(uuid.uuid4().hex),
                    _chat_hash(chat_id),
                    expires_at,
                    status,
                    timestamp,
                    timestamp,
                ),
            )
            _append_audit_event(
                conn,
                hotel_id=hotel_id,
                request_id=request_id,
                actor=requester,
                action="chat_request_created",
                payload_hash=payload_hash,
                created_at=timestamp,
            )
    return {
        "status": status,
        "request_id": request_id,
        "request_kind": request_kind,
        "hotel_id": hotel_id,
        "expires_at": expires_at,
        "confirmation_command": f"确认 {request_id}",
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def create_chat_binding_request(
    db_path: str,
    *,
    hotel_id: str,
    chat_id: str,
    chat_type: str,
    requester: dict[str, Any],
    operation: str = "bind",
    expires_at: str,
    now: str | None = None,
) -> dict[str, Any]:
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    """Create a sealed BIND request. It never changes chat binding by itself."""
    if operation not in {"bind", "unbind"}:
        return {"status": "blocked", "reason": "chat_binding_invalid_operation"}
    if not chat_id or not _actor_value(requester, "principal_id"):
        return {"status": "blocked", "reason": "chat_binding_identity_or_chat_missing"}
    if not _chat_binding_actor_allowed(requester, hotel_id):
        return {"status": "blocked", "reason": "chat_binding_request_not_authorized"}
    timestamp = _timestamp(now)
    if _is_expired(expires_at, timestamp):
        return {"status": "blocked", "reason": "chat_binding_request_expired"}
    request_id = f"BIND-{uuid.uuid4().hex[:16].upper()}"
    payload = {
        "operation": operation,
        "hotel_id": hotel_id,
        "chat_id_hash": _chat_hash(chat_id),
        "chat_type": chat_type or "unknown",
    }
    payload_hash = _hash(_canonical_json(payload))
    status = "pending_confirmation"
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO chat_binding_requests
                  (request_id, hotel_id, chat_id_hash, chat_type, operation, payload_hash, expires_at, status, requester_principal_id, requester_role, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    hotel_id,
                    _chat_hash(chat_id),
                    chat_type or "unknown",
                    operation,
                    payload_hash,
                    expires_at,
                    status,
                    _actor_value(requester, "principal_id"),
                    _actor_value(requester, "role"),
                    timestamp,
                    timestamp,
                ),
            )
            _append_audit_event(
                conn,
                hotel_id=hotel_id,
                request_id=request_id,
                actor=requester,
                action="chat_binding_request_created",
                payload_hash=payload_hash,
                created_at=timestamp,
            )
    return {
        "status": status,
        "request_id": request_id,
        "request_kind": CHAT_BINDING_KIND,
        "hotel_id": hotel_id,
        "chat_type": chat_type or "unknown",
        "operation": operation,
        "expires_at": expires_at,
        "confirmation_command": f"确认 {request_id}",
        "config_change_applied": False,
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def _chat_binding_request_row(conn: Any, request_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM chat_binding_requests WHERE request_id=?", (request_id,)).fetchone()
    return dict(row) if row else None


def confirm_chat_binding_request(
    db_path: str,
    *,
    request_id: str,
    actor: dict[str, Any],
    chat_id: str,
    chat_type: str,
    now: str | None = None,
) -> dict[str, Any]:
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    timestamp = _timestamp(now)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            request = _chat_binding_request_row(conn, request_id)
            if not request:
                return {"status": "not_found", "reason": "chat_binding_request_not_found"}
            if request["chat_id_hash"] != _chat_hash(chat_id):
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_binding_confirmation_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "chat_binding_request_chat_mismatch"}
            if _is_expired(request["expires_at"], timestamp):
                conn.execute("UPDATE chat_binding_requests SET status='expired', updated_at=? WHERE request_id=?", (timestamp, request_id))
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_binding_request_expired", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "chat_binding_request_expired"}
            if request["status"] != "pending_confirmation":
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_binding_confirmation_replayed", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "chat_binding_request_not_pending"}
            if not _chat_binding_actor_allowed(actor, request["hotel_id"]):
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_binding_confirmation_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "chat_binding_confirmation_not_authorized"}
            if request["operation"] == "bind":
                conn.execute(
                    """
                    INSERT INTO chat_bindings (chat_id, chat_type, hotel_id, status, source, created_at, updated_at)
                    VALUES (?, ?, ?, 'active', 'chat_confirmed', ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET chat_type=excluded.chat_type, hotel_id=excluded.hotel_id, status='active', source=excluded.source, updated_at=excluded.updated_at
                    """,
                    (chat_id, chat_type or request["chat_type"] or "unknown", request["hotel_id"], timestamp, timestamp),
                )
                if (chat_type or request["chat_type"]) == "group":
                    conn.execute(
                        "INSERT INTO group_chat_bindings (chat_id, hotel_id, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?) ON CONFLICT(chat_id) DO UPDATE SET hotel_id=excluded.hotel_id, status='active', updated_at=excluded.updated_at",
                        (chat_id, request["hotel_id"], timestamp, timestamp),
                    )
            else:
                conn.execute("UPDATE chat_bindings SET status='revoked', updated_at=? WHERE chat_id=?", (timestamp, chat_id))
                conn.execute("UPDATE group_chat_bindings SET status='revoked', updated_at=? WHERE chat_id=?", (timestamp, chat_id))
            conn.execute(
                "UPDATE chat_binding_requests SET status='confirmed', approver_principal_id=?, approver_role=?, updated_at=? WHERE request_id=?",
                (_actor_value(actor, "principal_id"), _actor_value(actor, "role"), timestamp, request_id),
            )
            _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_binding_request_confirmed", payload_hash=request["payload_hash"], created_at=timestamp)
    return {
        "status": "confirmed",
        "request_id": request_id,
        "hotel_id": request["hotel_id"],
        "chat_type": chat_type or request["chat_type"],
        "operation": request["operation"],
        "config_change_applied": True,
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def cancel_chat_binding_request(
    db_path: str,
    *,
    request_id: str,
    actor: dict[str, Any],
    chat_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    timestamp = _timestamp(now)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            request = _chat_binding_request_row(conn, request_id)
            if not request:
                return {"status": "not_found", "reason": "chat_binding_request_not_found"}
            if request["chat_id_hash"] != _chat_hash(chat_id):
                return {"status": "blocked", "reason": "chat_binding_request_chat_mismatch"}
            if request["status"] != "pending_confirmation":
                return {"status": "blocked", "reason": "chat_binding_request_not_pending"}
            if not _chat_binding_actor_allowed(actor, request["hotel_id"]):
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_binding_cancel_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "chat_binding_cancellation_not_authorized"}
            conn.execute("UPDATE chat_binding_requests SET status='cancelled', updated_at=? WHERE request_id=?", (timestamp, request_id))
            _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_binding_request_cancelled", payload_hash=request["payload_hash"], created_at=timestamp)
    return {"status": "cancelled", "request_id": request_id, "hotel_id": request["hotel_id"], "config_change_applied": False}


def create_role_membership_request_from_role_map(
    db_path: str,
    *,
    hotel_id: str,
    requester: dict[str, Any],
    role_map: dict[str, Any],
    payload: dict[str, Any],
    nonce: str,
    expires_at: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Create a queued V3 membership request after validating private role-map scope.

    The caller supplies already-loaded private configuration; this helper never reads or
    writes a filesystem path, which keeps Gateway incapable of changing `/etc` directly.
    """
    principal_id = str(payload.get("principal_id") or "")
    requester_id = _actor_value(requester, "principal_id")
    principals = {
        str(item.get("principal_id") or "")
        for item in role_map.get("users") or []
        if isinstance(item, dict) and item.get("principal_id")
    }
    if principal_id not in principals:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}
    if _actor_value(requester, "role") == "owner":
        if principal_id == requester_id:
            return {"status": "blocked", "reason": "owner_cannot_modify_self_membership"}
        if payload.get("role") not in TENANT_MEMBER_ROLES:
            return {"status": "blocked", "reason": "owner_cannot_manage_requested_role"}
        owner_membership = any(
            isinstance(item, dict)
            and str(item.get("principal_id") or "") == requester_id
            and str(item.get("hotel_id") or "") == hotel_id
            and item.get("role") == "owner"
            for item in role_map.get("hotel_memberships") or []
        )
        if not owner_membership:
            return {"status": "blocked", "reason": "owner_not_hotel_member"}
    sealed_payload = {
        **payload,
        "expected_config_hash": _hash(_canonical_json(role_map)),
    }
    return create_configuration_request(
        db_path,
        request_kind=ROLE_MEMBERSHIP_KIND,
        hotel_id=hotel_id,
        requester=requester,
        payload=sealed_payload,
        nonce=nonce,
        expires_at=expires_at,
        role_map=role_map,
        now=now,
    )


def _card_summary(request_kind: str, requester: dict[str, Any] | None = None, payload: dict[str, Any] | None = None, hotel_id: str = "") -> str:
    if request_kind == PRICE_GUARD_KIND:
        return "Price guard policy change awaiting a second in-scope approver."
    if requester and _owner_membership_change_allowed(requester, hotel_id, payload):
        return "Scoped hotel membership change awaiting Owner confirmation."
    return "Hotel membership change awaiting a second global administrator."


def create_configuration_card(
    db_path: str,
    *,
    request_kind: str,
    hotel_id: str,
    requester: dict[str, Any],
    payload: dict[str, Any],
    nonce: str,
    expires_at: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Create a sealed card contract; delivery/callback transport remains external."""
    request = create_configuration_request(
        db_path,
        request_kind=request_kind,
        hotel_id=hotel_id,
        requester=requester,
        payload=payload,
        nonce=nonce,
        expires_at=expires_at,
        now=now,
    )
    if request.get("status") != "pending":
        return request
    return {
        **request,
        "card": {
            "schema_version": "tenant_admin_card_v1",
            "action": "approve_configuration_request",
            "request_id": request["request_id"],
            "nonce": nonce,
            "payload_hash": request["payload_hash"],
            "expires_at": request["expires_at"],
            "summary": _card_summary(request_kind, requester, payload, hotel_id),
        },
    }


def _request_row(conn: Any, request_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM config_change_requests WHERE request_id=?", (request_id,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["payload"] = json.loads(result.pop("payload_json"))
    return result


def _apply_price_guard_policy(conn: Any, request: dict[str, Any], now: str) -> dict[str, Any]:
    payload = request["payload"]
    version_row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS version FROM price_guard_policies WHERE hotel_id=? AND room_type_id=?",
        (request["hotel_id"], payload["room_type_id"]),
    ).fetchone()
    version = int(version_row["version"]) + 1
    policy_id = f"pgp-{uuid.uuid4().hex}"
    conn.execute(
        """
        INSERT INTO price_guard_policies
          (policy_id, hotel_id, room_type_id, channel_source, ota_product_id, floor_price, ceiling_price, max_single_change_pct, max_increase_pct, max_decrease_pct, min_increase_pct, min_decrease_pct, effective_from, effective_to, version, status, source_request_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            policy_id,
            request["hotel_id"],
            payload["room_type_id"],
            payload.get("channel_source"),
            payload.get("ota_product_id"),
            float(payload["floor_price"]),
            float(payload["ceiling_price"]),
            max(float(payload["max_increase_pct"]), float(payload["max_decrease_pct"])),
            float(payload["max_increase_pct"]),
            float(payload["max_decrease_pct"]),
            float(payload["min_increase_pct"]),
            float(payload["min_decrease_pct"]),
            payload.get("effective_from") or now,
            payload.get("effective_to"),
            version,
            request["request_id"],
            now,
        ),
    )
    return {
        "policy_id": policy_id,
        "version": version,
        "max_increase_pct": float(payload["max_increase_pct"]),
        "max_decrease_pct": float(payload["max_decrease_pct"]),
        "min_increase_pct": float(payload["min_increase_pct"]),
        "min_decrease_pct": float(payload["min_decrease_pct"]),
    }


def _queue_role_map_apply(conn: Any, request: dict[str, Any], now: str) -> str:
    queue_id = f"role-apply-{uuid.uuid4().hex}"
    patch = {
        "operation": request["payload"]["operation"],
        "principal_id": request["payload"]["principal_id"],
        "hotel_id": request["hotel_id"],
        "role": request["payload"].get("role"),
    }
    conn.execute(
        """
        INSERT INTO role_map_apply_queue (queue_id, request_id, hotel_id, patch_json, expected_config_hash, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """,
        (queue_id, request["request_id"], request["hotel_id"], _canonical_json(patch), request["payload"].get("expected_config_hash"), now),
    )
    return queue_id


def _apply_hotel_role_membership(conn: Any, request: dict[str, Any], now: str) -> dict[str, Any]:
    payload = request["payload"]
    principal = conn.execute(
        "SELECT principal_id FROM auth_principals WHERE principal_id=?",
        (payload["principal_id"],),
    ).fetchone()
    if not principal:
        raise ValueError("role_membership_target_not_found")
    if payload["operation"] == "grant":
        conn.execute(
            """
            INSERT INTO hotel_memberships (principal_id, hotel_id, role, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            ON CONFLICT(principal_id, hotel_id) DO UPDATE SET role=excluded.role, status='active', updated_at=excluded.updated_at
            """,
            (payload["principal_id"], request["hotel_id"], payload["role"], now, now),
        )
    else:
        conn.execute(
            "UPDATE hotel_memberships SET status='revoked', updated_at=? WHERE principal_id=? AND hotel_id=?",
            (now, payload["principal_id"], request["hotel_id"]),
        )
    return {"principal_id": payload["principal_id"], "operation": payload["operation"], "role": payload["role"]}


def confirm_chat_configuration_request(
    db_path: str,
    *,
    request_id: str,
    actor: dict[str, Any],
    chat_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Apply a previously sealed request after a second authenticated chat command."""
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    timestamp = _timestamp(now)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            request = _request_row(conn, request_id)
            if not request:
                return {"status": "not_found", "reason": "configuration_request_not_found"}
            if request.get("request_chat_hash") != _chat_hash(chat_id):
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_confirmation_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "configuration_request_chat_mismatch"}
            if _is_expired(request["expires_at"], timestamp):
                conn.execute("UPDATE config_change_requests SET status='expired', updated_at=? WHERE request_id=?", (timestamp, request_id))
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_request_expired", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "configuration_request_expired"}
            if request["status"] not in {"pending_confirmation", "pending_owner_approval"}:
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_confirmation_replayed", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "configuration_request_not_pending"}
            if not _chat_confirmer_allowed(actor, request):
                reason = "operator_request_requires_owner_confirmation" if request["requester_role"] == "operator" and _actor_value(actor, "principal_id") == request["requester_principal_id"] else "configuration_confirmation_not_authorized"
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_confirmation_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": reason}

            conn.execute(
                "UPDATE config_change_requests SET status='confirmed', approver_principal_id=?, approver_role=?, updated_at=? WHERE request_id=?",
                (_actor_value(actor, "principal_id"), _actor_value(actor, "role"), timestamp, request_id),
            )
            if request["request_kind"] == PRICE_GUARD_KIND:
                details = {"policy": _apply_price_guard_policy(conn, request, timestamp)}
            else:
                details = {"membership": _apply_hotel_role_membership(conn, request, timestamp)}
            _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_request_confirmed", payload_hash=request["payload_hash"], created_at=timestamp)
    return {
        "status": "confirmed",
        "request_id": request_id,
        "hotel_id": request["hotel_id"],
        "formal_approval_created": False,
        "live_execution_count": 0,
        **details,
    }


def cancel_chat_configuration_request(
    db_path: str,
    *,
    request_id: str,
    actor: dict[str, Any],
    chat_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    timestamp = _timestamp(now)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            request = _request_row(conn, request_id)
            if not request:
                return {"status": "not_found", "reason": "configuration_request_not_found"}
            if request.get("request_chat_hash") != _chat_hash(chat_id):
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_cancel_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "configuration_request_chat_mismatch"}
            same_requester = _actor_value(actor, "principal_id") == request["requester_principal_id"]
            if request["status"] not in {"pending_confirmation", "pending_owner_approval"}:
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_cancel_replayed", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "configuration_request_not_pending"}
            if not same_requester and not _chat_confirmer_allowed(actor, request):
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_cancel_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "configuration_cancellation_not_authorized"}
            conn.execute("UPDATE config_change_requests SET status='cancelled', updated_at=? WHERE request_id=?", (timestamp, request_id))
            _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="chat_request_cancelled", payload_hash=request["payload_hash"], created_at=timestamp)
    return {"status": "cancelled", "request_id": request_id, "hotel_id": request["hotel_id"]}


def _candidate_principal_id(identity: dict[str, Any]) -> tuple[str, dict[str, str]]:
    values = {
        key: str(identity.get(key) or "").strip()
        for key in ("open_id", "user_id", "union_id")
        if str(identity.get(key) or "").strip()
    }
    if not values:
        raise ValueError("candidate_identity_missing")
    canonical = next(iter(values.values()))
    return f"feishu:{_hash(canonical)[:24]}", values


def create_chat_join_request(
    db_path: str,
    *,
    hotel_id: str | None,
    chat_id: str,
    identity: dict[str, Any],
    requested_role: str = "operator",
    now: str | None = None,
) -> dict[str, Any]:
    """Create a tenant-bound candidate membership request without changing JSON auth."""
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    if requested_role not in {"operator", "frontdesk"}:
        return {"status": "blocked", "reason": "role_membership_invalid_role"}
    timestamp = _timestamp(now)
    expires_at = (datetime.fromisoformat(timestamp) + timedelta(minutes=_chat_request_ttl_minutes())).isoformat(timespec="seconds")
    try:
        candidate_id, values = _candidate_principal_id(identity)
    except ValueError as exc:
        return {"status": "blocked", "reason": str(exc)}
    payload = {"principal_id": candidate_id, "role": requested_role, "operation": "grant"}
    payload_hash = _hash(_canonical_json(payload))
    request_id = f"ROLE-{uuid.uuid4().hex[:16].upper()}"
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            binding = conn.execute(
                "SELECT hotel_id FROM group_chat_bindings WHERE chat_id=? AND status='active'",
                (chat_id,),
            ).fetchone()
            if not binding or (hotel_id and str(binding["hotel_id"]) != hotel_id):
                return {"status": "blocked", "reason": "chat_not_bound_to_hotel"}
            resolved_hotel_id = str(binding["hotel_id"])
            existing = conn.execute(
                "SELECT principal_id FROM auth_principals WHERE open_id=? OR user_id=? OR union_id=? LIMIT 1",
                (values.get("open_id"), values.get("user_id"), values.get("union_id")),
            ).fetchone()
            principal_id = str(existing["principal_id"]) if existing else candidate_id
            if existing:
                membership = conn.execute(
                    "SELECT role, status FROM hotel_memberships WHERE principal_id=? AND hotel_id=? AND status='active'",
                    (principal_id, resolved_hotel_id),
                ).fetchone()
                if membership and str(membership["role"]) == requested_role:
                    return {
                        "status": "already_member",
                        "request_id": None,
                        "hotel_id": resolved_hotel_id,
                        "requested_role": requested_role,
                        "confirmation_command": None,
                        "formal_approval_created": False,
                        "live_execution_count": 0,
                    }
            if not existing:
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, user_id, union_id, is_global_admin, status, created_at, updated_at) VALUES (?, ?, ?, ?, 0, 'candidate', ?, ?)",
                    (principal_id, values.get("open_id"), values.get("user_id"), values.get("union_id"), timestamp, timestamp),
                )
            elif not conn.execute("SELECT 1 FROM auth_principals WHERE principal_id=? AND status='active'", (principal_id,)).fetchone():
                conn.execute("UPDATE auth_principals SET status='candidate', updated_at=? WHERE principal_id=?", (timestamp, principal_id))
            payload["principal_id"] = principal_id
            payload_hash = _hash(_canonical_json(payload))
            conn.execute(
                """
                INSERT INTO role_change_requests
                  (request_id, hotel_id, target_principal_id, requested_role, operation, payload_hash, expires_at, status, requester_principal_id, requester_role, request_chat_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'grant', ?, ?, 'pending_owner_approval', ?, 'candidate', ?, ?, ?)
                """,
                (request_id, resolved_hotel_id, principal_id, requested_role, payload_hash, expires_at, principal_id, _chat_hash(chat_id), timestamp, timestamp),
            )
            _append_audit_event(
                conn,
                hotel_id=resolved_hotel_id,
                request_id=request_id,
                actor={"principal_id": principal_id, "role": "candidate"},
                action="role_join_requested",
                payload_hash=payload_hash,
                created_at=timestamp,
            )
    return {
        "status": "pending_owner_approval",
        "request_id": request_id,
        "target_principal_hash": _hash(principal_id)[:16],
        "hotel_id": resolved_hotel_id,
        "requested_role": requested_role,
        "confirmation_command": f"确认 {request_id}",
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


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
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    requester_role = _actor_value(requester, "role")
    if requested_role not in TENANT_MEMBER_ROLES or operation not in {"grant", "revoke"}:
        return {"status": "blocked", "reason": "role_membership_invalid_request"}
    if not _chat_requester_allowed(requester, hotel_id):
        return {"status": "blocked", "reason": "role_membership_request_not_authorized"}
    requester_id = _actor_value(requester, "principal_id")
    if requester_role == "owner" and requester_id == target_principal_id:
        return {"status": "blocked", "reason": "owner_cannot_modify_self_membership"}
    timestamp = _timestamp(now)
    expires_at = (datetime.fromisoformat(timestamp) + timedelta(minutes=_chat_request_ttl_minutes())).isoformat(timespec="seconds")
    payload_hash = _hash(_canonical_json({"principal_id": target_principal_id, "role": requested_role, "operation": operation}))
    request_id = f"ROLE-{uuid.uuid4().hex[:16].upper()}"
    status = "pending_confirmation"
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            binding = conn.execute("SELECT hotel_id FROM group_chat_bindings WHERE chat_id=? AND status='active'", (chat_id,)).fetchone()
            if not binding or str(binding["hotel_id"]) != hotel_id:
                return {"status": "blocked", "reason": "chat_not_bound_to_hotel"}
            target = conn.execute("SELECT principal_id FROM auth_principals WHERE principal_id=?", (target_principal_id,)).fetchone()
            if not target:
                return {"status": "blocked", "reason": "role_membership_target_not_found"}
            target_membership = conn.execute(
                "SELECT role, status FROM hotel_memberships WHERE principal_id=? AND hotel_id=? AND status='active'",
                (target_principal_id, hotel_id),
            ).fetchone()
            if target_membership:
                target_role = str(target_membership["role"])
                if operation == "grant" and target_role == requested_role:
                    return {
                        "status": "already_member",
                        "request_id": None,
                        "hotel_id": hotel_id,
                        "requested_role": requested_role,
                        "operation": operation,
                        "confirmation_command": None,
                        "formal_approval_created": False,
                        "live_execution_count": 0,
                    }
                if target_role == "admin":
                    return {"status": "blocked", "reason": "owner_cannot_modify_admin_membership"}
                if target_role == "owner" and operation != "revoke":
                    return {"status": "blocked", "reason": "owner_cannot_modify_owner_or_admin_membership"}
            conn.execute(
                "INSERT INTO role_change_requests (request_id, hotel_id, target_principal_id, requested_role, operation, payload_hash, expires_at, status, requester_principal_id, requester_role, request_chat_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (request_id, hotel_id, target_principal_id, requested_role, operation, payload_hash, expires_at, status, requester_id, requester_role, _chat_hash(chat_id), timestamp, timestamp),
            )
            _append_audit_event(conn, hotel_id=hotel_id, request_id=request_id, actor=requester, action="role_change_requested", payload_hash=payload_hash, created_at=timestamp)
    return {
        "status": status,
        "request_id": request_id,
        "hotel_id": hotel_id,
        "requested_role": requested_role,
        "operation": operation,
        "confirmation_command": f"确认 {request_id}",
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def confirm_chat_role_change_request(
    db_path: str,
    *,
    request_id: str,
    actor: dict[str, Any],
    chat_id: str,
    requested_role: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Confirm one sealed ROLE request using a tenant-scoped authenticated actor."""
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    timestamp = _timestamp(now)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            row = conn.execute("SELECT * FROM role_change_requests WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                return {"status": "not_found", "reason": "role_request_not_found"}
            request = dict(row)
            if request.get("request_chat_hash") != _chat_hash(chat_id):
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_confirmation_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "role_request_chat_mismatch"}
            if _is_expired(request["expires_at"], timestamp):
                conn.execute("UPDATE role_change_requests SET status='expired', updated_at=? WHERE request_id=?", (timestamp, request_id))
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_request_expired", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "role_request_expired"}
            if request["status"] not in {"pending_owner_approval", "pending_confirmation"}:
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_confirmation_replayed", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "role_request_not_pending"}
            if requested_role is not None and requested_role != request["requested_role"]:
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_confirmation_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "role_request_role_mismatch"}
            if not _actor_has_hotel_scope(actor, request["hotel_id"]):
                return {"status": "blocked", "reason": "tenant_scope_mismatch"}
            actor_is_owner_or_admin = _actor_value(actor, "role") == "owner" or bool(actor.get("global_admin"))
            if not actor_is_owner_or_admin:
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_confirmation_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "role_request_requires_owner_confirmation"}
            if _actor_value(actor, "principal_id") == request.get("requester_principal_id"):
                if request.get("requester_role") == "operator":
                    return {"status": "blocked", "reason": "role_request_requires_owner_confirmation"}
            if _actor_value(actor, "principal_id") == request["target_principal_id"]:
                return {"status": "blocked", "reason": "role_target_cannot_confirm_own_request"}
            if request["requested_role"] not in TENANT_MEMBER_ROLES:
                return {"status": "blocked", "reason": "role_membership_invalid_role"}
            target_membership = conn.execute(
                "SELECT role, status FROM hotel_memberships WHERE principal_id=? AND hotel_id=? AND status='active'",
                (request["target_principal_id"], request["hotel_id"]),
            ).fetchone()
            if target_membership:
                target_role = str(target_membership["role"])
                same_role_grant = request["operation"] == "grant" and target_role == request["requested_role"]
                if not same_role_grant:
                    if target_role == "admin":
                        _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_confirmation_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                        return {"status": "blocked", "reason": "owner_cannot_modify_admin_membership"}
                    if target_role == "owner" and request["operation"] != "revoke":
                        _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_confirmation_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                        return {"status": "blocked", "reason": "owner_cannot_modify_owner_or_admin_membership"}
            if request["operation"] == "grant":
                conn.execute(
                    "INSERT INTO hotel_memberships (principal_id, hotel_id, role, status, created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?) ON CONFLICT(principal_id, hotel_id) DO UPDATE SET role=excluded.role, status='active', updated_at=excluded.updated_at",
                    (request["target_principal_id"], request["hotel_id"], request["requested_role"], timestamp, timestamp),
                )
                conn.execute("UPDATE auth_principals SET status='active', updated_at=? WHERE principal_id=?", (timestamp, request["target_principal_id"]))
            else:
                conn.execute(
                    "UPDATE hotel_memberships SET status='revoked', updated_at=? WHERE principal_id=? AND hotel_id=?",
                    (timestamp, request["target_principal_id"], request["hotel_id"]),
                )
            conn.execute(
                "UPDATE role_change_requests SET status='confirmed', approver_principal_id=?, approver_role=?, approved_at=?, updated_at=? WHERE request_id=?",
                (_actor_value(actor, "principal_id"), _actor_value(actor, "role"), timestamp, timestamp, request_id),
            )
            _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_request_confirmed", payload_hash=request["payload_hash"], created_at=timestamp)
    return {"status": "confirmed", "request_id": request_id, "hotel_id": request["hotel_id"], "role": request["requested_role"], "auth_backend": "sqlite_active", "formal_approval_created": False, "live_execution_count": 0}


def cancel_chat_role_change_request(
    db_path: str,
    *,
    request_id: str,
    actor: dict[str, Any],
    chat_id: str,
    now: str | None = None,
) -> dict[str, Any]:
    chat_id = normalize_feishu_chat_id(chat_id) or ""
    timestamp = _timestamp(now)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            row = conn.execute("SELECT * FROM role_change_requests WHERE request_id=?", (request_id,)).fetchone()
            if not row:
                return {"status": "not_found", "reason": "role_request_not_found"}
            request = dict(row)
            if request.get("request_chat_hash") != _chat_hash(chat_id):
                return {"status": "blocked", "reason": "role_request_chat_mismatch"}
            if request["status"] != "pending_owner_approval" and request["status"] != "pending_confirmation":
                return {"status": "blocked", "reason": "role_request_not_pending"}
            requester = _actor_value(actor, "principal_id") == request.get("requester_principal_id")
            approver = _actor_has_hotel_scope(actor, request["hotel_id"]) and (_actor_value(actor, "role") == "owner" or bool(actor.get("global_admin")))
            if not requester and not approver:
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_cancel_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "role_cancellation_not_authorized"}
            conn.execute("UPDATE role_change_requests SET status='cancelled', updated_at=? WHERE request_id=?", (timestamp, request_id))
            _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=actor, action="role_request_cancelled", payload_hash=request["payload_hash"], created_at=timestamp)
    return {"status": "cancelled", "request_id": request_id, "hotel_id": request["hotel_id"]}


def approve_configuration_request(
    db_path: str,
    *,
    request_id: str,
    nonce: str,
    approver: dict[str, Any],
    callback_payload_hash: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(now)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            request = _request_row(conn, request_id)
            if not request:
                return {"status": "not_found", "reason": "configuration_request_not_found"}
            if _is_expired(request["expires_at"], timestamp):
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=approver, action="nonce_expired", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "card_nonce_expired"}
            if request["status"] != "pending":
                return {"status": "blocked", "reason": "configuration_request_not_pending"}
            if callback_payload_hash is not None and callback_payload_hash != request["payload_hash"]:
                _append_audit_event(
                    conn,
                    hotel_id=request["hotel_id"],
                    request_id=request_id,
                    actor=approver,
                    action="payload_hash_rejected",
                    payload_hash=request["payload_hash"],
                    created_at=timestamp,
                )
                return {"status": "blocked", "reason": "card_payload_hash_mismatch"}
            if _hash(nonce) != request["nonce_hash"]:
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=approver, action="nonce_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "card_nonce_invalid"}
            same_principal = _actor_value(approver, "principal_id") == request["requester_principal_id"]
            owner_self_confirmation = (
                same_principal
                and request["request_kind"] == ROLE_MEMBERSHIP_KIND
                and _owner_membership_change_allowed(approver, request["hotel_id"], request["payload"])
            )
            if same_principal and not owner_self_confirmation:
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=approver, action="self_approval_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "self_approval_not_allowed"}
            if not _actor_can_approve(approver, request["request_kind"], request["hotel_id"], request["payload"]):
                _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=approver, action="approval_rejected", payload_hash=request["payload_hash"], created_at=timestamp)
                return {"status": "blocked", "reason": "configuration_approval_not_authorized"}

            conn.execute(
                """
                UPDATE config_change_requests
                SET status='approved', approver_principal_id=?, approver_role=?, updated_at=?
                WHERE request_id=? AND status='pending'
                """,
                (_actor_value(approver, "principal_id"), _actor_value(approver, "role"), timestamp, request_id),
            )
            details: dict[str, Any] = {}
            if request["request_kind"] == PRICE_GUARD_KIND:
                details["policy"] = _apply_price_guard_policy(conn, request, timestamp)
            else:
                details["apply_queue_id"] = _queue_role_map_apply(conn, request, timestamp)
            _append_audit_event(conn, hotel_id=request["hotel_id"], request_id=request_id, actor=approver, action="approved", payload_hash=request["payload_hash"], created_at=timestamp)
    return {
        "status": "approved",
        "request_id": request_id,
        "hotel_id": request["hotel_id"],
        "formal_approval_created": False,
        "live_execution_count": 0,
        **details,
    }


def approve_configuration_card_callback(
    db_path: str,
    *,
    callback: dict[str, Any],
    approver: dict[str, Any],
    now: str | None = None,
) -> dict[str, Any]:
    """Validate a platform-neutral card action before approving its stored request."""
    required = {"schema_version", "action", "request_id", "nonce", "payload_hash", "expires_at", "summary"}
    if not isinstance(callback, dict) or not required.issubset(callback):
        return {"status": "blocked", "reason": "card_callback_invalid"}
    if callback.get("schema_version") != "tenant_admin_card_v1" or callback.get("action") != "approve_configuration_request":
        return {"status": "blocked", "reason": "card_callback_action_not_allowed"}
    return approve_configuration_request(
        db_path,
        request_id=str(callback["request_id"]),
        nonce=str(callback["nonce"]),
        callback_payload_hash=str(callback["payload_hash"]),
        approver=approver,
        now=now,
    )


def active_price_guard_policy(
    db_path: str,
    hotel_id: str,
    room_type_id: str,
    at_time: str,
    *,
    channel_source: str | None = None,
    ota_product_id: str | None = None,
) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        init_schema(conn)
        channel = (channel_source or "").strip().lower()
        product = (ota_product_id or "").strip()
        row = conn.execute(
            """
            SELECT * FROM price_guard_policies
            WHERE hotel_id=? AND room_type_id=? AND status='active'
              AND effective_from<=? AND (effective_to IS NULL OR effective_to>?)
              AND (channel_source IS NULL OR channel_source='' OR lower(channel_source)=? OR channel_source='all')
              AND (ota_product_id IS NULL OR ota_product_id='' OR ota_product_id=?)
            ORDER BY
              CASE
                WHEN ota_product_id=? AND ota_product_id!='' THEN 0
                WHEN lower(channel_source)=? AND channel_source!='' THEN 1
                ELSE 2
              END,
              version DESC
            LIMIT 1
            """,
            (hotel_id, room_type_id, at_time, at_time, channel, product, product, channel),
        ).fetchone()
    if not row:
        return None
    policy = dict(row)
    stored_directional = all(
        policy.get(key) is not None
        for key in ("max_increase_pct", "max_decrease_pct", "min_increase_pct", "min_decrease_pct")
    )
    legacy_limit = float(policy.get("max_single_change_pct") or 0.0)
    policy["max_increase_pct"] = float(policy.get("max_increase_pct") if policy.get("max_increase_pct") is not None else legacy_limit)
    policy["max_decrease_pct"] = float(policy.get("max_decrease_pct") if policy.get("max_decrease_pct") is not None else legacy_limit)
    policy["min_increase_pct"] = float(policy.get("min_increase_pct") if policy.get("min_increase_pct") is not None else 0.0)
    policy["min_decrease_pct"] = float(policy.get("min_decrease_pct") if policy.get("min_decrease_pct") is not None else 0.0)
    policy["policy_schema"] = "directional_v2" if stored_directional else "legacy_single_cap"
    return policy


def resolve_price_guard_policy(
    db_path: str,
    *,
    hotel_id: str,
    room_type_id: str,
    at_time: str,
    channel_source: str | None = None,
    ota_product_id: str | None = None,
) -> dict[str, Any]:
    """Return the only policy representation consumers may use.

    An active, versioned SQLite policy is authoritative. The fallback is deliberately
    incomplete for execution because it has no room-type floor or ceiling; it is only
    suitable for preview calculations and must remain visibly labeled.
    """
    try:
        active = active_price_guard_policy(
            db_path,
            hotel_id,
            room_type_id,
            at_time,
            channel_source=channel_source,
            ota_product_id=ota_product_id,
        )
        resolver_error = None
    except Exception as exc:
        active = None
        resolver_error = f"price_guard_policy_unavailable:{exc.__class__.__name__}"
    if active:
        return {
            **active,
            "source": "active_price_guard_policy",
            "policy_state": active["policy_schema"],
        }
    return {
        **DEFAULT_PRICE_GUARD_POLICY,
        "policy_id": None,
        "hotel_id": hotel_id,
        "room_type_id": room_type_id,
        "version": None,
        "policy_schema": "default_policy",
        "policy_state": "default_policy",
        "source": "default_policy",
        "execution_allowed": False,
        "resolver_error": resolver_error,
    }


def list_role_map_apply_queue(db_path: str) -> list[dict[str, Any]]:
    with closing(connect(db_path)) as conn:
        init_schema(conn)
        rows = conn.execute(
            "SELECT queue_id, request_id, hotel_id, status, created_at, applied_at FROM role_map_apply_queue ORDER BY created_at, queue_id"
        ).fetchall()
    return [dict(row) for row in rows]


def build_tenant_management_read_model(
    db_path: str,
    *,
    hotel_id: str,
    role_map: dict[str, Any] | None = None,
    chat_id: str | None = None,
    at_time: str | None = None,
) -> dict[str, Any]:
    """Return a tenant-scoped, identifier-free control-plane summary for Feishu."""
    member_counts = {role: 0 for role in ("owner", "operator", "frontdesk")}
    role_scope = "hotel_summary"

    with closing(connect(db_path)) as conn:
        init_schema(conn)
        member_rows = conn.execute(
            """
            SELECT role, COUNT(*) AS count
            FROM hotel_memberships
            WHERE hotel_id=? AND status='active'
            GROUP BY role
            """,
            (hotel_id,),
        ).fetchall()
        for row in member_rows:
            role = str(row["role"])
            if role in member_counts:
                member_counts[role] = int(row["count"])
        request_rows = conn.execute(
            """
            SELECT request_kind, status, COUNT(*) AS count
            FROM config_change_requests
            WHERE hotel_id=?
            GROUP BY request_kind, status
            """,
            (hotel_id,),
        ).fetchall()
        policy_rows = conn.execute(
            """
            SELECT room_type_id, version, max_increase_pct, max_decrease_pct, min_increase_pct, min_decrease_pct
            FROM price_guard_policies
            WHERE hotel_id=? AND status='active'
            ORDER BY room_type_id, version DESC
            """,
            (hotel_id,),
        ).fetchall()
        audit_count = int(
            conn.execute("SELECT COUNT(*) AS count FROM configuration_audit_events WHERE hotel_id=?", (hotel_id,)).fetchone()["count"]
        )

    pending_by_kind: dict[str, int] = {}
    request_count = 0
    for row in request_rows:
        item = dict(row)
        request_count += int(item["count"])
        if item["status"] == "pending":
            pending_by_kind[str(item["request_kind"])] = int(item["count"])

    resolver_time = at_time or datetime.now().isoformat(timespec="seconds")
    guards: list[dict[str, Any]] = []
    seen_room_types: set[str] = set()
    for row in policy_rows:
        item = dict(row)
        room_type_id = str(item["room_type_id"])
        if room_type_id in seen_room_types:
            continue
        seen_room_types.add(room_type_id)
        resolved = resolve_price_guard_policy(
            db_path,
            hotel_id=hotel_id,
            room_type_id=room_type_id,
            at_time=resolver_time,
        )
        guards.append(
            {
                key: resolved.get(key)
                for key in (
                    "source",
                    "policy_id",
                    "room_type_id",
                    "version",
                    "policy_state",
                    "floor_price",
                    "ceiling_price",
                    "max_increase_pct",
                    "max_decrease_pct",
                    "min_increase_pct",
                    "min_decrease_pct",
                    "effective_from",
                    "effective_to",
                    "execution_allowed",
                    "resolver_error",
                )
            }
        )
    if not guards:
        resolved = resolve_price_guard_policy(
            db_path,
            hotel_id=hotel_id,
            room_type_id="*",
            at_time=resolver_time,
        )
        guards.append(
            {
                key: resolved.get(key)
                for key in (
                    "source",
                    "policy_id",
                    "room_type_id",
                    "version",
                    "policy_state",
                    "floor_price",
                    "ceiling_price",
                    "max_increase_pct",
                    "max_decrease_pct",
                    "min_increase_pct",
                    "min_decrease_pct",
                    "effective_from",
                    "effective_to",
                    "execution_allowed",
                    "resolver_error",
                )
            }
        )

    return {
        "status": "ok",
        "hotel_id": hotel_id,
        "role_scope": role_scope,
        "member_role_counts": member_counts,
        "active_price_guard_count": len(seen_room_types),
        "price_guard_statuses": guards,
        "pending_configuration_requests": pending_by_kind,
        "configuration_request_count": request_count,
        "audit_event_count": audit_count,
        "audit_chain_valid": verify_audit_chain(db_path, hotel_id)["valid"],
        "configuration_mutation_allowed": False,
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def create_formal_price_approval(
    db_path: str,
    *,
    hotel_id: str,
    room_type_id: str,
    old_price: float | None,
    proposed_price: float,
    business_payload: dict[str, Any],
    requester: dict[str, Any],
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(now)
    if not _actor_can_request(requester, PRICE_GUARD_KIND, hotel_id):
        return {"status": "blocked", "reason": "formal_price_approval_not_authorized"}
    if business_payload.get("freshness_status") != "fresh" or business_payload.get("business_status") != "current":
        return {"status": "blocked", "reason": "formal_price_approval_requires_fresh_current_data"}
    if business_payload.get("data_source_type") in {"demo_data", "sample_data", "synthetic_today_demo", "manual_chat"}:
        return {"status": "blocked", "reason": "formal_price_approval_requires_authoritative_data"}
    begin_date = str(business_payload.get("begin_date") or "").strip()
    end_date = str(business_payload.get("end_date") or "").strip()
    if not begin_date or not end_date:
        return {"status": "blocked", "reason": "formal_price_approval_effective_date_required"}
    try:
        if date.fromisoformat(begin_date) > date.fromisoformat(end_date):
            return {"status": "blocked", "reason": "formal_price_approval_effective_date_range_invalid"}
    except ValueError:
        return {"status": "blocked", "reason": "formal_price_approval_effective_date_invalid"}
    channel_source = business_payload.get("channel_source") or business_payload.get("channel")
    ota_product_id = business_payload.get("ota_product_id")
    policy = resolve_price_guard_policy(
        db_path,
        hotel_id=hotel_id,
        room_type_id=room_type_id,
        at_time=timestamp,
        channel_source=channel_source,
        ota_product_id=ota_product_id,
    )
    policy_version = int(policy["version"]) if policy.get("version") is not None else None
    guard = price_guard(
        old_price=old_price,
        new_price=float(proposed_price),
        floor_price=None,
        ceiling_price=None,
        max_increase_pct=float(policy["max_increase_pct"]),
        max_decrease_pct=float(policy["max_decrease_pct"]),
        min_increase_pct=float(policy["min_increase_pct"]),
        min_decrease_pct=float(policy["min_decrease_pct"]),
        require_old_price=True,
    )
    if not guard["passed"]:
        return {"status": "blocked", "reason": "formal_price_approval_guard_failed", "guard": guard}
    execution = price_execution_payload(
        hotel_id=hotel_id,
        room_type_id=room_type_id,
        channel=channel_source or "ota",
        ota_product_id=ota_product_id,
        normal_price=float(proposed_price),
        old_price=float(old_price) if old_price is not None else None,
        price_guard_policy_id=policy["policy_id"],
        begin_date=begin_date,
        end_date=end_date,
        floor_price=None,
        ceiling_price=None,
        max_increase_pct=float(policy["max_increase_pct"]),
        max_decrease_pct=float(policy["max_decrease_pct"]),
        min_increase_pct=float(policy["min_increase_pct"]),
        min_decrease_pct=float(policy["min_decrease_pct"]),
        freshness_status=business_payload["freshness_status"],
        guard_version=policy_version,
    )
    execution_payload_hash = price_execution_payload_hash(execution)
    approval_id = f"appr-{uuid.uuid4().hex}"
    payload = {
        **business_payload,
        **execution,
        "old_price": float(old_price) if old_price is not None else None,
        "price_guard_policy_id": policy["policy_id"],
        "price_guard_policy_version": policy_version,
        "approved_payload_hash": execution_payload_hash,
        "execution_payload_hash": execution_payload_hash,
        "requester_principal_id": _actor_value(requester, "principal_id"),
        "formal_approval_created": True,
        "live_execution_count": 0,
    }
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO approvals
                  (approval_id, hotel_id, action_type, status, requested_by, approved_by, payload_json, created_at, updated_at)
                VALUES (?, ?, 'price_update', 'pending', ?, NULL, ?, ?, ?)
                """,
                (approval_id, hotel_id, _actor_value(requester, "principal_id"), _canonical_json(payload), timestamp, timestamp),
            )
            _append_audit_event(
                conn,
                hotel_id=hotel_id,
                request_id=approval_id,
                actor=requester,
                action="formal_price_approval_requested",
                payload_hash=execution_payload_hash,
                created_at=timestamp,
            )
    return {
        "status": "pending",
        "approval_id": approval_id,
        "hotel_id": hotel_id,
        "price_guard_policy_version": policy_version,
        "execution_payload_hash": execution_payload_hash,
        "execution_payload": execution,
        "formal_approval_created": True,
        "live_execution_count": 0,
    }


def approve_formal_price_approval(
    db_path: str,
    *,
    approval_id: str,
    approver: dict[str, Any],
    now: str | None = None,
) -> dict[str, Any]:
    timestamp = _timestamp(now)
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            row = conn.execute("SELECT * FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
            if not row:
                return {"status": "not_found", "reason": "formal_price_approval_not_found"}
            approval = dict(row)
            payload = json.loads(approval["payload_json"])
            if approval["status"] != "pending":
                return {"status": "blocked", "reason": "formal_price_approval_not_pending"}
            if approval["requested_by"] == _actor_value(approver, "principal_id"):
                return {"status": "blocked", "reason": "self_approval_not_allowed"}
            if not _actor_can_approve(approver, PRICE_GUARD_KIND, approval["hotel_id"]):
                return {"status": "blocked", "reason": "formal_price_approval_not_authorized"}
            policy = active_price_guard_policy(
                db_path,
                approval["hotel_id"],
                payload.get("room_type_id"),
                timestamp,
                channel_source=payload.get("channel_source") or payload.get("channel"),
                ota_product_id=payload.get("ota_product_id"),
            )
            if not policy or int(policy["version"]) != int(payload.get("price_guard_policy_version") or -1):
                return {"status": "blocked", "reason": "formal_price_approval_policy_version_mismatch"}
            conn.execute(
                "UPDATE approvals SET status='approved', approved_by=?, updated_at=? WHERE approval_id=? AND status='pending'",
                (_actor_value(approver, "principal_id"), timestamp, approval_id),
            )
            _append_audit_event(
                conn,
                hotel_id=approval["hotel_id"],
                request_id=approval_id,
                actor=approver,
                action="formal_price_approved",
                payload_hash=str(payload.get("execution_payload_hash") or ""),
                created_at=timestamp,
            )
    return {"status": "approved", "approval_id": approval_id, "hotel_id": approval["hotel_id"], "live_execution_count": 0}


def verify_audit_chain(db_path: str, hotel_id: str) -> dict[str, Any]:
    with closing(connect(db_path)) as conn:
        init_schema(conn)
        rows = conn.execute(
            "SELECT * FROM configuration_audit_events WHERE hotel_id=? ORDER BY rowid",
            (hotel_id,),
        ).fetchall()
    previous_hash = ""
    for row in rows:
        item = dict(row)
        expected = _hash(
            "|".join(
                [
                    item["hotel_id"],
                    item["request_id"],
                    item["actor_principal_id"],
                    item["actor_role"],
                    item["action"],
                    item["payload_hash"],
                    previous_hash,
                    item["created_at"],
                ]
            )
        )
        if item.get("previous_event_hash") != (previous_hash or None) or item["event_hash"] != expected:
            return {"valid": False, "event_count": len(rows), "reason": "audit_hash_chain_invalid"}
        previous_hash = item["event_hash"]
    return {"valid": True, "event_count": len(rows), "head_hash": previous_hash or None}

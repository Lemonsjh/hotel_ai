from __future__ import annotations

import contextlib
import contextvars
import hashlib
import re
from typing import Any


_INSTALLED = False
_CURRENT_NAMED_REVOKE: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "hotel_ota_named_role_revoke",
    default=False,
)
_CURRENT_ROLE_SENTINEL = "__current_hotel_role__"
_TENANT_ROLES = {"owner", "operator", "frontdesk"}


def parse_named_role_revoke(message: str | None) -> dict[str, str] | None:
    """Parse a narrow natural-language request to revoke a person's hotel role."""
    text = str(message or "").strip()
    patterns = (
        r"^\s*(?:帮我)?(?:把|将)\s*(?P<target>.+?)\s*(?:的)?(?:身份|角色)\s*撤销\s*$",
        r"^\s*撤销\s*(?P<target>.+?)\s*(?:的)?(?:身份|角色)\s*$",
    )
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if not match:
            continue
        target = match.group("target").strip()
        if target:
            return {
                "target": target,
                "role": _CURRENT_ROLE_SENTINEL,
                "operation": "revoke",
            }
    return None


def _hotel_scoped_named_role_target(
    db_path: str | None,
    *,
    hotel_id: str | None,
    target: str,
    member_info: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a named target from hotel-level membership, never current-chat role state."""
    from runtime.common import now_local
    from runtime.storage import connect, init_schema

    target_text = str(target or "").strip()
    if not db_path or not hotel_id or not target_text:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}
    if target_text in {"群里的一个人", "群里一个人", "某个人", "某某", "那个人", "一个人"}:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}

    try:
        with contextlib.closing(connect(db_path)) as conn:
            init_schema(conn)
            exact = conn.execute(
                """
                SELECT p.principal_id
                FROM auth_principals p
                WHERE p.principal_id=? AND p.status='active'
                """,
                (target_text,),
            ).fetchall()
            if exact:
                candidates = exact
            else:
                candidates = conn.execute(
                    """
                    SELECT DISTINCT p.principal_id
                    FROM auth_principals p
                    JOIN hotel_memberships m ON m.principal_id=p.principal_id
                    WHERE m.hotel_id=? AND m.status='active' AND p.status='active'
                      AND (p.display_name=? OR p.alias=? OR p.name_snapshot=?)
                    """,
                    (hotel_id, target_text, target_text, target_text),
                ).fetchall()
    except Exception:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}

    if len(candidates) == 1:
        principal_id = str(candidates[0]["principal_id"])
        if _CURRENT_NAMED_REVOKE.get():
            try:
                with contextlib.closing(connect(db_path)) as conn:
                    init_schema(conn)
                    membership = conn.execute(
                        """
                        SELECT role
                        FROM hotel_memberships
                        WHERE principal_id=? AND hotel_id=? AND status='active'
                        """,
                        (principal_id, hotel_id),
                    ).fetchone()
            except Exception:
                membership = None
            if not membership or str(membership["role"]) not in _TENANT_ROLES:
                return {"status": "blocked", "reason": "role_membership_target_not_active"}
        return {"status": "ok", "principal_id": principal_id, "source": "hotel_membership"}

    if _CURRENT_NAMED_REVOKE.get():
        return {
            "status": "blocked",
            "reason": (
                "role_membership_target_not_unique_in_hotel"
                if len(candidates) > 1
                else "role_membership_target_not_active"
            ),
        }

    matches: list[dict[str, Any]] = []
    for item in member_info or []:
        names = {
            str(item.get("name") or "").strip(),
            str(item.get("display_name") or "").strip(),
            str(item.get("nickname") or "").strip(),
        }
        if target_text in names:
            matches.append(item)
    if len(matches) != 1:
        return {
            "status": "blocked",
            "reason": "member_info_match_not_unique" if matches else "role_membership_target_not_found",
        }

    identity = matches[0]
    open_id = str(identity.get("open_id") or "").strip() or None
    user_id = str(identity.get("user_id") or "").strip() or None
    union_id = str(identity.get("union_id") or "").strip() or None
    identity_value = open_id or user_id or union_id
    if not identity_value:
        return {"status": "blocked", "reason": "member_info_identity_missing"}

    principal_id = f"feishu:{hashlib.sha256(identity_value.encode('utf-8')).hexdigest()[:12]}"
    timestamp = now_local()
    try:
        with contextlib.closing(connect(db_path)) as conn:
            with conn:
                init_schema(conn)
                existing = conn.execute(
                    """
                    SELECT principal_id
                    FROM auth_principals
                    WHERE (open_id=? OR user_id=? OR union_id=?)
                    LIMIT 1
                    """,
                    (open_id, user_id, union_id),
                ).fetchone()
                if existing:
                    principal_id = str(existing["principal_id"])
                else:
                    conn.execute(
                        """
                        INSERT INTO auth_principals (
                          principal_id, open_id, user_id, union_id, display_name,
                          status, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, 'candidate', ?, ?)
                        """,
                        (principal_id, open_id, user_id, union_id, target_text, timestamp, timestamp),
                    )
    except Exception:
        return {"status": "blocked", "reason": "member_info_candidate_persist_failed"}
    return {"status": "ok", "principal_id": principal_id, "source": "member_info"}


_MENTION_TAG_RE = re.compile(r"<at[^>]*>(.*?)</at>", re.IGNORECASE | re.DOTALL)


def _strip_mention_tags(text: str) -> str:
    """Replace Feishu <at ...>name</at> mentions with their display name."""
    return _MENTION_TAG_RE.sub(lambda m: (m.group(1) or "").strip(), text or "")


def _normalize_named_role_message(message: str | None) -> str:
    """Normalize named-role phrasing so targets resolve without agent-side fixes.

    Handles Feishu mention markup and stray whitespace/particles, e.g.:
      '将<at ...>杨毅</at> 的角色设为老板' -> '将杨毅设为老板'
    Only touches 将/把 named-role phrasing; other command formats are untouched.
    """
    text = _strip_mention_tags(message)
    text = re.sub(r"\s+", " ", text).strip()
    if not re.match(r"^(?:帮我)?(?:将|把)", text):
        return text
    text = re.sub(r"\s*(?:的)?(?:身份|角色)?\s*(?=(?:分配角色|设置为|设为|设成|改成|改为|换成))", "", text)
    text = re.sub(r"^(帮我)?(将|把)\s+", r"\1\2", text)
    return text


def _active_hotel_role(db_path: str, *, hotel_id: str, principal_id: str) -> str | None:
    from runtime.storage import connect, init_schema

    try:
        with contextlib.closing(connect(db_path)) as conn:
            init_schema(conn)
            row = conn.execute(
                """
                SELECT role
                FROM hotel_memberships
                WHERE principal_id=? AND hotel_id=? AND status='active'
                """,
                (principal_id, hotel_id),
            ).fetchone()
    except Exception:
        return None
    role = str(row["role"]) if row else ""
    return role if role in _TENANT_ROLES else None


def install() -> None:
    """Install hotel-scoped named role handling after other Feishu runtime patches."""
    global _INSTALLED
    if _INSTALLED:
        return

    from runtime import feishu_command_router as router

    previous_named_payload = router._chat_role_named_payload
    previous_create_role_change = router.create_chat_role_change_request
    previous_route = router.route_feishu_command

    def chat_role_named_payload(message: str) -> dict[str, str] | None:
        revoke = parse_named_role_revoke(message)
        if revoke is not None:
            return revoke
        return previous_named_payload(_normalize_named_role_message(message))

    def create_chat_role_change_request_with_current_role(
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
        resolved_role = requested_role
        if operation == "revoke" and requested_role == _CURRENT_ROLE_SENTINEL:
            resolved_role = _active_hotel_role(
                db_path,
                hotel_id=hotel_id,
                principal_id=target_principal_id,
            ) or ""
            if not resolved_role:
                return {"status": "blocked", "reason": "role_membership_target_not_active"}
        return previous_create_role_change(
            db_path,
            hotel_id=hotel_id,
            chat_id=chat_id,
            requester=requester,
            target_principal_id=target_principal_id,
            requested_role=resolved_role,
            operation=operation,
            now=now,
        )

    def route_feishu_command_with_named_revoke(message: str, **kwargs: Any) -> dict[str, Any]:
        token = _CURRENT_NAMED_REVOKE.set(parse_named_role_revoke(message) is not None)
        try:
            return previous_route(message, **kwargs)
        finally:
            _CURRENT_NAMED_REVOKE.reset(token)

    router._chat_role_named_payload = chat_role_named_payload
    router._resolve_named_role_target = _hotel_scoped_named_role_target
    router.create_chat_role_change_request = create_chat_role_change_request_with_current_role
    router.route_feishu_command = route_feishu_command_with_named_revoke
    _INSTALLED = True

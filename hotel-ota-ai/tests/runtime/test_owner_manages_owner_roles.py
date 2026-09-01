from __future__ import annotations

from contextlib import closing

from runtime.control_plane import (
    confirm_chat_role_change_request,
    create_chat_role_change_request,
)
from runtime.storage import connect, init_schema


HOTEL_ID = "hotel-owner-test"
CHAT_ID = "oc_owner_test"
NOW = "2026-08-06T20:00:00"


def _actor() -> dict[str, object]:
    return {
        "principal_id": "owner-a",
        "role": "owner",
        "hotel_ids": [HOTEL_ID],
        "resolved_hotel_id": HOTEL_ID,
        "global_admin": False,
    }


def _seed(db_path: str, *, target_hotel_role: str = "operator", target_chat_role: str | None = None) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            for principal_id in ("owner-a", "owner-b"):
                conn.execute(
                    "INSERT INTO auth_principals "
                    "(principal_id, is_global_admin, status, created_at, updated_at) "
                    "VALUES (?, 0, 'active', ?, ?)",
                    (principal_id, NOW, NOW),
                )
            conn.execute(
                "INSERT INTO hotel_memberships "
                "(principal_id, hotel_id, role, status, created_at, updated_at) "
                "VALUES ('owner-a', ?, 'owner', 'active', ?, ?)",
                (HOTEL_ID, NOW, NOW),
            )
            conn.execute(
                "INSERT INTO hotel_memberships "
                "(principal_id, hotel_id, role, status, created_at, updated_at) "
                "VALUES ('owner-b', ?, ?, 'active', ?, ?)",
                (HOTEL_ID, target_hotel_role, NOW, NOW),
            )
            conn.execute(
                "INSERT INTO group_chat_bindings "
                "(chat_id, hotel_id, status, created_at, updated_at) "
                "VALUES (?, ?, 'active', ?, ?)",
                (CHAT_ID, HOTEL_ID, NOW, NOW),
            )
            if target_chat_role:
                from runtime.control_plane import _chat_hash

                conn.execute(
                    "INSERT INTO chat_role_memberships "
                    "(chat_id_hash, hotel_id, principal_id, role, status, created_at, updated_at) "
                    "VALUES (?, ?, 'owner-b', ?, 'active', ?, ?)",
                    (_chat_hash(CHAT_ID), HOTEL_ID, target_chat_role, NOW, NOW),
                )


def test_owner_can_appoint_another_owner(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = str(tmp_path / "owner-grant.sqlite")
    _seed(db_path)

    request = create_chat_role_change_request(
        db_path,
        hotel_id=HOTEL_ID,
        chat_id=CHAT_ID,
        requester=_actor(),
        target_principal_id="owner-b",
        requested_role="owner",
        operation="grant",
        now=NOW,
    )
    assert request["status"] == "pending_confirmation"

    confirmed = confirm_chat_role_change_request(
        db_path,
        request_id=request["request_id"],
        actor=_actor(),
        chat_id=CHAT_ID,
        now=NOW,
    )
    assert confirmed["status"] == "confirmed"

    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT role, status FROM chat_role_memberships "
            "WHERE hotel_id=? AND principal_id='owner-b'",
            (HOTEL_ID,),
        ).fetchone()
    assert row is not None
    assert row["role"] == "owner"
    assert row["status"] == "active"


def test_owner_can_revoke_another_owner_in_current_chat(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = str(tmp_path / "owner-revoke.sqlite")
    _seed(db_path, target_chat_role="owner")

    request = create_chat_role_change_request(
        db_path,
        hotel_id=HOTEL_ID,
        chat_id=CHAT_ID,
        requester=_actor(),
        target_principal_id="owner-b",
        requested_role="owner",
        operation="revoke",
        now=NOW,
    )
    assert request["status"] == "pending_confirmation"

    confirmed = confirm_chat_role_change_request(
        db_path,
        request_id=request["request_id"],
        actor=_actor(),
        chat_id=CHAT_ID,
        now=NOW,
    )
    assert confirmed["status"] == "confirmed"

    with closing(connect(db_path)) as conn:
        row = conn.execute(
            "SELECT status FROM chat_role_memberships "
            "WHERE hotel_id=? AND principal_id='owner-b'",
            (HOTEL_ID,),
        ).fetchone()
    assert row is not None
    assert row["status"] == "revoked"


def test_owner_still_cannot_modify_self(tmp_path) -> None:  # type: ignore[no-untyped-def]
    db_path = str(tmp_path / "owner-self.sqlite")
    _seed(db_path)

    result = create_chat_role_change_request(
        db_path,
        hotel_id=HOTEL_ID,
        chat_id=CHAT_ID,
        requester=_actor(),
        target_principal_id="owner-a",
        requested_role="owner",
        operation="revoke",
        now=NOW,
    )

    assert result == {
        "status": "blocked",
        "reason": "owner_cannot_modify_self_membership",
    }

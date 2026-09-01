from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.control_plane import (
    confirm_chat_role_change_request,
    create_chat_join_request,
    create_chat_role_change_request,
)
from runtime.storage import connect, init_schema


class TestChatRoleMembershipRequests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self._tmp.name) / "auth.sqlite")
        self.owner = {
            "principal_id": "owner-1",
            "role": "owner",
            "hotel_ids": ["hotel-a"],
            "resolved_hotel_id": "hotel-a",
            "global_admin": False,
        }
        with closing(connect(self.db_path)) as conn:
            with conn:
                init_schema(conn)
                conn.execute(
                    "INSERT INTO group_chat_bindings (chat_id, hotel_id, status, created_at, updated_at) VALUES ('oc_hotel_a', 'hotel-a', 'active', '2026-06-24T00:00:00', '2026-06-24T00:00:00')"
                )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_join_request_creates_candidate_then_owner_confirmation_grants_membership(self) -> None:
        request = create_chat_join_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            identity={"open_id": "ou_candidate"},
            requested_role="operator",
            now="2026-06-24T10:00:00",
        )

        self.assertEqual(request["status"], "pending_owner_approval")
        self.assertTrue(request["request_id"].startswith("ROLE-"))
        self.assertNotIn("ou_candidate", str(request))

        confirmed = confirm_chat_role_change_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.owner,
            chat_id="oc_hotel_a",
            now="2026-06-24T10:01:00",
        )
        self.assertEqual(confirmed["status"], "confirmed")

        with closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT role, status FROM hotel_memberships WHERE hotel_id='hotel-a'"
            ).fetchone()
        self.assertEqual(dict(row), {"role": "operator", "status": "active"})

    def test_operator_cannot_confirm_own_role_request(self) -> None:
        request = create_chat_join_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            identity={"open_id": "ou_candidate"},
            requested_role="frontdesk",
            now="2026-06-24T10:00:00",
        )
        blocked = confirm_chat_role_change_request(
            self.db_path,
            request_id=request["request_id"],
            actor={
                "principal_id": self._role_request_target(request["request_id"]),
                "role": "operator",
                "hotel_ids": ["hotel-a"],
                "resolved_hotel_id": "hotel-a",
                "global_admin": False,
            },
            chat_id="oc_hotel_a",
            now="2026-06-24T10:01:00",
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason"], "role_request_requires_owner_confirmation")

    def test_owner_can_confirm_own_ordinary_member_request(self) -> None:
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, status, created_at, updated_at) VALUES ('operator-1', 'ou_operator', 'active', '2026-06-24T00:00:00', '2026-06-24T00:00:00')"
                )
        request = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="operator-1",
            requested_role="operator",
            operation="grant",
            now="2026-06-24T10:00:00",
        )
        self.assertEqual(request["status"], "pending_confirmation")

        confirmed = confirm_chat_role_change_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.owner,
            chat_id="oc_hotel_a",
            now="2026-06-24T10:01:00",
        )
        self.assertEqual(confirmed["status"], "confirmed")

    def test_global_admin_can_self_confirm_ordinary_member_request(self) -> None:
        admin = {
            "principal_id": "admin-1",
            "role": "admin",
            "hotel_ids": [],
            "resolved_hotel_id": "hotel-a",
            "global_admin": True,
        }
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, status, created_at, updated_at) VALUES ('frontdesk-1', 'ou_frontdesk', 'active', '2026-06-24T00:00:00', '2026-06-24T00:00:00')"
                )

        request = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=admin,
            target_principal_id="frontdesk-1",
            requested_role="frontdesk",
            operation="grant",
            now="2026-06-24T10:00:00",
        )
        self.assertEqual(request["status"], "pending_confirmation")

        confirmed = confirm_chat_role_change_request(
            self.db_path,
            request_id=request["request_id"],
            actor=admin,
            chat_id="oc_hotel_a",
            now="2026-06-24T10:01:00",
        )
        self.assertEqual(confirmed["status"], "confirmed")

        with closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT role, status FROM hotel_memberships WHERE principal_id='frontdesk-1' AND hotel_id='hotel-a'"
            ).fetchone()
        self.assertEqual(dict(row), {"role": "frontdesk", "status": "active"})

    def test_owner_can_grant_owner_to_current_chat_member(self) -> None:
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, status, created_at, updated_at) VALUES ('owner-2', 'ou_owner_2', 'active', '2026-06-24T00:00:00', '2026-06-24T00:00:00')"
                )

        request = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="owner-2",
            requested_role="owner",
            operation="grant",
            now="2026-06-24T10:00:00",
        )

        self.assertEqual(request["status"], "pending_confirmation")

    def test_owner_cannot_grant_operator_to_existing_owner_target(self) -> None:
        self._insert_existing_member("owner-2", "owner")

        request = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="owner-2",
            requested_role="operator",
            operation="grant",
            now="2026-06-24T10:00:00",
        )

        self.assertEqual(request["status"], "blocked")
        self.assertEqual(request["reason"], "owner_cannot_modify_owner_or_admin_membership")

    def test_owner_same_role_grant_is_idempotent(self) -> None:
        self._insert_existing_member("owner-2", "owner")

        request = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="owner-2",
            requested_role="owner",
            operation="grant",
            now="2026-06-24T10:00:00",
        )

        self.assertEqual(request["status"], "already_member")
        self.assertIsNone(request["request_id"])

    def test_owner_can_revoke_existing_owner_target(self) -> None:
        self._insert_existing_member("owner-2", "owner")

        request = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="owner-2",
            requested_role="operator",
            operation="revoke",
            now="2026-06-24T10:00:00",
        )

        self.assertEqual(request["status"], "pending_confirmation")

    def _role_request_target(self, request_id: str) -> str:
        with closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT target_principal_id FROM role_change_requests WHERE request_id=?", (request_id,)
            ).fetchone()
        self.assertIsNotNone(row)
        return str(row["target_principal_id"])

    def _insert_existing_member(self, principal_id: str, role: str) -> None:
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, status, created_at, updated_at) VALUES (?, ?, 'active', '2026-06-24T00:00:00', '2026-06-24T00:00:00')",
                    (principal_id, f"ou_{principal_id}"),
                )
                conn.execute(
                    "INSERT INTO hotel_memberships (principal_id, hotel_id, role, status, created_at, updated_at) VALUES (?, 'hotel-a', ?, 'active', '2026-06-24T00:00:00', '2026-06-24T00:00:00')",
                    (principal_id, role),
                )


if __name__ == "__main__":
    unittest.main()
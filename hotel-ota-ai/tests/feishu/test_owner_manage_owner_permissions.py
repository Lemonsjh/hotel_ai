from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.control_plane import (
    confirm_chat_role_change_request,
    create_chat_role_change_request,
)
from runtime.storage import connect, init_schema


class TestOwnerManageOwnerPermissions(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self.tmp.name) / "auth.sqlite")
        self.owner = {
            "principal_id": "owner-1",
            "role": "owner",
            "global_admin": False,
            "hotel_ids": ["hotel-a"],
            "resolved_hotel_id": "hotel-a",
        }
        self.admin = {
            "principal_id": "admin-1",
            "role": "admin",
            "global_admin": True,
            "hotel_ids": ["hotel-a"],
            "resolved_hotel_id": "hotel-a",
        }
        with closing(connect(self.db_path)) as conn:
            with conn:
                init_schema(conn)
                conn.execute(
                    "INSERT INTO group_chat_bindings "
                    "(chat_id, hotel_id, status, created_at, updated_at) "
                    "VALUES ('oc_hotel_a', 'hotel-a', 'active', "
                    "'2026-08-06T10:00:00', '2026-08-06T10:00:00')"
                )
                principals = (
                    ("owner-1", "ou_owner-1", "发起老板"),
                    ("admin-1", "ou_admin-1", "全局管理员"),
                    ("owner-target", "ou_owner-target", "目标老板"),
                )
                for principal_id, open_id, display_name in principals:
                    conn.execute(
                        "INSERT INTO auth_principals "
                        "(principal_id, open_id, display_name, status, created_at, updated_at) "
                        "VALUES (?, ?, ?, 'active', '2026-08-06T10:00:00', "
                        "'2026-08-06T10:00:00')",
                        (principal_id, open_id, display_name),
                    )
                conn.execute(
                    "INSERT INTO hotel_memberships "
                    "(principal_id, hotel_id, role, status, created_at, updated_at) "
                    "VALUES ('owner-1', 'hotel-a', 'owner', 'active', "
                    "'2026-08-06T10:00:00', '2026-08-06T10:00:00')"
                )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _request_and_confirm(self, operation: str) -> dict:
        requested = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="owner-target",
            requested_role="owner",
            operation=operation,
            now="2026-08-06T10:01:00",
        )
        self.assertEqual(requested["status"], "pending_confirmation")
        self.assertTrue(requested["self_confirmation_allowed"])
        self.assertEqual(requested["confirmation_policy"], "requester_owner_may_confirm")
        return confirm_chat_role_change_request(
            self.db_path,
            request_id=requested["request_id"],
            actor=self.owner,
            chat_id="oc_hotel_a",
            requested_role="owner",
            now="2026-08-06T10:02:00",
        )

    def _make_target_owner(self) -> None:
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO hotel_memberships "
                    "(principal_id, hotel_id, role, status, created_at, updated_at) "
                    "VALUES ('owner-target', 'hotel-a', 'owner', 'active', "
                    "'2026-08-06T10:00:00', '2026-08-06T10:00:00') "
                    "ON CONFLICT(principal_id, hotel_id) DO UPDATE SET "
                    "role='owner', status='active', updated_at='2026-08-06T10:00:00'"
                )

    def test_owner_can_appoint_and_revoke_another_owner(self) -> None:
        granted = self._request_and_confirm("grant")
        self.assertEqual(granted["status"], "confirmed")
        self.assertTrue(granted["self_confirmed"])
        self.assertEqual(
            granted["role_change_identity"]["approver"]["display_name"],
            "发起老板",
        )

        with closing(connect(self.db_path)) as conn:
            active = conn.execute(
                "SELECT role, status FROM hotel_memberships "
                "WHERE hotel_id='hotel-a' AND principal_id='owner-target'"
            ).fetchone()
        self.assertEqual((active["role"], active["status"]), ("owner", "active"))

        revoked = self._request_and_confirm("revoke")
        self.assertEqual(revoked["status"], "confirmed")
        self.assertTrue(revoked["self_confirmed"])

        with closing(connect(self.db_path)) as conn:
            current = conn.execute(
                "SELECT role, status FROM hotel_memberships "
                "WHERE hotel_id='hotel-a' AND principal_id='owner-target'"
            ).fetchone()
        self.assertIsNone(current)

    def test_owner_can_directly_change_another_owner_to_frontdesk_and_self_confirm(self) -> None:
        self._make_target_owner()

        requested = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="owner-target",
            requested_role="frontdesk",
            operation="grant",
            now="2026-08-06T10:03:00",
        )

        self.assertEqual(requested["status"], "pending_confirmation")
        self.assertTrue(requested["direct_role_replacement"])
        self.assertEqual(requested["previous_role"], "owner")
        self.assertTrue(requested["self_confirmation_allowed"])
        self.assertEqual(
            requested["role_change_identity"]["requester"]["display_name"],
            "发起老板",
        )
        self.assertEqual(
            requested["role_change_identity"]["target"]["display_name"],
            "目标老板",
        )

        confirmed = confirm_chat_role_change_request(
            self.db_path,
            request_id=requested["request_id"],
            actor=self.owner,
            chat_id="oc_hotel_a",
            requested_role="frontdesk",
            now="2026-08-06T10:04:00",
        )

        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["direct_role_replacement"])
        self.assertTrue(confirmed["self_confirmed"])
        self.assertEqual(confirmed["identity_source"], "sqlite_active_auth")
        self.assertEqual(
            confirmed["role_change_identity"]["approver"]["display_name"],
            "发起老板",
        )
        self.assertEqual(
            confirmed["role_change_identity"]["target"]["display_name"],
            "目标老板",
        )

        with closing(connect(self.db_path)) as conn:
            membership = conn.execute(
                "SELECT role, status FROM hotel_memberships "
                "WHERE hotel_id='hotel-a' AND principal_id='owner-target'"
            ).fetchone()
            request_row = conn.execute(
                "SELECT requester_principal_id, approver_principal_id, approver_role, status "
                "FROM role_change_requests WHERE request_id=?",
                (requested["request_id"],),
            ).fetchone()

        self.assertEqual((membership["role"], membership["status"]), ("frontdesk", "active"))
        self.assertEqual(request_row["requester_principal_id"], "owner-1")
        self.assertEqual(request_row["approver_principal_id"], "owner-1")
        self.assertEqual(request_row["approver_role"], "owner")
        self.assertEqual(request_row["status"], "confirmed")

    def test_admin_can_directly_change_owner_to_frontdesk_and_self_confirm(self) -> None:
        self._make_target_owner()

        requested = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.admin,
            target_principal_id="owner-target",
            requested_role="frontdesk",
            operation="grant",
            now="2026-08-06T10:05:00",
        )

        self.assertEqual(requested["status"], "pending_confirmation")
        self.assertTrue(requested["direct_role_replacement"])
        self.assertEqual(requested["previous_role"], "owner")
        self.assertTrue(requested["self_confirmation_allowed"])
        self.assertEqual(requested["confirmation_policy"], "requester_admin_may_confirm")
        self.assertEqual(
            requested["role_change_identity"]["requester"]["display_name"],
            "全局管理员",
        )

        confirmed = confirm_chat_role_change_request(
            self.db_path,
            request_id=requested["request_id"],
            actor=self.admin,
            chat_id="oc_hotel_a",
            requested_role="frontdesk",
            now="2026-08-06T10:06:00",
        )

        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["direct_role_replacement"])
        self.assertTrue(confirmed["self_confirmed"])
        self.assertEqual(confirmed["confirmation_policy"], "requester_admin_may_confirm")
        self.assertEqual(
            confirmed["role_change_identity"]["approver"]["display_name"],
            "全局管理员",
        )

        with closing(connect(self.db_path)) as conn:
            membership = conn.execute(
                "SELECT role, status FROM hotel_memberships "
                "WHERE hotel_id='hotel-a' AND principal_id='owner-target'"
            ).fetchone()
            request_row = conn.execute(
                "SELECT requester_principal_id, requester_role, approver_principal_id, approver_role, status "
                "FROM role_change_requests WHERE request_id=?",
                (requested["request_id"],),
            ).fetchone()

        self.assertEqual((membership["role"], membership["status"]), ("frontdesk", "active"))
        self.assertEqual(request_row["requester_principal_id"], "admin-1")
        self.assertEqual(request_row["requester_role"], "admin")
        self.assertEqual(request_row["approver_principal_id"], "admin-1")
        self.assertEqual(request_row["approver_role"], "admin")
        self.assertEqual(request_row["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.control_plane import create_chat_role_change_request
from runtime.storage import connect, init_schema


class TestOwnerRoleScope(unittest.TestCase):
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
        with closing(connect(self.db_path)) as conn:
            with conn:
                init_schema(conn)
                conn.execute(
                    "INSERT INTO group_chat_bindings (chat_id, hotel_id, status, created_at, updated_at) VALUES ('oc_hotel_a', 'hotel-a', 'active', '2026-06-30T10:00:00', '2026-06-30T10:00:00')"
                )
                conn.execute(
                    "INSERT INTO group_chat_bindings (chat_id, hotel_id, status, created_at, updated_at) VALUES ('oc_hotel_b', 'hotel-b', 'active', '2026-06-30T10:00:00', '2026-06-30T10:00:00')"
                )
                for principal in ("member-1", "owner-target"):
                    conn.execute(
                        "INSERT INTO auth_principals (principal_id, open_id, status, created_at, updated_at) VALUES (?, ?, 'active', '2026-06-30T10:00:00', '2026-06-30T10:00:00')",
                        (principal, f"ou_{principal}"),
                    )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_owner_can_grant_owner_role_in_current_chat_scope(self) -> None:
        result = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="owner-target",
            requested_role="owner",
            operation="grant",
            now="2026-06-30T10:01:00",
        )

        self.assertEqual(result["status"], "pending_confirmation")
        self.assertEqual(result["hotel_id"], "hotel-a")

    def test_owner_cannot_modify_self(self) -> None:
        result = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="owner-1",
            requested_role="owner",
            operation="grant",
            now="2026-06-30T10:01:00",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "owner_cannot_modify_self_membership")

    def test_owner_cannot_modify_admin(self) -> None:
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, status, created_at, updated_at) VALUES ('admin-target', 'ou_admin_target', 'active', '2026-06-30T10:00:00', '2026-06-30T10:00:00')"
                )
                conn.execute(
                    "INSERT INTO hotel_memberships (principal_id, hotel_id, role, status, created_at, updated_at) VALUES ('admin-target', 'hotel-a', 'admin', 'active', '2026-06-30T10:00:00', '2026-06-30T10:00:00')"
                )
        result = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.owner,
            target_principal_id="admin-target",
            requested_role="owner",
            operation="revoke",
            now="2026-06-30T10:01:00",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "owner_cannot_modify_admin_membership")

    def test_owner_cannot_manage_cross_hotel_member(self) -> None:
        result = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-b",
            chat_id="oc_hotel_b",
            requester=self.owner,
            target_principal_id="member-1",
            requested_role="operator",
            operation="grant",
            now="2026-06-30T10:01:00",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "role_membership_request_not_authorized")


if __name__ == "__main__":
    unittest.main()

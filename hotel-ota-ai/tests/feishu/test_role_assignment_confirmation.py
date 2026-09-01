from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.control_plane import create_chat_role_change_request, confirm_chat_role_change_request
from runtime.storage import connect, init_schema


class TestRoleAssignmentConfirmation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self.tmp.name) / "auth.sqlite")
        with closing(connect(self.db_path)) as conn:
            with conn:
                init_schema(conn)
                conn.execute(
                    "INSERT INTO group_chat_bindings (chat_id, hotel_id, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
                    ("oc_hotel_a", "hotel-a", "2026-06-30T10:00:00", "2026-06-30T10:00:00"),
                )
                for principal in ("owner-target", "operator-target"):
                    conn.execute(
                        "INSERT INTO auth_principals (principal_id, open_id, status, created_at, updated_at) VALUES (?, ?, 'active', ?, ?)",
                        (principal, f"ou_{principal}", "2026-06-30T10:00:00", "2026-06-30T10:00:00"),
                    )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_global_admin_can_confirm_owner_membership(self) -> None:
        admin = {
            "principal_id": "admin-1",
            "role": "admin",
            "global_admin": True,
            "hotel_ids": [],
            "resolved_hotel_id": "hotel-a",
        }

        request = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=admin,
            target_principal_id="owner-target",
            requested_role="owner",
            operation="grant",
            now="2026-06-30T10:01:00",
        )

        self.assertEqual(request["status"], "pending_confirmation")
        confirmed = confirm_chat_role_change_request(
            self.db_path,
            request_id=request["request_id"],
            actor=admin,
            chat_id="oc_hotel_a",
            now="2026-06-30T10:02:00",
        )
        self.assertEqual(confirmed["status"], "confirmed")
        with closing(connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT role, status FROM hotel_memberships WHERE principal_id=? AND hotel_id=?",
                ("owner-target", "hotel-a"),
            ).fetchone()
        self.assertEqual(dict(row), {"role": "owner", "status": "active"})

    def test_operator_cannot_create_role_assignment_request(self) -> None:
        operator = {
            "principal_id": "operator-actor",
            "role": "operator",
            "global_admin": False,
            "hotel_ids": ["hotel-a"],
            "resolved_hotel_id": "hotel-a",
        }

        result = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=operator,
            target_principal_id="operator-target",
            requested_role="frontdesk",
            operation="grant",
            now="2026-06-30T10:01:00",
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "role_membership_request_not_authorized")


if __name__ == "__main__":
    unittest.main()

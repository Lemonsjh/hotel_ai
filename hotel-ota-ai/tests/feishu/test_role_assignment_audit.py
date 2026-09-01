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


class TestRoleAssignmentAudit(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self.tmp.name) / "auth.sqlite")
        self.admin = {
            "principal_id": "admin-1",
            "role": "admin",
            "global_admin": True,
            "hotel_ids": [],
            "resolved_hotel_id": "hotel-a",
        }
        with closing(connect(self.db_path)) as conn:
            with conn:
                init_schema(conn)
                conn.execute(
                    "INSERT INTO group_chat_bindings (chat_id, hotel_id, status, created_at, updated_at) VALUES ('oc_hotel_a', 'hotel-a', 'active', '2026-06-30T10:00:00', '2026-06-30T10:00:00')"
                )
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, status, created_at, updated_at) VALUES ('member-1', 'ou_member', 'active', '2026-06-30T10:00:00', '2026-06-30T10:00:00')"
                )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_confirmed_role_change_writes_audit_events(self) -> None:
        request = create_chat_role_change_request(
            self.db_path,
            hotel_id="hotel-a",
            chat_id="oc_hotel_a",
            requester=self.admin,
            target_principal_id="member-1",
            requested_role="operator",
            operation="grant",
            now="2026-06-30T10:01:00",
        )
        confirmed = confirm_chat_role_change_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.admin,
            chat_id="oc_hotel_a",
            now="2026-06-30T10:02:00",
        )

        self.assertEqual(confirmed["status"], "confirmed")
        with closing(connect(self.db_path)) as conn:
            rows = conn.execute(
                "SELECT action, event_hash FROM configuration_audit_events WHERE request_id=? ORDER BY rowid",
                (request["request_id"],),
            ).fetchall()
        self.assertEqual([row["action"] for row in rows], ["role_change_requested", "role_request_confirmed"])
        self.assertTrue(all(row["event_hash"] for row in rows))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.control_plane import (
    PRICE_GUARD_KIND,
    ROLE_MEMBERSHIP_KIND,
    confirm_chat_binding_request,
    confirm_chat_configuration_request,
    create_chat_binding_request,
    create_chat_configuration_request,
)
from runtime.storage import connect, init_schema


class TestControlPlaneRoleCfgBind(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self._tmp.name) / "control.sqlite")
        self.actor = {
            "principal_id": "owner-1",
            "role": "owner",
            "hotel_ids": ["xingfeng"],
            "resolved_hotel_id": "xingfeng",
            "global_admin": False,
        }
        with closing(connect(self.db_path)) as conn:
            with conn:
                init_schema(conn)
                conn.execute(
                "INSERT INTO auth_principals (principal_id, display_name, status, created_at, updated_at) VALUES (?, ?, 'active', 'now', 'now')",
                ("member-1", "成员一"),
                )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_bind_request_confirm_writes_chat_bindings(self) -> None:
        request = create_chat_binding_request(
            self.db_path,
            hotel_id="xingfeng",
            chat_id="chat-xingfeng",
            chat_type="group",
            requester=self.actor,
            expires_at="2999-01-01T00:00:00",
        )
        self.assertEqual(request["status"], "pending_confirmation")

        confirmed = confirm_chat_binding_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.actor,
            chat_id="chat-xingfeng",
            chat_type="group",
        )

        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["config_change_applied"])
        with closing(connect(self.db_path)) as conn:
            row = conn.execute("SELECT hotel_id, status FROM chat_bindings WHERE chat_id=?", ("chat-xingfeng",)).fetchone()
        self.assertEqual(row["hotel_id"], "xingfeng")
        self.assertEqual(row["status"], "active")

    def test_cfg_request_confirm_writes_price_guard_policy(self) -> None:
        payload = {
            "room_type_id": "NAME_ROOM_FALLBACK",
            "room_type_name": "至臻·电竞大床房",
            "room_type_match_quality": "name_fallback",
            "floor_price": 158,
            "ceiling_price": 238,
            "min_increase_pct": 0.01,
            "min_decrease_pct": 0.01,
            "max_increase_pct": 0.15,
            "max_decrease_pct": 0.15,
        }
        request = create_chat_configuration_request(
            self.db_path,
            request_kind=PRICE_GUARD_KIND,
            hotel_id="xingfeng",
            requester=self.actor,
            chat_id="chat-xingfeng",
            payload=payload,
            expires_at="2999-01-01T00:00:00",
        )
        self.assertEqual(request["status"], "pending_confirmation")

        confirmed = confirm_chat_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.actor,
            chat_id="chat-xingfeng",
        )

        self.assertEqual(confirmed["status"], "confirmed")
        with closing(connect(self.db_path)) as conn:
            row = conn.execute("SELECT room_type_id, floor_price, ceiling_price, status FROM price_guard_policies WHERE hotel_id=?", ("xingfeng",)).fetchone()
        self.assertEqual(row["room_type_id"], "NAME_ROOM_FALLBACK")
        self.assertEqual(float(row["floor_price"]), 158.0)
        self.assertEqual(float(row["ceiling_price"]), 238.0)
        self.assertEqual(row["status"], "active")

    def test_role_request_confirm_writes_hotel_membership(self) -> None:
        payload = {"principal_id": "member-1", "role": "operator", "operation": "grant"}
        request = create_chat_configuration_request(
            self.db_path,
            request_kind=ROLE_MEMBERSHIP_KIND,
            hotel_id="xingfeng",
            requester=self.actor,
            chat_id="chat-xingfeng",
            payload=payload,
            expires_at="2999-01-01T00:00:00",
        )
        self.assertEqual(request["status"], "pending_confirmation")

        confirmed = confirm_chat_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.actor,
            chat_id="chat-xingfeng",
        )

        self.assertEqual(confirmed["status"], "confirmed")
        with closing(connect(self.db_path)) as conn:
            row = conn.execute("SELECT role, status FROM hotel_memberships WHERE principal_id=? AND hotel_id=?", ("member-1", "xingfeng")).fetchone()
        self.assertEqual(row["role"], "operator")
        self.assertEqual(row["status"], "active")

    def test_confirm_unknown_request_does_not_succeed(self) -> None:
        result = confirm_chat_configuration_request(
            self.db_path,
            request_id="CFG-NOTFOUND",
            actor=self.actor,
            chat_id="chat-xingfeng",
        )

        self.assertIn(result["status"], {"not_found", "blocked"})
        self.assertNotEqual(result["status"], "confirmed")


if __name__ == "__main__":
    unittest.main()

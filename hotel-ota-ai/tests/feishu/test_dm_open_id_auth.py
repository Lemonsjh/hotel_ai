from __future__ import annotations

import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import runtime.safety.auth as auth_module
from runtime.storage import connect, init_schema


class TestDmOpenIdAuth(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self._tmp.name) / "auth.sqlite")
        with closing(connect(self.db_path)) as conn:
            with conn:
                init_schema(conn)
                conn.execute(
                "INSERT INTO auth_backend_state (backend_name, status, schema_version, activated_at, updated_at) VALUES ('feishu_active_auth', 'active', 1, 'now', 'now')"
                )
                conn.execute(
                "INSERT INTO auth_principals (principal_id, open_id, display_name, is_global_admin, status, created_at, updated_at) VALUES (?, ?, ?, 1, 'active', 'now', 'now')",
                ("admin_zhang", "test-admin-open", "张宇翔"),
                )
                conn.execute(
                "INSERT INTO hotel_memberships (principal_id, hotel_id, role, status, created_at, updated_at) VALUES (?, ?, 'admin', 'active', 'now', 'now')",
                ("admin_zhang", "xingfeng"),
                )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_private_chat_user_send_target_falls_back_to_open_id_membership(self) -> None:
        self.assertFalse(
            getattr(auth_module, "_LIVE_CONTRACT_PATCHED", False),
            "DM open_id auth must be implemented in runtime.safety.auth, not live_contract_patch",
        )
        context = auth_module.build_auth_context(
            source="feishu",
            open_id="test-admin-open",
            chat_id="user:test-admin-open",
            chat_type="p2p",
            auth_db_path=self.db_path,
            requested_hotel_id="xingfeng",
        )

        self.assertEqual(context["auth_status"], "authorized")
        self.assertEqual(context["user_role"], "admin")
        self.assertEqual(context["principal_id"], "admin_zhang")
        self.assertEqual(context["resolved_hotel_id"], "xingfeng")
        self.assertEqual(context["tenant_status"], "bound_by_open_id")
        self.assertEqual(context["auth_backend"], "sqlite_active")

    def test_private_chat_missing_real_chat_id_uses_single_open_id_membership(self) -> None:
        context = auth_module.build_auth_context(
            source="feishu",
            open_id="test-admin-open",
            chat_id=None,
            chat_type="p2p",
            auth_db_path=self.db_path,
        )

        self.assertEqual(context["auth_status"], "authorized")
        self.assertEqual(context["resolved_hotel_id"], "xingfeng")
        self.assertEqual(context["tenant_status"], "bound_by_open_id")

    def test_private_chat_open_id_without_membership_is_blocked_not_guest_fallback(self) -> None:
        with closing(connect(self.db_path)) as conn:
            with conn:
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, display_name, is_global_admin, status, created_at, updated_at) VALUES (?, ?, ?, 0, 'active', 'now', 'now')",
                    ("memberless_user", "test-memberless-open", "Memberless"),
                )

        context = auth_module.build_auth_context(
            source="feishu",
            open_id="test-memberless-open",
            chat_id="user:test-memberless-open",
            chat_type="p2p",
            auth_db_path=self.db_path,
        )

        self.assertEqual(context["auth_status"], "unauthorized")
        self.assertEqual(context["reason"], "direct_message_hotel_membership_missing")
        self.assertEqual(context["tenant_status"], "direct_message_unbound")
        self.assertEqual(context["auth_backend"], "sqlite_active")


if __name__ == "__main__":
    unittest.main()

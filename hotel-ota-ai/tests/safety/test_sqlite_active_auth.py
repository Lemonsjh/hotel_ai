from __future__ import annotations

import json
import contextlib
import io
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.safety.auth import bootstrap_active_auth, build_auth_context
from runtime.cli import main as cli_main
from runtime.storage import connect, init_schema


class TestSqliteActiveAuth(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.db_path = str(root / "auth.sqlite")
        self.role_map_path = root / "role-map.json"
        self.role_map_path.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": ["admin-1"],
                    "users": [
                        {"principal_id": "admin-1", "open_id": "ou_admin"},
                        {"principal_id": "operator-1", "open_id": "ou_operator"},
                    ],
                    "hotel_memberships": [{"principal_id": "operator-1", "hotel_id": "hotel-a", "role": "operator"}],
                    "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sqlite_membership_is_preferred_over_bootstrap_json(self) -> None:
        bootstrap_active_auth(self.db_path, config_path=str(self.role_map_path))
        with closing(connect(self.db_path)) as conn:
            with conn:
                init_schema(conn)
                conn.execute("UPDATE hotel_memberships SET role='frontdesk' WHERE principal_id='operator-1'")

        context = build_auth_context(
            source="feishu",
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_operator",
            config_path=str(self.role_map_path),
            auth_db_path=self.db_path,
        )

        self.assertEqual(context["auth_backend"], "sqlite_active")
        self.assertEqual(context["auth_status"], "authorized")
        self.assertEqual(context["user_role"], "frontdesk")
        self.assertEqual(context["resolved_hotel_id"], "hotel-a")

    def test_unbootstrapped_v3_sqlite_denies_normal_roles_instead_of_falling_back_to_json(self) -> None:
        context = build_auth_context(
            source="feishu",
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_operator",
            config_path=str(self.role_map_path),
            auth_db_path=self.db_path,
        )

        self.assertEqual(context["auth_backend"], "sqlite_active_unavailable")
        self.assertEqual(context["auth_status"], "unauthorized")
        self.assertEqual(context["reason"], "sqlite_active_auth_unavailable")

    def test_unbootstrapped_v3_sqlite_allows_only_global_admin_emergency_readonly(self) -> None:
        context = build_auth_context(
            source="feishu",
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_admin",
            config_path=str(self.role_map_path),
            auth_db_path=self.db_path,
        )

        self.assertEqual(context["auth_backend"], "emergency_json_global_admin_readonly")
        self.assertEqual(context["tenant_status"], "emergency_readonly")
        self.assertEqual(context["permissions"], ["runtime_status", "view_diagnosis", "view_hotel_controls"])

    def test_sqlite_bootstrap_preserves_global_admin_without_hotel_membership(self) -> None:
        bootstrap_active_auth(self.db_path, config_path=str(self.role_map_path))

        context = build_auth_context(
            source="feishu",
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_admin",
            config_path=str(self.role_map_path),
            auth_db_path=self.db_path,
        )

        self.assertEqual(context["auth_backend"], "sqlite_active")
        self.assertEqual(context["user_role"], "admin")
        self.assertTrue(context["global_admin"])

    def test_auth_bootstrap_sync_cli_only_imports_private_role_map(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli_main(
                [
                    "--db",
                    self.db_path,
                    "auth-bootstrap-sync",
                    "--auth-config",
                    str(self.role_map_path),
                ]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["auth_backend"], "sqlite_active")


if __name__ == "__main__":
    unittest.main()

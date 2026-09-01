from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from runtime.cli import main as cli_main
from runtime.safety.auth import bootstrap_active_auth


class TestExecutePriceSqliteAuth(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.db_path = str(root / "auth.sqlite")
        self.auth_config = root / "role-map.json"
        self.auth_config.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": [],
                    "users": [{"principal_id": "owner-1", "open_id": "ou_owner"}],
                    "hotel_memberships": [{"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"}],
                    "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.auth_config))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _execute(self, *, open_id: str = "ou_owner", chat_id: str = "oc_hotel_a") -> dict:
        output = io.StringIO()
        args = [
            "--db",
            self.db_path,
            "execute-price",
            "--hotel-id",
            "hotel-a",
            "--room-type-id",
            "KING",
            "--normal-price",
            "199",
            "--begin-date",
            "2026-06-25",
            "--end-date",
            "2026-06-25",
            "--dry-run",
            "--auth-source",
            "feishu",
            "--open-id",
            open_id,
            "--chat-id",
            chat_id,
            "--chat-type",
            "group",
            "--auth-config",
            str(self.auth_config),
        ]
        with contextlib.redirect_stdout(output):
            exit_code = cli_main(args)
        self.assertEqual(exit_code, 0)
        return json.loads(output.getvalue())

    def test_execute_price_feishu_dry_run_uses_sqlite_active_auth(self) -> None:
        result = self._execute()

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["auth_context"]["auth_backend"], "sqlite_active")
        self.assertEqual(result["auth_context"]["resolved_hotel_id"], "hotel-a")
        self.assertTrue(result["guard"]["passed"])
        self.assertEqual(result["guard"]["guard_source"], "default_policy")
        self.assertIsNone(result["guard"]["floor_price"])
        self.assertIsNone(result["guard"]["ceiling_price"])

    def test_execute_price_fake_identity_is_blocked_by_sqlite_active_auth(self) -> None:
        result = self._execute(open_id="ou_fake")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["auth_context"]["auth_backend"], "sqlite_active")
        self.assertEqual(result["auth_context"]["reason"], "sqlite_principal_not_found")

    def test_execute_price_unbound_chat_is_blocked_by_tenant_scope(self) -> None:
        result = self._execute(chat_id="oc_unbound")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["auth_context"]["auth_backend"], "sqlite_active")
        self.assertEqual(result["auth_context"]["reason"], "chat_not_bound_to_hotel")


if __name__ == "__main__":
    unittest.main()

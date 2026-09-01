from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.safety.auth import bootstrap_active_auth
from runtime.storage import connect, init_schema


class TestAuthBootstrapEmptyIdentityFields(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.db_path = str(root / "auth.sqlite")
        self.config_path = root / "role-map.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_config(self, users: list[dict]) -> None:
        self.config_path.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": [],
                    "users": users,
                    "hotel_memberships": [
                        {"principal_id": user["principal_id"], "hotel_id": "hotel-a", "role": "operator"}
                        for user in users
                    ],
                    "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_multiple_blank_union_ids_are_normalized_to_null_and_idempotent(self) -> None:
        self._write_config(
            [
                {"principal_id": "user-1", "open_id": "ou_one", "user_id": "", "union_id": ""},
                {"principal_id": "user-2", "open_id": "ou_two", "user_id": " ", "union_id": " "},
            ]
        )

        first = bootstrap_active_auth(self.db_path, config_path=str(self.config_path))
        second = bootstrap_active_auth(self.db_path, config_path=str(self.config_path))

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        with closing(connect(self.db_path)) as conn:
            init_schema(conn)
            rows = conn.execute(
                "SELECT principal_id, open_id, user_id, union_id FROM auth_principals ORDER BY principal_id"
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]["user_id"])
        self.assertIsNone(rows[0]["union_id"])
        self.assertIsNone(rows[1]["user_id"])
        self.assertIsNone(rows[1]["union_id"])

    def test_duplicate_non_empty_identity_is_blocked_before_partial_write(self) -> None:
        self._write_config(
            [
                {"principal_id": "user-1", "open_id": "ou_dup"},
                {"principal_id": "user-2", "open_id": "ou_dup"},
            ]
        )

        with self.assertRaisesRegex(ValueError, "bootstrap_duplicate_identity"):
            bootstrap_active_auth(self.db_path, config_path=str(self.config_path))

        with closing(connect(self.db_path)) as conn:
            init_schema(conn)
            count = conn.execute("SELECT COUNT(*) FROM auth_principals").fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()

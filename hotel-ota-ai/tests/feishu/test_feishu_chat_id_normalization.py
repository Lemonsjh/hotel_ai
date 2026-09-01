from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from runtime.cli import main as cli_main
from runtime.safety.auth import bootstrap_active_auth, normalize_feishu_chat_id, normalize_feishu_conversation_id


class TestFeishuChatIdNormalization(unittest.TestCase):
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
                    "global_admin_principal_ids": ["admin-1"],
                    "users": [{"principal_id": "admin-1", "open_id": "ou_admin"}],
                    "hotel_memberships": [{"principal_id": "admin-1", "hotel_id": "puyue", "role": "owner"}],
                    "group_chat_bindings": [{"chat_id": "oc_group", "hotel_id": "puyue"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.auth_config))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _route(self, message: str, chat_id: str) -> dict:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli_main(
                [
                    "--db",
                    self.db_path,
                    "feishu-route",
                    "--message",
                    message,
                    "--production-feishu",
                    "--open-id",
                    "ou_admin",
                    "--chat-id",
                    chat_id,
                    "--chat-type",
                    "group",
                    "--auth-config",
                    str(self.auth_config),
                    "--render",
                ]
            )
        self.assertEqual(code, 0)
        return json.loads(output.getvalue())

    def test_normalizes_chat_and_conversation_ids(self) -> None:
        self.assertEqual(normalize_feishu_chat_id("chat:oc_group"), "oc_group")
        self.assertEqual(normalize_feishu_conversation_id("conversation:oc_group"), "oc_group")
        self.assertEqual(normalize_feishu_chat_id("oc_group"), "oc_group")
        self.assertIsNone(normalize_feishu_chat_id("user:ou_admin"))

    def test_group_binding_matches_prefixed_chat_id(self) -> None:
        result = self._route("\u67e5\u770b\u5f53\u524d\u4f1a\u8bdd\u7ed1\u5b9a", "chat:oc_group")

        self.assertNotEqual(result["status"], "blocked")
        self.assertEqual(result["intent"], "chat_binding_status")
        self.assertTrue(result["chat_bound"])
        self.assertEqual(result["hotel_id"], "puyue")
        payload_text = result["send_payload"]["text"]
        self.assertNotIn("user:ou_admin", payload_text)


if __name__ == "__main__":
    unittest.main()

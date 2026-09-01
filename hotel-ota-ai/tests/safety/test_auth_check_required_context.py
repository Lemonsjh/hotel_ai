from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from runtime.cli import main
from runtime.safety.auth import build_auth_context


class TestAuthCheckRequiredContext(unittest.TestCase):
    def test_auth_check_requires_chat_id_for_feishu_source(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "auth-check",
                        "--source",
                        "feishu",
                        "--open-id",
                        "ou_test",
                        "--action",
                        "view_diagnosis",
                    ]
                )

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("--chat-id", stderr.getvalue())

    def test_feishu_auth_missing_chat_id_is_invalid_context_not_guest_decision(self) -> None:
        context = build_auth_context(source="feishu", open_id="ou_test", chat_id=None)

        self.assertEqual(context["auth_status"], "invalid_context")
        self.assertEqual(context["reason"], "missing_required_chat_id")
        self.assertEqual(context["user_role"], "guest")

    def test_feishu_auth_missing_identity_is_invalid_context(self) -> None:
        # 有效业务 chat_id 但无身份 → invalid_context/missing_feishu_identity。
        # (user:ou_* 是私信发送目标,非业务会话 id,会先被 resolve_feishu_business_chat_id
        #  以 missing_business_chat_id fail-closed,到不了身份检查——见 auth.py:91。)
        context = build_auth_context(source="feishu", chat_id="oc_business_chat")

        self.assertEqual(context["auth_status"], "invalid_context")
        self.assertEqual(context["reason"], "missing_feishu_identity")
        self.assertEqual(context["user_role"], "guest")

    def test_auth_check_reports_redacted_role_map_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            auth_path = Path(tmp) / "feishu-role-map.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "allowed_chat_ids": ["oc_allowed"],
                        "users": [
                            {
                                "role": "admin",
                                "open_id": "ou_admin",
                                "feishu_open_id": "ou_admin",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                code = main(
                    [
                        "auth-check",
                        "--source",
                        "feishu",
                        "--open-id",
                        "ou_admin",
                        "--chat-id",
                        "oc_allowed",
                        "--auth-config",
                        str(auth_path),
                        "--action",
                        "view_diagnosis",
                    ]
                )

        payload = json.loads(buffer.getvalue())
        serialized = json.dumps(payload, ensure_ascii=False)
        diagnostics = payload["feishu_auth_diagnostics"]

        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(diagnostics["config_loaded"])
        self.assertTrue(diagnostics["chat_allowed"])
        self.assertTrue(diagnostics["user_matched"])
        self.assertEqual(diagnostics["matched_by"], "open_id")
        self.assertEqual(diagnostics["role"], "admin")
        self.assertNotIn("ou_admin", serialized)
        self.assertNotIn("oc_allowed", serialized)
        self.assertNotIn(str(auth_path), serialized)


if __name__ == "__main__":
    unittest.main()

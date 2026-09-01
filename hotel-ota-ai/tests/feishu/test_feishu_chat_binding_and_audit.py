from __future__ import annotations

import json
import contextlib
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth
from runtime.storage import connect, init_schema


class TestFeishuChatBindingAndAudit(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.db_path = str(root / "active-auth.sqlite")
        self.config_path = root / "role-map.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": ["admin-1"],
                    "users": [
                        {"principal_id": "admin-1", "open_id": "ou_admin", "display_name": "Admin"},
                        {"principal_id": "owner-1", "open_id": "ou_owner", "display_name": "Owner"},
                    ],
                    "hotel_memberships": [
                        {"principal_id": "owner-1", "hotel_id": "puyue", "role": "owner"},
                    ],
                    "group_chat_bindings": [
                        {"chat_id": "oc_bound_group", "hotel_id": "puyue"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.config_path))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _route(self, message: str, *, chat_id: str, chat_type: str, open_id: str) -> dict:
        return safe_route_feishu_command(
            message,
            db_path=self.db_path,
            chat_id=chat_id,
            chat_type=chat_type,
            open_id=open_id,
            auth_config=str(self.config_path),
            production_feishu=True,
            render=True,
            compact=False,
        )

    def _activate_private_binding(self) -> None:
        with contextlib.closing(connect(self.db_path)) as conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO chat_bindings (chat_id, chat_type, hotel_id, status, source, created_at, updated_at)
                VALUES ('oc_private_admin', 'p2p', 'puyue', 'active', 'chat_confirmed', '2026-06-26T10:00:00', '2026-06-26T10:00:00')
                ON CONFLICT(chat_id) DO UPDATE SET chat_type=excluded.chat_type, hotel_id=excluded.hotel_id, status='active', source=excluded.source, updated_at=excluded.updated_at
                """
            )
            conn.commit()

    def test_bound_private_chat_status_uses_conversation_id_not_send_target(self) -> None:
        self._activate_private_binding()

        result = self._route("查看当前会话绑定", chat_id="oc_private_admin", chat_type="p2p", open_id="ou_admin")

        self.assertEqual(result["intent"], "chat_binding_status")
        self.assertTrue(result["chat_bound"])
        self.assertEqual(result["resolved_hotel_id"], "puyue")
        self.assertEqual(result["chat_type"], "p2p")
        self.assertTrue(result["send_payload"]["send_allowed"])
        self.assertEqual(result["send_payload"]["warnings"], [])
        self.assertNotIn("config_or_secret_export_not_allowed", json.dumps(result["send_payload"], ensure_ascii=False))
        self.assertNotIn("user:ou_admin", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("ou_admin", result["send_payload"]["text"])
        self.assertNotIn("oc_private_admin", result["send_payload"]["text"])
        self.assertNotIn("user:ou_admin", result["send_payload"]["text"])

    def test_identity_uses_sqlite_active_auth_and_never_claims_live_execution(self) -> None:
        self._activate_private_binding()

        result = self._route("我是谁", chat_id="oc_private_admin", chat_type="p2p", open_id="ou_admin")
        text = result["send_payload"]["text"]

        self.assertEqual(result["intent"], "identity")
        self.assertEqual(result["auth_backend"], "sqlite_active")
        self.assertTrue(result["chat_bound"])
        self.assertEqual(result["resolved_hotel_id"], "puyue")
        self.assertFalse(result["live_allowed"])
        self.assertFalse(result["formal_approval_allowed"])
        self.assertIn("puyue", text)
        self.assertIn("本指令只检查身份、角色、群绑定和当前可用权限", text)
        self.assertIn("经营数据、调价和诊断能力会在对应业务指令中单独校验权限与数据条件", text)
        self.assertNotIn("PMS/MySQL", text)
        self.assertNotIn("当前数据源", text)
        self.assertNotIn("实时房态", text)
        self.assertNotIn("demo/dry-run/production_locked", text)
        self.assertNotIn("demo_data", text)
        self.assertNotIn("sample_data", text)
        self.assertNotIn("正式审批", text)
        self.assertNotIn("live 执行不可用", text)
        self.assertNotIn("live 执行全部权限", text)
        self.assertNotIn("ou_admin", text)

    def test_unbound_private_can_create_then_confirm_bind_request_before_business(self) -> None:
        blocked = self._route("经营快照", chat_id="oc_private_admin", chat_type="p2p", open_id="ou_admin")
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn(blocked.get("blocked_reason") or blocked.get("reason"), {"chat_not_bound_to_hotel", "permission_denied:chat_not_bound_to_hotel"})

        created = self._route("绑定当前私聊到酒店 puyue", chat_id="oc_private_admin", chat_type="p2p", open_id="ou_admin")
        self.assertEqual(created["intent"], "chat_binding_request")
        self.assertEqual(created["status"], "pending_confirmation")
        self.assertTrue(created["request_id"].startswith("BIND-"))
        self.assertFalse(created["config_change_applied"])
        self.assertIn(created["request_id"], created["send_payload"]["text"])

        still_blocked = self._route("经营快照", chat_id="oc_private_admin", chat_type="p2p", open_id="ou_admin")
        self.assertEqual(still_blocked["status"], "blocked")

        confirmed = self._route(f"确认 {created['request_id']}", chat_id="oc_private_admin", chat_type="p2p", open_id="ou_admin")
        self.assertEqual(confirmed["intent"], "chat_binding_confirm")
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["config_change_applied"])

        allowed = self._route("经营快照", chat_id="oc_private_admin", chat_type="p2p", open_id="ou_admin")
        self.assertNotEqual(allowed["status"], "blocked")
        self.assertEqual(allowed.get("resolved_hotel_id") or allowed.get("hotel_id"), "puyue")

    def test_unbound_group_owner_can_create_group_bind_request_for_own_hotel(self) -> None:
        created = self._route("绑定当前群到酒店 puyue", chat_id="oc_new_group", chat_type="group", open_id="ou_owner")
        self.assertEqual(created["intent"], "chat_binding_request")
        self.assertEqual(created["status"], "pending_confirmation")
        self.assertTrue(created["request_id"].startswith("BIND-"))
        self.assertFalse(created["config_change_applied"])

    def test_route_records_chat_registry_and_redacted_message_audit(self) -> None:
        result = self._route("当前模式 token=abc123", chat_id="oc_bound_group", chat_type="group", open_id="ou_owner")
        self.assertIn(result["status"], {"ok", "warning"})
        with contextlib.closing(connect(self.db_path)) as conn:
            init_schema(conn)
            chat_count = conn.execute("SELECT COUNT(*) FROM feishu_chat_registry").fetchone()[0]
            audit = conn.execute("SELECT message_text_redacted, auth_status, role FROM feishu_message_audit ORDER BY created_at DESC LIMIT 1").fetchone()
        self.assertGreaterEqual(chat_count, 1)
        self.assertIsNotNone(audit)
        self.assertIn("***", audit["message_text_redacted"])
        self.assertNotIn("abc123", audit["message_text_redacted"])
        self.assertEqual(audit["auth_status"], "authorized")
        self.assertEqual(audit["role"], "owner")


if __name__ == "__main__":
    unittest.main()

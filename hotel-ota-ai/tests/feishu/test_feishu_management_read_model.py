from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth


class TestFeishuManagementReadModel(unittest.TestCase):
    def _role_map(self, directory: str) -> str:
        path = Path(directory) / "role-map-v3.json"
        path.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": ["admin-1"],
                    "users": [
                        {"principal_id": "admin-1", "open_id": "ou_admin"},
                        {"principal_id": "owner-1", "open_id": "ou_owner"},
                        {"principal_id": "operator-1", "open_id": "ou_operator"},
                    ],
                    "hotel_memberships": [
                        {"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"},
                        {"principal_id": "operator-1", "hotel_id": "hotel-a", "role": "operator"},
                    ],
                    "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return str(path)

    def test_owner_can_read_tenant_control_summary_without_identity_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            role_map = self._role_map(tmp)
            db_path = str(Path(tmp) / "controls.sqlite")
            bootstrap_active_auth(db_path, config_path=role_map)
            result = safe_route_feishu_command(
                "房型价格护栏状态",
                db_path=db_path,
                chat_id="oc_hotel_a",
                open_id="ou_owner",
                auth_config=role_map,
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["intent"], "price_guard_status")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["hotel_id"], "hotel-a")
        self.assertNotIn("ou_owner", result["send_payload"]["text"])
        self.assertNotIn("principal_id", result["send_payload"]["text"])
        self.assertNotIn("raw_json", result["send_payload"]["text"])

    def test_operator_cannot_read_tenant_control_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            role_map = self._role_map(tmp)
            db_path = str(Path(tmp) / "controls.sqlite")
            bootstrap_active_auth(db_path, config_path=role_map)
            result = safe_route_feishu_command(
                "待处理配置申请",
                db_path=db_path,
                chat_id="oc_hotel_a",
                open_id="ou_operator",
                auth_config=role_map,
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["intent"], "pending_configuration_requests")
        self.assertEqual(result["status"], "blocked")
        self.assertNotIn("hotel-a", result["send_payload"]["text"])

    def test_free_text_change_remains_blocked_not_a_management_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            role_map = self._role_map(tmp)
            db_path = str(Path(tmp) / "controls.sqlite")
            bootstrap_active_auth(db_path, config_path=role_map)
            result = safe_route_feishu_command(
                "把房型价格护栏调整为 10%",
                db_path=db_path,
                chat_id="oc_hotel_a",
                open_id="ou_owner",
                auth_config=role_map,
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["intent"], "config_change_request")
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["config_change_applied"])

    def test_group_member_role_query_uses_sqlite_active_auth_read_model(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            role_map = self._role_map(tmp)
            db_path = str(Path(tmp) / "controls.sqlite")
            bootstrap_active_auth(db_path, config_path=role_map)
            result = safe_route_feishu_command(
                "查询当前所有人身份",
                db_path=db_path,
                chat_id="oc_hotel_a",
                chat_type="group",
                open_id="ou_owner",
                auth_config=role_map,
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["intent"], "member_role_status")
        self.assertEqual(result["auth_backend"], "sqlite_active")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["role_scope"], "hotel_summary")
        text = result["send_payload"]["text"]
        self.assertIn("SQLite Active Auth", text)
        self.assertIn("auth-bootstrap-sync", text)
        self.assertNotIn("角色表只在 JSON", text)
        self.assertNotIn("SQLite 只有经营数据", text)
        self.assertNotIn("手改 feishu-role-map", text)
        self.assertNotIn("ou_owner", text)

    def test_bound_groups_share_hotel_member_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            role_map = self._role_map(tmp)
            db_path = str(Path(tmp) / "controls.sqlite")
            bootstrap_active_auth(db_path, config_path=role_map)
            from runtime.control_plane import confirm_chat_role_change_request, create_chat_role_change_request

            owner_actor = {
                "principal_id": "owner-1",
                "role": "owner",
                "hotel_ids": ["hotel-a"],
                "resolved_hotel_id": "hotel-a",
                "global_admin": False,
            }
            from runtime.storage import connect, init_schema

            conn = connect(db_path)
            try:
                init_schema(conn)
                conn.execute(
                    "INSERT INTO group_chat_bindings (chat_id, hotel_id, status, created_at, updated_at) VALUES ('oc_hotel_b', 'hotel-a', 'active', '2026-07-02T00:00:00', '2026-07-02T00:00:00')"
                )
                conn.execute(
                    "INSERT INTO chat_bindings (chat_id, chat_type, hotel_id, status, source, created_at, updated_at) VALUES ('oc_hotel_b', 'group', 'hotel-a', 'active', 'test', '2026-07-02T00:00:00', '2026-07-02T00:00:00')"
                )
                conn.execute(
                    "INSERT INTO auth_principals (principal_id, open_id, display_name, status, created_at, updated_at) VALUES ('operator-2', 'ou_operator_2', '李四', 'active', '2026-07-02T00:00:00', '2026-07-02T00:00:00')"
                )
                conn.commit()
            finally:
                conn.close()

            req_a = create_chat_role_change_request(
                db_path,
                hotel_id="hotel-a",
                chat_id="oc_hotel_a",
                requester=owner_actor,
                target_principal_id="owner-1",
                requested_role="owner",
                operation="grant",
                now="2026-07-02T01:00:00",
            )
            self.assertEqual(req_a["status"], "blocked")
            self.assertEqual(req_a["reason"], "owner_cannot_modify_self_membership")
            req_a = create_chat_role_change_request(
                db_path,
                hotel_id="hotel-a",
                chat_id="oc_hotel_a",
                requester=owner_actor,
                target_principal_id="operator-1",
                requested_role="owner",
                operation="grant",
                now="2026-07-02T01:01:00",
            )
            self.assertEqual(req_a["status"], "pending_confirmation")
            self.assertEqual(confirm_chat_role_change_request(db_path, request_id=req_a["request_id"], actor=owner_actor, chat_id="oc_hotel_a", now="2026-07-02T01:02:00")["status"], "confirmed")

            req_b = create_chat_role_change_request(
                db_path,
                hotel_id="hotel-a",
                chat_id="oc_hotel_b",
                requester=owner_actor,
                target_principal_id="operator-2",
                requested_role="operator",
                operation="grant",
                now="2026-07-02T01:03:00",
            )
            self.assertEqual(req_b["status"], "pending_confirmation")
            self.assertEqual(confirm_chat_role_change_request(db_path, request_id=req_b["request_id"], actor=owner_actor, chat_id="oc_hotel_b", now="2026-07-02T01:04:00")["status"], "confirmed")

            group_a = safe_route_feishu_command(
                "查询当前所有人身份",
                db_path=db_path,
                chat_id="oc_hotel_a",
                chat_type="group",
                open_id="ou_owner",
                auth_config=role_map,
                production_feishu=True,
                render=True,
            )
            group_b = safe_route_feishu_command(
                "查询当前所有人身份",
                db_path=db_path,
                chat_id="oc_hotel_b",
                chat_type="group",
                open_id="ou_owner",
                auth_config=role_map,
                production_feishu=True,
                render=True,
            )

        expected = {"owner": 2, "operator": 1, "frontdesk": 0}
        self.assertEqual(group_a["member_role_counts"], expected)
        self.assertEqual(group_b["member_role_counts"], expected)
        self.assertNotIn("ou_operator_2", group_b["send_payload"]["text"])

    def test_auth_path_question_returns_controlled_runtime_explanation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            role_map = self._role_map(tmp)
            db_path = str(Path(tmp) / "controls.sqlite")
            bootstrap_active_auth(db_path, config_path=role_map)
            result = safe_route_feishu_command(
                "你从哪查，不应该从 sqlite 查吗？",
                db_path=db_path,
                chat_id="oc_hotel_a",
                chat_type="group",
                open_id="ou_owner",
                auth_config=role_map,
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["intent"], "auth_path_explanation")
        self.assertEqual(result["auth_backend"], "sqlite_active")
        self.assertEqual(result["tenant_status"], "hotel_bound")
        text = result["send_payload"]["text"]
        self.assertIn("当前主路径", text)
        self.assertIn("Feishu channel", text)
        self.assertIn("runtime feishu-route/auth-check", text)
        self.assertIn("SQLite Active Auth", text)
        self.assertIn("permission_gate", text)
        self.assertIn("hotel-ota-feishu-auth 插件仅作为可选防护/诊断", text)
        self.assertNotIn("插件层：inbound_claim", text)
        self.assertNotIn("插件层已拦截", text)
        self.assertNotIn("fail-closed 后调用 runtime", text)
        self.assertNotIn("ou_owner", text)


if __name__ == "__main__":
    unittest.main()
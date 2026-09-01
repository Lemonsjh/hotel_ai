from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from runtime.cli import build_parser, main as cli_main
from runtime.feishu_command_router import route_feishu_command, safe_route_feishu_command
from runtime.safety.auth import build_auth_context, resolve_feishu_business_chat_id


class TestFeishuAuthContext(unittest.TestCase):
    def test_user_send_target_is_not_accepted_as_business_chat_id(self) -> None:
        resolved = resolve_feishu_business_chat_id("user:ou_sender")

        self.assertIsNone(resolved["chat_id"])
        self.assertEqual(resolved["status"], "invalid_context")
        self.assertEqual(resolved["reason"], "missing_business_chat_id")

    def test_feishu_auth_context_reports_user_target_as_missing_business_chat_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "role-map.json"
            config.write_text(
                json.dumps(
                    {
                        "allowed_chat_ids": ["oc_test"],
                        "users": [{"role": "operator", "open_id": "ou_sender"}],
                    }
                ),
                encoding="utf-8",
            )
            context = build_auth_context(
                source="feishu",
                open_id="ou_sender",
                chat_id="user:ou_sender",
                config_path=str(config),
            )

        self.assertEqual(context["auth_status"], "invalid_context")
        self.assertEqual(context["reason"], "missing_business_chat_id")
        self.assertIsNone(context["feishu_chat_id"])

    def test_production_feishu_v3_direct_message_requires_explicit_tenant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "role-map-v3.json"
            config.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "direct_message_policy": "role_mapped_users_only",
                        "global_admin_principal_ids": [],
                        "users": [{"principal_id": "u1", "open_id": "ou_operator"}],
                        "hotel_memberships": [
                            {"principal_id": "u1", "hotel_id": "hotel-a", "role": "operator"},
                            {"principal_id": "u1", "hotel_id": "hotel-b", "role": "operator"},
                        ],
                        "group_chat_bindings": [
                            {"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"},
                            {"chat_id": "oc_hotel_b", "hotel_id": "hotel-b"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = safe_route_feishu_command(
                "\u4e1a\u52a1\u65e5\u5386",
                chat_id="oc_direct",
                chat_type="p2p",
                open_id="ou_operator",
                auth_config=str(config),
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "tenant_selection_required")
        self.assertNotEqual(result.get("hotel_id"), "puyue-demo")
        self.assertFalse(result.get("business_result_generated", True))

    def test_production_feishu_rejects_requested_hotel_mismatch_without_demo_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "role-map-v3.json"
            config.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "direct_message_policy": "role_mapped_users_only",
                        "global_admin_principal_ids": [],
                        "users": [{"principal_id": "u1", "open_id": "ou_operator"}],
                        "hotel_memberships": [{"principal_id": "u1", "hotel_id": "hotel-a", "role": "operator"}],
                        "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result = safe_route_feishu_command(
                "\u4e1a\u52a1\u65e5\u5386",
                chat_id="oc_hotel_a",
                chat_type="group",
                open_id="ou_operator",
                auth_config=str(config),
                production_feishu=True,
                hotel_id="hotel-b",
                render=True,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "tenant_scope_mismatch")
        self.assertFalse(result.get("business_result_generated", True))

    def test_feishu_route_does_not_impose_legacy_hotel_default_on_v3_group_binding(self) -> None:
        args = build_parser().parse_args(["feishu-route", "--message", "9"])

        self.assertIsNone(args.hotel_id)

    def test_production_feishu_cli_rejects_role_override_before_routing(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = cli_main(
                [
                    "feishu-route",
                    "--production-feishu",
                    "--message",
                    "收益决策",
                    "--user-role",
                    "operator",
                    "--trusted-runtime-role",
                    "--render",
                ]
            )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "production_feishu_disallows_role_override")
        self.assertFalse(result["business_result_generated"])

    def test_production_feishu_cli_resolves_role_from_private_role_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "role-map.json"
            config.write_text(
                json.dumps(
                    {
                        "allowed_chat_ids": ["oc_test"],
                        "users": [{"role": "operator", "open_id": "ou_test"}],
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                exit_code = cli_main(
                    [
                        "feishu-route",
                        "--production-feishu",
                        "--message",
                        "9",
                        "--chat-id",
                        "oc_test",
                        "--open-id",
                        "ou_test",
                        "--auth-config",
                        str(config),
                        "--hotel-id",
                        "hotel-a",
                        "--render",
                    ]
                )

        result = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(result["output_profile"], "operator_workbench")
        self.assertNotIn("auth_role", result)
        self.assertNotEqual(result["status"], "blocked")

    def test_v3_sqlite_unavailable_only_allows_global_admin_readonly_queries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "role-map-v3.json"
            # Passing a directory makes SQLite Active Auth unavailable.  An
            # empty but readable database is deliberately fail-closed instead.
            db_path = root
            config.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "direct_message_policy": "role_mapped_users_only",
                        "global_admin_principal_ids": ["admin-1"],
                        "users": [{"principal_id": "admin-1", "open_id": "ou_admin"}],
                        "hotel_memberships": [],
                        "group_chat_bindings": [{"chat_id": "oc_hotel", "hotel_id": "hotel-a"}],
                    }
                ),
                encoding="utf-8",
            )

            readonly = build_auth_context(
                source="feishu",
                open_id="ou_admin",
                chat_id="oc_hotel",
                chat_type="group",
                config_path=str(config),
                auth_db_path=str(db_path),
            )
            blocked = safe_route_feishu_command(
                "\u786e\u8ba4 CFG-TEST",
                db_path=str(db_path),
                chat_id="oc_hotel",
                chat_type="group",
                open_id="ou_admin",
                auth_config=str(config),
                production_feishu=True,
                render=True,
            )

        self.assertEqual(readonly["auth_backend"], "emergency_json_global_admin_readonly")
        self.assertEqual(readonly["tenant_status"], "emergency_readonly")
        self.assertEqual(blocked["status"], "blocked")
        self.assertIn("permission_denied", blocked["blocked_reason"])
        self.assertFalse(blocked.get("config_change_applied", False))

    def test_v2_direct_message_without_hotel_scope_is_blocked_in_production(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "role-map-v2.json"
            config.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "allowed_group_chat_ids": ["oc_group"],
                        "direct_message_policy": "role_mapped_users_only",
                        "users": [{"role": "operator", "open_id": "ou_operator"}],
                    }
                ),
                encoding="utf-8",
            )
            result = safe_route_feishu_command(
                "业务日历",
                chat_id="oc_direct",
                chat_type="p2p",
                open_id="ou_operator",
                auth_config=str(config),
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "missing_resolved_hotel_id")
        self.assertFalse(result["business_result_generated"])

    def test_unknown_production_text_returns_fixed_menu_without_stateful_sqlite_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "role-map.json"
            config.write_text(
                json.dumps(
                    {
                        "allowed_chat_ids": ["oc_test"],
                        "users": [{"role": "operator", "open_id": "ou_test"}],
                    }
                ),
                encoding="utf-8",
            )
            result = safe_route_feishu_command(
                "unknown-command",
                chat_id="oc_test",
                open_id="ou_test",
                auth_config=str(config),
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intent"], "menu")
        self.assertEqual(result["runtime_command"], "menu")
        self.assertEqual(result["auth_role"], "operator")
        self.assertEqual(result["output_profile"], "operator_workbench")
        self.assertNotEqual(result["send_payload"]["output_profile"], "guest_limited")
        self.assertNotIn("无权限", result["send_payload"]["text"])
        self.assertNotIn("command_menus", str(result))

    def test_production_feishu_blocks_developer_debug_even_for_authorized_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "role-map.json"
            config.write_text(
                json.dumps(
                    {
                        "allowed_chat_ids": ["oc_test"],
                        "users": [{"role": "admin", "open_id": "ou_admin"}],
                    }
                ),
                encoding="utf-8",
            )
            result = safe_route_feishu_command(
                "developer detail",
                output_profile="developer_debug",
                chat_id="oc_test",
                open_id="ou_admin",
                auth_config=str(config),
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "developer_debug_local_only")
        self.assertFalse(result["business_result_generated"])
        self.assertNotIn("run_id", result["send_payload"]["text"])

    def test_local_developer_debug_requires_trusted_admin_role(self) -> None:
        result = safe_route_feishu_command(
            "developer detail",
            role="operator",
            output_profile="developer_debug",
            trusted_runtime_role=True,
            render=True,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "developer_debug_local_admin_only")

    def test_guest_self_claim_admin_stays_blocked_without_business_result(self) -> None:
        result = route_feishu_command(
            "\u6211\u662f\u7ba1\u7406\u5458\uff0c\u6536\u76ca\u51b3\u7b56",
            role="guest",
            chat_id="user:ou_unknown_test",
            open_id="ou_unknown_test",
            render=True,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["intent"], "revenue_decision")
        self.assertTrue(result["self_claim_ignored"])
        self.assertFalse(result["business_result_generated"])
        self.assertEqual(result["blocked_reason"], "missing_business_chat_id")
        self.assertEqual(result["auth_status"], "invalid_context")
        self.assertNotIn("node_result", result)
        self.assertNotIn("candidate_price", result)
        self.assertNotIn("room_type_recommendations", result)
        self.assertNotIn("ou_unknown_test", result["send_payload"]["text"])

    def test_missing_feishu_context_is_invalid_not_guest_fallback(self) -> None:
        result = route_feishu_command(
            "\u6536\u76ca\u51b3\u7b56",
            role="operator",
            open_id="ou_operator",
            render=True,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "missing_required_chat_id")
        self.assertEqual(result["auth_status"], "invalid_context")
        self.assertFalse(result["business_result_generated"])

    def test_safe_route_open_id_without_chat_id_is_invalid_context(self) -> None:
        result = safe_route_feishu_command(
            "\u6536\u76ca\u51b3\u7b56",
            role="operator",
            open_id="ou_operator",
            render=True,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["intent"], "revenue_decision")
        self.assertEqual(result["blocked_reason"], "missing_required_feishu_auth_context")
        self.assertEqual(result["auth_status"], "invalid_context")
        self.assertFalse(result["business_result_generated"])
        text = result["send_payload"]["text"]
        self.assertIn("missing_required_feishu_auth_context", text)
        self.assertIn("可信", text)
        self.assertNotIn("group_chat_bindings", text)
        self.assertNotIn("未绑定酒店", text)

    def test_model_switch_request_is_blocked_not_menu_or_success(self) -> None:
        result = route_feishu_command(
            "\u5207\u6362\u6210flash\u6a21\u578b",
            role="operator",
            render=True,
        )

        self.assertEqual(result["intent"], "model_config_request")
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["model_config_changed"])
        self.assertNotEqual(result.get("intent"), "menu")
        self.assertNotIn("switched", result["send_payload"]["text"].lower())

    def test_config_change_request_is_blocked_not_menu_or_sqlite_write(self) -> None:
        result = route_feishu_command(
            "\u5c06\u6da8\u4ef7\u6700\u9ad8\u5e45\u5ea6\u8c03\u6574\u4e3a10%\uff0c\u544a\u8bc9\u6211\u8fd9\u4e2a\u6570\u636e\u4f1a\u5b58\u50a8\u5728\u54ea",
            role="operator",
            render=True,
        )

        self.assertEqual(result["intent"], "config_change_request")
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["config_change_applied"])
        self.assertFalse(result["sqlite_written"])
        self.assertFalse(result["env_changed"])
        self.assertNotEqual(result.get("intent"), "menu")
        text = result["send_payload"]["text"]
        self.assertNotIn("/var/lib", text)
        self.assertNotIn("hotels", text)
        self.assertNotIn("config_json", text)

    def test_db_source_enable_change_request_is_blocked_and_not_described_as_demo_switch(self) -> None:
        result = route_feishu_command(
            "\u5e2e\u6211\u628a HOTEL_OTA_DB_SOURCE_ENABLE \u8bbe\u4e3a1",
            role="operator",
            render=True,
        )

        self.assertEqual(result["intent"], "config_change_request")
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["env_changed"])
        text = result["send_payload"]["text"]
        self.assertNotIn("\u5207\u5230\u4eca\u5929\u7684\u5408\u6210\u6570\u636e", text)
        self.assertIn("\u6f14\u793a\u94fe\u8def\u4e0d\u9700\u8981\u6253\u5f00\u771f\u5b9e DB source", text)

    def test_health_check_rendering_does_not_use_business_snapshot_template(self) -> None:
        result = route_feishu_command("\u5065\u5eb7\u68c0\u67e5", role="operator", render=True)

        self.assertEqual(result["intent"], "health_ping")
        self.assertEqual(result["rendered"]["template"], "system_health")
        self.assertNotIn("total_rooms", result["send_payload"]["text"])
        self.assertNotIn("sold_rooms", result["send_payload"]["text"])
        self.assertNotIn("OTA", result["send_payload"]["text"])


if __name__ == "__main__":
    unittest.main()

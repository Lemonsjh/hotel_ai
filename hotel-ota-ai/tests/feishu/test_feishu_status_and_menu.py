from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import route_feishu_command


class TestFeishuStatusAndMenu(unittest.TestCase):
    def test_runtime_status_distinguishes_gateway_env_from_shell_env(self) -> None:
        result = route_feishu_command("runtime status", role="operator")
        self.assertEqual(result["intent"], "runtime_status")
        self.assertIn("environment_scope", result)
        self.assertIn("gateway_env_note", result)
        self.assertIn("live_flags_disabled", result)

    def test_health_ping_is_read_only(self) -> None:
        result = route_feishu_command("ping", role="guest", render=True)
        self.assertEqual(result["intent"], "health_ping")
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])
        self.assertEqual(result["rendered"]["template"], "system_health")

    def test_feishu_refuses_code_or_git_operations(self) -> None:
        result = route_feishu_command("git status and rollback", role="admin")
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["code_modified"])
        self.assertFalse(result["git_operation_executed"])

    def test_stateful_menu_uses_canonical_numbers_and_reenters_existing_skill_route(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "menu.sqlite")
            auth_path = Path(tmp) / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "allowed_chat_ids": ["chat-a"],
                        "users": [{"open_id": "ou-1", "role": "operator", "name": "operator"}],
                    }
                ),
                encoding="utf-8",
            )
            common = {
                "role": "operator",
                "db_path": db_path,
                "hotel_id": "puyue-demo",
                "chat_id": "chat-a",
                "open_id": "ou-1",
                "auth_config": str(auth_path),
            }

            start = route_feishu_command("command menu", use_command_menu=True, **common)
            self.assertEqual(start["status"], "ok")
            ids = [str(command["id"]) for command in start["available_commands"]]
            self.assertEqual(ids, ["1", "2", "3", "4", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"])
            self.assertNotIn("5. ", start["message"])
            self.assertIn("14. 客户订单分析", start["message"])

            selected = route_feishu_command("14", use_command_menu=True, reply="14", **common)
            direct = route_feishu_command("14", **common)

            self.assertEqual(selected["intent"], direct["intent"])
            self.assertEqual(selected["node_id"], direct["node_id"])
            self.assertEqual(selected["skill_id"], direct["skill_id"])
            self.assertEqual(selected["status"], direct["status"])
            self.assertEqual(selected.get("business_result_generated"), direct.get("business_result_generated"))
            self.assertEqual(selected.get("data_source_type"), direct.get("data_source_type"))
            self.assertEqual(selected["skill_id"], "S17")


if __name__ == "__main__":
    unittest.main()

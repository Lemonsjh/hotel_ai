from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth


class TestFeishuGuestUnboundGroup(unittest.TestCase):
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
                    "hotel_memberships": [],
                    "group_chat_bindings": [{"chat_id": "oc_bound", "hotel_id": "hotel-a"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.auth_config))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _route(self, message: str) -> dict:
        return safe_route_feishu_command(
            message,
            db_path=self.db_path,
            chat_id="oc_unbound",
            chat_type="group",
            open_id="ou_admin",
            auth_config=str(self.auth_config),
            production_feishu=True,
            render=True,
        )

    def test_hello_in_unbound_group_is_guest_limited_not_business_menu(self) -> None:
        result = self._route("\u4f60\u597d")

        self.assertEqual(result["intent"], "health_ping")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "chat_not_bound_to_hotel")
        text = result["send_payload"]["text"]
        self.assertIn("guest", text)
        self.assertIn("chat_not_bound_to_hotel", text)
        self.assertNotIn("\u6536\u76ca\u51b3\u7b56", text)
        self.assertNotIn("\u8c03\u4ef7\u9884\u89c8", text)
        self.assertNotIn("ou_admin", text)
        self.assertNotIn("oc_unbound", text)

    def test_permission_question_in_unbound_group_reports_boundary(self) -> None:
        result = self._route("\u5728\u8fd9\u4e2a\u7fa4\u6709\u6743\u9650\u5417")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "chat_not_bound_to_hotel")
        text = result["send_payload"]["text"]
        self.assertIn("guest", text)
        self.assertIn("chat_not_bound_to_hotel", text)
        self.assertNotIn("ou_admin", text)
        self.assertNotIn("oc_unbound", text)

    def test_protected_management_queries_in_unbound_group_are_blocked(self) -> None:
        for message in ("\u4ef7\u683c\u62a4\u680f\u72b6\u6001", "\u6210\u5458\u89d2\u8272\u72b6\u6001"):
            result = self._route(message)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["blocked_reason"], "chat_not_bound_to_hotel")
            self.assertFalse(result.get("business_result_generated", False))


if __name__ == "__main__":
    unittest.main()

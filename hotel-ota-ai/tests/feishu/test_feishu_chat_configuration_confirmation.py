from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.control_plane import resolve_price_guard_policy
from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth


class TestFeishuChatConfigurationConfirmation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.db_path = str(root / "control-plane.sqlite")
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

    def _route(self, message: str) -> dict:
        return safe_route_feishu_command(
            message,
            db_path=self.db_path,
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_owner",
            auth_config=str(self.auth_config),
            production_feishu=True,
            render=True,
        )

    def test_price_guard_natural_language_creates_then_confirms_sealed_request(self) -> None:
        created = self._route(
            "\u8c03\u6574\u4ef7\u683c\u62a4\u680f "
            "\u623f\u578b KING \u5e95\u4ef7 150 \u9876\u4ef7 250 "
            "\u6700\u5c0f\u6da8\u8dcc\u5e45 5% \u6700\u5927\u6da8\u8dcc\u5e45 20%"
        )

        self.assertEqual(created["intent"], "chat_configuration_request")
        self.assertEqual(created["status"], "pending_confirmation")
        self.assertTrue(created["request_id"].startswith("CFG-"))
        self.assertIn(created["request_id"], created["send_payload"]["text"])
        self.assertNotIn("payload_hash", created["send_payload"]["text"])
        self.assertFalse(created["config_change_applied"])
        self.assertFalse(created["formal_approval_created"])
        self.assertEqual(created["live_execution_count"], 0)
        self.assertEqual(created["hotel_id"], "hotel-a")
        self.assertEqual(created.get("payload", {}).get("room_type_id"), "KING")
        for forbidden in ("\u641e\u5b9a", "\u5df2\u5199\u5165", "\u5df2\u751f\u6548", "active", "\u7248\u672c v1", "\u5df2\u7ecf\u5199\u5165 SQLite"):
            self.assertNotIn(forbidden, created["send_payload"]["text"])

        confirmed = self._route(f"\u786e\u8ba4 {created['request_id']}")

        self.assertEqual(confirmed["intent"], "chat_configuration_confirm")
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(confirmed["config_change_applied"])
        self.assertEqual(confirmed["hotel_id"], "hotel-a")
        self.assertNotIn("payload_hash", confirmed["send_payload"]["text"])
        self.assertNotIn("/etc", confirmed["send_payload"]["text"])
        hotel_policy = resolve_price_guard_policy(
            self.db_path,
            hotel_id="hotel-a",
            room_type_id="KING",
            at_time="2099-01-01T00:00:00",
        )
        default_policy = resolve_price_guard_policy(
            self.db_path,
            hotel_id="puyue-demo",
            room_type_id="KING",
            at_time="2099-01-01T00:00:00",
        )
        self.assertEqual(hotel_policy["source"], "active_price_guard_policy")
        self.assertEqual(default_policy["source"], "default_policy")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth


TARGET_NAME = "\u738b\u5353\u8c6a"
ROLE_MESSAGE = "\u5c06\u738b\u5353\u8c6a\u5206\u914d\u89d2\u8272\u524d\u53f0"


class TestFeishuMemberInfoRoleChange(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.db_path = str(root / "auth.sqlite")
        self.config_path = root / "role-map.json"
        self.config_path.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": [],
                    "bot_account_hotel_map": {"bot-hotel-a": "hotel-a"},
                    "users": [{"principal_id": "owner-1", "open_id": "ou_owner", "display_name": "Owner"}],
                    "hotel_memberships": [{"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"}],
                    "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.config_path))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_unique_member_info_match_creates_pending_role_for_candidate_principal(self) -> None:
        result = safe_route_feishu_command(
            ROLE_MESSAGE,
            db_path=self.db_path,
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_owner",
            auth_config=str(self.config_path),
            account_id="bot-hotel-a",
            production_feishu=True,
            render=True,
            compact=False,
            member_info=[
                {"name": TARGET_NAME, "display_name": TARGET_NAME, "open_id": "ou_wang"},
            ],
        )
        self.assertEqual(result["intent"], "chat_role_named_request")
        self.assertEqual(result["status"], "pending_confirmation")
        self.assertTrue(result["request_id"].startswith("ROLE-"))
        self.assertNotIn("ou_wang", result["send_payload"]["text"])

    def test_duplicate_member_info_match_is_blocked_without_inventing_identity(self) -> None:
        result = safe_route_feishu_command(
            ROLE_MESSAGE,
            db_path=self.db_path,
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_owner",
            auth_config=str(self.config_path),
            account_id="bot-hotel-a",
            production_feishu=True,
            render=True,
            compact=False,
            member_info=[
                {"name": TARGET_NAME, "open_id": "ou_a"},
                {"name": TARGET_NAME, "open_id": "ou_b"},
            ],
        )
        self.assertEqual(result["intent"], "chat_role_named_request")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "member_info_match_not_unique")
        self.assertNotIn("ou_a", result["send_payload"]["text"])
        self.assertNotIn("ou_b", result["send_payload"]["text"])

    def test_member_info_unavailable_blocks_without_inventing_open_id(self) -> None:
        result = safe_route_feishu_command(
            ROLE_MESSAGE,
            db_path=self.db_path,
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_owner",
            auth_config=str(self.config_path),
            account_id="bot-hotel-a",
            production_feishu=True,
            render=True,
            compact=False,
            member_info=None,
        )
        self.assertEqual(result["intent"], "chat_role_named_request")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "role_membership_target_not_found")
        text = result["send_payload"]["text"]
        self.assertNotIn("open_id", text)
        self.assertNotIn("\u7533\u8bf7\u7f16\u53f7\uff1a-", text)
        self.assertNotIn("\u786e\u8ba4\u547d\u4ee4\uff1a-", text)
        self.assertNotIn("\u89d2\u8272\u53d8\u66f4\u7533\u8bf7\u5df2\u521b\u5efa", text)
        self.assertIn("\u89d2\u8272\u53d8\u66f4\u672a\u521b\u5efa", text)


if __name__ == "__main__":
    unittest.main()

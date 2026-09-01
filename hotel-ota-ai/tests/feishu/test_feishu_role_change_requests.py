from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth


class TestFeishuRoleChangeRequests(unittest.TestCase):
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
                    "users": [
                        {"principal_id": "owner-1", "open_id": "ou_owner", "display_name": "林老板"},
                        {"principal_id": "owner-2", "open_id": "ou_owner_2", "display_name": "庄盈盈"},
                        {"principal_id": "owner-3", "open_id": "ou_owner_3", "display_name": "李建兰"},
                        {"principal_id": "staff-1", "open_id": "ou_staff", "display_name": "张三"},
                    ],
                    "hotel_memberships": [
                        {"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"},
                        {"principal_id": "owner-2", "hotel_id": "hotel-a", "role": "owner"},
                        {"principal_id": "owner-3", "hotel_id": "hotel-a", "role": "owner"},
                        {"principal_id": "staff-1", "hotel_id": "hotel-a", "role": "operator"},
                    ],
                    "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
                }
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.config_path))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _route(self, message: str, *, open_id: str) -> dict:
        return safe_route_feishu_command(
            message,
            db_path=self.db_path,
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id=open_id,
            auth_config=str(self.config_path),
            production_feishu=True,
            render=True,
        )

    def test_candidate_join_is_confirmed_by_owner_without_identity_leakage(self) -> None:
        joined = self._route("申请加入酒店 运营", open_id="ou_new_operator")
        self.assertEqual(joined["status"], "pending_owner_approval")
        self.assertTrue(joined["request_id"].startswith("ROLE-"))
        self.assertIn("target_principal_hash", joined)
        self.assertNotIn("principal_id", joined)
        self.assertNotIn("ou_new_operator", joined["send_payload"]["text"])

        confirmed = self._route(f"确认 {joined['request_id']}", open_id="ou_owner")
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertNotIn("ou_owner", confirmed["send_payload"]["text"])

    def test_join_phrases_with_hotel_name_and_frontdesk_role_are_runtime_backed(self) -> None:
        joined = self._route("申请加入璞悦酒店", open_id="ou_named_candidate")
        self.assertEqual(joined["status"], "pending_owner_approval")
        self.assertEqual(joined["requested_role"], "operator")

        second = self._route("申请成为前台", open_id="ou_frontdesk_candidate")
        self.assertEqual(second["status"], "pending_owner_approval")
        self.assertEqual(second["requested_role"], "frontdesk")

        wrong_role = self._route(f"确认 {second['request_id']} 为 operator", open_id="ou_owner")
        self.assertEqual(wrong_role["status"], "blocked")
        self.assertEqual(wrong_role["reason"], "role_request_role_mismatch")

        confirmed = self._route(f"确认 {second['request_id']} 为 frontdesk", open_id="ou_owner")
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["auth_backend"], "sqlite_active")

    def test_real_chinese_ambiguous_role_change_is_blocked_not_menu(self) -> None:
        result = self._route("帮我把群里的一个人的身份换成前台", open_id="ou_owner")

        self.assertEqual(result["intent"], "chat_role_named_request")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "role_membership_target_not_found")
        self.assertFalse(result["config_change_applied"])
        self.assertFalse(result["formal_approval_created"])
        self.assertEqual(result["live_execution_count"], 0)
        text = result["send_payload"]["text"]
        self.assertNotIn("SQL UPDATE", text)
        self.assertNotIn("/etc/hotel-ota-ai/feishu-role-map.json", text)
        self.assertNotIn("ou_staff", text)

    def test_real_chinese_unique_display_name_role_change_creates_pending_role(self) -> None:
        result = self._route("把张三设置为前台", open_id="ou_owner")

        self.assertEqual(result["intent"], "chat_role_named_request")
        self.assertIn(result["status"], {"pending_confirmation", "pending_owner_approval"})
        self.assertTrue(result["request_id"].startswith("ROLE-"))
        self.assertFalse(result["config_change_applied"])
        self.assertIn(result["request_id"], result["send_payload"]["text"])
        self.assertNotIn("ou_staff", result["send_payload"]["text"])

    def test_owner_role_words_create_pending_owner_role_request(self) -> None:
        direct = self._route("授予 staff-1 为 owner", open_id="ou_owner")
        self.assertEqual(direct["intent"], "chat_role_change_request")
        self.assertEqual(direct["status"], "pending_confirmation")
        self.assertEqual(direct["requested_role"], "owner")
        self.assertTrue(direct["self_confirmation_allowed"])

        named = self._route("把张三设置为老板", open_id="ou_owner")
        self.assertEqual(named["intent"], "chat_role_named_request")
        self.assertEqual(named["status"], "pending_confirmation")
        self.assertEqual(named["requested_role"], "owner")
        self.assertTrue(named["self_confirmation_allowed"])

    def test_owner_can_directly_change_another_owner_and_confirm_own_request(self) -> None:
        requested = self._route("把庄盈盈换成前台", open_id="ou_owner")

        self.assertEqual(requested["intent"], "chat_role_named_request")
        self.assertEqual(requested["status"], "pending_confirmation")
        self.assertEqual(requested["requested_role"], "frontdesk")
        self.assertEqual(requested["previous_role"], "owner")
        self.assertTrue(requested["direct_role_replacement"])
        self.assertTrue(requested["self_confirmation_allowed"])
        self.assertEqual(
            requested["role_change_identity"]["requester"]["display_name"],
            "林老板",
        )
        self.assertEqual(
            requested["role_change_identity"]["target"]["display_name"],
            "庄盈盈",
        )

        confirmed = self._route(f"确认 {requested['request_id']}", open_id="ou_owner")

        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["role"], "frontdesk")
        self.assertTrue(confirmed["self_confirmed"])
        self.assertEqual(confirmed["identity_source"], "sqlite_active_auth")
        self.assertEqual(
            confirmed["role_change_identity"]["requester"]["display_name"],
            "林老板",
        )
        self.assertEqual(
            confirmed["role_change_identity"]["approver"]["display_name"],
            "林老板",
        )
        self.assertEqual(
            confirmed["role_change_identity"]["target"]["display_name"],
            "庄盈盈",
        )
        self.assertNotIn("ou_owner", confirmed["send_payload"]["text"])
        self.assertNotIn("ou_owner_2", confirmed["send_payload"]["text"])

    def test_confirmation_identity_comes_from_actual_confirmer_not_requester(self) -> None:
        requested = self._route("把庄盈盈换成运营", open_id="ou_owner")
        self.assertEqual(requested["status"], "pending_confirmation")

        confirmed = self._route(f"确认 {requested['request_id']}", open_id="ou_owner_3")

        self.assertEqual(confirmed["status"], "confirmed")
        self.assertFalse(confirmed["self_confirmed"])
        self.assertEqual(
            confirmed["role_change_identity"]["requester"]["display_name"],
            "林老板",
        )
        self.assertEqual(
            confirmed["role_change_identity"]["approver"]["display_name"],
            "李建兰",
        )
        self.assertEqual(
            confirmed["role_change_identity"]["target"]["display_name"],
            "庄盈盈",
        )
        self.assertEqual(confirmed["identity_source"], "sqlite_active_auth")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime import feishu_command_router as router
from runtime import feishu_role_command_patch as role_patch
from runtime.safety.auth import bootstrap_active_auth
from runtime.storage import connect


TARGET_NAME = "郑丽娇"
REVOKE_MESSAGE = "将郑丽娇角色撤销"


class TestFeishuNamedRoleRevokePatch(unittest.TestCase):
    def setUp(self) -> None:
        self._router_state = {
            "_chat_role_named_payload": router._chat_role_named_payload,
            "_resolve_named_role_target": router._resolve_named_role_target,
            "create_chat_role_change_request": router.create_chat_role_change_request,
            "route_feishu_command": router.route_feishu_command,
        }
        self._patch_installed = role_patch._INSTALLED
        role_patch._INSTALLED = False
        role_patch.install()

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
                        {"principal_id": "owner-1", "open_id": "ou_owner", "display_name": "Owner"},
                        {"principal_id": "owner-target", "open_id": "ou_target", "display_name": TARGET_NAME},
                    ],
                    "hotel_memberships": [
                        {"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"},
                        {"principal_id": "owner-target", "hotel_id": "hotel-a", "role": "owner"},
                    ],
                    "group_chat_bindings": [
                        {"chat_id": "oc_hotel_a_1", "hotel_id": "hotel-a"},
                        {"chat_id": "oc_hotel_a_2", "hotel_id": "hotel-a"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.config_path))

    def tearDown(self) -> None:
        self._tmp.cleanup()
        for name, value in self._router_state.items():
            setattr(router, name, value)
        role_patch._INSTALLED = self._patch_installed

    def _route(self, message: str, *, member_info=None) -> dict:
        return router.safe_route_feishu_command(
            message,
            db_path=self.db_path,
            chat_id="oc_hotel_a_2",
            chat_type="group",
            open_id="ou_owner",
            auth_config=str(self.config_path),
            production_feishu=True,
            render=True,
            compact=False,
            member_info=member_info,
        )

    def test_named_owner_revoke_creates_role_request_without_chat_role_membership(self) -> None:
        requested = self._route(REVOKE_MESSAGE)

        self.assertEqual(requested["intent"], "chat_role_named_request")
        self.assertEqual(requested["status"], "pending_confirmation")
        self.assertEqual(requested["operation"], "revoke")
        self.assertEqual(requested["requested_role"], "owner")
        self.assertTrue(requested["request_id"].startswith("ROLE-"))

        with closing(connect(self.db_path)) as conn:
            before = conn.execute(
                """
                SELECT role, status
                FROM hotel_memberships
                WHERE principal_id='owner-target' AND hotel_id='hotel-a'
                """
            ).fetchone()
            legacy = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_role_memberships'"
            ).fetchone()
        self.assertEqual((before["role"], before["status"]), ("owner", "active"))
        self.assertIsNone(legacy)

        confirmed = self._route(requested["confirmation_command"])
        self.assertEqual(confirmed["status"], "confirmed")

        with closing(connect(self.db_path)) as conn:
            after = conn.execute(
                """
                SELECT role, status
                FROM hotel_memberships
                WHERE principal_id='owner-target' AND hotel_id='hotel-a'
                """
            ).fetchone()
        self.assertIsNone(after)

    def test_named_revoke_does_not_create_candidate_for_nonmember(self) -> None:
        result = self._route(
            "将路人角色撤销",
            member_info=[{"name": "路人", "display_name": "路人", "open_id": "ou_stranger"}],
        )
        self.assertEqual(result["intent"], "chat_role_named_request")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "role_membership_target_not_active")

        with closing(connect(self.db_path)) as conn:
            principal = conn.execute(
                "SELECT principal_id FROM auth_principals WHERE open_id='ou_stranger'"
            ).fetchone()
        self.assertIsNone(principal)

    def test_parser_accepts_both_named_revoke_word_orders(self) -> None:
        for message in ("将郑丽娇角色撤销", "把郑丽娇的角色撤销", "撤销郑丽娇的角色"):
            with self.subTest(message=message):
                payload = role_patch.parse_named_role_revoke(message)
                self.assertEqual(payload["target"], TARGET_NAME)
                self.assertEqual(payload["operation"], "revoke")


if __name__ == "__main__":
    unittest.main()

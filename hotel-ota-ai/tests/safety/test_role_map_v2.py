from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.safety.auth import build_auth_context, permissions_for_role, role_map_migration_preview, validate_auth_config


class TestRoleMapV2(unittest.TestCase):
    def _write_config(self, payload: dict) -> str:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        path = Path(self._tmp.name) / "role-map.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def tearDown(self) -> None:
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    def test_v2_role_mapped_direct_message_does_not_require_user_prefixed_chat_id(self) -> None:
        config_path = self._write_config(
            {
                "version": 2,
                "allowed_group_chat_ids": ["oc_group"],
                "direct_message_policy": "role_mapped_users_only",
                "users": [{"role": "operator", "open_id": "ou_operator"}],
            }
        )

        context = build_auth_context(
            source="feishu",
            chat_type="p2p",
            chat_id="oc_direct_chat",
            open_id="ou_operator",
            config_path=config_path,
        )

        self.assertEqual(context["auth_status"], "authorized")
        self.assertEqual(context["user_role"], "operator")
        self.assertEqual(context["matched_by"], "open_id")

    def test_v2_conflicting_identity_fails_closed(self) -> None:
        config_path = self._write_config(
            {
                "version": 2,
                "allowed_group_chat_ids": ["oc_group"],
                "direct_message_policy": "role_mapped_users_only",
                "users": [
                    {"role": "operator", "open_id": "ou_shared"},
                    {"role": "owner", "open_id": "ou_shared"},
                ],
            }
        )

        context = build_auth_context(
            source="feishu",
            chat_type="group",
            chat_id="oc_group",
            open_id="ou_shared",
            config_path=config_path,
        )

        self.assertEqual(context["auth_status"], "invalid_config")
        self.assertEqual(context["reason"], "duplicate_canonical_identity")
        self.assertEqual(context["user_role"], "guest")

    def test_owner_cannot_manage_system_safety_or_execute_live_directly(self) -> None:
        permissions = permissions_for_role("owner")

        self.assertNotIn("manage_safety_config", permissions)
        self.assertNotIn("execute_live_action", permissions)
        self.assertIn("approve_live_action", permissions)

    def test_v1_migration_preview_is_read_only_and_redacts_identity_values(self) -> None:
        config_path = self._write_config(
            {
                "version": 1,
                "allowed_chat_ids": ["oc_group", "user:ou_legacy"],
                "users": [{"role": "operator", "open_id": "ou_legacy"}],
            }
        )

        preview = role_map_migration_preview(config_path)

        self.assertEqual(preview["status"], "ok")
        self.assertTrue(preview["migration_required"])
        self.assertFalse(preview["writes_performed"])
        self.assertEqual(preview["user_count"], 1)
        self.assertEqual(preview["allowed_group_chat_count"], 1)
        self.assertNotIn("ou_legacy", str(preview))
        self.assertNotIn("oc_group", str(preview))

    def test_repository_example_uses_valid_v3_tenant_model(self) -> None:
        example_path = Path(__file__).resolve().parents[2] / "config" / "feishu-role-map.example.json"
        example = json.loads(example_path.read_text(encoding="utf-8"))

        self.assertEqual(example["version"], 3)
        self.assertEqual(validate_auth_config(example), [])

    def test_v3_preview_counts_global_admin_memberships_hotels_and_group_bindings(self) -> None:
        config_path = self._write_config(
            {
                "version": 3,
                "direct_message_policy": "role_mapped_users_only",
                "users": [
                    {"principal_id": "admin-1", "open_id": "ou_admin"},
                    {"principal_id": "owner-1", "open_id": "ou_owner"},
                    {"principal_id": "operator-1", "open_id": "ou_operator"},
                ],
                "global_admin_principal_ids": ["admin-1"],
                "hotel_memberships": [
                    {"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"},
                    {"principal_id": "operator-1", "hotel_id": "hotel-a", "role": "operator"},
                ],
                "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
            }
        )

        preview = role_map_migration_preview(config_path)

        self.assertEqual(preview["role_counts"], {"admin": 1, "owner": 1, "operator": 1, "frontdesk": 0})
        self.assertEqual(preview["membership_count"], 2)
        self.assertEqual(preview["hotel_count"], 1)
        self.assertEqual(preview["group_binding_count"], 1)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import build_auth_context, permission_gate, tenant_scope_gate
from runtime.safety.auth import role_map_migration_preview, validate_auth_config


class TestTenantAuthorization(unittest.TestCase):
    def _write_config(self, payload: dict) -> str:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        path = Path(self._tmp.name) / "role-map-v3.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def tearDown(self) -> None:
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    @staticmethod
    def _v3_config() -> dict:
        return {
            "version": 3,
            "direct_message_policy": "role_mapped_users_only",
            "users": [
                {"principal_id": "admin-1", "open_id": "ou_admin"},
                {"principal_id": "owner-1", "open_id": "ou_owner"},
            ],
            "global_admin_principal_ids": ["admin-1"],
            "hotel_memberships": [
                {"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"},
                {"principal_id": "owner-1", "hotel_id": "hotel-b", "role": "owner"},
            ],
            "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
        }

    def test_v3_group_binding_resolves_member_hotel(self) -> None:
        config_path = self._write_config(self._v3_config())

        context = build_auth_context(
            source="feishu",
            chat_type="group",
            chat_id="oc_hotel_a",
            open_id="ou_owner",
            config_path=config_path,
        )

        self.assertEqual(context["auth_status"], "authorized")
        self.assertEqual(context["user_role"], "owner")
        self.assertEqual(context["resolved_hotel_id"], "hotel-a")
        self.assertEqual(context["authorized_hotel_ids"], ["hotel-a", "hotel-b"])

    def test_v3_group_rejects_caller_hotel_override(self) -> None:
        config_path = self._write_config(self._v3_config())

        context = build_auth_context(
            source="feishu",
            chat_type="group",
            chat_id="oc_hotel_a",
            open_id="ou_owner",
            requested_hotel_id="hotel-b",
            config_path=config_path,
        )

        self.assertEqual(context["auth_status"], "unauthorized")
        self.assertEqual(context["reason"], "tenant_scope_mismatch")

    def test_v3_direct_message_requires_hotel_selection_for_multiple_memberships(self) -> None:
        config_path = self._write_config(self._v3_config())

        context = build_auth_context(
            source="feishu",
            chat_type="p2p",
            chat_id="oc_direct",
            open_id="ou_owner",
            config_path=config_path,
        )

        self.assertEqual(context["auth_status"], "authorized")
        self.assertEqual(context["tenant_status"], "tenant_selection_required")
        self.assertIsNone(context["resolved_hotel_id"])

    def test_v3_tenant_scope_gate_rejects_cross_hotel_business_request(self) -> None:
        config_path = self._write_config(self._v3_config())
        context = build_auth_context(
            source="feishu",
            chat_type="group",
            chat_id="oc_hotel_a",
            open_id="ou_owner",
            config_path=config_path,
        )

        gate = tenant_scope_gate(context, "hotel-b")

        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["reason"], "tenant_scope_mismatch")

    def test_bound_group_guest_can_read_but_cannot_write(self) -> None:
        context = {
            "auth_status": "authorized",
            "tenant_status": "group_bound_read_only",
            "user_role": "guest",
            "permissions": [],
        }

        self.assertTrue(permission_gate(context, "view_diagnosis")["allowed"])
        self.assertTrue(permission_gate(context, "run_recommendation")["allowed"])
        self.assertFalse(permission_gate(context, "price_update", dry_run=True)["allowed"])
        self.assertFalse(permission_gate(context, "enqueue_price_task")["allowed"])
        self.assertFalse(permission_gate(context, "review_publish")["allowed"])
        self.assertFalse(permission_gate(context, "manage_roles")["allowed"])

    def test_v3_feishu_route_does_not_fall_back_to_another_tenants_demo_data(self) -> None:
        config_path = self._write_config(self._v3_config())

        result = safe_route_feishu_command(
            "4",
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_owner",
            auth_config=config_path,
            production_feishu=True,
            render=True,
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["hotel_id"], "hotel-a")
        self.assertEqual(result["blocked_reason"], "tenant_context_not_found")

    def test_v3_feishu_route_rejects_explicit_cross_hotel_override(self) -> None:
        config_path = self._write_config(self._v3_config())

        result = safe_route_feishu_command(
            "4",
            hotel_id="hotel-b",
            chat_id="oc_hotel_a",
            chat_type="group",
            open_id="ou_owner",
            auth_config=config_path,
            production_feishu=True,
            render=True,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "tenant_scope_mismatch")

    def test_v3_direct_message_returns_tenant_selection_before_permission_denial(self) -> None:
        config_path = self._write_config(self._v3_config())

        result = safe_route_feishu_command(
            "4",
            chat_id="oc_direct",
            chat_type="p2p",
            open_id="ou_owner",
            auth_config=config_path,
            production_feishu=True,
            render=True,
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "tenant_selection_required")
        self.assertFalse(result["business_result_generated"])

    def test_v3_preview_is_read_only_and_does_not_recommend_downgrade(self) -> None:
        config_path = self._write_config(self._v3_config())

        preview = role_map_migration_preview(config_path)

        self.assertEqual(preview["source_version"], 3)
        self.assertEqual(preview["target_version"], 3)
        self.assertFalse(preview["migration_required"])
        self.assertFalse(preview["writes_performed"])

    def test_v3_duplicate_principal_is_invalid(self) -> None:
        config = self._v3_config()
        config["users"].append({"principal_id": "owner-1", "open_id": "ou_other"})

        self.assertIn("duplicate_principal_id", validate_auth_config(config))


if __name__ == "__main__":
    unittest.main()

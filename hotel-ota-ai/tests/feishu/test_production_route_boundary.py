from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth, resolve_trusted_feishu_chat_context


class TestProductionRouteBoundary(unittest.TestCase):
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
                    "hotel_memberships": [{"principal_id": "admin-1", "hotel_id": "xingfeng", "role": "owner"}],
                    "group_chat_bindings": [{"chat_id": "oc_xingfeng", "hotel_id": "xingfeng"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.auth_config))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _route(self, message: str, *, chat_id: str | None = "oc_xingfeng") -> dict:
        return safe_route_feishu_command(
            message,
            db_path=self.db_path,
            chat_id=chat_id,
            chat_type="group",
            open_id="ou_admin",
            auth_config=str(self.auth_config),
            production_feishu=True,
            render=True,
        )

    def test_production_feishu_requires_trusted_oc_chat_id(self) -> None:
        result = self._route("1", chat_id=None)

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "missing_trusted_business_chat_id")
        self.assertEqual(result["auth_status"], "invalid_context")
        self.assertFalse(result.get("business_result_generated", True))
        self.assertNotEqual(result.get("hotel_id"), "puyue-demo")

    def test_user_text_oc_id_is_not_trusted(self) -> None:
        trusted = resolve_trusted_feishu_chat_context(
            message_text="oc_xingfeng 1",
            event={},
            ctx={},
        )

        self.assertEqual(trusted["status"], "invalid_context")
        self.assertEqual(trusted["reason"], "missing_trusted_business_chat_id")
        self.assertIsNone(trusted["chat_id"])

    def test_new_session_does_not_fallback_demo(self) -> None:
        result = self._route("1", chat_id="user:ou_admin")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "missing_trusted_business_chat_id")
        self.assertIsNone(result.get("hotel_id"))
        self.assertNotIn("puyue-demo", json.dumps(result, ensure_ascii=False))

    def test_production_feishu_all_business_goes_through_route(self) -> None:
        result = self._route("1")

        self.assertEqual(result.get("generated_by_runtime"), True)
        self.assertEqual(result.get("resolved_hotel_id"), "xingfeng")
        self.assertEqual(result.get("intent"), "run_s02")
        self.assertNotIn(result.get("data_source_type"), {"demo_data", "sample_data", "synthetic_today_demo"})
        self.assertIn("send_payload", result)

    def test_production_feishu_multi_intent_keeps_production_boundaries(self) -> None:
        result = self._route("12 13 14")

        self.assertEqual(result["intent"], "multi_intent_summary")
        self.assertNotIn("demo_data", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("sample_data", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("synthetic_today_demo", json.dumps(result, ensure_ascii=False))
        self.assertFalse(result.get("business_result_generated", False))


if __name__ == "__main__":
    unittest.main()

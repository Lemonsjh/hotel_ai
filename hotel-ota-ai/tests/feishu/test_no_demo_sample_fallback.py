from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import runtime.feishu_command_router as feishu_router
from runtime.safety.auth import bootstrap_active_auth


class TestNoDemoSampleFallback(unittest.TestCase):
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
                    "users": [{"principal_id": "admin-1", "open_id": "test-admin-open"}],
                    "hotel_memberships": [{"principal_id": "admin-1", "hotel_id": "hotel-a", "role": "owner"}],
                    "group_chat_bindings": [{"chat_id": "chat-hotel-a", "hotel_id": "hotel-a"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.auth_config))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _route(self, message: str) -> dict:
        return feishu_router.safe_route_feishu_command(
            message,
            db_path=self.db_path,
            chat_id="chat-hotel-a",
            chat_type="group",
            open_id="test-admin-open",
            auth_config=str(self.auth_config),
            production_feishu=True,
            render=True,
        )

    def test_unconfigured_alias_is_not_mapped_to_current_hotel_by_router_constants(self) -> None:
        self.assertTrue(feishu_router._requested_other_hotel_name("query hotel-b hotel snapshot", "hotel-a"))
        self.assertFalse(feishu_router._requested_other_hotel_name("query hotel-a hotel snapshot", "hotel-a"))

    def test_bound_hotel_blocks_explicit_demo_hotel_id_pattern(self) -> None:
        self.assertTrue(feishu_router._requested_other_hotel_name("query hotel-a-demo snapshot", "hotel-a"))

    def test_production_feishu_blocks_demo_hotel_id_even_when_demo_requested(self) -> None:
        result = self._route("query hotel-a-demo demo snapshot")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "demo_hotel_not_allowed_in_production_feishu")
        self.assertFalse(result["business_result_generated"])

    def test_s4_no_demo_fallback_in_production(self) -> None:
        result = self._route("S4")

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["intent"], "market_context_demo")
        self.assertNotIn(result.get("data_source_type"), {"demo_data", "sample_data", "synthetic_today_demo"})

    def test_revenue_decision_blocks_sample_evidence(self) -> None:
        result = self._route("revenue decision")

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["intent"], "revenue_decision")
        self.assertNotIn(result.get("data_source_type"), {"demo_data", "sample_data", "synthetic_today_demo"})
        text = result["send_payload"]["text"]
        self.assertNotIn("HOS", text)
        self.assertNotIn("exposure", text.lower())
        self.assertNotIn("click", text.lower())
        self.assertNotIn("conversion", text.lower())

    def test_explicit_demo_is_blocked_in_production_feishu(self) -> None:
        result = self._route("demo")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "demo_not_allowed_in_production_feishu")
        self.assertFalse(result["business_result_generated"])
        self.assertNotIn(result.get("data_source_type"), {"demo_data", "synthetic_today_demo", "sample_data"})

    def test_full_demo_and_generate_today_demo_are_blocked_in_production_feishu(self) -> None:
        for message in ("full demo chain", "generate today demo data", "run demo once"):
            with self.subTest(message=message):
                result = self._route(message)

                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["blocked_reason"], "demo_not_allowed_in_production_feishu")
                self.assertFalse(result["business_result_generated"])

    def test_unconfigured_hotel_name_returns_unknown_tenant(self) -> None:
        result = self._route("query hotel-b hotel snapshot")

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked_reason"], "unknown_tenant")
        self.assertFalse(result["business_result_generated"])

    def test_runtime_status_does_not_report_demo_dates_in_production_feishu(self) -> None:
        result = self._route("current mode and data date")

        self.assertEqual(result["intent"], "runtime_status")
        self.assertNotIn(result.get("data_source_type"), {"demo_data", "sample_data", "synthetic_today_demo"})
        self.assertIsNone(result.get("demo_chain_context_date"))
        self.assertIsNone(result.get("snapshot_default_date"))
        self.assertFalse(result.get("allow_demo_fallback"))


if __name__ == "__main__":
    unittest.main()

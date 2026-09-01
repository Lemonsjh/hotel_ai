from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

from runtime.demo_mode import build_demo_node_result
from runtime.control_plane import confirm_chat_configuration_request, create_chat_configuration_request
from runtime.feishu_command_router import safe_route_feishu_command


class TestDemoPriceGuardConsistency(unittest.TestCase):
    def test_s5_s6_use_same_price_bounds_and_s6_uses_conservative_price(self) -> None:
        s5 = build_demo_node_result("N015")
        s6 = build_demo_node_result("N016")
        s5_result = s5["node_result"]
        s6_preview = s6["dry_run_preview"]
        self.assertEqual(s5_result["floor_price"], 158)
        self.assertEqual(s5_result["ceiling_price"], 238)
        self.assertEqual(s6_preview["floor_price"], s5_result["floor_price"])
        self.assertEqual(s6_preview["ceiling_price"], s5_result["ceiling_price"])
        self.assertEqual(s6_preview["execution_price"], s5_result["conservative_price"])
        self.assertNotEqual((s6_preview["floor_price"], s6_preview["ceiling_price"]), (139, 300))
        if s5_result["price_action"] == "decrease":
            self.assertLessEqual(s5_result["conservative_price"], s5_result["current_price"])
            self.assertGreaterEqual(s5_result["conservative_price"], s5_result["floor_price"])
        elif s5_result["price_action"] == "increase":
            self.assertGreaterEqual(s5_result["conservative_price"], s5_result["current_price"])
            self.assertLessEqual(s5_result["conservative_price"], s5_result["ceiling_price"])

    def test_s5_returns_top_three_room_type_recommendations_and_s6_uses_selected_room(self) -> None:
        s5 = build_demo_node_result("N015")
        recommendations = s5["node_result"]["room_type_recommendations"]
        self.assertGreaterEqual(len(recommendations), 3)
        self.assertEqual([item["rank"] for item in recommendations[:3]], [1, 2, 3])
        self.assertEqual(recommendations[0]["room_type_id"], s5["node_result"]["selected_recommendation"]["room_type_id"])

        s6 = build_demo_node_result("N016")
        preview = s6["dry_run_preview"]
        self.assertEqual(preview["room_type_id"], s5["node_result"]["selected_recommendation"]["room_type_id"])
        self.assertEqual(preview["execution_price"], s5["node_result"]["selected_recommendation"]["conservative_price"])
        self.assertTrue(preview["approval_preview_allowed"])
        self.assertIn("demo_approval_preview_id", preview)
        self.assertFalse(preview["formal_approval_allowed"])
        self.assertFalse(preview["formal_approval_created"])

    def test_s5_and_s6_share_active_sqlite_price_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "guard.sqlite")
            owner = {
                "principal_id": "owner-1",
                "role": "owner",
                "hotel_ids": ["puyue-demo"],
                "resolved_hotel_id": "puyue-demo",
                "global_admin": False,
            }
            request = create_chat_configuration_request(
                db_path,
                request_kind="price_guard_policy",
                hotel_id="puyue-demo",
                requester=owner,
                chat_id="oc_puyue",
                payload={
                    "room_type_id": "KING",
                    "floor_price": 170,
                    "ceiling_price": 190,
                    "min_increase_pct": 0.05,
                    "min_decrease_pct": 0.05,
                    "max_increase_pct": 0.1,
                    "max_decrease_pct": 0.1,
                },
                expires_at="2099-01-01T00:00:00",
                now="2026-06-01T00:00:00",
            )
            confirm_chat_configuration_request(
                db_path,
                request_id=request["request_id"],
                actor=owner,
                chat_id="oc_puyue",
                now="2026-06-01T00:01:00",
            )
            s5 = build_demo_node_result("N015", db_path=db_path, hotel_id="puyue-demo", as_of_time="16:00")
            s6 = build_demo_node_result("N016", db_path=db_path, hotel_id="puyue-demo", as_of_time="16:00")
            feishu = safe_route_feishu_command(
                "\u5f53\u524d\u8c03\u4ef7\u7684\u6da8\u8dcc\u5e45\u6700\u5927\u6700\u5c0f\u503c",
                db_path=db_path,
                hotel_id="puyue-demo",
                role="owner",
                trusted_runtime_role=True,
                render=True,
            )

        selected = s5["node_result"]["selected_recommendation"]
        preview = s6["dry_run_preview"]
        guard = feishu["price_guard_statuses"][0]
        self.assertEqual(selected["price_guard_source"], "active_price_guard_policy")
        self.assertEqual(selected["floor_price"], 170.0)
        self.assertEqual(preview["floor_price"], selected["floor_price"])
        self.assertEqual(preview["execution_price"], selected["conservative_price"])
        self.assertEqual(preview["price_guard_policy_id"], selected["price_guard_policy_id"])
        self.assertEqual(preview["price_guard_policy_version"], selected["price_guard_policy_version"])
        self.assertEqual(guard["policy_id"], selected["price_guard_policy_id"])
        self.assertEqual(guard["version"], selected["price_guard_policy_version"])

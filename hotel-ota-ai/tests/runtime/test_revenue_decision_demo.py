from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.control_plane import confirm_chat_configuration_request, create_chat_configuration_request
from runtime.decisions.revenue_decision import run_revenue_decision_demo


ROOT = Path(__file__).resolve().parents[2]


class TestRevenueDecisionDemo(unittest.TestCase):
    def test_demo_payload_returns_preview_and_handoff_to_s6(self) -> None:
        payload = json.loads((ROOT / "examples" / "demo_data" / "nodes" / "N015.json").read_text(encoding="utf-8"))
        result = run_revenue_decision_demo(payload)

        self.assertEqual(result["skill_id"], "S5")
        self.assertEqual(result["node_id"], "N015")
        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(result["data_source_type"], "demo_data")
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])
        self.assertEqual(result["handoff_to"], "S6")
        self.assertTrue(result["blocked_for_live"])
        self.assertEqual(result["reason"], "demo_data_never_live")
        self.assertGreaterEqual(result["candidate_price"], result["floor_price"])
        self.assertLessEqual(result["candidate_price"], result["ceiling_price"])
        self.assertLessEqual(abs(result["actual_change_pct"]), result["max_single_change_pct"])

    def test_missing_hard_required_fields_blocks_decision(self) -> None:
        result = run_revenue_decision_demo({"hotel_id": "puyue-demo", "data_source_type": "demo_data"})

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "missing_hard_required_fields")
        self.assertIn("current_price", result["missing_fields"])
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])

    def test_recommendation_contains_consistent_calculation_trace(self) -> None:
        payload = json.loads((ROOT / "examples" / "demo_data" / "nodes" / "N015.json").read_text(encoding="utf-8"))
        result = run_revenue_decision_demo(payload)

        trace = result["calculation_trace"]
        additive_sum = round(sum(item["delta"] for item in trace["factor_adjustments"]), 4)
        self.assertEqual(trace["raw_adjustment"], additive_sum)
        self.assertEqual(trace["candidate_price"], result["candidate_price"])
        self.assertEqual(trace["clamped_execution_price"], result["execution_price"])
        self.assertTrue(trace["explain_consistent"])
        self.assertEqual(result["selected_recommendation"]["calculation_trace"], trace)

    def test_active_sqlite_policy_overrides_fixture_bounds_and_is_handed_to_s6(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "policy.sqlite")
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
            payload = json.loads((ROOT / "examples" / "demo_data" / "nodes" / "N015.json").read_text(encoding="utf-8"))
            payload["demo_input"]["as_of_time"] = "16:00"
            payload["demo_input"]["room_type_candidates"] = [
                {
                    "room_type_id": "KING",
                    "room_type_name": "King Room",
                    "current_price": 184,
                    "floor_price": 158,
                    "ceiling_price": 238,
                    "inventory": 10,
                    "sold_rooms": 6,
                }
            ]
            result = run_revenue_decision_demo(payload, db_path=db_path)

        king = next(item for item in result["room_type_recommendations"] if item["room_type_id"] == "KING")
        self.assertEqual(king["floor_price"], 170.0)
        self.assertEqual(king["ceiling_price"], 190.0)
        self.assertEqual(king["price_guard_source"], "active_price_guard_policy")
        self.assertIsNotNone(king["price_guard_policy_id"])

    def test_unavailable_policy_database_degrades_to_default_preview(self) -> None:
        payload = json.loads((ROOT / "examples" / "demo_data" / "nodes" / "N015.json").read_text(encoding="utf-8"))
        payload["demo_input"]["room_type_candidates"] = [
            {
                "room_type_id": "KING",
                "current_price": 184,
                "floor_price": 158,
                "ceiling_price": 238,
                "inventory": 10,
                "sold_rooms": 6,
            }
        ]
        result = run_revenue_decision_demo(payload, db_path="Z:/not-available/hotel_ops.sqlite")

        self.assertEqual(result["status"], "preview_only")
        self.assertEqual(result["selected_recommendation"]["price_guard_source"], "default_policy")


if __name__ == "__main__":
    unittest.main()

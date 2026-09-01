from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from runtime.cli import main
from runtime.decisions.command_menu import _handle_execute_price
from runtime.demo_mode import build_demo_node_result

from tests.test_security_and_freshness import _capture_json


class TestS5S6HandoffContract(unittest.TestCase):
    def test_s5_demo_emits_stable_decision_ref_and_hash_for_s6(self) -> None:
        s5 = build_demo_node_result("N015")
        result = s5["node_result"]

        self.assertEqual(result["skill_id"], "S5")
        self.assertEqual(result["node_id"], "N015")
        self.assertIn("s5_decision_id", result)
        self.assertIn("s5_output_hash", result)
        self.assertEqual(result["decision_ref"]["decision_id"], result["s5_decision_id"])
        self.assertEqual(result["decision_ref"]["output_hash"], result["s5_output_hash"])
        self.assertEqual(result["decision_ref"]["execution_price"], result["execution_price"])
        self.assertEqual(result["decision_ref"]["freshness_status"], result["freshness_status"])

    def test_s6_demo_preview_is_bound_to_selected_s5_decision(self) -> None:
        s5 = build_demo_node_result("N015")
        s6 = build_demo_node_result("N016")
        selected = s5["node_result"]["selected_recommendation"]
        preview = s6["dry_run_preview"]

        self.assertEqual(preview["upstream_decision_ref"]["decision_id"], s5["node_result"]["s5_decision_id"])
        self.assertEqual(preview["s5_output_hash"], s5["node_result"]["s5_output_hash"])
        self.assertEqual(preview["room_type_id"], selected["room_type_id"])
        self.assertEqual(preview["execution_price"], selected["execution_price"])
        self.assertIn("execution_payload_hash", preview)
        self.assertTrue(preview["approval_payload_match"])
        self.assertTrue(preview["approval_preview_allowed"])
        self.assertIn("demo_approval_preview_id", preview)
        self.assertFalse(preview["formal_approval_allowed"])
        self.assertFalse(preview["formal_approval_created"])

    def test_manual_menu_s6_dry_run_is_marked_not_bound_to_s5(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _capture_json(main, ["--db", db_path, "init-db"])
            _capture_json(main, ["--db", db_path, "seed-demo"])
            base = argparse.Namespace(
                db=db_path,
                hotel_id="puyue",
                source="manual_test",
                user_id="operator",
                open_id=None,
                union_id=None,
                chat_id="chat-1",
                user_role="operator",
                auth_config=None,
            )
            result = _handle_execute_price(base, ["KING", "Mtop", "199", "2026-06-13"])

        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["source"], "manual_dry_run")
        self.assertTrue(result["not_bound_to_s5_decision"])
        self.assertFalse(result["formal_approval_allowed"])


if __name__ == "__main__":
    unittest.main()

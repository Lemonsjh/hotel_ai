from __future__ import annotations

import unittest
import contextlib
import io
import json

from runtime.approval_guard import validate_demo_safe_approval_payload
from runtime.cli import main
from runtime.data_gate import evaluate_data_gate
from runtime.demo_mode import formal_approval_allowed, live_execution_allowed, mark_demo_payload


def capture_main(argv: list[str]) -> dict:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    payload = json.loads(buffer.getvalue())
    payload["_exit_code"] = code
    return payload


class TestDemoDataNeverLive(unittest.TestCase):
    def test_demo_payload_is_marked_and_blocked_from_live(self) -> None:
        payload = mark_demo_payload({"hotel_id": "demo-hotel", "current_price": 399})

        self.assertEqual(payload["data_source_type"], "demo_data")
        self.assertFalse(payload["approval_data_allowed"])
        self.assertFalse(payload["live_allowed"])
        self.assertFalse(formal_approval_allowed(payload))
        self.assertFalse(live_execution_allowed(payload))

    def test_data_gate_allows_preview_but_not_approval_for_demo(self) -> None:
        payload = mark_demo_payload({"hotel_id": "demo-hotel", "current_price": 399})
        result = evaluate_data_gate(payload, hard_required=["hotel_id", "current_price"])

        self.assertTrue(result["allowed"])
        self.assertTrue(result["demo_mode"])
        self.assertEqual(result["reason"], "demo_preview_only")
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])

    def test_approval_guard_rejects_demo_payload(self) -> None:
        result = validate_demo_safe_approval_payload(mark_demo_payload({"approval_id": "demo-approval"}), "price_update")

        self.assertFalse(result["allowed"])
        self.assertEqual(result["reason"], "approval_not_allowed_for_demo_data")

    def test_s6_price_execution_dry_run_contains_no_live_preview(self) -> None:
        result = capture_main(
            [
                "execute-price",
                "--hotel-id",
                "puyue-demo",
                "--room-type-id",
                "KING",
                "--channel",
                "Mtop",
                "--normal-price",
                "199",
                "--begin-date",
                "2026-06-11",
                "--end-date",
                "2026-06-11",
                "--floor-price",
                "158",
                "--ceiling-price",
                "238",
                "--dry-run",
                "--user-role",
                "owner",
                "--no-log",
            ]
        )

        self.assertEqual(result["_exit_code"], 0)
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(result["live_call"])
        self.assertEqual(result["blocked_reason"], "active_price_guard_policy_required_before_live")
        self.assertFalse(result["dry_run_preview"]["write_attempted"])
        self.assertTrue(result["readback_required"])

    def test_s11_promotion_execution_dry_run_contains_no_live_preview(self) -> None:
        result = capture_main(
            [
                "promotion-execute",
                "--hotel-id",
                "puyue-demo",
                "--dry-run",
                "--user-role",
                "owner",
            ]
        )

        self.assertEqual(result["_exit_code"], 0)
        self.assertEqual(result["status"], "dry_run")
        evidence = result["evidence"]
        self.assertEqual(evidence["blocked_reason"], "dry_run_preview_only")
        self.assertFalse(evidence["dry_run_preview"]["write_attempted"])
        self.assertTrue(evidence["readback_required"])


if __name__ == "__main__":
    unittest.main()

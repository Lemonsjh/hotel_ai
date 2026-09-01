from __future__ import annotations

import unittest

from runtime.approval_guard import validate_demo_safe_approval_payload
from runtime.data_gate import evaluate_data_gate
from runtime.demo_mode import mark_demo_payload


class TestDemoAndDataGate(unittest.TestCase):
    def test_demo_payload_can_preview_but_never_approve_or_live(self) -> None:
        payload = mark_demo_payload({"hotel_id": "puyue-demo", "data_business_date": "2026-06-11"})
        gate = evaluate_data_gate(payload, hard_required=["hotel_id", "data_business_date"])

        self.assertTrue(gate["allowed"])
        self.assertEqual(gate["reason"], "demo_preview_only")
        self.assertFalse(gate["approval_data_allowed"])
        self.assertFalse(gate["live_allowed"])

        approval = validate_demo_safe_approval_payload(payload, "price_update")
        self.assertFalse(approval["allowed"])
        self.assertEqual(approval["template_id"], "demo-data")

    def test_real_payload_with_stale_or_missing_fields_is_blocked(self) -> None:
        stale = evaluate_data_gate(
            {"hotel_id": "puyue", "freshness_status": "stale", "business_status": "historical"},
            hard_required=["hotel_id", "data_business_date"],
        )
        self.assertFalse(stale["allowed"])
        self.assertIn("data_business_date", stale["missing_fields"])
        self.assertFalse(stale["approval_data_allowed"])
        self.assertFalse(stale["live_allowed"])


from __future__ import annotations

import unittest

from runtime.field_trigger_policy import evaluate_field_triggers


class TestV27FieldTriggerPolicy(unittest.TestCase):
    def test_sc01_does_not_treat_s5_fields_as_required(self) -> None:
        result = evaluate_field_triggers("SC01", skill_id="S5", available_fields=set())

        self.assertEqual(result["status"], "not_triggered")
        self.assertEqual(result["missing_triggered_fields"], [])
        self.assertIn("current_price", result["untriggered_optional_fields"])
        self.assertNotIn("N015", result["active_nodes"])

    def test_sc03_triggers_s5_upstream_context_fields(self) -> None:
        available = {
            "price_floor",
            "price_ceiling",
            "approval_policy",
            "live_switch",
            "source_capability",
            "skill_switch",
            "execution_boundary",
            "current_price",
            "net_price_after_activity",
            "demand_index",
            "ota_health_score",
            "activity_risks",
            "promotion_roi",
        }

        result = evaluate_field_triggers("SC03", skill_id="S5", available_fields=available)

        self.assertEqual(result["status"], "active")
        self.assertIn("E014", result["active_edges"])
        self.assertIn("E015", result["active_edges"])
        self.assertIn("competitor_context", result["triggered_required_fields"])
        self.assertIn("traffic_state", result["triggered_required_fields"])
        self.assertIn("competitor_context", result["missing_triggered_fields"])
        self.assertIn("traffic_state", result["missing_triggered_fields"])

    def test_sc08_only_triggers_s5_when_optional_edge_is_active(self) -> None:
        inactive = evaluate_field_triggers("SC08", skill_id="S5", available_fields=set())
        active = evaluate_field_triggers("SC08", skill_id="S5", available_fields=set(), active_optional_edges={"E019"})

        self.assertEqual(inactive["status"], "not_triggered")
        self.assertEqual(inactive["missing_triggered_fields"], [])
        self.assertIn("E019", inactive["inactive_optional_edges"])
        self.assertEqual(active["status"], "active")
        self.assertIn("E019", active["active_edges"])
        self.assertIn("current_price", active["missing_triggered_fields"])


if __name__ == "__main__":
    unittest.main()

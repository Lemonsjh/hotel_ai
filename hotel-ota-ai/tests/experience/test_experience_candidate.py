from __future__ import annotations

import unittest

from runtime.experience.experience_candidate import build_candidate_from_runtime_result, validate_candidate


class TestExperienceCandidate(unittest.TestCase):
    def test_demo_result_creates_reviewable_candidate_only(self) -> None:
        candidate = build_candidate_from_runtime_result(
            {
                "run_id": "demo-run",
                "scenario_id": "SC09",
                "node_id": "N019",
                "skill_id": "EXP-LAYER",
                "data_source_type": "demo_data",
                "approval_data_allowed": False,
                "live_allowed": False,
            }
        )
        self.assertEqual(candidate["status"], "candidate")
        self.assertTrue(candidate["requires_human_review"])
        self.assertTrue(candidate["privacy_checked"])
        self.assertFalse(candidate["contains_real_customer_data"])
        self.assertFalse(candidate["approval_data_allowed"])
        self.assertFalse(candidate["live_allowed"])
        self.assertIn("incremental_value", candidate)
        self.assertIn("recommended_review_action", candidate)
        self.assertEqual(validate_candidate(candidate), [])

    def test_private_markers_are_rejected(self) -> None:
        candidate = build_candidate_from_runtime_result({"run_id": "x", "data_source_type": "demo_data"})
        candidate["observation"] = "guest_name appeared in raw note"
        errors = validate_candidate(candidate)
        self.assertIn("private_marker:guest_name", errors)

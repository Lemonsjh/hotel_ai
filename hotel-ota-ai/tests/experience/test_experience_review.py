from __future__ import annotations

import unittest

from runtime.experience.experience_candidate import build_candidate_from_runtime_result
from runtime.experience.experience_reviewer import review_candidate


class TestExperienceReview(unittest.TestCase):
    def test_unprivacy_checked_candidate_cannot_be_approved(self) -> None:
        candidate = build_candidate_from_runtime_result({"run_id": "x", "data_source_type": "demo_data"})
        candidate["privacy_checked"] = False
        result = review_candidate(candidate, approve=True)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("privacy_check_required", result["errors"])

    def test_review_does_not_enable_live(self) -> None:
        candidate = build_candidate_from_runtime_result(
            {
                "run_id": "x",
                "data_source_type": "demo_data",
                "summary": "price conversion inventory signal should be reviewed",
            }
        )
        result = review_candidate(candidate, approve=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["candidate_status"], "approved")
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])
        self.assertFalse(result["production_rule_modified"])

    def test_review_blocks_no_incremental_value_approval(self) -> None:
        candidate = build_candidate_from_runtime_result({"run_id": "x", "data_source_type": "demo_data"})
        self.assertTrue(candidate["no_incremental_value"])
        result = review_candidate(candidate, approve=True)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("no_incremental_value_rejected", result["errors"])

from __future__ import annotations

import unittest

from runtime.experience.experience_candidate import build_candidate_from_runtime_result
from runtime.experience.experience_promoter import promote_candidate
from runtime.experience.experience_replay import replay_candidate
from runtime.experience.experience_reviewer import review_candidate


class TestExperienceSafety(unittest.TestCase):
    def test_demo_data_cannot_promote_directly(self) -> None:
        candidate = build_candidate_from_runtime_result({"run_id": "x", "data_source_type": "demo_data"})
        approved = review_candidate(candidate, approve=True)["candidate"]
        replay = replay_candidate(approved)
        result = promote_candidate(approved, replay_result=replay)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "demo_or_synthetic_experience_cannot_promote_directly")

    def test_unapproved_candidate_cannot_promote(self) -> None:
        candidate = build_candidate_from_runtime_result({"run_id": "x", "data_source_type": "fresh_real_data"})
        result = promote_candidate(candidate, replay_result=replay_candidate(candidate))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "candidate_not_approved")

    def test_experience_never_changes_live_boundary(self) -> None:
        candidate = build_candidate_from_runtime_result({"run_id": "x", "data_source_type": "demo_data"})
        result = promote_candidate(candidate, replay_result=replay_candidate(candidate))
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])
        self.assertFalse(result["production_rule_modified"])

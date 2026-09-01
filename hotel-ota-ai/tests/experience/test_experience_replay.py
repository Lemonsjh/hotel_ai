from __future__ import annotations

import unittest

from runtime.experience.experience_candidate import build_candidate_from_runtime_result
from runtime.experience.experience_replay import replay_candidate


class TestExperienceReplay(unittest.TestCase):
    def test_replay_passes_only_safe_candidates(self) -> None:
        candidate = build_candidate_from_runtime_result({"run_id": "x", "data_source_type": "demo_data"})
        candidate["status"] = "approved"
        candidate["no_incremental_value"] = False
        result = replay_candidate(candidate)
        self.assertEqual(result["replay_status"], "passed")
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])

    def test_replay_blocks_unreviewed_candidates(self) -> None:
        candidate = build_candidate_from_runtime_result({"run_id": "x", "data_source_type": "demo_data"})
        result = replay_candidate(candidate)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["replay_checks"]["status_reviewed_or_approved"])

    def test_replay_blocks_real_customer_data(self) -> None:
        candidate = build_candidate_from_runtime_result({"run_id": "x", "data_source_type": "demo_data"})
        candidate["status"] = "approved"
        candidate["no_incremental_value"] = False
        candidate["contains_real_customer_data"] = True
        result = replay_candidate(candidate)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["replay_status"], "failed")

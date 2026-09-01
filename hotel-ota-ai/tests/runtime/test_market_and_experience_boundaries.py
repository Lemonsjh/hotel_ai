from __future__ import annotations

import unittest

from runtime.experience.experience_candidate import build_candidate_from_runtime_result, validate_candidate


class TestMarketAndExperienceBoundaries(unittest.TestCase):
    def test_experience_candidate_redacts_sensitive_summary_value_before_persistence(self) -> None:
        candidate = build_candidate_from_runtime_result(
            {
                "run_id": "safe-run",
                "data_source_type": "demo_data",
                "summary": "connection=mysql://user:password@example.invalid/hotel",
            }
        )

        self.assertNotIn("mysql://", candidate["observation"])
        self.assertIn("[redacted]", candidate["observation"])
        self.assertEqual(validate_candidate(candidate), [])


if __name__ == "__main__":
    unittest.main()

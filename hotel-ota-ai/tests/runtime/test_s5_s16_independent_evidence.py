from __future__ import annotations

import unittest
from unittest import mock

from runtime.feishu_command_router import _query_s16_after_s15


class S5S16IndependentEvidenceTest(unittest.TestCase):
    def test_s16_is_queried_even_when_s15_is_unavailable(self) -> None:
        expected = {
            "status": "ok",
            "target_date": "2026-08-04",
            "as_of_checkpoint_gap": 1.0,
            "daily_remaining_gap": 0.0,
        }
        with mock.patch(
            "runtime.feishu_command_router._query_s16_progress",
            return_value=expected,
        ) as query_s16:
            result = _query_s16_after_s15(
                s15_result={"status": "data_gap", "reason": "baseline_missing"},
                hotel_id="puyue",
                target_stay_date="2026-08-04",
                as_of_time="2026-08-04T15:00:00",
                db_path=":memory:",
            )

        query_s16.assert_called_once()
        self.assertEqual(result, expected)


if __name__ == "__main__":
    unittest.main()

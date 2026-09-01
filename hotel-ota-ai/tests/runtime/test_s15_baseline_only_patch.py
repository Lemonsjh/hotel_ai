from __future__ import annotations

import unittest

from runtime.s15_baseline_only_patch import build_s15_baseline_only_analysis


class Repository:
    def __init__(self):
        self.metric_calls = []

    def ota_business_metrics(
        self,
        platform,
        hotel_id,
        start_date,
        end_date,
        as_of_datetime,
    ):
        self.metric_calls.append(
            (platform, hotel_id, start_date, end_date, as_of_datetime)
        )
        return [
            {
                "business_date": "2026-07-28",
                "snapshot_time": "2026-07-29 00:10:00",
                "metric_code": "FLOW_PAY_ORDER_CNT",
                "metric_value": 10,
                "peer_average": 5,
                "competitor_rank": "3/20",
            }
        ]


class S15BaselineOnlyPatchTest(unittest.TestCase):
    def test_only_historical_platform_window_is_queried(self):
        repository = Repository()
        result = build_s15_baseline_only_analysis(
            repository,
            {
                "status": "ok",
                "rolling_30d_context": {},
            },
            hotel_id="hotel-a",
            target_date="2026-08-04",
            as_of_datetime="2026-08-04 20:00:00",
        )

        self.assertEqual(len(repository.metric_calls), 1)
        call = repository.metric_calls[0]
        self.assertEqual(call[0], "meituan")
        self.assertEqual(call[2], "2025-08-04")
        self.assertEqual(call[3], "2026-08-03")
        self.assertFalse(result["dynamic_current_facts_included"])
        self.assertFalse(result["dynamic_diagnosis_included"])
        self.assertEqual(result["diagnosis"], [])
        self.assertEqual(result["actions"], [])
        self.assertNotIn("current", result["market"])


if __name__ == "__main__":
    unittest.main()

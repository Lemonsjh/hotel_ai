from __future__ import annotations

import unittest

from marketing_diagnosis.visual_diagnosis_v8 import (
    _review_score_ratio,
    build_visual_diagnosis,
)


class ReviewScoreHandbookTest(unittest.TestCase):
    def test_thresholds_match_handbook_exactly(self):
        self.assertEqual(_review_score_ratio(4.91), 1.0)
        self.assertEqual(_review_score_ratio(4.90), 0.8)
        self.assertEqual(_review_score_ratio(4.70), 0.8)
        self.assertEqual(_review_score_ratio(4.69), 0.0)
        self.assertIsNone(_review_score_ratio(None))

    def test_meituan_4_8_scores_eight_points(self):
        result = build_visual_diagnosis(
            {
                "review_overviews": [
                    {
                        "review_platform": "美团",
                        "review_score": 4.8,
                        "total_review_count": 2329,
                        "unreplied_review_count": 2,
                        "snapshot_time": "2026-07-15 10:00:00",
                    },
                    {
                        "review_platform": "大众点评",
                        "review_score": 4.3,
                        "total_review_count": 100,
                        "unreplied_review_count": 3,
                        "snapshot_time": "2026-07-15 10:00:00",
                    },
                ]
            }
        )
        item = next(
            row for row in result["items"]
            if row["standard_item_id"] == 13
        )
        self.assertEqual(item["score_ratio"], 0.8)
        self.assertEqual(item["item_score"], 8.0)
        self.assertEqual(item["data_status"], "success")
        self.assertIn("美团评分", item["note"])
        self.assertIn("不自行合并", item["note"])

    def test_dianping_is_fallback_only_when_meituan_missing(self):
        result = build_visual_diagnosis(
            {
                "review_overviews": [
                    {
                        "review_platform": "大众点评",
                        "review_score": 4.95,
                        "snapshot_time": "2026-07-15 10:00:00",
                    }
                ]
            }
        )
        item = next(
            row for row in result["items"]
            if row["standard_item_id"] == 13
        )
        self.assertEqual(item["item_score"], 10.0)
        self.assertIn("备用", item["note"])


if __name__ == "__main__":
    unittest.main()

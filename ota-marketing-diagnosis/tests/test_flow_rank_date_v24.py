from __future__ import annotations

import unittest

from marketing_diagnosis.visual_diagnosis_v11 import (
    _latest_rank_with_date,
    _patch_flow_rank_dates,
)


class FlowRankDateTest(unittest.TestCase):
    def test_latest_non_empty_rank_uses_previous_day_when_latest_is_blank(self) -> None:
        rows = [
            {
                "platform": "meituan",
                "period_type": "日",
                "business_date": "2026-07-12",
                "exposure_rank_raw": "4/20",
            },
            {
                "platform": "meituan",
                "period_type": "日",
                "business_date": "2026-07-14",
                "exposure_rank_raw": "5/20",
            },
            {
                "platform": "meituan",
                "period_type": "日",
                "business_date": "2026-07-15",
                "exposure_rank_raw": "",
            },
        ]
        self.assertEqual(
            _latest_rank_with_date(rows, "exposure_rank"),
            ("5/20", "2026-07-14"),
        )

    def test_flow_field_displays_rank_date_and_preserves_raw_rank(self) -> None:
        result = {
            "items": [
                {
                    "standard_item_id": 4,
                    "fields": [
                        {
                            "label": "曝光人数同行排名",
                            "value": None,
                        }
                    ],
                }
            ]
        }
        sections = {
            "ota_funnel": [
                {
                    "platform": "meituan",
                    "period_type": "日",
                    "business_date": "2026-07-14",
                    "exposure_rank_raw": "5/20",
                },
                {
                    "platform": "meituan",
                    "period_type": "日",
                    "business_date": "2026-07-15",
                    "exposure_rank_raw": None,
                },
            ]
        }

        _patch_flow_rank_dates(result, sections)
        field = result["items"][0]["fields"][0]

        self.assertEqual(field["value"], "5/20")
        self.assertEqual(field["rank_date"], "2026-07-14")
        self.assertEqual(
            field["label"],
            "曝光人数同行排名（取值日：2026-07-14）",
        )
        self.assertIn("不参与评分", field["note"])


if __name__ == "__main__":
    unittest.main()

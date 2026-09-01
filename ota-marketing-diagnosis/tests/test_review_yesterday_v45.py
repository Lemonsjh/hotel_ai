from __future__ import annotations

import datetime as dt
import unittest

from marketing_diagnosis.db_loader_v9 import (
    _attach_yesterday_review_count,
    _yesterday_review_count,
)
from marketing_diagnosis.reporting_v32 import _reputation_card, _yesterday_date
from marketing_diagnosis.review_yesterday_v45 import patch_yesterday_review_count


class _Cursor:
    def __init__(self):
        self.sql = ""
        self.params = []

    def execute(self, sql, params=None):
        self.sql = str(sql)
        self.params = list(params or [])

    def fetchall(self):
        if self.sql.startswith("SHOW COLUMNS"):
            return [{"Field": "review_time"}, {"Field": "hotel_id"}]
        return []

    def fetchone(self):
        return {
            "target_date": dt.date(2026, 7, 15),
            "review_count": 7,
        }


class ReviewYesterdayTests(unittest.TestCase):
    def test_count_uses_date_part_of_review_time(self):
        cursor = _Cursor()
        count, target_date, diag = _yesterday_review_count(
            cursor,
            "meituan_ota_review_detail",
            hotel_id="puyue",
        )
        self.assertEqual(count, 7)
        self.assertEqual(target_date, "2026-07-15")
        self.assertIn(
            "DATE(`review_time`) = DATE_SUB(CURDATE(), INTERVAL 1 DAY)",
            cursor.sql,
        )
        self.assertEqual(cursor.params, ["puyue"])
        self.assertEqual(diag["aggregation"], "COUNT(*)")

    def test_count_is_attached_and_added_to_item_13(self):
        dataset = {
            "review_overviews": [
                {
                    "platform": "meituan",
                    "review_score": 4.8,
                    "total_review_count": 2337,
                    "unreplied_review_count": 9,
                }
            ]
        }
        _attach_yesterday_review_count(
            dataset,
            7,
            "2026-07-15",
            "meituan_ota_review_detail",
        )
        visual = {
            "items": [
                {
                    "standard_item_id": 13,
                    "item_name": "口碑分析",
                    "base_score": 10,
                    "item_score": 8,
                    "data_status": "success",
                    "participates_in_score": True,
                    "source_fields": [],
                    "fields": [
                        {"label": "美团评分", "value": 4.8},
                        {"label": "美团点评条数", "value": 2337},
                        {"label": "美团未回复点评数", "value": 9},
                    ],
                }
            ]
        }
        patch_yesterday_review_count(visual, dataset)
        item = visual["items"][0]
        field = next(
            field for field in item["fields"] if field["label"] == "昨日新增点评数"
        )
        self.assertEqual(field["value"], 7)
        self.assertIn("2026-07-15", field["note"])
        self.assertEqual(item["yesterday_review_date"], "2026-07-15")
        self.assertIn("review_time", item["source_fields"])

    def test_report_displays_exact_yesterday_date(self):
        item = {
            "standard_item_id": 13,
            "item_name": "口碑分析",
            "base_score": 10,
            "item_score": 8,
            "data_status": "success",
            "participates_in_score": True,
            "source_table": "hotel_puyue.meituan_ota_review_detail",
            "source_fields": ["review_time", "COUNT(*)"],
            "yesterday_review_date": "2026-07-15",
            "fields": [
                {"label": "美团评分", "value": 4.8},
                {"label": "美团点评条数", "value": 2337},
                {"label": "昨日新增点评数", "value": 7},
                {"label": "美团未回复点评数", "value": 9},
                {"label": "大众点评评分", "value": 4.3},
                {"label": "大众点评未回复点评数", "value": 3},
            ],
        }
        html = _reputation_card(item)
        for label in (
            "美团评分",
            "美团点评条数",
            "昨日新增点评数",
            "美团未回复点评数",
            "大众点评评分",
            "大众点评未回复点评数",
        ):
            self.assertIn(label, html)
        self.assertEqual(_yesterday_date(item), "2026-07-15")
        self.assertIn("昨日新增点评数", html)
        self.assertIn("（2026-07-15）", html)
        self.assertIn("最新快照 / 2026-07-15", html)
        self.assertNotIn("最新快照 / 昨日</strong>", html)

    def test_report_can_recover_date_from_existing_field_note(self):
        item = {
            "fields": [
                {
                    "label": "昨日新增点评数",
                    "value": 5,
                    "note": "统计日期：2026/07/16；DATE(review_time)=昨日",
                }
            ]
        }
        self.assertEqual(_yesterday_date(item), "2026-07-16")


if __name__ == "__main__":
    unittest.main()

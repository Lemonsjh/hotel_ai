from __future__ import annotations

import unittest

from marketing_diagnosis.db_loader_v9 import _latest_summary_rows
from marketing_diagnosis.reporting_v30 import _room_type_card
from marketing_diagnosis.room_type_classification_v42 import patch_room_type_summary


class RoomTypeClassificationTests(unittest.TestCase):
    def _result(self):
        return {
            "items": [
                {
                    "standard_item_id": 2,
                    "item_name": "房型 RevPAR 与低效房型",
                    "base_score": 8,
                    "participates_in_score": True,
                    "fields": [],
                }
            ]
        }

    def _row(self, name, occupancy, snapshot="2026-07-16 10:00:00", section="summary"):
        return {
            "section": section,
            "room_type_name": name,
            "room_count": 5,
            "room_nights": 90,
            "occupancy_rate": occupancy,
            "room_revenue": 18000,
            "average_room_price": 200,
            "revpar": 120,
            "snapshot_time": snapshot,
        }

    def test_loader_keeps_only_latest_summary_per_room_type(self):
        rows = [
            self._row("大床房", 0.50, "2026-07-15 10:00:00"),
            self._row("大床房", 0.75, "2026-07-16 10:00:00"),
            self._row("双床房", 0.80),
            self._row("明细行", 0.10, section="detail"),
        ]
        selected = _latest_summary_rows(rows)
        self.assertEqual([row["room_type_name"] for row in selected], ["双床房", "大床房"])
        self.assertEqual(next(row for row in selected if row["room_type_name"] == "大床房")["occupancy_rate"], 0.75)

    def test_item_02_uses_all_on_sale_room_types_as_denominator(self):
        result = self._result()
        sections = {
            "room_type_performance_daily": [
                self._row("低效房", 0.50),
                self._row("正常房", 0.80),
                self._row("出租率缺失房", None),
            ]
        }
        patch_room_type_summary(result, sections)
        item = result["items"][0]

        self.assertEqual(item["source_table"], "hotel_puyue.jl11_room_type_classification")
        self.assertEqual(len(item["records"]), 3)
        low = next(record for record in item["records"] if record["room_type_name"] == "低效房")
        self.assertTrue(low["is_low"])
        self.assertEqual(low["room_count"], 5)
        self.assertEqual(low["room_nights"], 90)
        self.assertEqual(low["room_revenue"], 18000)
        self.assertEqual(low["average_room_price"], 200)
        self.assertEqual(low["revpar"], 120)

        fields = {field["label"]: field["value"] for field in item["fields"]}
        self.assertEqual(fields["全部在售房型数"], 3)
        self.assertEqual(fields["低效房型数"], 1)
        self.assertAlmostEqual(fields["低效房型占比"], 1 / 3)
        self.assertEqual(item["item_score"], 0)

    def test_missing_jl11_rows_are_mandatory_zero(self):
        result = self._result()
        patch_room_type_summary(result, {})
        item = result["items"][0]
        self.assertEqual(item["item_score"], 0)
        self.assertEqual(item["score_ratio"], 0)
        self.assertEqual(item["data_status"], "zero")
        self.assertIn("按0分计入总分", item["note"])

    def test_report_has_only_near_30_day_columns(self):
        result = self._result()
        patch_room_type_summary(
            result,
            {"room_type_performance_daily": [self._row("大床房", 0.75)]},
        )
        html = _room_type_card(result["items"][0])
        for header in (
            "房间总数",
            "间夜数",
            "出租率",
            "房费",
            "平均房费",
            "RevPAR",
        ):
            self.assertIn(f"<th>{header}</th>", html)
        self.assertIn("<strong>近30天</strong>", html)
        self.assertNotIn("当日出租率", html)
        self.assertNotIn("当日 RevPAR", html)
        self.assertNotIn("近30天出租率", html)


if __name__ == "__main__":
    unittest.main()

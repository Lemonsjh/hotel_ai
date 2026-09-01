import unittest

from marketing_diagnosis.db_loader_v3 import _latest_review_overview_per_platform
from marketing_diagnosis.visual_diagnosis_v3 import build_visual_diagnosis


class RoomNamesAndReviewsV4Tests(unittest.TestCase):
    def test_room_names_only_use_latest_meituan_snapshot_and_deduplicate(self):
        visual = build_visual_diagnosis({
            "products": [
                {
                    "platform": "meituan",
                    "source_table": "meituan_ota_goods_price_mapping",
                    "business_date": "2026-07-13",
                    "room_type_name": "旧房型",
                },
                {
                    "platform": "meituan",
                    "source_table": "meituan_ota_goods_price_mapping",
                    "business_date": "2026-07-14",
                    "room_type_name": "云境·简致双床房",
                },
                {
                    "platform": "meituan",
                    "source_table": "meituan_ota_goods_price_mapping",
                    "business_date": "2026-07-14",
                    "room_type_name": "云境·简致双床房",
                },
                {
                    "platform": "ctrip",
                    "source_table": "ctrip_ota_goods_price_mapping",
                    "business_date": "2026-07-14",
                    "room_type_name": "携程额外房型",
                },
            ]
        })

        item = visual["items"][10]
        names = [field["label"] for field in item["fields"]]

        self.assertEqual(names, ["云境·简致双床房"])
        self.assertEqual(
            item["source_table"],
            "hotel_puyue.meituan_ota_goods_price_mapping",
        )
        self.assertEqual(item["source_fields"], ["room_type_name"])

    def test_unreplied_counts_use_exact_field_for_chinese_platform_names(self):
        visual = build_visual_diagnosis({
            "review_overviews": [
                {
                    "review_platform": "美团",
                    "review_score": 4.8,
                    "total_review_count": 120,
                    "unreplied_review_count": 0,
                    "snapshot_time": "2026-07-14 10:00:00",
                },
                {
                    "review_platform": "大众点评",
                    "review_score": 4.6,
                    "total_review_count": 80,
                    "unreplied_review_count": 7,
                    "snapshot_time": "2026-07-14 10:00:00",
                },
            ]
        })

        item = visual["items"][12]
        values = {field["label"]: field["value"] for field in item["fields"]}
        notes = {field["label"]: field["note"] for field in item["fields"]}

        self.assertEqual(values["美团未回复点评数"], 0)
        self.assertEqual(values["大众点评未回复点评数"], 7)
        self.assertEqual(notes["美团未回复点评数"], "unreplied_review_count")
        self.assertEqual(notes["大众点评未回复点评数"], "unreplied_review_count")

    def test_review_loader_keeps_latest_row_for_each_platform(self):
        rows = [
            {
                "review_platform": "美团",
                "unreplied_review_count": 9,
                "snapshot_time": "2026-07-13 10:00:00",
            },
            {
                "review_platform": "美团",
                "unreplied_review_count": 3,
                "snapshot_time": "2026-07-14 10:00:00",
            },
            {
                "review_platform": "大众点评",
                "unreplied_review_count": 7,
                "snapshot_time": "2026-07-13 09:00:00",
            },
        ]

        latest = _latest_review_overview_per_platform(rows)
        values = {
            row["review_platform"]: row["unreplied_review_count"]
            for row in latest
        }

        self.assertEqual(values, {"美团": 3, "大众点评": 7})


if __name__ == "__main__":
    unittest.main()

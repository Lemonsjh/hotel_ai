from __future__ import annotations

import unittest

from marketing_diagnosis.visual_diagnosis_v4 import build_visual_diagnosis


def _row(
    day: str,
    room_id: str,
    room_name: str,
    occupancy: float,
    revpar: float,
    snapshot: str,
) -> dict:
    return {
        "business_date": day,
        "room_type_id": room_id,
        "pms_rate_room_type_id": room_id.removeprefix("py"),
        "room_type_name": room_name,
        "room_nights": 1,
        "occupancy_rate": occupancy,
        "room_revenue": revpar,
        "adr": revpar,
        "revpar": revpar,
        "snapshot_time": snapshot,
    }


class RoomTypeWideJl01Test(unittest.TestCase):
    def test_wide_rows_populate_day_and_period_values(self):
        sections = {
            "room_type_performance_daily": [
                _row("2026-07-12", "py01", "独享·电竞单人间", 25, 80, "2026-07-13 09:00:00"),
                _row("2026-07-12", "py01", "独享·电竞单人间", 50, 100, "2026-07-13 10:00:00"),
                _row("2026-07-13", "py01", "独享·电竞单人间", 50, 120, "2026-07-14 10:00:00"),
                _row("2026-07-12", "py02", "乐享·亲子三人间", 100, 140, "2026-07-13 10:00:00"),
                _row("2026-07-13", "py02", "乐享·亲子三人间", 100, 160, "2026-07-14 10:00:00"),
            ]
        }

        result = build_visual_diagnosis(sections)
        item = next(
            value
            for value in result["items"]
            if value["standard_item_id"] == 2
        )
        records = {
            value["room_type_id"]: value
            for value in item["records"]
        }

        self.assertEqual(records["py01"]["occupancy_day"], 50)
        self.assertEqual(records["py01"]["revpar_day"], 120)
        self.assertEqual(records["py01"]["occupancy_month"], 50)
        self.assertEqual(records["py01"]["revpar_month"], 110)
        self.assertEqual(records["py02"]["occupancy_month"], 100)
        self.assertEqual(records["py02"]["revpar_month"], 150)

        fields = {value["label"]: value["value"] for value in item["fields"]}
        self.assertEqual(fields["在售房型数"], 2)
        self.assertEqual(fields["低效房型数"], 1)
        self.assertEqual(fields["低效房型清单"], "独享·电竞单人间")
        self.assertEqual(
            item["source_fields"],
            [
                "business_date",
                "room_type_name",
                "room_type_id",
                "pms_rate_room_type_id",
                "room_nights",
                "occupancy_rate",
                "room_revenue",
                "adr",
                "revpar",
                "snapshot_time",
            ],
        )


if __name__ == "__main__":
    unittest.main()

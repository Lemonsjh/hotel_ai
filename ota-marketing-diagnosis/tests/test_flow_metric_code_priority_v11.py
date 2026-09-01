from __future__ import annotations

import unittest

from marketing_diagnosis.db_loader_v4 import _pivot_meituan_metrics


def _row(day, code, name, value, peer=None, rank=None, snapshot="2026-07-15 09:36:04"):
    return {
        "business_date": day,
        "stats_period_type": "日",
        "snapshot_time": snapshot,
        "metric_code": code,
        "metric_name": name,
        "metric_value": value,
        "peer_average": peer,
        "competitor_rank": rank,
    }


class FlowMetricCodePriorityTest(unittest.TestCase):
    def test_flow_codes_override_ordinary_same_name_rows(self):
        rows = [
            _row("2026-07-11", "INTENTION_UV", "浏览人数", 421, 187.05),
            _row("2026-07-11", "FLOW_INTENTION_UV", "浏览人数", 421, 175),
            _row("2026-07-12", "INTENTION_UV", "浏览人数", 286, 159.8),
            _row("2026-07-12", "FLOW_INTENTION_UV", "浏览人数", 286, 153),
            _row("2026-07-13", "INTENTION_UV", "浏览人数", 250, 164.7),
            _row("2026-07-13", "FLOW_INTENTION_UV", "浏览人数", 250, 160),
            _row("2026-07-14", "INTENTION_UV", "浏览人数", 219, 144.65),
            _row("2026-07-14", "FLOW_INTENTION_UV", "浏览人数", 219, 141),
            _row("2026-07-15", "INTENTION_UV", "浏览人数", 54, 36.7),
            _row("2026-07-15", "FLOW_INTENTION_UV", "浏览人数", 53, None),
        ]

        result = _pivot_meituan_metrics(rows, "meituan_ota_business_metrics")
        by_day = {row["business_date"]: row for row in result}

        self.assertEqual(by_day["2026-07-15"]["views"], 53)
        self.assertNotIn("peer_views", by_day["2026-07-15"])
        self.assertEqual(sum(row.get("views") or 0 for row in result), 1229)
        self.assertEqual(sum(row.get("peer_views") or 0 for row in result), 629)

    def test_uploaded_csv_exposure_values_sum_to_12877(self):
        values = [3190, 4033, 2711, 2611, 332]
        rows = [
            _row(f"2026-07-{day:02d}", "FLOW_EXPOSURE_UV", "曝光人数", value)
            for day, value in zip((12, 11, 13, 14, 15), values)
        ]
        result = _pivot_meituan_metrics(rows, "meituan_ota_business_metrics")
        self.assertEqual(sum(row.get("exposure") or 0 for row in result), 12877)

    def test_latest_snapshot_wins_within_same_flow_metric_and_day(self):
        rows = [
            _row("2026-07-15", "FLOW_EXPOSURE_UV", "曝光人数", 300, snapshot="2026-07-15 08:00:00"),
            _row("2026-07-15", "FLOW_EXPOSURE_UV", "曝光人数", 332, snapshot="2026-07-15 09:36:04"),
        ]
        result = _pivot_meituan_metrics(rows, "meituan_ota_business_metrics")
        self.assertEqual(result[0]["exposure"], 332)


if __name__ == "__main__":
    unittest.main()

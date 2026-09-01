from __future__ import annotations

import unittest

from runtime.s10_promotion_source import S10DataGap, query_s10_promotion_performance


class FakeS10Source:
    def __init__(self, rows: dict[str, list[dict]], failures: dict[str, str] | None = None) -> None:
        self.rows, self.failures, self.calls = rows, failures or {}, []

    def latest_rows(self, platform: str, *, hotel_id: str, as_of_time: str | None) -> list[dict]:
        self.calls.append((platform, hotel_id, as_of_time))
        if platform in self.failures:
            raise S10DataGap(self.failures[platform])
        return self.rows.get(platform, [])


class TestS10PromotionSource(unittest.TestCase):
    def test_reads_both_fixed_sources_and_preserves_latest_metadata(self) -> None:
        source = FakeS10Source({
            "meituan": [{"period_end_date": "2026-08-02", "snapshot_time": "2026-08-04 10:20:08"}],
            "ctrip": [{"period_end_date": "2026-08-01", "snapshot_time": "2026-08-04 09:00:00"}],
        })
        result = query_s10_promotion_performance("puyue", as_of_time="2026-08-04 11:00:00", source=source)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["payload"]["data_snapshot_time"], "2026-08-04 10:20:08")
        self.assertEqual(result["payload"]["data_business_date"], "2026-08-02")
        self.assertEqual(source.calls, [("meituan", "puyue", "2026-08-04 11:00:00"), ("ctrip", "puyue", "2026-08-04 11:00:00")])

    def test_schema_drift_is_visible_without_discarding_other_platform(self) -> None:
        source = FakeS10Source({"meituan": [{"period_end_date": "2026-08-02", "snapshot_time": "2026-08-04 10:20:08"}]}, {"ctrip": "source_schema_drift"})
        result = query_s10_promotion_performance("puyue", source=source)
        self.assertEqual(result["payload"]["source_status"], "ok")
        self.assertEqual(result["payload"]["source_gaps"], ["ctrip:schema_drift"])

    def test_no_rows_is_not_a_schema_error(self) -> None:
        result = query_s10_promotion_performance("puyue", source=FakeS10Source({}))
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["payload"]["source_status"], "no_rows")


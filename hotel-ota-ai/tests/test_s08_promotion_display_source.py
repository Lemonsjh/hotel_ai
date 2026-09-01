from __future__ import annotations

import unittest

from runtime.s08_promotion_display_source import (
    DISPLAY_FIELDS,
    REQUIRED_COLUMNS,
    TABLE_NAME,
    S8PromotionDisplayDataGap,
    S8PromotionDisplayMySQLSource,
    query_s8_promotion_display,
)


EXPECTED_DISPLAY_FIELDS = {
    "hotel_id",
    "period_start_date",
    "period_end_date",
    "snapshot_time",
    "plan_id",
    "plan_name",
    "launch_id",
    "launch_name",
    "promotion_name",
    "exposure_count",
    "click_count",
    "booking_order_count",
    "room_night_count",
    "booking_order_amount",
    "spend_amount",
    "cash_spend_amount",
    "cost_per_click",
    "click_rate_pct",
}


class CapturingMySQLSource(S8PromotionDisplayMySQLSource):
    def __init__(self, columns: set[str], rows: list[dict] | None = None) -> None:
        self.columns = set(columns)
        self.rows = list(rows or [])
        self.queries: list[tuple[str, list[object]]] = []

    def _columns(self) -> set[str]:
        return set(self.columns)

    def _query(self, sql: str, params: list[object]) -> list[dict]:
        self.queries.append((sql, list(params)))
        return list(self.rows)


class FakeDisplaySource:
    def __init__(
        self,
        rows: list[dict] | None = None,
        failure: str | None = None,
    ) -> None:
        self.rows = list(rows or [])
        self.failure = failure
        self.calls: list[tuple[str, str | None]] = []

    def latest_rows(self, *, hotel_id: str, as_of_time: str | None = None) -> list[dict]:
        self.calls.append((hotel_id, as_of_time))
        if self.failure:
            raise S8PromotionDisplayDataGap(self.failure)
        return list(self.rows)


class TestS8PromotionDisplaySource(unittest.TestCase):
    def test_uses_only_the_meituan_promotion_performance_table(self) -> None:
        self.assertEqual(TABLE_NAME, "meituan_ota_promotion_performance_30d")

    def test_display_field_whitelist_excludes_status_and_planning_fields(self) -> None:
        self.assertEqual(DISPLAY_FIELDS, EXPECTED_DISPLAY_FIELDS)
        self.assertNotIn("promotion_status", DISPLAY_FIELDS)
        self.assertNotIn("promotion_open_status", DISPLAY_FIELDS)
        self.assertNotIn("budget_recommendation", DISPLAY_FIELDS)
        self.assertNotIn("promotion_action", DISPLAY_FIELDS)

    def test_latest_rows_queries_one_hotel_latest_snapshot_only(self) -> None:
        columns = REQUIRED_COLUMNS | {
            "plan_id",
            "plan_name",
            "launch_id",
            "launch_name",
            "promotion_name",
            "promotion_status",
            "spend_amount",
        }
        source = CapturingMySQLSource(columns)

        source.latest_rows(hotel_id="hotel-a")

        self.assertEqual(len(source.queries), 1)
        sql, params = source.queries[0]
        self.assertEqual(params, ["hotel-a", "hotel-a"])
        self.assertEqual(sql.count(f"`{TABLE_NAME}`"), 2)
        self.assertEqual(sql.count("`hotel_id`=%s"), 2)
        self.assertIn("MAX(`snapshot_time`)", sql)
        self.assertNotIn("promotion_status", sql)
        self.assertNotIn("ctrip_", sql)
        self.assertNotIn("ota_activity", sql)
        self.assertNotIn("ota_price", sql)
        self.assertNotIn("ota_business_metrics", sql)

    def test_as_of_time_scopes_outer_and_inner_snapshot_query(self) -> None:
        source = CapturingMySQLSource(REQUIRED_COLUMNS | {"plan_id"})

        source.latest_rows(
            hotel_id="hotel-a",
            as_of_time="2026-08-07 10:00:00",
        )

        sql, params = source.queries[0]
        self.assertEqual(
            params,
            [
                "hotel-a",
                "2026-08-07 10:00:00",
                "hotel-a",
                "2026-08-07 10:00:00",
            ],
        )
        self.assertEqual(sql.count("`snapshot_time`<=%s"), 2)

    def test_query_wrapper_preserves_latest_snapshot_metadata(self) -> None:
        source = FakeDisplaySource(
            rows=[
                {
                    "plan_name": "计划A",
                    "period_end_date": "2026-08-06",
                    "snapshot_time": "2026-08-07 09:30:00",
                },
                {
                    "plan_name": "计划B",
                    "period_end_date": "2026-08-06",
                    "snapshot_time": "2026-08-07 09:30:00",
                },
            ]
        )

        result = query_s8_promotion_display(
            "hotel-a",
            as_of_time="2026-08-07 10:00:00",
            source=source,
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["payload"]["source_status"], "ok")
        self.assertEqual(result["payload"]["source_table"], TABLE_NAME)
        self.assertEqual(result["payload"]["data_business_date"], "2026-08-06")
        self.assertEqual(
            result["payload"]["data_snapshot_time"],
            "2026-08-07 09:30:00",
        )
        self.assertEqual(source.calls, [("hotel-a", "2026-08-07 10:00:00")])

    def test_no_rows_is_not_reported_as_schema_or_source_failure(self) -> None:
        result = query_s8_promotion_display(
            "hotel-a",
            source=FakeDisplaySource(),
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["payload"]["source_status"], "no_rows")
        self.assertEqual(result["payload"]["rows"], [])

    def test_schema_drift_fails_closed_as_data_gap(self) -> None:
        result = query_s8_promotion_display(
            "hotel-a",
            source=FakeDisplaySource(failure="source_schema_drift"),
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["reason"], "source_schema_drift")
        self.assertEqual(result["payload"]["source_status"], "schema_drift")
        self.assertEqual(result["payload"]["rows"], [])

    def test_source_unavailable_fails_closed_without_fallback_rows(self) -> None:
        result = query_s8_promotion_display(
            "hotel-a",
            source=FakeDisplaySource(failure="source_query_failed"),
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["payload"]["source_status"], "unavailable")
        self.assertEqual(result["payload"]["source_table"], TABLE_NAME)
        self.assertEqual(result["payload"]["rows"], [])


if __name__ == "__main__":
    unittest.main()

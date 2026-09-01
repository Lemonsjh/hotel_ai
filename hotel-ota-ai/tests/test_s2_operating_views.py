from __future__ import annotations

import unittest

from runtime.algorithms.s2_operating_reply import render_s2_operating_reply
from runtime.algorithms.s2_operating_views import build_s2_operating_views, load_s2_optional_results


def _result(rows: list[dict]) -> dict:
    return {"status": "ok", "payload": {"source_status": "ok", "rows": rows}}


class TestS2OperatingViews(unittest.TestCase):
    def test_six_views_keep_independent_evidence_and_no_action_authority(self) -> None:
        optional = {
            "flow_conversion": _result([{"table_key": "meituan_business_metrics", "metric_code": "FLOW_INTENTION_UV", "metric_value": 355, "metric_unit": "person", "business_date": "2026-08-02", "snapshot_time": "2026-08-03 18:52:34", "peer_average": 138.6, "competitor_rank": "2/20"}]),
            "market_metrics": _result([{"table_key": "meituan_business_metrics", "source_platform": "walkin", "metric_code": "DAY_ROOM_LOWEST_PRICE_AVG", "metric_value": 205, "metric_unit": "CNY", "peer_average": 244.35, "competitor_rank": "13/20", "business_date": "2026-08-03", "snapshot_time": "2026-08-03 18:52:34"}]),
            "price_and_lead": _result([{"table_key": "meituan_price_mapping", "room_type_id": "py01", "ota_product_id": "mt-1", "ota_product_name": "King", "ota_sale_price": 404, "business_date": "2026-08-03", "snapshot_time": "2026-08-03 18:57:25"}]),
            "market_competition": _result([]),
            "monthly_loss": _result([{"table_key": "meituan_order_loss_monthly", "competitor_circle_name": "Circle", "competitor_poi_id": "p1", "competitor_hotel_name": "peer", "competitor_loss_order_count": 20, "competitor_loss_amount": 1000, "total_loss_order_count": 20, "total_loss_order_amount": 1000, "period_start_date": "2026-07-04", "period_end_date": "2026-08-02", "snapshot_time": "2026-08-03 18:55:12"}]),
            "promotion_activity": _result([{"table_key": "meituan_promotion_activity", "activity_id": "a1", "activity_name": "sale", "activity_status": "active", "snapshot_time": "2026-08-03 18:56:29"}]),
            "promotion_products": _result([{"table_key": "meituan_activity_product_detail", "activity_id": "a1", "room_type_id": "py01", "snapshot_time": "2026-08-03 18:56:29"}]),
        }
        operating = {"source_status": "ok", "data_business_date": "2026-08-03", "data_snapshot_time": "2026-08-03 18:58:24", "total_rooms": 31, "available_rooms": 12, "base_committed_sold_rooms": 19, "overbooking_rooms": 0, "committed_sold_rooms": 19, "committed_occupancy_rate": 0.6129, "physical_occupied_rooms": 12, "physical_occupancy_rate": 0.3871, "room_revenue": 3100, "adr": 163.16, "revpar": 100, "room_type_forecasts": [{"room_type_id": "py01", "room_type_name": "King", "total_rooms": 10, "available_rooms": 3, "overbooking_rooms": 0, "committed_sold_rooms": 7, "physical_occupied_rooms": 5}]}

        views = build_s2_operating_views(operating_payload=operating, optional_results=optional)

        self.assertEqual(views["schema_version"], "s2_operating_snapshot_v2")
        self.assertEqual(views["core_operating"]["committed_sold_rooms"], 19)
        self.assertEqual(views["flow_conversion"]["platforms"]["meituan"]["metric_count"], 1)
        self.assertEqual(views["market_competition"]["platforms"]["meituan"]["loss_context"]["loss_order_count"], 20)
        self.assertEqual(views["price_and_lead"]["platforms"]["meituan"]["products"][0]["price"], 404)
        self.assertEqual(views["price_and_lead"]["platforms"]["meituan"]["lead_price"]["lead_price_index"], 0.839)
        self.assertEqual(views["promotion_activity"]["platforms"]["meituan"]["mapping_missing_count"], 0)
        self.assertFalse(views["direct_price_trigger_allowed"])
        self.assertFalse(views["live_allowed"])
        text = render_s2_operating_reply(views)
        self.assertIn("一、经营总览", text)
        self.assertIn("六、推广活动状态", text)
        self.assertIn("不判断根因、不生成收益或渠道动作", text)

    def test_optional_queries_are_date_bound_only_for_daily_sources(self) -> None:
        calls: list[tuple[str, dict]] = []

        def query(template: str, hotel_id: str, **kwargs) -> dict:
            calls.append((template, kwargs))
            return _result([])

        results = load_s2_optional_results(query, hotel_id="puyue", business_date="2026-08-03", as_of_time="2026-08-03 19:00:00")

        self.assertEqual(set(results), {"flow_conversion", "market_metrics", "price_and_lead", "market_competition", "monthly_loss", "promotion_activity", "promotion_products"})
        metric_dates = {kwargs["date"] for template, kwargs in calls if template == "ota_business_metrics"}
        by_template = {template: kwargs for template, kwargs in calls if template != "ota_business_metrics"}
        self.assertEqual(metric_dates, {"2026-08-02", "2026-08-03"})
        self.assertEqual(by_template["ota_price_mapping"]["as_of_time"], "2026-08-03 19:00:00")
        self.assertEqual(by_template["ota_order_loss_monthly"], {})
        self.assertEqual(by_template["ota_activity_summary"], {})

    def test_optional_view_distinguishes_no_records_from_query_failure(self) -> None:
        no_rows = {"status": "ok", "payload": {"source_status": "no_rows", "rows": []}}
        failed = {"status": "data_gap", "reason": "schema_drift"}
        operating = {"source_status": "ok", "data_business_date": "2026-08-03", "total_rooms": 31}

        views = build_s2_operating_views(
            operating_payload=operating,
            optional_results={
                "flow_conversion": no_rows,
                "market_metrics": no_rows,
                "price_and_lead": _result([]),
                "market_competition": _result([]),
                "monthly_loss": _result([]),
                "promotion_activity": no_rows,
                "promotion_products": failed,
            },
        )

        self.assertEqual(views["flow_conversion"]["status"], "no_records")
        self.assertEqual(views["promotion_activity"]["status"], "data_gap")
        self.assertIn("source_missing:promotion_activity:schema_drift", views["promotion_activity"]["quality_flags"])
        text = render_s2_operating_reply(views)
        self.assertIn("来源已查询，当前范围无记录", text)
        self.assertIn("未形成可用结果", text)

    def test_flow_uses_only_canonical_codes_and_lead_gap_is_not_a_source_gap(self) -> None:
        optional = {
            "flow_conversion": _result([
                {"table_key": "meituan_business_metrics", "metric_code": "FLOW_EXPOSURE_UV", "metric_value": 5351, "metric_unit": "人"},
                {"table_key": "meituan_business_metrics", "metric_code": "FLOW_INTENTION_UV", "metric_value": 539, "metric_unit": "人"},
                {"table_key": "meituan_business_metrics", "metric_code": "FLOW_PAY_ORDER_CNT", "metric_value": 24, "metric_unit": "单"},
                {"table_key": "meituan_business_metrics", "metric_code": "FLOW_INTENTION_PER_EXPOSURE", "metric_value": 0.1007},
                {"table_key": "meituan_business_metrics", "metric_code": "FLOW_PAY_ORDER_PER_INTENTION", "metric_value": 0.0445},
                {"table_key": "meituan_business_metrics", "metric_code": "INTENTION_UV", "metric_value": 539, "metric_unit": "人"},
                {"table_key": "meituan_business_metrics", "metric_code": "PAY_ORDER_CNT", "metric_value": 24, "metric_unit": "单"},
            ]),
            "market_metrics": _result([{"table_key": "meituan_business_metrics", "metric_code": "FLOW_EXPOSURE_UV", "metric_value": 3807, "metric_unit": "人"}]),
            "price_and_lead": _result([{"table_key": "meituan_price_mapping", "room_type_id": "py01", "ota_product_id": "mt-1", "ota_sale_price": 404}]),
            "market_competition": _result([]), "monthly_loss": _result([]),
            "promotion_activity": _result([]), "promotion_products": _result([]),
        }
        views = build_s2_operating_views(operating_payload={"source_status": "ok"}, optional_results=optional)

        flow = views["flow_conversion"]["platforms"]["meituan"]
        self.assertEqual([item["metric_code"] for item in flow["metrics"]], [
            "FLOW_EXPOSURE_UV", "FLOW_INTENTION_UV", "FLOW_PAY_ORDER_CNT",
            "FLOW_INTENTION_PER_EXPOSURE", "FLOW_PAY_ORDER_PER_INTENTION",
        ])
        self.assertEqual(flow["metric_count"], 5)
        self.assertEqual(
            views["price_and_lead"]["platforms"]["meituan"]["quality_flags"],
            ["metric_code_missing:meituan:DAY_ROOM_LOWEST_PRICE_AVG"],
        )


if __name__ == "__main__":
    unittest.main()

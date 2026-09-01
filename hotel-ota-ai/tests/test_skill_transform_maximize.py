from __future__ import annotations

import argparse
import contextlib
import io
import json
import unittest
from unittest import mock

from runtime.decisions.competition import competition_alert
from runtime.decisions.customer import customer_analysis
from runtime.decisions.promotion import promotion_plan, promotion_roi
from runtime.decisions.reputation import reputation_diagnosis


def _capture_json(func: object, args: argparse.Namespace) -> dict:
    with contextlib.redirect_stdout(io.StringIO()) as stream:
        func(args)  # type: ignore[operator]
    return json.loads(stream.getvalue())


def _v4(rows: list[dict], *, freshness: str = "fresh", business: str = "current") -> dict:
    return {
        "status": "ok",
        "payload": {
            "rows": rows,
            "freshness_status": freshness,
            "business_status": business,
            "data_business_date": "2026-06-27",
        },
    }


class TestSkillTransformMaximize(unittest.TestCase):
    def test_s8_promotion_plan_uses_database_activity_context(self) -> None:
        def template(name: str, hotel_id: str):
            if name == "ota_activity_summary":
                return _v4([{"activity_status": "active", "activity_name": "member", "room_type_name": "KING"}])
            if name == "ota_activity_product_detail":
                return _v4([{"room_type_name": "KING"}])
            return _v4([])

        with mock.patch("runtime.decisions.promotion.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.promotion.database_template_result", side_effect=template
        ):
            result = _capture_json(promotion_plan, argparse.Namespace(hotel_id="xingfeng"))

        context = result["evidence"]["promotion_context"]
        self.assertEqual(result["skill_id"], "S8")
        self.assertEqual(context["active_campaign_count"], 1)
        self.assertIn("promotion_activity_summary", context["commercial_sections"])
        self.assertNotIn("api_status", result["evidence"])

    def test_s10_roi_uses_fixed_performance_source_not_mapping(self) -> None:
        performance = _v4([{"table_key": "meituan_promotion_performance_30d", "period_start_date": "2026-07-04", "period_end_date": "2026-08-02", "snapshot_time": "2026-08-03 20:17:26", "spend_amount": 100, "booking_order_amount": 500}])
        with mock.patch("runtime.decisions.promotion.query_s10_promotion_performance", return_value=performance), mock.patch(
            "runtime.decisions.promotion.database_template_result", side_effect=AssertionError("S10 must not use template mapping")
        ):
            result = _capture_json(promotion_roi, argparse.Namespace(hotel_id="xingfeng"))

        roi = result["evidence"]["promotion_roi"]
        self.assertEqual(roi["platforms"]["meituan"]["items"][0]["observed_roas"], 5.0)
        self.assertNotIn("estimated", result["summary"])

    def test_s12_reputation_uses_review_overview_not_fake_review_text(self) -> None:
        def template(name: str, hotel_id: str):
            if name == "ota_review_overview":
                return _v4([{"rating_score": 4.6, "bad_review_count": 2, "unreplied_review_count": 1}])
            if name == "ota_review_ranking":
                return _v4([{"keyword": "service", "rank": 8}])
            return _v4([])

        with mock.patch("runtime.decisions.reputation.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.reputation.database_template_result", side_effect=template
        ):
            result = _capture_json(reputation_diagnosis, argparse.Namespace(hotel_id="xingfeng"))

        context = result["evidence"]["reputation_context"]
        self.assertEqual(context["negative_review_count"], 2)
        self.assertNotIn("reply_draft", json.dumps(result, ensure_ascii=False))
        self.assertFalse(result["actions"][0]["auto_publish"])

    def test_s12_reputation_returns_data_gap_without_review_overview(self) -> None:
        def template(name: str, hotel_id: str):
            return _v4([])

        with mock.patch("runtime.decisions.reputation.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.reputation.database_template_result", side_effect=template
        ):
            result = _capture_json(reputation_diagnosis, argparse.Namespace(hotel_id="xingfeng"))

        context = result["evidence"]["reputation_context"]
        text = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "data_gap")
        self.assertFalse(context["commercial_visible"])
        self.assertIn("review_overview_rows_missing", context["internal_missing_fields"])
        self.assertNotIn("reply_draft", text)
        self.assertNotIn("差评", result["summary"])

    def test_s7_competition_uses_peer_aggregate_without_fake_prices(self) -> None:
        def template(name: str, hotel_id: str):
            if name == "ota_business_metrics":
                return _v4([{"source_platform": "meituan", "metric_code": "DAY_ROOM_LOWEST_PRICE_AVG", "metric_value": 210, "metric_unit": "CNY", "peer_average": 216.95, "competitor_rank": "8/20"}])
            return _v4([])

        with mock.patch("runtime.decisions.competition.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.competition.database_template_result", side_effect=template
        ):
            result = _capture_json(competition_alert, argparse.Namespace(hotel_id="xingfeng"))

        context = result["evidence"]["competitor_context"]
        peer = context["platforms"]["meituan"]["peer_aggregate"][0]
        self.assertEqual(peer["comparison_level"], "peer_aggregate")
        self.assertEqual(peer["lead_price_index"], 0.968)
        self.assertEqual(peer["lead_price_gap_pct"], -0.032)
        self.assertFalse(context["exact_product_available"])
        self.assertNotIn("competitor_prices", json.dumps(result, ensure_ascii=False))

    def test_s17_customer_analysis_uses_aggregate_transform_context(self) -> None:
        def template(name: str, hotel_id: str, **kwargs):
            if name == "customer_order_analysis":
                return {
                    "status": "ok",
                    "payload": {
                        "status": "ok",
                        "hotel_id": hotel_id,
                        "window_start": "2026-06-01 00:00:00",
                        "window_end": "2026-07-01 00:00:00",
                        "as_of_datetime": "2026-06-30 23:59:59",
                        "populations": {"pms_booking_created": {"created_order_count": 1}},
                        "data_gaps": [],
                        "direct_action_allowed": False,
                        "row_level_export_allowed": False,
                        "raw_contact_included": False,
                        "raw_order_rows_included": False,
                    },
                }
            return _v4([])

        with mock.patch("runtime.decisions.customer.database_source_enabled", return_value=True), mock.patch(
            "runtime.decisions.customer.database_template_result", side_effect=template
        ):
            result = _capture_json(customer_analysis, argparse.Namespace(hotel_id="xingfeng"))

        context = result["evidence"]
        self.assertEqual(context["populations"]["pms_booking_created"]["created_order_count"], 1)
        self.assertFalse(context["row_level_export_allowed"])
        self.assertNotIn("private-order", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("private", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("801", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()

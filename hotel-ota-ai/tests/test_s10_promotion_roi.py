from __future__ import annotations

import unittest
from unittest import mock

from runtime.algorithms.s10_promotion_roi import build_s10_promotion_roi
from runtime.feishu_command_router import _detect_intent, route_feishu_command
from runtime.feishu_output_renderer import build_feishu_send_payload


def _result(rows: list[dict]) -> dict:
    return {"status": "ok", "payload": {"source_status": "ok", "rows": rows}}


class TestS10PromotionRoi(unittest.TestCase):
    def test_meituan_units_and_weighted_portfolio_are_separate(self) -> None:
        result = build_s10_promotion_roi(performance_result=_result([
            {"table_key": "meituan_promotion_performance_30d", "plan_id": 1, "launch_id": 11, "plan_name": "运行中", "promotion_status": "RUNNING", "period_start_date": "2026-07-04", "period_end_date": "2026-08-02", "snapshot_time": "2026-08-03 20:17:26", "exposure_count": 100, "click_count": 10, "booking_order_count": 2, "room_night_count": 3, "booking_order_amount": 600, "spend_amount": 100, "cash_spend_amount": 80, "cost_per_click": 10, "click_rate_pct": 10},
            {"table_key": "meituan_promotion_performance_30d", "plan_id": 2, "launch_id": 22, "plan_name": "已暂停", "promotion_status": "PAUSED", "period_start_date": "2026-07-04", "period_end_date": "2026-08-02", "snapshot_time": "2026-08-03 20:17:26", "exposure_count": 100, "click_count": 20, "booking_order_count": 1, "room_night_count": 2, "booking_order_amount": 500, "spend_amount": 200, "cash_spend_amount": 100},
        ]), as_of_time="2026-08-03 20:20:00")
        meituan = result["platforms"]["meituan"]
        self.assertEqual(len(meituan["items"]), 2)
        self.assertEqual(meituan["items"][0]["observed_roas"], 6.0)
        self.assertEqual(meituan["portfolios"][0]["observed_roas"], 3.6667)
        self.assertEqual(meituan["portfolios"][0]["cpc"], 10.0)
        self.assertEqual(meituan["portfolios"][0]["cpa"], 100.0)
        self.assertEqual(result["contribution_estimate"]["status"], "unavailable")
        self.assertFalse(result["live_allowed"])

    def test_zero_delivery_is_not_no_records_or_zero_roas(self) -> None:
        result = build_s10_promotion_roi(performance_result=_result([{"table_key": "ctrip_promotion_performance_30d", "period_start_date": "2026-06-27", "period_end_date": "2026-07-26", "snapshot_time": "2026-07-27 12:08:04", "data_delayed": 0, "exposure_count": 0, "click_count": 0, "spend_amount": 0, "booking_order_count": 0, "booking_order_amount": 0, "room_night_count": 0}]), as_of_time=None)
        item = result["platforms"]["ctrip"]["items"][0]
        self.assertIn("observed_zero_delivery", item["quality_flags"])
        self.assertEqual(item["observed_roas"], "not_computable")

    def test_delay_and_source_conflict_are_explicit(self) -> None:
        result = build_s10_promotion_roi(performance_result=_result([{"table_key": "ctrip_promotion_performance_30d", "period_start_date": "2026-06-27", "period_end_date": "2026-07-26", "snapshot_time": "2026-07-27 12:08:04", "data_delayed": 1, "exposure_count": 10, "click_count": 2, "spend_amount": 10, "booking_order_count": 1, "booking_order_amount": 100, "room_night_count": 1, "return_on_ad_spend": 2}]), as_of_time=None)
        flags = result["platforms"]["ctrip"]["items"][0]["quality_flags"]
        self.assertIn("source_delayed", flags)
        self.assertIn("source_derived_conflict:return_on_ad_spend", flags)

    def test_null_spend_makes_a_portfolio_partial_even_when_other_unit_has_value(self) -> None:
        result = build_s10_promotion_roi(performance_result=_result([
            {"table_key": "meituan_promotion_performance_30d", "plan_id": 1, "launch_id": 1, "period_start_date": "2026-07-04", "period_end_date": "2026-08-02", "snapshot_time": "2026-08-03 20:17:26", "spend_amount": 100, "booking_order_amount": 500},
            {"table_key": "meituan_promotion_performance_30d", "plan_id": 2, "launch_id": 2, "period_start_date": "2026-07-04", "period_end_date": "2026-08-02", "snapshot_time": "2026-08-03 20:17:26", "spend_amount": None, "booking_order_amount": 500},
        ]), as_of_time=None)
        self.assertEqual(result["platforms"]["meituan"]["status"], "data_gap")
        self.assertIn("spend_amount", result["platforms"]["meituan"]["portfolios"][0]["data_gaps"])

    def test_no_rows_and_missing_mapping_remain_distinct(self) -> None:
        no_rows = build_s10_promotion_roi(performance_result={"status": "ok", "payload": {"source_status": "no_rows", "rows": []}}, as_of_time=None)
        missing = build_s10_promotion_roi(performance_result={"status": "ok", "payload": {"source_status": "mapping_missing", "rows": []}}, as_of_time=None)
        self.assertEqual(no_rows["status"], "no_records")
        self.assertEqual(missing["status"], "data_gap")

    def test_partial_source_schema_drift_is_not_hidden_by_other_platform_rows(self) -> None:
        result = build_s10_promotion_roi(performance_result={"status": "ok", "payload": {"source_status": "ok", "source_gaps": ["ctrip:schema_drift"], "rows": [{"table_key": "meituan_promotion_performance_30d", "period_start_date": "2026-07-04", "period_end_date": "2026-08-02", "snapshot_time": "2026-08-03 20:17:26", "spend_amount": 10, "booking_order_amount": 100}]}}, as_of_time=None)
        self.assertEqual(result["status"], "partial")
        self.assertIn("ctrip:schema_drift", result["data_gaps"])

    def test_roi_phrases_use_the_real_s10_intent(self) -> None:
        self.assertEqual(_detect_intent("当前推广 ROI 怎么样"), "roi_decision")
        self.assertEqual(_detect_intent("广告效果和投产比"), "roi_decision")

    def test_feishu_route_uses_fixed_s10_source_not_database_mapping(self) -> None:
        performance = _result([{"table_key": "meituan_promotion_performance_30d", "period_start_date": "2026-07-04", "period_end_date": "2026-08-02", "snapshot_time": "2026-08-03 20:17:26", "spend_amount": 10, "booking_order_amount": 100}])
        with mock.patch("runtime.feishu_command_router.query_s10_promotion_performance", return_value=performance) as source, mock.patch(
            "runtime.feishu_command_router.database_template_result", side_effect=AssertionError("S10 must not load database mappings")
        ):
            result = route_feishu_command("当前推广 ROI 怎么样", role="owner", hotel_id="puyue")
        source.assert_called_once_with("puyue", as_of_time=mock.ANY)
        self.assertEqual(result["skill_id"], "S10")
        self.assertEqual(result["status"], "partial")

    def test_feishu_s10_includes_plan_name_snapshot_and_non_profit_difference(self) -> None:
        result = build_s10_promotion_roi(performance_result=_result([{
            "table_key": "meituan_promotion_performance_30d", "plan_id": 1, "plan_name": "智能推广", "launch_id": 2, "launch_name": "周末", "promotion_status": "RUNNING",
            "period_start_date": "2026-07-04", "period_end_date": "2026-08-02", "snapshot_time": "2026-08-03 20:17:26", "exposure_count": 10, "click_count": 2,
            "booking_order_count": 1, "room_night_count": 1, "booking_order_amount": 100, "spend_amount": 10,
        }]), as_of_time=None)
        result.update({"intent": "roi_decision", "auth_role": "owner"})
        text = build_feishu_send_payload(result)["text"]
        self.assertIn("智能推广", text)
        self.assertIn("2026-08-03 20:17:26", text)
        self.assertIn("归因金额－总花费 ¥90.0（仅观测差额，非净利润）", text)


if __name__ == "__main__":
    unittest.main()

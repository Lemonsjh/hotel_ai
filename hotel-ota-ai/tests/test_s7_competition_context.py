from __future__ import annotations

import unittest

from runtime.algorithms.s7_competition_context import build_s7_competition_context
from runtime.algorithms.s7_competition_reply import render_s7_competition_reply
from runtime.feishu_output_renderer import build_feishu_send_payload


def _result(rows: list[dict]) -> dict:
    return {"payload": {"rows": rows, "data_business_date": "2026-07-30", "data_snapshot_time": "2026-07-30T12:00:00", "freshness_status": "fresh", "business_status": "current"}}


class TestS7CompetitionContext(unittest.TestCase):
    def test_meituan_lead_price_and_loss_context_never_become_exact_product_comparison(self) -> None:
        result = build_s7_competition_context(
            price_result=_result([{"channel": "meituan", "room_type_id": "KING", "ota_product_id": "mt-1", "ota_product_name": "King", "current_price": 210, "business_date": "2026-07-30"}]),
            metrics_result=_result([{"source_platform": "meituan", "metric_code": "DAY_ROOM_LOWEST_PRICE_AVG", "metric_value": 210, "metric_unit": "CNY", "peer_average": 216.95, "competitor_rank": "8/20"}]),
            competition_result=_result([]),
            loss_result=_result([{"source_platform": "meituan", "period_start_date": "2026-07-01", "period_end_date": "2026-07-30", "total_loss_order_count": 935, "total_loss_room_night_count": 1089, "total_loss_order_amount": 326121.64, "competitor_hotel_name": "peer-a", "competitor_lowest_price": 115}]),
            activity_result=_result([]), activity_detail_result=_result([]), rights_result=_result([]), psi_result=_result([]), ranking_result=_result([]),
        )

        meituan = result["platforms"]["meituan"]
        peer = meituan["peer_aggregate"][0]
        self.assertEqual(peer["comparison_level"], "peer_aggregate")
        self.assertEqual(peer["lead_price_index"], 0.968)
        self.assertEqual(peer["lead_price_gap_pct"], -0.032)
        self.assertEqual((peer["rank_position"], peer["peer_count"]), (8, 20))
        self.assertEqual(meituan["loss_context"]["comparison_level"], "loss_context")
        self.assertEqual(meituan["loss_context"]["loss_order_count"], 935)
        self.assertFalse(result["exact_product_available"])
        self.assertEqual(meituan["exact_product_comparisons"], [])

    def test_missing_canonical_mapping_is_visible_without_name_fallback(self) -> None:
        result = build_s7_competition_context(
            price_result=_result([{"channel": "ctrip", "ota_product_id": "ct-1", "ota_product_name": "Unmapped", "current_price": 300}]),
            metrics_result=_result([]), competition_result=_result([]), loss_result=_result([]), activity_result=_result([]),
            activity_detail_result=_result([{"channel_source": "ctrip", "activity_name": "sale", "room_type_name": "Unmapped"}]),
            rights_result=_result([]), psi_result=_result([]), ranking_result=_result([]),
        )

        ctrip = result["platforms"]["ctrip"]
        self.assertEqual(ctrip["own_products"][0]["product_state"], "mapping_missing")
        self.assertEqual(ctrip["activity_context"]["mapping_missing_count"], 1)

    def test_peer_aggregate_never_mixes_current_value_with_yesterday_peer_data(self) -> None:
        result = build_s7_competition_context(
            price_result=_result([]),
            metrics_result=_result([
                {"source_platform": "meituan", "metric_code": "FLOW_INTENTION_UV", "metric_value": 533, "metric_unit": "人", "business_date": "2026-08-03", "snapshot_time": "2026-08-03 23:03:11"},
                {"source_platform": "meituan", "metric_code": "FLOW_INTENTION_UV", "metric_value": 539, "metric_unit": "人", "peer_average": 222, "competitor_rank": "2/20", "business_date": "2026-08-02", "snapshot_time": "2026-08-03 23:03:11"},
            ]),
            competition_result=_result([]), loss_result=_result([]), activity_result=_result([]), activity_detail_result=_result([]), rights_result=_result([]), psi_result=_result([]), ranking_result=_result([]),
        )
        peers = result["platforms"]["meituan"]["peer_aggregate"]
        self.assertEqual(len(peers), 1)
        self.assertEqual((peers[0]["own_value"], peers[0]["peer_average"], peers[0]["business_date"]), (539.0, 222.0, "2026-08-02"))

    def test_ctrip_loss_rows_sum_row_level_loss_counts_without_missing_total_columns(self) -> None:
        result = build_s7_competition_context(
            price_result=_result([]), metrics_result=_result([]), competition_result=_result([]),
            loss_result=_result([
                {"source_platform": "ctrip", "period_start_date": "2026-07-01", "period_end_date": "2026-07-30", "competitor_hotel_name": "peer-a", "competitor_loss_order_count": 3},
                {"source_platform": "ctrip", "period_start_date": "2026-07-01", "period_end_date": "2026-07-30", "competitor_hotel_name": "peer-b", "competitor_loss_order_count": 4},
            ]),
            activity_result=_result([]), activity_detail_result=_result([]), rights_result=_result([]), psi_result=_result([]), ranking_result=_result([]),
        )

        loss = result["platforms"]["ctrip"]["loss_context"]
        self.assertEqual(loss["loss_order_count"], 7)
        self.assertEqual(loss["competitor_count"], 2)

    def test_meituan_competition_circles_use_competitor_rows_not_repeated_window_totals(self) -> None:
        result = build_s7_competition_context(
            price_result=_result([]), metrics_result=_result([]), competition_result=_result([]),
            loss_result=_result([
                {"source_platform": "meituan", "competitor_circle_name": "十字街", "competitor_poi_id": "a", "competitor_loss_order_count": 20, "competitor_loss_amount": 1000, "competitor_lowest_price": 200, "period_start_date": "2026-07-01", "period_end_date": "2026-07-30", "total_loss_order_count": 999},
                {"source_platform": "meituan", "competitor_circle_name": "十字街", "competitor_poi_id": "b", "competitor_loss_order_count": 30, "competitor_loss_amount": 2000, "competitor_lowest_price": 250, "period_start_date": "2026-07-01", "period_end_date": "2026-07-30", "total_loss_order_count": 999},
                {"source_platform": "meituan", "competitor_circle_name": "无合适商圈", "competitor_poi_id": "c", "competitor_loss_order_count": 10, "competitor_loss_amount": 500},
            ]),
            activity_result=_result([]), activity_detail_result=_result([]), rights_result=_result([]), psi_result=_result([]), ranking_result=_result([]),
        )

        circles = result["platforms"]["meituan"]["competition_circle_context"]["circles"]
        crossroad = next(item for item in circles if item["competition_circle_name"] == "十字街")
        self.assertEqual(crossroad["competitor_count"], 2)
        self.assertEqual(crossroad["loss_order_count"], 50)
        self.assertEqual(crossroad["loss_order_amount"], 3000)
        self.assertEqual(crossroad["competitor_lowest_price_range"], [200, 250])
        self.assertNotIn("meituan_ota_scan_order_detail", result["used_tables"])
        self.assertNotIn("ctrip_ota_order_detail", result["used_tables"])
        self.assertEqual(next(item for item in circles if item["circle_classification"] == "source_unclassified")["competition_circle_name"], "来源未归类")

    def test_reply_template_keeps_comparison_boundaries_and_action_limit(self) -> None:
        context = build_s7_competition_context(
            price_result=_result([{"channel": "meituan", "room_type_id": "KING", "ota_product_id": "mt-1", "ota_product_name": "King", "current_price": 209, "business_date": "2026-08-03"}]),
            metrics_result=_result([{"source_platform": "meituan", "metric_code": "DAY_ROOM_LOWEST_PRICE_AVG", "metric_name": "引流价", "metric_value": 209, "metric_unit": "CNY", "peer_average": 252.3, "competitor_rank": "14/20", "business_date": "2026-08-03", "snapshot_time": "2026-08-03 23:03:11"}]),
            competition_result=_result([]), loss_result=_result([]), activity_result=_result([]), activity_detail_result=_result([]), rights_result=_result([]), psi_result=_result([]), ranking_result=_result([]),
        )

        text = render_s7_competition_reply(context)
        self.assertIn("一、结论边界", text)
        self.assertIn("引流价（DAY_ROOM_LOWEST_PRICE_AVG）", text)
        self.assertIn("DAY_ROOM_LOWEST_PRICE_AVG", text)
        self.assertIn("来源排名 14/20", text)
        self.assertIn("同行指标抓取时间：2026-08-03 23:03:11", text)
        self.assertIn("月度流失背景：来源缺失或无记录", text)
        self.assertIn("不创建调价或推广任务", text)
        self.assertNotIn("流量领先", text)

        payload = build_feishu_send_payload({"intent": "competition_alert", "evidence": {"competitor_context": context}}, role="owner")
        self.assertTrue(payload["send_allowed"])
        self.assertIn("一、结论边界", payload["text"])
        self.assertIn("数据质量与行动限制", payload["text"])
        self.assertIn("业务日 2026-08-03", payload["text"])
        self.assertIn("同行指标抓取时间：2026-08-03 23:03:11", payload["text"])

    def test_reply_template_groups_review_ranking_by_its_source_semantics(self) -> None:
        context = build_s7_competition_context(
            price_result=_result([]), metrics_result=_result([]), competition_result=_result([]), loss_result=_result([]),
            activity_result=_result([]), activity_detail_result=_result([]), rights_result=_result([]), psi_result=_result([]),
            ranking_result=_result([
                {"channel_source": "美团", "ranking_type": "positive_impression", "ranking_position": 1, "rank_item_name": "环境很好", "rank_item_value": 671},
                {"channel_source": "美团", "ranking_type": "positive_keyword", "ranking_position": 1, "rank_item_name": "房间好", "rank_item_value": 70},
                {"channel_source": "美团", "ranking_type": "negative_keyword", "ranking_position": 1, "rank_item_name": "设施一般", "rank_item_value": 1},
                {"channel_source": "美团", "ranking_type": "peer_score", "ranking_position": 1, "rank_item_name": "蜜悦设计师酒店", "rank_item_value": 4.9},
            ]),
        )

        text = render_s7_competition_reply(context)
        self.assertIn("好评印象（来源 Top）：环境很好 671。", text)
        self.assertIn("竞争圈酒店评分排名（美团来源榜单）：", text)
        self.assertIn("1. 蜜悦设计师酒店：4.9", text)
        self.assertNotIn("好评关键词", text)
        self.assertNotIn("待关注反馈", text)
        self.assertNotIn("评分/排名（仅本店来源记录", text)


if __name__ == "__main__":
    unittest.main()

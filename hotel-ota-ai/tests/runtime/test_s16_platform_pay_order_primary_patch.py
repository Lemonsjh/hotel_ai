from __future__ import annotations

import unittest

from runtime.s16_meituan_projection_advisory_patch import (
    build_meituan_market_proxy as original_market_proxy,
)
from runtime.s16_platform_pay_order_primary_patch import (
    _platform_primary_proxy,
    _rewrite_user_text,
)
from runtime.sales_progress.repository import DirectSalesProgressRepository


class PuyueArchiveRepository:
    def __init__(self, flow_orders, pay_orders=15):
        self.flow_orders = flow_orders
        self.pay_orders = pay_orders

    def ota_business_metrics(self, platform, hotel_id, start_date, end_date, as_of):
        self.asserted_args = (platform, hotel_id, start_date, end_date, as_of)
        return [
            {
                "metric_code": "FLOW_PAY_ORDER_CNT",
                "metric_value": self.flow_orders,
                "business_date": "2026-08-06",
                "snapshot_time": "2026-08-06 14:20:00",
            },
            {
                "metric_code": "PAY_ORDER_CNT",
                "metric_value": self.pay_orders,
                "peer_average": 6.05,
                "competitor_rank": "3/20",
                "business_date": "2026-08-06",
                "snapshot_time": "2026-08-06 14:20:00",
            },
        ]


class SameBatchPeerCountRepository:
    def __init__(self):
        self.calls = []

    def ota_business_metrics(self, platform, hotel_id, start_date, end_date, as_of):
        self.calls.append((platform, hotel_id, start_date, end_date, as_of))
        return [
            {
                "metric_code": "PAY_ORDER_CNT",
                "metric_value": 0,
                "peer_average": 2.05,
                "competitor_rank": None,
                "business_date": "2026-08-11",
                "snapshot_time": "2026-08-11 10:00:48",
            },
            {
                "metric_code": "FLOW_EXPOSURE_UV",
                "metric_value": 100,
                "competitor_rank": "7/20",
                "business_date": "2026-08-11",
                "snapshot_time": "2026-08-11 10:00:48",
            },
            {
                "metric_code": "FLOW_INTENTION_UV",
                "metric_value": 10,
                "competitor_rank": "12/20",
                "business_date": "2026-08-11",
                "snapshot_time": "2026-08-11 10:00:48",
            },
        ]


class PreviousDayPeerRepository:
    def __init__(self):
        self.calls = []

    def ota_business_metrics(self, platform, hotel_id, start_date, end_date, as_of):
        self.calls.append((platform, hotel_id, start_date, end_date, as_of))
        if start_date == "2026-08-11":
            return [
                {
                    "metric_code": "PAY_ORDER_CNT",
                    "metric_value": 0,
                    "peer_average": 2.05,
                    "competitor_rank": None,
                    "business_date": "2026-08-11",
                    "snapshot_time": "2026-08-11 10:00:48",
                }
            ]
        if start_date == "2026-08-10":
            return [
                {
                    "metric_code": "PAY_ORDER_CNT",
                    "metric_value": 99,
                    "peer_average": 13.5,
                    "competitor_rank": "3/20",
                    "business_date": "2026-08-10",
                    "snapshot_time": "2026-08-10 23:20:00",
                }
            ]
        return []


class HourlyMarketRepository:
    def __init__(self):
        self.hourly_calls = []

    def ota_business_metrics(self, platform, hotel_id, start_date, end_date, as_of):
        return [
            {
                "metric_code": "FLOW_PAY_ORDER_CNT",
                "metric_value": 5,
                "business_date": "2026-08-18",
                "snapshot_time": "2026-08-18 13:00:00",
            },
            {
                "metric_code": "PAY_ORDER_CNT",
                "metric_value": 5,
                "peer_average": 4,
                "competitor_rank": "3/20",
                "business_date": "2026-08-18",
                "snapshot_time": "2026-08-18 13:00:00",
            },
        ]

    def _query(self, sql, params):
        if "FROM meituan_ota_business_metrics_hourly" not in sql:
            raise AssertionError(sql)
        self.hourly_calls.append((sql, tuple(params)))
        return [
            {
                "business_date": "2026-08-04",
                "snapshot_hour": "2026-08-04 13:00:00",
                "metric_value": 3,
                "peer_average": None,
            },
            {
                "business_date": "2026-08-04",
                "snapshot_hour": "2026-08-04 23:00:00",
                "metric_value": 6,
                "peer_average": 8,
            },
            {
                "business_date": "2026-08-11",
                "snapshot_hour": "2026-08-11 13:00:00",
                "metric_value": 4,
                "peer_average": 5,
            },
            {
                "business_date": "2026-08-11",
                "snapshot_hour": "2026-08-11 23:00:00",
                "metric_value": 10,
                "peer_average": 10,
            },
            {
                "business_date": "2026-08-17",
                "snapshot_hour": "2026-08-17 13:00:00",
                "metric_value": 8,
                "peer_average": 8,
            },
            {
                "business_date": "2026-08-17",
                "snapshot_hour": "2026-08-17 23:00:00",
                "metric_value": 10,
                "peer_average": 10,
            },
        ]


class CapturingRepository(DirectSalesProgressRepository):
    def __init__(self):
        self.sql = ""
        self.params = ()

    def _query(self, sql, params):
        self.sql = sql
        self.params = tuple(params)
        return []


class S16PlatformPayOrderPrimaryPatchTests(unittest.TestCase):
    def test_pay_order_cnt_drives_market_when_pay_fields_are_available(self):
        result = _platform_primary_proxy(
            original_market_proxy,
            PuyueArchiveRepository(flow_orders=22, pay_orders=15),
            hotel_id="puyue",
            target_date="2026-08-06",
            as_of_datetime="2026-08-06 14:45:00",
            baseline_market_orders=276.9,
            baseline_market_share=0.096,
        )

        expected_market = 121
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["own_orders"], 15)
        self.assertAlmostEqual(result["current_estimated_market_orders"], expected_market)
        self.assertAlmostEqual(result["current_estimated_market_share"], 15 / expected_market)
        self.assertEqual(
            result["own_order_source"],
            "meituan_ota_business_metrics.PAY_ORDER_CNT",
        )
        self.assertEqual(
            result["peer_context_source"],
            "meituan_ota_business_metrics.PAY_ORDER_CNT",
        )
        self.assertFalse(result["peer_context_previous_day_fallback_used"])

    def test_market_projection_uses_independent_hourly_completion_ratios(self):
        repository = HourlyMarketRepository()
        result = _platform_primary_proxy(
            original_market_proxy,
            repository,
            hotel_id="puyue",
            target_date="2026-08-18",
            as_of_datetime="2026-08-18 13:20:00",
            baseline_market_orders=150,
            baseline_market_share=0.08,
        )

        expected_current_market = 80
        expected_projected_market = 160
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["peer_hotel_count"], 20)
        self.assertAlmostEqual(
            result["current_estimated_market_orders"],
            expected_current_market,
        )
        self.assertAlmostEqual(
            result["market_projection"]["projected_full_day"],
            expected_projected_market,
        )
        self.assertAlmostEqual(
            result["market_projection"]["own_hourly_completion_ratio"],
            0.45,
        )
        self.assertAlmostEqual(
            result["market_projection"]["peer_hourly_completion_ratio"],
            0.50,
        )
        self.assertAlmostEqual(
            result["market_projection"]["market_hourly_completion_ratio"],
            expected_current_market / expected_projected_market,
        )
        self.assertEqual(
            result["market_projection"]["market_projection_method"],
            "historical_hourly_completion_ratio",
        )
        self.assertFalse(result["market_projection"]["linear_projection_only"])
        self.assertEqual(len(repository.hourly_calls), 1)
        _, params = repository.hourly_calls[0]
        self.assertEqual(
            params,
            ("puyue", "2026-06-19", "2026-08-18", "PAY_ORDER_CNT"),
        )

    def test_missing_pay_order_value_uses_same_batch_flow_only(self):
        jd01_fallback_called = False

        def forbidden_jd01_fallback(*args, **kwargs):
            nonlocal jd01_fallback_called
            jd01_fallback_called = True
            return {"status": "available", "own_orders_proxy": 99}

        result = _platform_primary_proxy(
            forbidden_jd01_fallback,
            PuyueArchiveRepository(flow_orders=22, pay_orders=None),
            hotel_id="puyue",
            target_date="2026-08-06",
            as_of_datetime="2026-08-06 14:45:00",
            baseline_market_orders=276.9,
            baseline_market_share=0.096,
        )

        expected_market = 121
        self.assertEqual(result["status"], "available")
        self.assertFalse(jd01_fallback_called)
        self.assertEqual(result["own_orders"], 22)
        self.assertAlmostEqual(result["current_estimated_market_orders"], expected_market)
        self.assertEqual(
            result["own_order_source"],
            "meituan_ota_business_metrics.FLOW_PAY_ORDER_CNT",
        )

    def test_same_batch_other_metric_rank_supplies_peer_hotel_count_only(self):
        repository = SameBatchPeerCountRepository()
        result = _platform_primary_proxy(
            original_market_proxy,
            repository,
            hotel_id="puyue",
            target_date="2026-08-11",
            as_of_datetime="2026-08-11 10:26:00",
            baseline_market_orders=276.9,
            baseline_market_share=0.096,
        )

        expected_market = 41
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["own_orders"], 0)
        self.assertEqual(result["peer_average_orders"], 2.05)
        self.assertIsNone(result["peer_rank"])
        self.assertEqual(result["peer_hotel_count"], 20)
        self.assertAlmostEqual(result["current_estimated_market_orders"], expected_market)
        self.assertEqual(result["current_estimated_market_share"], 0)
        self.assertEqual(
            result["peer_hotel_count_metric_codes"],
            ("FLOW_EXPOSURE_UV", "FLOW_INTENTION_UV"),
        )
        self.assertIn("same_batch_peer_hotel_count", result["peer_context_source"])
        self.assertEqual(result["peer_context_business_date"], "2026-08-11")
        self.assertEqual(result["peer_context_snapshot_time"], "2026-08-11 10:00:48")
        self.assertFalse(result["peer_context_previous_day_fallback_used"])
        self.assertEqual(
            [(call[2], call[3]) for call in repository.calls],
            [("2026-08-11", "2026-08-11")],
        )

    def test_missing_same_batch_peer_count_never_queries_previous_day(self):
        repository = PreviousDayPeerRepository()
        result = _platform_primary_proxy(
            original_market_proxy,
            repository,
            hotel_id="puyue",
            target_date="2026-08-11",
            as_of_datetime="2026-08-11 10:26:00",
            baseline_market_orders=276.9,
            baseline_market_share=0.096,
        )

        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], "meituan_current_market_context_unavailable")
        self.assertFalse(result["peer_context_previous_day_fallback_used"])
        self.assertEqual(
            [(call[2], call[3]) for call in repository.calls],
            [("2026-08-11", "2026-08-11")],
        )

    def test_meituan_repository_selects_peer_context_columns(self):
        repository = CapturingRepository()
        repository.ota_business_metrics(
            "meituan",
            "puyue",
            "2026-08-11",
            "2026-08-11",
            "2026-08-11 10:26:00",
        )
        self.assertIn("peer_average", repository.sql)
        self.assertIn("competitor_rank", repository.sql)
        self.assertEqual(
            repository.params[1:3],
            ("2026-08-11", "2026-08-11"),
        )

    def test_user_text_does_not_call_platform_orders_a_proxy(self):
        text = _rewrite_user_text("本店今日美团订单代理 8 单；JD01美团订单代理口径。")
        self.assertIn("本店今日美团支付订单 8 单", text)
        self.assertNotIn("订单代理", text)


if __name__ == "__main__":
    unittest.main()

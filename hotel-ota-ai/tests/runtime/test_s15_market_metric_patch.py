from __future__ import annotations

import unittest

from runtime.s15_market_metric_patch import market_point
from runtime.s16_platform_pay_order_primary_patch import _latest_rows


def _row(metric_code: str, **values: object) -> dict[str, object]:
    row: dict[str, object] = {
        "metric_code": metric_code,
        "business_date": "2026-08-11",
        "snapshot_time": "2026-08-11T10:00:48",
    }
    row.update(values)
    return row


class MarketMetricPriorityTest(unittest.TestCase):
    def test_pay_order_cnt_wins_for_all_available_market_fields(self) -> None:
        point = market_point(
            {
                "PAY_ORDER_CNT": _row(
                    "PAY_ORDER_CNT",
                    metric_value=10,
                    peer_average=8,
                    competitor_rank="2/5",
                ),
                "FLOW_PAY_ORDER_CNT": _row(
                    "FLOW_PAY_ORDER_CNT",
                    metric_value=99,
                    peer_average=88,
                    competitor_rank="4/9",
                ),
            }
        )

        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point["own_orders"], 10)
        self.assertEqual(point["peer_average_orders"], 8)
        self.assertEqual(point["peer_rank"], 2)
        self.assertEqual(point["peer_hotel_count"], 5)
        self.assertEqual(point["estimated_market_orders"], 40)
        self.assertEqual(point["estimated_market_share"], 0.25)
        self.assertEqual(point["same_batch_fallback_fields"], ())
        self.assertEqual(point["peer_hotel_count_metric_codes"], ("PAY_ORDER_CNT",))
        self.assertFalse(point["own_order_fallback_used"])
        self.assertTrue(point["flow_peer_fields_ignored"])

    def test_same_batch_flow_only_fills_missing_pay_value_and_peer_average(self) -> None:
        point = market_point(
            {
                "PAY_ORDER_CNT": _row(
                    "PAY_ORDER_CNT",
                    metric_value=None,
                    peer_average=None,
                    competitor_rank=None,
                ),
                "FLOW_PAY_ORDER_CNT": _row(
                    "FLOW_PAY_ORDER_CNT",
                    metric_value=11,
                    peer_average=9,
                    competitor_rank="3/6",
                ),
            }
        )

        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point["own_orders"], 11)
        self.assertEqual(point["peer_average_orders"], 9)
        self.assertIsNone(point["peer_rank"])
        self.assertEqual(point["peer_hotel_count"], 6)
        self.assertEqual(
            point["same_batch_fallback_fields"],
            ("metric_value", "peer_average", "peer_hotel_count"),
        )
        self.assertEqual(
            point["same_batch_flow_fallback_fields"],
            ("metric_value", "peer_average"),
        )
        self.assertEqual(
            point["peer_hotel_count_metric_codes"],
            ("FLOW_PAY_ORDER_CNT",),
        )
        self.assertTrue(point["own_order_fallback_used"])
        self.assertFalse(point["flow_peer_fields_ignored"])

    def test_same_batch_flow_supplements_value_and_average_while_other_metric_supplies_count(self) -> None:
        point = market_point(
            {
                "PAY_ORDER_CNT": _row(
                    "PAY_ORDER_CNT",
                    metric_value=None,
                    peer_average=None,
                    competitor_rank=None,
                ),
                "FLOW_PAY_ORDER_CNT": _row(
                    "FLOW_PAY_ORDER_CNT",
                    metric_value=0,
                    peer_average=2.05,
                    competitor_rank=None,
                ),
                "FLOW_EXPOSURE_UV": _row(
                    "FLOW_EXPOSURE_UV",
                    metric_value=514,
                    competitor_rank="8/20",
                ),
                "FLOW_INTENTION_UV": _row(
                    "FLOW_INTENTION_UV",
                    metric_value=52,
                    competitor_rank="13/20",
                ),
            }
        )

        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point["own_orders"], 0)
        self.assertEqual(point["peer_average_orders"], 2.05)
        self.assertIsNone(point["peer_rank"])
        self.assertEqual(point["peer_hotel_count"], 20)
        self.assertEqual(point["estimated_market_orders"], 41)
        self.assertEqual(point["estimated_market_share"], 0)
        self.assertEqual(
            point["same_batch_flow_fallback_fields"],
            ("metric_value", "peer_average"),
        )
        self.assertEqual(
            point["peer_hotel_count_metric_codes"],
            ("FLOW_EXPOSURE_UV", "FLOW_INTENTION_UV"),
        )

    def test_same_batch_other_metrics_supply_only_peer_hotel_count(self) -> None:
        point = market_point(
            {
                "PAY_ORDER_CNT": _row(
                    "PAY_ORDER_CNT",
                    metric_value=0,
                    peer_average=2.05,
                    competitor_rank=None,
                ),
                "FLOW_EXPOSURE_UV": _row(
                    "FLOW_EXPOSURE_UV",
                    metric_value=120,
                    competitor_rank="7/20",
                ),
                "FLOW_INTENTION_UV": _row(
                    "FLOW_INTENTION_UV",
                    metric_value=16,
                    competitor_rank="12/20",
                ),
            }
        )

        self.assertIsNotNone(point)
        assert point is not None
        self.assertEqual(point["own_orders"], 0)
        self.assertEqual(point["peer_average_orders"], 2.05)
        self.assertIsNone(point["peer_rank"])
        self.assertEqual(point["peer_hotel_count"], 20)
        self.assertEqual(point["estimated_market_orders"], 41)
        self.assertEqual(point["estimated_market_share"], 0)
        self.assertEqual(
            point["peer_hotel_count_metric_codes"],
            ("FLOW_EXPOSURE_UV", "FLOW_INTENTION_UV"),
        )
        self.assertEqual(
            point["same_batch_fallback_fields"],
            ("peer_hotel_count",),
        )
        self.assertEqual(point["peer_context_business_date"], "2026-08-11")
        self.assertEqual(
            point["peer_context_snapshot_time"],
            "2026-08-11T10:00:48",
        )

    def test_conflicting_same_batch_peer_counts_fail_closed(self) -> None:
        point = market_point(
            {
                "PAY_ORDER_CNT": _row(
                    "PAY_ORDER_CNT",
                    metric_value=0,
                    peer_average=2.05,
                    competitor_rank=None,
                ),
                "FLOW_EXPOSURE_UV": _row(
                    "FLOW_EXPOSURE_UV",
                    competitor_rank="7/20",
                ),
                "FLOW_INTENTION_UV": _row(
                    "FLOW_INTENTION_UV",
                    competitor_rank="12/19",
                ),
            }
        )

        self.assertIsNone(point)

    def test_flow_supplement_never_crosses_snapshot(self) -> None:
        point = market_point(
            {
                "PAY_ORDER_CNT": _row(
                    "PAY_ORDER_CNT",
                    metric_value=None,
                    peer_average=8,
                    competitor_rank="2/5",
                ),
                "FLOW_PAY_ORDER_CNT": _row(
                    "FLOW_PAY_ORDER_CNT",
                    snapshot_time="2026-08-11T11:00:00",
                    metric_value=11,
                    peer_average=9,
                    competitor_rank="3/6",
                ),
            }
        )

        self.assertIsNone(point)

    def test_flow_supplement_never_crosses_business_date(self) -> None:
        point = market_point(
            {
                "PAY_ORDER_CNT": _row(
                    "PAY_ORDER_CNT",
                    metric_value=10,
                    peer_average=None,
                    competitor_rank="2/5",
                ),
                "FLOW_PAY_ORDER_CNT": _row(
                    "FLOW_PAY_ORDER_CNT",
                    business_date="2026-08-10",
                    metric_value=11,
                    peer_average=9,
                    competitor_rank="3/6",
                ),
            }
        )

        self.assertIsNone(point)

    def test_s16_keeps_every_metric_from_latest_pay_batch_only(self) -> None:
        rows = [
            _row(
                "FLOW_PAY_ORDER_CNT",
                snapshot_time="2026-08-11T11:00:00",
                metric_value=99,
            ),
            _row(
                "PAY_ORDER_CNT",
                metric_value=0,
                peer_average=2.05,
                competitor_rank=None,
            ),
            _row("FLOW_PAY_ORDER_CNT", metric_value=0),
            _row("FLOW_EXPOSURE_UV", competitor_rank="7/20"),
            _row("FLOW_INTENTION_UV", competitor_rank="12/20"),
            _row(
                "PAY_ADR",
                business_date="2026-08-10",
                competitor_rank="3/30",
            ),
        ]

        latest = _latest_rows(rows)

        self.assertEqual(
            set(latest),
            {
                "PAY_ORDER_CNT",
                "FLOW_PAY_ORDER_CNT",
                "FLOW_EXPOSURE_UV",
                "FLOW_INTENTION_UV",
            },
        )
        self.assertEqual(
            latest["PAY_ORDER_CNT"]["snapshot_time"],
            "2026-08-11T10:00:48",
        )
        self.assertEqual(latest["FLOW_PAY_ORDER_CNT"]["metric_value"], 0)
        self.assertEqual(latest["FLOW_EXPOSURE_UV"]["competitor_rank"], "7/20")


if __name__ == "__main__":
    unittest.main()

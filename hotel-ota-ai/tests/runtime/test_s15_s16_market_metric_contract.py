from __future__ import annotations

from typing import Any

from runtime import s15_market_metric_patch as market
from runtime import s15_technical_analysis
from runtime import s15_technical_sources
from runtime import s16_dynamic_diagnosis
from runtime import s16_platform_pay_order_primary_patch as platform
from runtime.s16_pay_order_price_sample_followup_patch import (
    current_platform_context,
)


def _row(
    code: str,
    *,
    value: Any,
    peer: Any,
    rank: Any = "3/20",
    snapshot: str = "2026-08-06 15:20:00",
) -> dict[str, Any]:
    return {
        "metric_code": code,
        "metric_value": value,
        "peer_average": peer,
        "competitor_rank": rank,
        "snapshot_time": snapshot,
    }


def test_flow_peer_fields_are_ignored_and_pay_peer_fields_are_used() -> None:
    point = market.market_point(
        {
            "FLOW_PAY_ORDER_CNT": _row(
                "FLOW_PAY_ORDER_CNT",
                value=15,
                peer=0.75,
            ),
            "PAY_ORDER_CNT": _row(
                "PAY_ORDER_CNT",
                value=15,
                peer=7.8,
            ),
        }
    )

    assert point is not None
    assert point["own_orders"] == 15
    assert point["peer_average_orders"] == 7.8
    assert point["estimated_market_orders"] == 156
    assert point["own_order_metric_code"] == "FLOW_PAY_ORDER_CNT"
    assert point["peer_context_metric_code"] == "PAY_ORDER_CNT"
    assert point["flow_peer_fields_ignored"] is True


def test_empty_flow_value_falls_back_to_pay_value_only_for_own_orders() -> None:
    point = market.market_point(
        {
            "FLOW_PAY_ORDER_CNT": _row(
                "FLOW_PAY_ORDER_CNT",
                value=None,
                peer=0.8,
            ),
            "PAY_ORDER_CNT": _row(
                "PAY_ORDER_CNT",
                value=15,
                peer=7.8,
            ),
        }
    )

    assert point is not None
    assert point["own_orders"] == 15
    assert point["peer_average_orders"] == 7.8
    assert point["own_order_metric_code"] == "PAY_ORDER_CNT"
    assert point["own_order_fallback_used"] is True


def test_missing_pay_peer_context_never_falls_back_to_flow_peer_fields() -> None:
    point = market.market_point(
        {
            "FLOW_PAY_ORDER_CNT": _row(
                "FLOW_PAY_ORDER_CNT",
                value=15,
                peer=7.8,
            ),
            "PAY_ORDER_CNT": _row(
                "PAY_ORDER_CNT",
                value=15,
                peer=None,
            ),
        }
    )

    assert point is None


def test_all_prebound_market_point_references_are_canonical() -> None:
    assert s15_technical_sources._market_point is market.market_point
    assert s15_technical_analysis._market_point is market.market_point
    assert s16_dynamic_diagnosis._market_point is market.market_point


def test_s16_platform_context_reuses_canonical_market_point() -> None:
    rows = [
        _row("FLOW_PAY_ORDER_CNT", value=15, peer=0.75),
        _row("PAY_ORDER_CNT", value=15, peer=7.8),
    ]

    class Repository:
        def ota_business_metrics(self, *args: Any) -> list[dict[str, Any]]:
            return rows

    context = current_platform_context(
        Repository(),
        "hotel-puyue",
        "2026-08-06",
        "2026-08-06 15:30:00",
    )

    assert context["status"] == "available"
    assert context["estimated_market_orders"] == 156
    assert context["peer_average_orders"] == 7.8
    assert context["market_metric_contract_version"] == market.VERSION
    assert platform._current_platform_context is current_platform_context

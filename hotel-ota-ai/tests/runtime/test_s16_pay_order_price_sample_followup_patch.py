from __future__ import annotations

from runtime.s16_pay_order_price_sample_followup_patch import (
    BASELINE_PACKAGE_VERSION,
    baseline_package_wrapper,
    contract_wrapper,
    metric_current_wrapper,
)


def test_second_conversion_uses_pay_order_fallback() -> None:
    wrapped = metric_current_wrapper(
        lambda rows: {
            "browse_uv": 183,
            "paid_orders": None,
            "paid_orders_duplicate": 15,
            "second_conversion": None,
        }
    )
    result = wrapped([])
    assert result["paid_orders"] == 15
    assert result["second_conversion"] == 15 / 183
    assert result["paid_orders_fallback_used"] is True
    assert result["paid_orders_source"] == "PAY_ORDER_CNT"


def test_source_row_count_becomes_price_reference_sample_count() -> None:
    wrapped = baseline_package_wrapper(
        lambda payload: {
            "version": "s15-baseline-package.v1",
            "room_type_transaction_references": [
                {
                    "room_type_id": "r1",
                    "p20": 123,
                    "median": 137,
                    "p80": 151,
                    "sample_count": 0,
                }
            ],
        }
    )
    package = wrapped(
        {
            "room_types": {
                "r1": {
                    "price_baseline": {
                        "source_row_count": 18,
                        "weighted_room_nights": 24,
                    }
                }
            }
        }
    )
    reference = package["room_type_transaction_references"][0]
    assert package["version"] == BASELINE_PACKAGE_VERSION
    assert reference["sample_count"] == 18
    assert reference["source_row_count"] == 18
    assert reference["comparison_ready"] is True


def test_delivery_contract_allows_fallback_and_room_net_comparison() -> None:
    wrapped = contract_wrapper(
        lambda result: {
            "must_preserve": [
                "美团大盘估算、估算份额，以及FLOW_PAY_ORDER_CNT本店订单与PAY_ORDER_CNT同行口径"
            ],
            "allowed": [],
            "forbidden": [
                "把PAY_ORDER_CNT.metric_value误当成本店支付订单",
                "没有同一OTA商品历史时输出确定的价格偏高或偏低",
            ],
        }
    )
    contract = wrapped({})
    assert any("经营口径" in item for item in contract["must_preserve"])
    assert not any("误当成本店支付订单" in item for item in contract["forbidden"])
    assert any("房型历史成交" in item for item in contract["allowed"])
    assert any("普通员工对话" in item for item in contract["forbidden"])

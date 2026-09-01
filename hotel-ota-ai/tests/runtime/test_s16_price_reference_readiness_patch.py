from __future__ import annotations

from runtime.s16_price_reference_readiness_patch import (
    _reference_for_product,
    _reference_sets,
    compare_product_net_price,
)


def _baseline(sample_count: int = 0) -> dict:
    return {
        "baseline_package": {
            "room_type_transaction_references": [
                {
                    "room_type_id": "KING",
                    "room_type_name": "至臻・电竞大床房",
                    "p20": 127,
                    "median": 141,
                    "p80": 167,
                    "sample_count": sample_count,
                }
            ]
        }
    }


def test_percentiles_allow_comparison_even_when_sample_field_is_zero() -> None:
    by_id, by_name = _reference_sets(_baseline(sample_count=0))
    reference = _reference_for_product(
        {
            "room_type_id": "KING",
            "room_type_name": "至臻・电竞大床房",
        },
        by_id,
        by_name,
    )
    result = compare_product_net_price(
        {
            "product_type": "普通全天房",
            "room_type_id": "KING",
            "estimated_activity_net_price": 220,
        },
        reference,
    )
    assert result["comparison_allowed"] is True
    assert result["price_status"] == "high"
    assert result["baseline_sample_count"] == 0
    assert result["reference_readiness"] == "transaction_percentiles_present"


def test_raw_s15_room_price_baseline_is_also_accepted() -> None:
    baseline = {
        "room_types": {
            "SINGLE": {
                "room_type_name": "独享・电竞单人间",
                "price_baseline": {
                    "p20": 123,
                    "median": 137,
                    "p80": 151,
                    "source_row_count": 18,
                },
            }
        }
    }
    by_id, by_name = _reference_sets(baseline)
    reference = _reference_for_product(
        {"room_type_id": "SINGLE"},
        by_id,
        by_name,
    )
    result = compare_product_net_price(
        {
            "product_type": "普通全天房",
            "room_type_id": "SINGLE",
            "estimated_activity_net_price": 140,
        },
        reference,
    )
    assert result["comparison_allowed"] is True
    assert result["price_status"] == "normal"
    assert result["baseline_source_row_count"] == 18


def test_non_full_day_products_remain_display_only() -> None:
    result = compare_product_net_price(
        {
            "product_type": "超级团购",
            "room_type_id": "KING",
            "estimated_activity_net_price": 120,
        },
        _baseline()["baseline_package"][
            "room_type_transaction_references"
        ][0],
    )
    assert result["comparison_allowed"] is False
    assert result["comparison_reason"] == "non_full_day_product_reference_only"

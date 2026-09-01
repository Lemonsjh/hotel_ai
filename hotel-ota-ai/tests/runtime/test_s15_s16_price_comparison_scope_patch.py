from __future__ import annotations

from runtime.s15_s16_price_comparison_scope_patch import (
    choose_room_price_baselines,
    compare_product_net_price,
    render_price_comparison_block,
)


def test_selected_similar_dates_are_primary() -> None:
    result = choose_room_price_baselines(
        full_baselines={
            "A": {
                "weighted_avg": 140,
                "p20": 120,
                "median": 140,
                "p80": 160,
                "weighted_room_nights": 20,
                "source_row_count": 10,
            }
        },
        selected_baselines={
            "A": {
                "weighted_avg": 155,
                "p20": 135,
                "median": 155,
                "p80": 175,
                "weighted_room_nights": 6,
                "source_row_count": 4,
            }
        },
        selected_date_counts={"A": 4},
    )
    assert result["A"]["reference_basis"] == "selected_similar_dates"
    assert result["A"]["p80"] == 175
    assert result["A"]["date_adjustment_applied"] is False


def test_low_selected_sample_uses_date_adr_fallback() -> None:
    result = choose_room_price_baselines(
        full_baselines={
            "A": {
                "weighted_avg": 100,
                "p20": 80,
                "median": 100,
                "p80": 120,
                "weighted_room_nights": 20,
                "source_row_count": 10,
            }
        },
        selected_baselines={
            "A": {
                "weighted_avg": 110,
                "p20": 100,
                "median": 110,
                "p80": 120,
                "weighted_room_nights": 1,
                "source_row_count": 1,
            }
        },
        selected_date_counts={"A": 1},
    )
    assert result["A"]["reference_basis"] == (
        "full_history_with_date_adr_fallback"
    )
    assert result["A"]["date_adjustment_factor"] == 1.1
    assert result["A"]["p80"] == 132


def test_p80_tolerance_uses_member_adjusted_net_price() -> None:
    reference = {
        "room_type_id": "A",
        "room_type_name": "标准房型A",
        "p20": 120,
        "median": 140,
        "p80": 160,
    }
    near = compare_product_net_price(
        {
            "product_type": "普通全天房",
            "estimated_activity_net_price": 168 / 0.85,
        },
        reference,
    )
    high = compare_product_net_price(
        {
            "product_type": "普通全天房",
            "estimated_activity_net_price": 180 / 0.85,
        },
        reference,
    )
    assert abs(near["estimated_activity_net_price"] - 168) < 1e-9
    assert near["price_status"] == "near_upper"
    assert near["price_cause_candidate"] is False
    assert abs(high["estimated_activity_net_price"] - 180) < 1e-9
    assert high["price_status"] == "high"
    assert high["price_cause_candidate"] is True


def test_renderer_lists_actual_full_day_products_only() -> None:
    text = render_price_comparison_block(
        {
            "dynamic_diagnosis": {
                "product_prices": [
                    {
                        "product_type": "普通全天房",
                        "ota_product_name": "荣耀战场大床房",
                        "reference_room_type_name": "至臻・电竞大床房",
                        "raw_price": 514,
                        "commission_net_base_price": 452,
                        "estimated_activity_net_price": 168,
                        "commission_rate": 0.12,
                        "matched_activity_count": 9,
                        "comparison_allowed": True,
                        "price_status": "near_upper",
                        "baseline_p20": 120,
                        "baseline_median": 140,
                        "baseline_p80": 160,
                        "reference_basis": "selected_similar_dates",
                        "selected_price_date_count": 4,
                    },
                    {
                        "product_type": "超级团购",
                        "ota_product_name": "超级团购商品X",
                    },
                    {
                        "product_type": "钟点房",
                        "ota_product_name": "钟点房商品Y",
                    },
                ]
            }
        }
    )
    assert "商品《荣耀战场大床房》" in text
    assert "预期会员折扣系数 0.85" in text
    assert "超级团购商品X" not in text
    assert "钟点房商品Y" not in text
    assert "接近历史上沿" in text

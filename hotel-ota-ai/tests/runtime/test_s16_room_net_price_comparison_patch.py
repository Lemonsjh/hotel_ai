from __future__ import annotations

from runtime.s16_room_net_price_comparison_patch import (
    compare_product_net_price,
    enrich_dynamic_price_comparison,
    render_price_comparison_block,
    replace_price_block,
)


def _reference() -> dict:
    return {
        "room_type_id": "r1",
        "p20": 100,
        "median": 120,
        "p80": 140,
        "sample_count": 20,
    }


def test_full_day_net_price_compares_to_room_transaction_range() -> None:
    compared = compare_product_net_price(
        {
            "product_type": "普通全天房",
            "room_type_id": "r1",
            "estimated_activity_net_price": 150,
        },
        _reference(),
    )
    assert compared["comparison_allowed"] is True
    assert compared["price_status"] == "high"
    assert compared["price_cause_candidate"] is True
    assert compared["action_eligible"] is False


def test_group_buy_is_display_only() -> None:
    compared = compare_product_net_price(
        {
            "product_type": "超级团购",
            "room_type_id": "r1",
            "estimated_activity_net_price": 90,
        },
        _reference(),
    )
    assert compared["comparison_allowed"] is False
    assert compared["comparison_reason"] == "non_full_day_product_reference_only"


def test_high_net_price_is_price_evidence_only_when_other_gates_pass() -> None:
    dynamic = {
        "sales": {"status": "slow", "sales_progress_delta_pp": -12, "judgment_allowed": True},
        "market": {"status": "normal"},
        "market_share": {"status": "normal"},
        "browse": {"status": "normal"},
        "first_conversion": {"status": "normal"},
        "second_conversion": {"is_weak": True, "status": "weak"},
        "promotion_state": {},
        "room_structure": {},
        "product_prices": [
            {
                "product_type": "普通全天房",
                "ota_product_id": "p1",
                "room_type_id": "r1",
                "estimated_activity_net_price": 150,
                "raw_price": 180,
                "commission_rate": 0.12,
                "commission_net_base_price": 158.4,
                "matched_activity_count": 1,
            }
        ],
        "data_limitations": ["当前商品缺少同一商品的可比历史价格，暂不判断价格高低。"],
    }
    baseline = {
        "baseline_package": {"room_type_transaction_references": [_reference()]}
    }
    result = enrich_dynamic_price_comparison(dynamic, baseline)
    assert result["product_prices"][0]["price_status"] == "high"
    assert result["primary_issue"]["code"] == "SECOND_CONVERSION_WEAK_PRICE_HIGH"
    assert result["action_candidates"][0]["action_type"] == "review_product_price"
    assert all("同一商品" not in item for item in result["data_limitations"])


def test_output_shows_calculation_and_room_history_result() -> None:
    report = {
        "dynamic_diagnosis": {
            "product_prices": [
                {
                    "product_type": "普通全天房",
                    "ota_product_name": "电竞大床房标准价",
                    "raw_price": 180,
                    "commission_rate": 0.12,
                    "commission_net_base_price": 158.4,
                    "matched_activity_count": 1,
                    "estimated_activity_net_price": 150,
                    "comparison_allowed": True,
                    "price_status": "high",
                    "baseline_p20": 100,
                    "baseline_median": 120,
                    "baseline_p80": 140,
                }
            ]
        }
    }
    block = render_price_comparison_block(report)
    assert "挂牌 ¥180 → 扣佣后 ¥158 → 活动后预计酒店到手 ¥150" in block
    assert "房型历史成交 P20/中位/P80=¥100/¥120/¥140" in block
    assert "高于房型历史成交区间" in block
    assert "同一商品可比历史" not in block

    old = (
        "四、原因判断\n- 价格：当前商品价格已读取，但暂无同一商品可比历史，"
        "本次不判断偏高或偏低。\n  - 普通全天房｜旧商品：¥180。\n\n五、建议动作"
    )
    replaced = replace_price_block(old, report)
    assert "暂无同一商品可比历史" not in replaced
    assert "活动后预计酒店到手 ¥150" in replaced
    assert "五、建议动作" in replaced

from runtime.algorithms.s5_real_reply import render_s5_real_reply
from runtime.s5_limited_preview_patch import apply_limited_evidence_previews


def _s15():
    return {
        "status": "ok",
        "baseline": {
            "baseline_package": {
                "sample_maturity": "trend_only",
                "room_type_transaction_references": [
                    {
                        "room_type_id": "RT-1",
                        "median": 480,
                        "p20": 420,
                        "sample_count": 7,
                    }
                ],
            }
        },
    }


def _result(candidate):
    return {
        "status": "ok",
        "target_stay_date": "2026-08-06",
        "data_business_date": "2026-08-06",
        "freshness_status": "fresh",
        "candidate_count": 1,
        "eligible_for_s6_count": 0,
        "candidates": [candidate],
    }


def test_limited_s15_evidence_does_not_override_hold_candidate():
    result = apply_limited_evidence_previews(
        _result(
            {
                "room_type_id": "RT-1",
                "ota_product_id": "P-1",
                "current_price": 500,
                "execution_price": 500,
                "actual_change_pct": 0,
                "reference_only": True,
                "strong_pricing_rule_status": "not_triggered",
                "product_sellable": True,
                "guard_valid": True,
                "total_rooms": 10,
                "remaining_room_ratio": 0.20,
                "sales_progress_delta_pp": 10,
                "market_not_cold": True,
                "effective_price_ceiling": 600,
            }
        ),
        s15_result=_s15(),
    )

    candidate = result["candidates"][0]
    assert "limited_evidence_preview" not in candidate
    assert candidate["current_price"] == 500
    assert result["eligible_for_s6_count"] == 0
    assert result["limited_evidence_preview_count"] == 0


def test_limited_s15_evidence_does_not_override_lower_hold_candidate():
    result = apply_limited_evidence_previews(
        _result(
            {
                "room_type_id": "RT-1",
                "ota_product_id": "P-1",
                "current_price": 500,
                "execution_price": 500,
                "actual_change_pct": 0,
                "reference_only": True,
                "strong_pricing_rule_status": "not_triggered",
                "product_sellable": True,
                "guard_valid": True,
                "total_rooms": 10,
                "remaining_room_ratio": 0.60,
                "sales_progress_delta_pp": -10,
                "traffic_status": "healthy",
                "second_conversion_weak": True,
                "price_high": True,
                "effective_price_floor": 400,
            }
        ),
        s15_result=_s15(),
    )

    candidate = result["candidates"][0]
    assert "limited_evidence_preview" not in candidate
    assert candidate["current_price"] == 500
    assert result["eligible_for_s6_count"] == 0


def test_preview_is_not_created_without_fresh_same_day_data():
    result = _result(
        {
            "room_type_id": "RT-1",
            "ota_product_id": "P-1",
            "current_price": 500,
            "reference_only": True,
            "strong_pricing_rule_status": "not_triggered",
            "product_sellable": True,
            "guard_valid": True,
            "total_rooms": 10,
            "remaining_room_ratio": 0.20,
            "sales_progress_delta_pp": 10,
            "market_not_cold": True,
            "effective_price_ceiling": 600,
        }
    )
    result["freshness_status"] = "stale"

    previewed = apply_limited_evidence_previews(result, s15_result=_s15())

    assert previewed["limited_evidence_preview_count"] == 0
    assert "limited_evidence_preview" not in previewed["candidates"][0]


def test_preview_is_not_created_without_room_type_price_reference():
    s15 = _s15()
    s15["baseline"]["baseline_package"]["room_type_transaction_references"] = []
    result = apply_limited_evidence_previews(
        _result(
            {
                "room_type_id": "RT-1",
                "ota_product_id": "P-1",
                "current_price": 500,
                "reference_only": True,
                "strong_pricing_rule_status": "not_triggered",
                "product_sellable": True,
                "guard_valid": True,
                "total_rooms": 10,
                "remaining_room_ratio": 0.20,
                "sales_progress_delta_pp": 10,
                "market_not_cold": True,
                "effective_price_ceiling": 600,
            }
        ),
        s15_result=s15,
    )

    assert result["limited_evidence_preview_count"] == 0


def test_feishu_reply_keeps_hold_candidate_out_of_s6():
    result = apply_limited_evidence_previews(
        _result(
            {
                "room_type_id": "RT-1",
                "ota_product_id": "P-1",
                "ota_product_name": "璞韵大床房",
                "channel": "meituan",
                "current_price": 500,
                "execution_price": 500,
                "actual_change_pct": 0,
                "reference_only": True,
                "strong_pricing_rule_status": "not_triggered",
                "product_sellable": True,
                "guard_valid": True,
                "total_rooms": 10,
                "remaining_room_ratio": 0.20,
                "sales_progress_delta_pp": 10,
                "market_not_cold": True,
                "effective_price_ceiling": 600,
            }
        ),
        s15_result=_s15(),
    )

    reply = render_s5_real_reply(result)

    assert "人工预览价" not in reply
    assert "仅收益参考" in reply

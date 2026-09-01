from runtime.algorithms.s5_real_reply import _compact_product_name, render_s5_real_reply
from runtime.s5_evidence_contract_patch import attach_s5_evidence_contract


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
                    }
                ],
            }
        },
    }


def _candidate(**overrides):
    candidate = {
        "room_type_id": "RT-1",
        "ota_product_id": "P-1",
        "ota_product_name": "璞韵大床房",
        "channel": "meituan",
        "current_price": 500,
        "execution_price": 500,
        "actual_change_pct": 0,
        "reference_only": True,
        "eligibility": "preview_only_strong_rule_not_satisfied",
        "strong_pricing_rule_status": "not_triggered",
        "product_sellable": True,
        "guard_valid": True,
        "total_rooms": 10,
        "remaining_room_ratio": 0.40,
        "sales_progress_delta_pp": 0,
        "baseline_price_median": 480,
        "baseline_price_p20": 420,
        "market_status": "normal",
        "market_not_cold": True,
        "traffic_status": "healthy",
        "second_conversion_weak": False,
        "price_high": False,
    }
    candidate.update(overrides)
    return candidate


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


def test_contract_declares_room_type_price_history_not_same_product_history():
    result = attach_s5_evidence_contract(
        _result(_candidate()),
        s15_result=_s15(),
    )

    candidate = result["candidates"][0]
    assert result["price_reference_scope"] == (
        "unified_room_type_transaction_history"
    )
    assert result["same_ota_product_history_required"] is False
    assert candidate["price_reference_scope"] == (
        "unified_room_type_transaction_history"
    )
    assert candidate["same_ota_product_history_required"] is False
    assert candidate["limited_preview_blockers"] == [
        "room_type_sales_progress_within_hold_band"
    ]


def test_raise_preview_diagnostic_explains_inventory_not_tight():
    result = attach_s5_evidence_contract(
        _result(
            _candidate(
                sales_progress_delta_pp=10,
                remaining_room_ratio=0.50,
                effective_price_ceiling=600,
            )
        ),
        s15_result=_s15(),
    )

    assert result["candidates"][0]["limited_preview_blockers"] == [
        "room_type_inventory_not_tight_for_raise"
    ]


def test_single_room_type_is_not_marked_as_inventory_scope_invalid():
    result = attach_s5_evidence_contract(
        _result(_candidate(total_rooms=1, remaining_room_ratio=1.0)),
        s15_result=_s15(),
    )

    assert "room_type_inventory_scope_invalid" not in result["candidates"][0][
        "limited_preview_blockers"
    ]


def test_insufficient_second_conversion_sample_is_not_described_as_not_weak():
    result = attach_s5_evidence_contract(
        _result(
            _candidate(
                sales_progress_delta_pp=-10,
                remaining_room_ratio=0.80,
                price_high=True,
                second_conversion_evidence_available=True,
                second_conversion_sample_valid=False,
            )
        ),
        s15_result=_s15(),
    )

    assert "second_conversion_data_insufficient" in result["candidates"][0][
        "limited_preview_blockers"
    ]
    assert "second_conversion_not_weak" not in result["candidates"][0][
        "limited_preview_blockers"
    ]


def test_reply_states_room_type_history_and_specific_hold_reason():
    result = attach_s5_evidence_contract(
        _result(_candidate()),
        s15_result=_s15(),
    )

    reply = render_s5_real_reply(result)

    assert "统一房型成交历史价格" in reply
    assert "不要求同一 OTA 商品连续历史价格" in reply
    assert "房型销售进度处于维持区间" in reply
    assert "S5 只生成调价建议" in reply


def test_reply_shows_s6_confirmation_for_an_executable_candidate():
    result = _result(
        _candidate(
            eligibility="eligible_for_s6_dry_run",
            auto_execution_eligible=True,
            s6_confirmation_command="确认调价 PRC-ABC123",
            s6_confirmation_expires_at="2026-08-11T12:00:00",
        )
    )

    reply = render_s5_real_reply(result)

    assert "PRC-ABC123" in reply
    assert "S6" in reply


def test_s5_candidate_heading_prefers_ota_room_type_name():
    assert _compact_product_name(
        {
            "ota_product_name": "璞悦双床房 - 不含早 - 入住当天 18:00 前免费取消 -【贵州大学南校区 5 分钟车程】lo…",
            "ota_room_type_name": "璞悦双床房",
            "room_type_name": "独享・电竞单人间",
            "ota_product_id": "1599630802",
        }
    ) == "璞悦双床房（OTA 商品 ID 1599630802）"

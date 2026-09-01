from __future__ import annotations

from runtime.s5_final_display_contract_patch import render_net_revenue_reference_line
from runtime.s5_product_net_revenue_patch import (
    apply_s5_product_net_revenue,
    calculate_net_revenue,
    extract_activity_factors_decimal,
    select_activity_factor_decimal,
)


def _source(rows: list[dict], status: str = "ok") -> dict:
    return {
        "status": "ok" if status in {"ok", "no_rows"} else "data_gap",
        "payload": {"source_status": status, "rows": rows},
    }


def test_calculation_uses_decimal_without_intermediate_rounding() -> None:
    result = calculate_net_revenue("199.99", "12%", ["0.9", "0.95"])

    assert result["status"] == "ok"
    assert result["commission_net_base_price_exact"] == "175.9912"
    assert result["combined_activity_factor_exact"] == "0.855"
    assert result["member_expected_factor_exact"] == "0.85"
    assert result["estimated_hotel_revenue_exact"] == "127.901604600"


def test_tiered_activity_selects_one_lowest_factor() -> None:
    factors = extract_activity_factors_decimal("会员9.5折，限时8.8折")
    assert [str(item) for item in factors] == ["0.95", "0.88"]
    assert str(select_activity_factor_decimal("会员9.5折，限时8.8折")) == "0.88"


def test_s5_enrichment_preserves_original_repricing_fields() -> None:
    original = {
        "target_stay_date": "2026-08-06",
        "as_of_time": "2026-08-06T13:58:00",
        "candidates": [
            {
                "channel": "meituan",
                "ota_product_id": "P1",
                "room_type_id": "R1",
                "ota_product_name": "商务大床房",
                "current_price": 199.99,
                "candidate_price": 209.99,
                "execution_price": 209.99,
                "actual_change_pct": 0.05,
                "eligibility": "eligible_for_s6_dry_run",
                "quality_flags": [],
            }
        ],
    }
    prices = _source(
        [
            {
                "source_platform": "meituan",
                "ota_product_id": "P1",
                "room_type_id": "R1",
                "commission_rate": "12%",
            }
        ]
    )
    summaries = _source(
        [
            {
                "source_platform": "meituan",
                "activity_id": "A1",
                "activity_name": "早鸟",
                "activity_status": "active",
                "activity_time_range": "2026/08/01 至 2026/08/31",
                "activity_rule_labels": "9折",
            },
            {
                "source_platform": "meituan",
                "activity_id": "A2",
                "activity_name": "会员",
                "activity_status": "进行中",
                "activity_time_range": "全年",
                "activity_rule_labels": "9.5折",
            },
        ]
    )
    details = _source(
        [
            {
                "source_platform": "meituan",
                "activity_id": "A1",
                "ota_product_id": "P1",
                "room_type_id": "R1",
            },
            {
                "source_platform": "meituan",
                "activity_id": "A2",
                "ota_product_id": "P1",
                "room_type_id": "R1",
            },
        ]
    )

    result = apply_s5_product_net_revenue(
        original,
        price_result=prices,
        activity_summary_result=summaries,
        activity_detail_result=details,
    )
    candidate = result["candidates"][0]

    assert candidate["current_price"] == 199.99
    assert candidate["candidate_price"] == 209.99
    assert candidate["execution_price"] == 209.99
    assert candidate["actual_change_pct"] == 0.05
    assert candidate["eligibility"] == "eligible_for_s6_dry_run"
    assert candidate["s5_repricing_price_basis"] == "ota_original_sale_price"
    assert candidate["estimated_hotel_revenue_exact"] == "127.901604600"
    assert candidate["proposed_estimated_hotel_revenue_exact"] == "134.297004600"
    assert candidate["matched_activity_count"] == 2


def test_no_activity_uses_factor_one_when_summary_source_is_empty() -> None:
    result = apply_s5_product_net_revenue(
        {
            "target_stay_date": "2026-08-06",
            "as_of_time": "2026-08-06T13:58:00",
            "candidates": [
                {
                    "channel": "meituan",
                    "ota_product_id": "P1",
                    "room_type_id": "R1",
                    "current_price": 100,
                    "candidate_price": 100,
                    "execution_price": 100,
                    "quality_flags": [],
                }
            ],
        },
        price_result=_source(
            [
                {
                    "ota_product_id": "P1",
                    "room_type_id": "R1",
                    "commission_rate": 0.12,
                }
            ]
        ),
        activity_summary_result=_source([], "no_rows"),
        activity_detail_result=_source([], "no_rows"),
    )
    candidate = result["candidates"][0]

    assert candidate["s5_net_revenue_calculation_status"] == "ok"
    assert candidate["matched_activity_count"] == 0
    assert candidate["combined_activity_factor_exact"] == "1"
    assert candidate["estimated_hotel_revenue_exact"] == "74.8000"


def test_missing_commission_does_not_assume_zero_commission() -> None:
    result = apply_s5_product_net_revenue(
        {
            "target_stay_date": "2026-08-06",
            "as_of_time": "2026-08-06T13:58:00",
            "candidates": [
                {
                    "channel": "meituan",
                    "ota_product_id": "P1",
                    "room_type_id": "R1",
                    "current_price": 100,
                    "candidate_price": 100,
                    "execution_price": 100,
                    "quality_flags": [],
                }
            ],
        },
        price_result=_source(
            [{"ota_product_id": "P1", "room_type_id": "R1"}]
        ),
        activity_summary_result=_source([], "no_rows"),
        activity_detail_result=_source([], "no_rows"),
    )
    candidate = result["candidates"][0]

    assert candidate["s5_net_revenue_calculation_status"] == "unavailable"
    assert (
        candidate["s5_net_revenue_calculation_reason"]
        == "commission_rate_missing_or_invalid"
    )
    assert candidate.get("estimated_hotel_revenue") is None


def test_reply_displays_two_decimals_and_gross_price_boundary() -> None:
    text = render_net_revenue_reference_line(
        {
            "channel": "meituan",
            "current_price": 199.99,
            "s5_net_revenue_calculation_status": "ok",
            "commission_rate_exact": "0.12",
            "commission_net_base_price_exact": "175.9912",
            "combined_activity_factor_exact": "0.855",
            "estimated_hotel_revenue_exact": "150.4724760",
            "proposed_estimated_hotel_revenue_exact": "157.9964760",
            "applied_activities": [
                {
                    "activity_name": "早鸟",
                    "discount_factor_exact": "0.9",
                },
                {
                    "activity_name": "会员",
                    "discount_factor_exact": "0.95",
                },
            ],
        }
    )

    assert text is not None
    assert "净收参考：原卖价 ¥199.99 → 酒店净收参考价 ¥150.47" in text
    assert "佣金 12.00%" in text
    assert "综合 0.8550" in text
    assert "不含用户券" in text

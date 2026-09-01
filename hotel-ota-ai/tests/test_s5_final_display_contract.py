from __future__ import annotations

import pytest

from runtime import s16_meituan_projection_advisory_patch as s16_source
from runtime.s5_final_display_contract_patch import (
    render_net_revenue_reference_line,
    render_net_revenue_with_room_history,
    render_s5_revenue_only_reply,
    s5_market_evidence_from_s16,
    s5_market_line,
)
from runtime.s5_market_heat_contract_patch import _finalize_market_fields


def test_s16_native_projection_remains_authoritative() -> None:
    assert s16_source._projection.__module__ == (
        "runtime.s16_meituan_projection_advisory_patch"
    )

    projection = s16_source._projection(
        current=75,
        baseline=200,
        elapsed=0.50,
    )
    assert projection["projected_full_day"] == pytest.approx(150)
    assert projection["projected_ratio_vs_history"] == pytest.approx(0.75)


def test_s5_trusts_s16_ratio_without_recomputing() -> None:
    evidence = s5_market_evidence_from_s16(
        {
            "dynamic_diagnosis": {
                "meituan_market_proxy": {
                    "current_estimated_market_orders": 100,
                    "baseline_market_orders": 200,
                    "elapsed_day_fraction": 0.50,
                    "market_projection": {
                        "status": "likely_below_history",
                        "projected_full_day": 999,
                        "projected_ratio_vs_history": 0.83,
                        "linear_projection_only": True,
                    },
                }
            }
        }
    )

    # 999 / 200 != 0.83: S5 must trust the S16-published ratio.
    assert evidence["market_heat_ratio"] == pytest.approx(0.83)
    assert evidence["market_orders"] == 999
    assert evidence["historical_daily_median"] == 200
    assert evidence["s5_recomputed_market_heat"] is False


def test_s5_market_line_uses_historical_daily_median_wording() -> None:
    evidence = _finalize_market_fields(
        s5_market_evidence_from_s16(
            {
                "dynamic_diagnosis": {
                    "meituan_market_proxy": {
                        "current_estimated_market_orders": 75,
                        "baseline_market_orders": 200,
                        "elapsed_day_fraction": 0.50,
                        "market_projection": {
                            "status": "likely_below_history",
                            "projected_full_day": 150,
                            "projected_ratio_vs_history": 0.75,
                            "linear_projection_only": True,
                        },
                    }
                }
            }
        ),
        threshold=0.90,
    )

    line = s5_market_line({"s5_market_heat": evidence})
    assert "直接采用 S16 预计/历史比例" in line
    assert "当天已过时间占比 50.0%" in line
    assert "线性预计收盘值 150" in line
    assert "历史日度中位 200" in line


def test_s5_market_line_labels_hourly_completion_projection() -> None:
    evidence = _finalize_market_fields(
        s5_market_evidence_from_s16(
            {
                "dynamic_diagnosis": {
                    "meituan_market_proxy": {
                        "current_estimated_market_orders": 100,
                        "baseline_market_orders": 200,
                        "market_projection": {
                            "status": "near_history",
                            "projected_full_day": 190,
                            "projected_ratio_vs_history": 0.95,
                            "linear_projection_only": False,
                        },
                    }
                }
            }
        ),
        threshold=0.90,
    )

    line = s5_market_line({"s5_market_heat": evidence})
    assert evidence["market_orders_basis"] == (
        "s16_hourly_completion_projected_full_day"
    )
    assert "按可比历史同小时至日终完成率预计收盘值 190" in line
    assert "线性预计收盘值" not in line


def test_meituan_net_reference_shows_all_activity_factors() -> None:
    line = render_net_revenue_reference_line(
        {
            "channel": "meituan",
            "current_price": 199.99,
            "s5_net_revenue_calculation_status": "ok",
            "commission_rate_exact": "0.12",
            "combined_activity_factor_exact": "0.855",
            "estimated_hotel_revenue_exact": "150.4724760",
            "applied_activities": [
                {"activity_name": "早鸟", "discount_factor_exact": "0.9"},
                {"activity_name": "会员", "discount_factor_exact": "0.95"},
            ],
        }
    )

    assert line is not None
    assert "原卖价 ¥199.99 → 酒店净收参考价 ¥150.47" in line
    assert "佣金 12.00%" in line
    assert "有效活动系数 0.90 × 0.95（综合 0.8550）" in line
    assert "不含用户券" in line


def test_meituan_net_reference_is_never_silently_omitted() -> None:
    line = render_net_revenue_reference_line(
        {
            "channel": "meituan",
            "current_price": 452,
            "s5_net_revenue_calculation_status": "unavailable",
            "s5_net_revenue_calculation_reason": (
                "commission_rate_missing_or_invalid"
            ),
        }
    )

    assert line is not None
    assert "原卖价 ¥452.00" in line
    assert "酒店净收参考价暂不可计算" in line
    assert "佣金率缺失或无效" in line


def test_non_meituan_candidate_keeps_existing_behavior() -> None:
    assert (
        render_net_revenue_reference_line(
            {"channel": "ctrip", "current_price": 500}
        )
        is None
    )


def test_s5_output_always_pairs_net_revenue_with_room_history_median() -> None:
    line = render_net_revenue_with_room_history(
        {
            "channel": "meituan", "current_price": 500,
            "s5_net_revenue_calculation_status": "ok",
            "estimated_hotel_revenue": 320, "commission_rate": 0.12,
            "combined_activity_factor": 0.73, "baseline_price_median": 226.66,
        }
    )
    assert "预计净收 ¥320 vs 房型历史成交中位 ¥226.66" in line
    assert "仅收益参考，不是商品级历史比价" in line


def test_s5_net_view_hides_the_ota_list_price() -> None:
    line = render_net_revenue_with_room_history(
        {
            "channel": "meituan",
            "current_price": 500,
            "s5_net_revenue_calculation_status": "ok",
            "estimated_hotel_revenue": 320,
            "commission_rate": 0.12,
            "combined_activity_factor": 0.73,
            "baseline_price_median": 226.66,
        }
    )

    assert "\u51c0\u6536\u9884\u4f30\uff1a\u00a5320" in line
    assert "\u4f1a\u5458\u9884\u671f\u7cfb\u6570 0.85" in line
    assert "\u9884\u8ba1\u51c0\u6536 \u00a5320 vs \u623f\u578b\u5386\u53f2\u6210\u4ea4\u4e2d\u4f4d \u00a5226.66" in line
    assert "\u539f\u5356\u4ef7" not in line
    assert "\u00a5500.00" not in line


def test_s5_triggered_reprice_shows_the_proposed_net_revenue() -> None:
    line = render_net_revenue_with_room_history(
        {
            "channel": "meituan",
            "s5_net_revenue_calculation_status": "ok",
            "estimated_hotel_revenue": 184.03,
            "proposed_estimated_hotel_revenue": 178.51,
            "actual_change_pct": -0.03,
            "commission_rate": 0.12,
            "combined_activity_factor": 0.3851,
            "baseline_price_median": 150.23,
        }
    )

    assert "\u8c03\u4ef7\u6536\u76ca\u53c2\u8003" in line
    assert "\u9884\u8ba1\u51c0\u6536 \u00a5184 \u2192 \u5efa\u8bae\u51c0\u6536 \u00a5179" in line
    assert "\u4e0b\u8c03 3.00%" in line


def test_s5_raise_shows_net_revenue_p80_headroom() -> None:
    line = render_net_revenue_with_room_history(
        {
            "channel": "meituan",
            "s5_net_revenue_calculation_status": "ok",
            "estimated_hotel_revenue": 180,
            "proposed_estimated_hotel_revenue": 185.4,
            "actual_change_pct": 0.03,
            "price_action": "increase",
            "raise_net_revenue_ceiling": 200,
            "commission_rate": 0.12,
            "combined_activity_factor": 0.73,
            "baseline_price_median": 170,
        }
    )

    assert "\u5f53\u524d\u51c0\u6536\u9884\u4f30 \u00a5180 < \u623f\u578b\u5386\u53f2\u6210\u4ea4 P80 \u00d7 98%\uff08\u00a5200\uff09" in line
    assert "\u5b9e\u9645\u6267\u884c\u65f6\u518d\u53cd\u7b97 OTA \u6302\u724c\u4ef7" in line


def test_s5_revenue_only_reply_hides_product_and_market_amounts() -> None:
    result = {
        "candidates": [
            {
                "channel": "meituan",
                "peer_price_evidence": {
                    "own_value": 300,
                    "peer_average": 250,
                },
            }
        ]
    }
    previous = lambda _result: (
        "- \u4ef7\u683c\uff1a\u5f53\u524d\u4ef7 \u00a5500.00 \u2192 \u5019\u9009 \u00a5480.00\n"
        "- \u7f8e\u56e2\u9152\u5e97\u7ea7\u5f15\u6d41\u4ef7\uff08\u4ec5\u4f5c\u5e02\u573a\u80cc\u666f\uff09\uff1a\u672c\u5e97 \u00a5300.00\uff5c\u540c\u884c\u5747\u503c \u00a5250.00\n"
        "  \u53e3\u5f84\uff1a\u9152\u5e97\u6574\u4f53\u6700\u4f4e\u5c55\u793a\u4ef7\u3002\n"
        "- \u6536\u76ca\u53e3\u5f84\uff1a\u5546\u54c1\u539f\u5356\u4ef7\u6298\u7b97\u3002"
    )

    text = render_s5_revenue_only_reply(previous, result)

    assert "\u00a5500.00" not in text
    assert "\u00a5480.00" not in text
    assert "\u00a5300.00" not in text
    assert "\u00a5250.00" not in text
    assert "\u8f83\u540c\u884c\u5747\u503c\u9ad8\u4e8e 20.0%" in text
    assert "\u51c0\u6536\u9884\u4f30\u6309\u6e20\u9053\u4f63\u91d1\u7387" in text


def test_s5_output_marks_missing_net_revenue_instead_of_omitting_it() -> None:
    line = render_net_revenue_with_room_history(
        {"channel": "ctrip", "current_price": 500, "baseline_price_median": 260}
    )
    assert "预计净收 暂不可计算 vs 房型历史成交中位 ¥260.00" in line

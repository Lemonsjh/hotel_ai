from __future__ import annotations

import pytest

from runtime.s5_market_heat_contract_patch import (
    _finalize_market_fields,
    _market_line,
    _refresh_candidate_market_blockers,
    _replace_market_blocker,
    deterministic_market_evidence,
)
from runtime.s5_s16_market_heat_sync_patch import (
    COMPARISON_BASIS,
    PROJECTION_METHOD,
    build_linear_market_projection,
)


def _s16(
    *,
    current_orders=163.2,
    baseline_orders=290.7,
    projected_orders=None,
    projected_ratio=None,
    projection_allowed=False,
    projection_status="unavailable",
    projection_reason="s16_linear_projection_unavailable",
    market_ratio=None,
    market_status="period_not_comparable",
    market_allowed=False,
    elapsed=0.70,
):
    return {
        "dynamic_diagnosis": {
            "market": {
                "estimated_market_orders": current_orders,
                "baseline_median": baseline_orders,
                "market_heat_ratio": market_ratio,
                "status": market_status,
                "comparison_allowed": market_allowed,
            },
            "meituan_market_proxy": {
                "current_estimated_market_orders": current_orders,
                "baseline_market_orders": baseline_orders,
                "elapsed_day_fraction": elapsed,
                "market_projection": {
                    "current_market_orders": current_orders,
                    "projected_market_orders": projected_orders,
                    "projected_full_day": projected_orders,
                    "baseline_market_orders": baseline_orders,
                    "projected_market_heat_ratio": projected_ratio,
                    "projected_ratio_vs_history": projected_ratio,
                    "market_heat_ratio": projected_ratio,
                    "market_status": projection_status,
                    "comparison_allowed": projection_allowed,
                    "comparison_basis": COMPARISON_BASIS,
                    "projection_method": PROJECTION_METHOD,
                    "projection_confidence": "linear_reference",
                    "linear_projection_only": True,
                    "elapsed_day_fraction": elapsed,
                    "market_heat_calculation_status": (
                        "ok" if projection_allowed else "unavailable"
                    ),
                    "market_heat_calculation_reason": (
                        None if projection_allowed else projection_reason
                    ),
                },
            },
        }
    }


def test_s16_linear_projection_publishes_comparable_market_heat():
    projection = build_linear_market_projection(
        current=163.2,
        baseline=290.7,
        elapsed=0.68,
    )

    assert projection["projected_market_orders"] == pytest.approx(240.0)
    assert projection["projected_market_heat_ratio"] == pytest.approx(
        240.0 / 290.7
    )
    assert projection["market_status"] == "cold"
    assert projection["market_not_cold"] is False
    assert projection["comparison_allowed"] is True
    assert projection["comparison_basis"] == COMPARISON_BASIS
    assert projection["projection_method"] == PROJECTION_METHOD
    assert projection["market_heat_calculation_status"] == "ok"
    assert projection["linear_projection_only"] is True


def test_s16_linear_projection_point_nine_boundary_is_not_cold():
    projection = build_linear_market_projection(
        current=45,
        baseline=100,
        elapsed=0.50,
    )

    assert projection["projected_market_heat_ratio"] == 0.90
    assert projection["market_status"] == "normal"
    assert projection["market_not_cold"] is True


def test_s16_linear_projection_requires_minimum_elapsed_day_fraction():
    projection = build_linear_market_projection(
        current=20,
        baseline=100,
        elapsed=0.20,
    )

    assert projection["comparison_allowed"] is False
    assert projection["projected_market_heat_ratio"] is None
    assert projection["market_heat_calculation_reason"] == (
        "elapsed_day_fraction_below_projection_floor"
    )


def test_s5_consumes_s16_projection_ratio_without_recomputing_it():
    evidence = deterministic_market_evidence(
        _s16(
            projected_orders=320,
            projected_ratio=1.01,
            projection_allowed=True,
            projection_status="normal",
            elapsed=0.50,
        )
    )

    # 320 / 290.7 is not 1.01. This proves S5 trusts S16's ratio instead of
    # silently rebuilding a different market heat from display fields.
    assert evidence["market_heat_ratio"] == 1.01
    assert evidence["market_orders"] == 320
    assert evidence["current_market_orders"] == 163.2
    assert evidence["baseline_market_orders"] == 290.7
    assert evidence["market_orders_basis"] == (
        "s16_linear_projected_full_day"
    )
    assert evidence["market_comparison_allowed"] is True
    assert evidence["market_comparison_basis"] == COMPARISON_BASIS
    assert evidence["market_evidence_source"] == (
        "s16.meituan_market_proxy.market_projection"
    )


def test_s5_uses_projection_when_current_daily_period_is_incomplete():
    evidence = deterministic_market_evidence(
        _s16(
            projected_orders=240,
            projected_ratio=240 / 290.7,
            projection_allowed=True,
            projection_status="cold",
            market_status="period_not_comparable",
            market_allowed=False,
            elapsed=0.68,
        )
    )
    finalized = _finalize_market_fields(evidence, threshold=0.90)

    assert finalized["market_heat_calculation_status"] == "ok"
    assert finalized["market_heat_ratio"] == pytest.approx(240 / 290.7)
    assert finalized["market_status"] == "cold"
    assert finalized["market_not_cold"] is False


def test_s5_never_divides_current_cumulative_by_full_day_baseline():
    evidence = deterministic_market_evidence(
        _s16(
            current_orders=163.2,
            baseline_orders=290.7,
            projected_orders=None,
            projected_ratio=None,
            projection_allowed=False,
            projection_reason="s16_linear_projection_unavailable",
            market_status="period_not_comparable",
            market_allowed=False,
        )
    )

    assert evidence["current_market_orders"] == 163.2
    assert evidence["baseline_market_orders"] == 290.7
    assert evidence["market_heat_ratio"] is None
    assert evidence["market_heat_calculation_status"] == "unavailable"
    assert evidence["market_heat_calculation_reason"] == (
        "s16_linear_projection_unavailable"
    )


def test_s5_can_fall_back_to_s16_completed_daily_ratio():
    evidence = deterministic_market_evidence(
        _s16(
            current_orders=305,
            baseline_orders=290.7,
            projected_orders=None,
            projected_ratio=None,
            projection_allowed=False,
            projection_reason="elapsed_day_fraction_not_intraday",
            market_ratio=1.0492,
            market_status="normal",
            market_allowed=True,
        )
    )

    assert evidence["market_heat_ratio"] == 1.0492
    assert evidence["market_orders"] == 305
    assert evidence["market_orders_basis"] == "s16_completed_daily_market"
    assert evidence["market_evidence_source"] == (
        "s16.dynamic_diagnosis.market"
    )


def test_market_not_cold_boundary_is_inclusive_at_point_nine():
    evidence = deterministic_market_evidence(
        _s16(
            projected_orders=261.63,
            projected_ratio=0.90,
            projection_allowed=True,
            projection_status="normal",
        )
    )
    finalized = _finalize_market_fields(evidence, threshold=0.90)

    assert finalized["market_heat_ratio"] == 0.90
    assert finalized["market_status"] == "normal"
    assert finalized["market_not_cold"] is True


def test_below_threshold_blocker_is_not_reported_as_missing_evidence():
    candidate = {
        "market_heat_calculation_status": "ok",
        "market_heat_ratio": 0.82,
        "market_not_cold": False,
    }

    blockers = _replace_market_blocker(
        ["market_not_cold_evidence_missing", "no_raise_price_headroom"],
        candidate,
    )

    assert blockers == [
        "no_raise_price_headroom",
        "market_heat_below_not_cold_threshold",
    ]


def test_final_market_merge_rewrites_stale_missing_blocker():
    candidate = {
        "market_heat_calculation_status": "ok",
        "market_heat_ratio": 0.82,
        "market_not_cold": False,
        "limited_preview_blockers": [
            "market_heat_evidence_missing",
            "no_raise_price_headroom",
        ],
    }

    _refresh_candidate_market_blockers(candidate)

    assert candidate["limited_preview_blockers"] == [
        "no_raise_price_headroom",
        "market_heat_below_not_cold_threshold",
    ]
    assert candidate["limited_preview_evidence_complete"] is False


def test_valid_not_cold_projection_removes_stale_market_blocker():
    candidate = {
        "market_heat_calculation_status": "ok",
        "market_heat_ratio": 1.02,
        "market_not_cold": True,
    }

    blockers = _replace_market_blocker(
        ["market_heat_evidence_missing", "no_raise_price_headroom"],
        candidate,
    )

    assert blockers == ["no_raise_price_headroom"]


def test_missing_projection_uses_missing_evidence_blocker():
    candidate = {
        "market_heat_calculation_status": "unavailable",
        "market_heat_calculation_reason": (
            "s16_linear_projection_unavailable"
        ),
        "market_not_cold": False,
    }

    blockers = _replace_market_blocker(
        ["market_not_cold_evidence_missing"],
        candidate,
    )

    assert blockers == ["market_heat_evidence_missing"]


def test_reply_line_explains_s16_linear_projection_and_comparability():
    evidence = deterministic_market_evidence(
        _s16(
            current_orders=163.2,
            baseline_orders=290.7,
            projected_orders=240,
            projected_ratio=240 / 290.7,
            projection_allowed=True,
            projection_status="cold",
            elapsed=0.68,
        )
    )
    evidence = _finalize_market_fields(evidence, threshold=0.90)
    line = _market_line({"s5_market_heat": evidence})

    assert "当前累计大盘订单 163.2" in line
    assert "经 S16 按已过时间 68.0% 线性外推" in line
    assert "预计全天 240" in line
    assert "历史完整日基线订单 290.7" in line
    assert "大盘热度：0.83" in line
    assert "市场不冷：否" in line
    assert "市场证据可比" in line


def test_reply_line_rejects_raw_current_vs_full_day_division():
    evidence = deterministic_market_evidence(
        _s16(
            projected_orders=None,
            projected_ratio=None,
            projection_allowed=False,
            projection_reason="s16_linear_projection_unavailable",
        )
    )
    evidence = _finalize_market_fields(evidence, threshold=0.90)
    line = _market_line({"s5_market_heat": evidence})

    assert "S16 线性预计全天大盘订单暂不可用" in line
    assert "不使用当前累计订单除以历史完整日基线" in line

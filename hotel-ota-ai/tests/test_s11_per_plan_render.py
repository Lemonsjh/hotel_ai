from __future__ import annotations

from runtime.decisions import promotion as promotion_module
from runtime.s11_per_plan_recommendation_patch import (
    _recommendation_lines,
    build_per_plan_recommendations,
)


def test_s11_render_keeps_all_launches_with_independent_snapshot_times() -> None:
    s8_result = {
        "status": "ok",
        "rows": [
            {
                "plan_id": "090510524719",
                "plan_name": "推广计划 090510524719",
                "launch_id": "launch-store",
                "launch_name": "门店推广",
                "promotion_name": "门店推广",
                "snapshot_time": "2026-08-10 09:46:00",
                "spend_amount": 1191.09,
                "booking_order_count": 8,
                "room_night_count": 10,
                "deterministic_display_metrics": {"roas": 3.1},
            },
            {
                "plan_id": "041617192624",
                "plan_name": "智能计划 041617192624",
                "launch_id": "launch-fast",
                "launch_name": "极速推",
                "promotion_name": "门店推广",
                "snapshot_time": "2026-08-10 17:06:00",
                "spend_amount": 300,
                "booking_order_count": 4,
                "room_night_count": 6,
                "deterministic_display_metrics": {"roas": 7.27},
            },
        ],
    }
    s10_result = {
        "status": "ok",
        "promotion_roi": {
            "platforms": {
                "meituan": {
                    "status": "ok",
                    "items": [
                        {
                            "status": "ok",
                            "plan_id": "090510524719",
                            "plan_name": "推广计划 090510524719",
                            "launch_id": "launch-store",
                            "promotion_status": "投放中",
                            "spend_amount": 1191.09,
                            "booking_order_count": 8,
                            "observed_roas": 3.1,
                            "cpa": 148.89,
                        },
                        {
                            "status": "ok",
                            "plan_id": "041617192624",
                            "plan_name": "智能计划 041617192624",
                            "launch_id": "launch-fast",
                            "promotion_status": "投放中",
                            "spend_amount": 300,
                            "booking_order_count": 4,
                            "observed_roas": 7.27,
                            "cpa": 75,
                        },
                    ],
                }
            }
        },
    }
    result = promotion_module.build_s11_promotion_plan(
        hotel_id="hotel-a",
        message="给我推广建议",
        target_date="2026-08-10",
        as_of_time="2026-08-10 18:00:00",
        s8_result=s8_result,
        s9_result={
            "status": "ok",
            "funnel": {"exposure_uv": 2224, "intention_uv": 276, "pay_order_count": 15},
        },
        s10_result=s10_result,
        s15_result={
            "status": "ok",
            "baseline": {"target_room_nights": 29, "selected_dates": ["2026-07-01"]},
        },
        s16_result={
            "status": "ok",
            "progress_status": "significant_fast",
            "actual_room_nights": 31,
            "target_room_nights": 29,
        },
    )

    recommendations = build_per_plan_recommendations(
        s8_result=s8_result,
        s10_result=s10_result,
        s15_result={"status": "ok"},
        s16_result={"status": "ok", "progress_status": "significant_fast"},
    )
    lines = _recommendation_lines({"per_plan_recommendations": recommendations})

    assert len(lines) == 2
    assert any(line.startswith("门店推广：") and "建议暂停" in line for line in lines)
    assert any(line.startswith("极速推：") and "建议维持" in line for line in lines)
    assert all("launch_id=" not in line for line in lines)

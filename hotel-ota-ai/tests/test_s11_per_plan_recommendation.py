from __future__ import annotations

from runtime.decisions import promotion as promotion_module
from runtime.s11_per_plan_recommendation_patch import build_per_plan_recommendations


def _s8(rows: list[dict]) -> dict:
    return {"status": "ok", "rows": rows}


def _s10(items: list[dict]) -> dict:
    return {
        "status": "ok",
        "promotion_roi": {
            "platforms": {
                "meituan": {
                    "status": "ok",
                    "items": items,
                }
            }
        },
    }


def _s15() -> dict:
    return {
        "status": "ok",
        "baseline": {
            "target_room_nights": 29,
            "selected_dates": ["2026-07-01", "2026-07-02"],
        },
    }


def _s16(status: str) -> dict:
    return {"status": "ok", "progress_status": status}


def _rows() -> list[dict]:
    return [
        {
            "plan_id": "090510524719",
            "plan_name": "推广计划 090510524719",
            "launch_id": "launch-store-20240905099",
            "launch_name": "门店推广 20240905099",
            "promotion_name": "门店推广",
            "snapshot_time": "2026-08-10 09:46:00",
        },
        {
            "plan_id": "041617192624",
            "plan_name": "智能计划 041617192624",
            "launch_id": "launch-fast-202604167df",
            "launch_name": "极速推 202604167df",
            "promotion_name": "极速推",
            "snapshot_time": "2026-08-10 17:06:00",
        },
    ]


def _items() -> list[dict]:
    return [
        {
            "status": "ok",
            "plan_id": "090510524719",
            "plan_name": "推广计划 090510524719",
            "launch_id": "launch-store-20240905099",
            "promotion_status": "投放中",
            "observed_roas": 3.10,
            "cpa": 148.89,
        },
        {
            "status": "ok",
            "plan_id": "041617192624",
            "plan_name": "智能计划 041617192624",
            "launch_id": "launch-fast-202604167df",
            "promotion_status": "投放中",
            "observed_roas": 7.27,
            "cpa": 75.0,
        },
    ]


def test_ahead_sales_recommends_pause_for_strictly_dominated_running_plan() -> None:
    recommendations = build_per_plan_recommendations(
        s8_result=_s8(_rows()),
        s10_result=_s10(_items()),
        s15_result=_s15(),
        s16_result=_s16("significant_fast"),
    )

    by_launch = {item["launch_id"]: item for item in recommendations}
    weaker = by_launch["launch-store-20240905099"]
    stronger = by_launch["launch-fast-202604167df"]

    assert weaker["suggested_action"] == "暂停"
    assert weaker["dominated_by_launch_id"] == "launch-fast-202604167df"
    assert weaker["source_snapshot_time"] == "2026-08-10 09:46:00"
    assert stronger["suggested_action"] == "维持"
    assert stronger["source_snapshot_time"] == "2026-08-10 17:06:00"


def test_paused_efficient_plan_can_be_recommended_for_recovery_when_sales_behind() -> None:
    rows = [_rows()[0]]
    items = [
        {
            "status": "ok",
            "plan_id": rows[0]["plan_id"],
            "launch_id": rows[0]["launch_id"],
            "promotion_status": "PAUSED",
            "observed_roas": 3.1,
            "cpa": 148.89,
        }
    ]

    recommendation = build_per_plan_recommendations(
        s8_result=_s8(rows),
        s10_result=_s10(items),
        s15_result=_s15(),
        s16_result=_s16("behind"),
    )[0]

    assert recommendation["current_state"] == "paused"
    assert recommendation["suggested_action"] == "恢复"


def test_unknown_promotion_state_never_guesses_pause_or_recover() -> None:
    items = [dict(_items()[0], promotion_status=None)]
    recommendation = build_per_plan_recommendations(
        s8_result=_s8([_rows()[0]]),
        s10_result=_s10(items),
        s15_result=_s15(),
        s16_result=_s16("behind"),
    )[0]

    assert recommendation["current_state"] == "unknown"
    assert recommendation["suggested_action"] == "观察"


def test_missing_formal_evidence_degrades_plan_action_to_observe() -> None:
    recommendation = build_per_plan_recommendations(
        s8_result=_s8([_rows()[0]]),
        s10_result=_s10([_items()[0]]),
        s15_result={"status": "data_gap"},
        s16_result=_s16("significant_fast"),
    )[0]

    assert recommendation["formal_evidence_complete"] is False
    assert recommendation["suggested_action"] == "观察"


def test_advisory_question_does_not_force_requested_pause_action() -> None:
    row = _rows()[1]
    item = _items()[1]
    result = promotion_module.build_s11_promotion_plan(
        hotel_id="hotel-a",
        message="是否应该暂停智能计划 041617192624",
        target_date="2026-08-10",
        as_of_time="2026-08-10 18:00:00",
        s8_result=_s8([row]),
        s9_result={"status": "ok", "funnel": {}},
        s10_result=_s10([item]),
        s15_result=_s15(),
        s16_result=_s16("significant_fast"),
    )

    plan = result["promotion_plan"]
    assert plan["scope_resolution"] == "resolved"
    recommendation = build_per_plan_recommendations(
        s8_result=_s8([row]),
        s10_result=_s10([item]),
        s15_result=_s15(),
        s16_result=_s16("significant_fast"),
    )[0]
    assert recommendation["suggested_action"] == "维持"
    assert plan["write_performed"] is False

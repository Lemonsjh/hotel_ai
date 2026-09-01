from __future__ import annotations

from pathlib import Path

from runtime.algorithms.s11_promotion_plan import build_s11_promotion_plan


ROOT = Path(__file__).resolve().parents[1]
S11_PATCH = ROOT / "runtime" / "s11_readonly_plan_patch.py"


def _inputs() -> dict:
    return {
        "hotel_id": "hotel-1",
        "message": "给我推广建议",
        "target_date": "2026-08-09",
        "as_of_time": "2026-08-09T20:00:00+08:00",
        "s8_result": {"status": "ok", "rows": []},
        "s9_result": {
            "status": "ok",
            "funnel": {"exposure_uv": 2224, "intention_uv": 276, "pay_order_count": 15},
        },
        "s10_result": {"status": "ok", "promotion_roi": {"platforms": {"meituan": {"items": []}}}},
        "s15_result": {
            "status": "ok",
            "baseline": {
                "target_room_nights": 31,
                "selected_dates": ["2026-07-12", "2026-07-19", "2026-07-26"],
                "baseline_confidence": "object_level",
            },
        },
        "s16_result": {
            "status": "ok",
            "progress_status": "ahead",
            "actual_room_nights": 31,
            "checkpoint_target_room_nights": 22.6,
            "room_night_gap": 8.4,
            "target_room_nights": 31,
        },
    }


def test_s15_is_formal_operating_evidence_and_s9_is_reference() -> None:
    result = build_s11_promotion_plan(**_inputs())

    assert result["status"] == "suggestion_only"
    plan = result["promotion_plan"]
    assert set(plan["source_alignment"]["sources"]) == {"S8", "S10", "S15", "S16"}
    assert plan["source_alignment"]["sources"]["S15"] == "ok"
    assert plan["source_alignment"]["reference_sources"] == {"S9": "ok"}
    assert plan["source_alignment"]["reference_policy"]["S9"] == "advisory_traffic_context_only_not_a_promotion_gate"

    observations = {item["source"]: item for item in plan["observation_metrics"] if item["source"] in {"S9", "S15", "S16"}}
    assert observations["S9"]["reference_only"] is True
    assert observations["S9"]["role"] == "advisory_reference"
    assert observations["S15"]["operating_evidence"] is True
    assert observations["S15"]["role"] == "operating_evidence"
    assert observations["S15"]["target_room_nights"] == 31
    assert observations["S15"]["sample_count"] == 3
    assert observations["S16"]["sales_status"] == "ahead"
    assert observations["S16"]["actual_room_nights"] == 31
    assert observations["S16"]["checkpoint_room_gap"] == 8.4


def test_missing_s9_does_not_create_formal_evidence_gap() -> None:
    values = _inputs()
    values["s9_result"] = {"status": "data_gap", "reason": "traffic_unavailable"}
    result = build_s11_promotion_plan(**values)

    assert result["status"] == "suggestion_only"
    plan = result["promotion_plan"]
    assert plan["source_alignment"]["reference_sources"]["S9"] == "data_gap"
    assert all("S9" not in risk for risk in plan["risks"] if "正式经营/推广证据当前不完整" in risk)


def test_missing_s15_is_exposed_as_formal_evidence_gap() -> None:
    values = _inputs()
    values["s15_result"] = {"status": "data_gap", "reason": "baseline_unavailable"}
    result = build_s11_promotion_plan(**values)

    assert result["status"] == "suggestion_only"
    plan = result["promotion_plan"]
    assert plan["source_alignment"]["sources"]["S15"] == "data_gap"
    assert "S15" not in plan["source_alignment"]["reference_sources"]
    assert any("S15" in risk for risk in plan["risks"] if "正式经营/推广证据当前不完整" in risk)


def test_healthy_s9_cannot_rescue_all_missing_formal_sources() -> None:
    result = build_s11_promotion_plan(
        hotel_id="hotel-1",
        message="给我推广建议",
        target_date="2026-08-09",
        as_of_time="2026-08-09T20:00:00+08:00",
        s8_result={"status": "data_gap"},
        s9_result={
            "status": "ok",
            "funnel": {"exposure_uv": 2224, "intention_uv": 276, "pay_order_count": 15},
        },
        s10_result={"status": "data_gap"},
        s15_result={"status": "data_gap"},
        s16_result={"status": "data_gap"},
    )

    assert result["status"] == "data_gap"
    plan = result["promotion_plan"]
    assert plan["source_alignment"]["reference_sources"]["S9"] == "ok"
    assert any(item.get("source") == "S9" for item in plan["observation_metrics"])
    assert set(plan["source_alignment"]["sources"]) == {"S8", "S10", "S15", "S16"}


def test_s11_route_defaults_real_db_and_auto_queries_s15_before_s16() -> None:
    text = S11_PATCH.read_text(encoding="utf-8")

    assert 'os.environ.get("HOTEL_OTA_DB")' in text
    assert "or DEFAULT_DB" in text
    assert 'values["db"] = str(db_path)' in text
    assert "_query_s15_baseline(" in text
    assert "_query_s16_progress(" in text
    assert text.index("_query_s15_baseline(") < text.index("_query_s16_progress(")

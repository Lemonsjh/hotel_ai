from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from runtime.s01_s17_exact_route_patch import exact_skill_code, route_target_for_code
from runtime.s09_traffic_conversion_real import build_30d_platform, build_daily_platform
from runtime.s12_reputation_real import S12MySQLSource, build_detail_platform, build_overview_row, build_s12_report
from runtime.s13_data_rules_patch import queue_priority, s12_detail_priority


def _metric(code: str, value: float, unit: str) -> dict[str, object]:
    return {
        "hotel_id": "hotel-puyue",
        "platform_scope": "meituan",
        "business_date": "2026-08-03",
        "metric_code": code,
        "metric_value": value,
        "metric_unit": unit,
        "snapshot_time": "2026-08-03 20:00:00",
    }


def test_s09_meituan_flow_uses_flow_rows_without_double_counting() -> None:
    rows = [
        _metric("FLOW_EXPOSURE_UV", 1000, "person"),
        _metric("FLOW_INTENTION_UV", 100, "person"),
        _metric("FLOW_PAY_ORDER_CNT", 5, "order"),
        _metric("FLOW_INTENTION_PER_EXPOSURE", 10, "%"),
        _metric("FLOW_PAY_ORDER_PER_INTENTION", 5, "%"),
        _metric("INTENTION_UV", 100, "person"),
        _metric("PAY_ORDER_CNT", 5, "order"),
        _metric("PAY_ORDER_CNT_UV", 5, "%"),
    ]
    result = build_daily_platform("meituan", rows)
    stages = result["stages"]
    assert stages["exposure_uv"] == 1000
    assert stages["browse_uv"] == 100
    assert stages["pay_orders"] == 5
    assert stages["exposure_to_browse_ratio"] == pytest.approx(0.10)
    assert stages["browse_to_pay_ratio"] == pytest.approx(0.05)
    assert result["source_conflicts"] == []
    assert result["first_stage_quality"] == "stable"
    assert result["second_stage_quality"] == "stable"


def test_s09_ctrip_preserves_impression_to_person_semantics() -> None:
    rows = [
        {
            **_metric("list_page_exposure_count", 1000, "count"),
            "platform_scope": "ctrip",
        },
        {
            **_metric("detail_page_visitor_count", 100, "person"),
            "platform_scope": "ctrip",
        },
        {
            **_metric("order_submit_count", 10, "order"),
            "platform_scope": "ctrip",
        },
        {
            **_metric("exposure_conversion_rate", 10, "%"),
            "platform_scope": "ctrip",
        },
        {
            **_metric("order_conversion_rate", 10, "%"),
            "platform_scope": "ctrip",
        },
    ]
    result = build_daily_platform("ctrip", rows)
    stages = result["stages"]
    assert stages["list_to_detail_ratio"] == pytest.approx(0.10)
    assert stages["detail_to_submit_ratio"] == pytest.approx(0.10)
    assert stages["first_denominator_kind"] == "impression_count"


def test_s09_ctrip_30d_keeps_three_adjacent_stages_and_single_window() -> None:
    result = build_30d_platform(
        "ctrip",
        {
            "period_start_date": "2026-07-05",
            "period_end_date": "2026-08-03",
            "list_exposure": 1000,
            "detail_exposure": 100,
            "order_filling_count": 20,
            "order_submit_count": 10,
            "exposure_to_detail_rate_pct": 10,
            "detail_to_order_rate_pct": 20,
            "order_to_submit_rate_pct": 50,
        },
    )
    assert result is not None
    stages = result["stages"]
    assert stages["list_to_detail_ratio"] == pytest.approx(0.10)
    assert stages["detail_to_order_filling_ratio"] == pytest.approx(0.20)
    assert stages["order_filling_to_submit_ratio"] == pytest.approx(0.50)
    assert stages["detail_to_submit_ratio"] == pytest.approx(0.10)
    assert result["single_window_only"] is True


def test_s12_overview_and_detail_are_separate_populations() -> None:
    overview = build_overview_row(
        "meituan",
        {
            "review_score": 4.8,
            "review_score_max": 5,
            "total_review_count": 100,
            "unreplied_review_count": 10,
            "negative_review_count": 5,
        },
    )
    detail = build_detail_platform(
        "meituan",
        [
            {
                "review_id": "r1",
                "review_score": 1,
                "review_content": "房间卫生差",
                "is_replied": 0,
                "is_negative_review": 1,
                "review_time": "2026-07-01 10:00:00",
            },
            {
                "review_id": "r2",
                "review_score": 5,
                "review_content": None,
                "is_replied": 0,
                "is_negative_review": 0,
                "review_time": "2026-07-02 10:00:00",
            },
        ],
    )
    assert overview["unreplied_rate"] == pytest.approx(0.10)
    assert overview["source_negative_rate"] == pytest.approx(0.05)
    assert detail["unreplied_rate"] == pytest.approx(1.0)
    assert detail["source_negative_rate"] == pytest.approx(0.5)
    assert detail["low_score_rate"] == pytest.approx(0.5)
    assert detail["pure_rating_unreplied_count"] == 1


def test_s12_overview_uses_review_platform_and_keeps_summary_authoritative() -> None:
    source = object.__new__(S12MySQLSource)
    source._columns = lambda table: {
        "id", "hotel_id", "snapshot_time", "channel_source", "review_platform",
        "review_score", "review_score_max", "total_review_count",
        "unreplied_review_count", "negative_review_count",
    }
    source._query = lambda sql, params: [
        {
            "id": 1, "hotel_id": "puyue", "snapshot_time": "2026-08-04 10:20:30",
            "channel_source": "meituan", "review_platform": "meituan",
            "total_review_count": 2393, "unreplied_review_count": 19,
            "negative_review_count": 28,
        },
        {
            "id": 2, "hotel_id": "puyue", "snapshot_time": "2026-08-04 10:20:30",
            "channel_source": "meituan", "review_platform": "dianping",
            "total_review_count": 11, "unreplied_review_count": 3,
            "negative_review_count": 0,
        },
    ]
    rows, _ = source.overview_rows(
        "meituan_ota_review_overview",
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 4),
        default_platform="meituan",
    )
    assert {(row["platform"], row["unreplied_review_count"]) for row in rows} == {
        ("meituan", 19), ("dianping", 3),
    }

    class SummaryAndDetailSource:
        def overview_rows(self, *args, **kwargs):
            return rows, 0

        def detail_rows(self, *args, **kwargs):
            return ([
                {"platform": "meituan", "review_id": "r-1", "is_replied": 0,
                 "review_score": 5, "review_content": "ok"},
            ] * 65), 0

        def ranking_rows(self, *args, **kwargs):
            return [], 0

    report = build_s12_report(
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 4),
        source=SummaryAndDetailSource(),
    )
    meituan = report["platforms"]["meituan"]
    assert meituan["authoritative_unreplied_review_count"] == 19
    assert meituan["unreplied_count_quality"] == "overview_detail_mismatch"


def test_s12_queue_uses_risk_flags_even_without_topic_keyword() -> None:
    risk = {
        "review_id": "risk",
        "review_score": 5,
        "review_content": "酒店泄露了我的隐私",
        "is_negative_review": 0,
        "review_time": "2026-07-03 10:00:00",
    }
    low = {
        "review_id": "low",
        "review_score": 1,
        "review_content": "体验不好",
        "is_negative_review": 0,
        "review_time": "2026-07-01 10:00:00",
    }
    assert s12_detail_priority(risk)[0] == 0
    assert s12_detail_priority(low)[0] == 2


def test_s13_queue_keeps_pure_rating_and_prioritizes_risk_then_oldest() -> None:
    records = [
        SimpleNamespace(
            review_id="pure",
            review_content=None,
            star_rating=5,
            review_time="2026-07-01T10:00:00+08:00",
            source_snapshot="2026-07-01T10:00:00+08:00",
        ),
        SimpleNamespace(
            review_id="risk",
            review_content="要求赔偿并报警",
            star_rating=5,
            review_time="2026-07-03T10:00:00+08:00",
            source_snapshot="2026-07-03T10:00:00+08:00",
        ),
        SimpleNamespace(
            review_id="low-old",
            review_content="很差",
            star_rating=1,
            review_time="2026-06-30T10:00:00+08:00",
            source_snapshot="2026-06-30T10:00:00+08:00",
        ),
        SimpleNamespace(
            review_id="low-new",
            review_content="很差",
            star_rating=1,
            review_time="2026-07-02T10:00:00+08:00",
            source_snapshot="2026-07-02T10:00:00+08:00",
        ),
    ]
    ordered = sorted(records, key=queue_priority)
    assert [item.review_id for item in ordered] == ["risk", "low-old", "low-new", "pure"]


def test_exact_s1_to_s17_are_skill_codes_not_numeric_menu_ids() -> None:
    for number in range(1, 18):
        code, suffix = exact_skill_code(f"@酒店数字员工测试机一号 s{number}")
        assert code == f"S{number}"
        assert suffix == ""
        target = route_target_for_code(code)
        assert target["kind"] in {"rewrite", "custom", "entry"}


def test_exact_code_preserves_followup_suffix_and_s11_routes_to_suggestions() -> None:
    code, suffix = exact_skill_code("s13 展开待回复评论")
    assert code == "S13"
    assert suffix == "展开待回复评论"
    target = route_target_for_code("S11")
    assert target["kind"] == "entry"
    assert target["intent"] == "promotion_suggestion"

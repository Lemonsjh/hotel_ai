from __future__ import annotations

from types import SimpleNamespace

import pytest

from runtime import p0_route_ownership_patch as route_patch
from runtime.sql_fact_query import (
    QUERY_TIMEOUT_MS,
    FactSqlBlocked,
    _prepare_fact_sql,
    _sensitive_column_references,
)


def test_fact_sql_uses_20_second_mysql_timeout_and_default_limit() -> None:
    prepared = _prepare_fact_sql(
        "SELECT SUM(spend_amount) AS spend_amount "
        "FROM meituan_ota_promotion_performance_30d "
        "WHERE hotel_id = :hotel_id"
    )

    assert QUERY_TIMEOUT_MS == 20_000
    assert prepared["table"] == "meituan_ota_promotion_performance_30d"
    assert prepared["statement"].endswith("LIMIT 200")
    assert "MAX_EXECUTION_TIME(20000)" in prepared["executable"]
    assert ":hotel_id" not in prepared["executable"]
    assert "%s" in prepared["executable"]


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("UPDATE jy01_hotel_statistics_daily SET adr=1 WHERE hotel_id=:hotel_id", "select_only"),
        (
            "SELECT adr FROM jy01_hotel_statistics_daily WHERE hotel_id=:hotel_id; SELECT 1",
            "multiple_statements_not_allowed",
        ),
        ("SELECT adr FROM jy01_hotel_statistics_daily", "exact_hotel_scope_required"),
        (
            "SELECT a.adr FROM jy01_hotel_statistics_daily a JOIN jl01_room_type_performance_daily b ON a.hotel_id=b.hotel_id WHERE a.hotel_id=:hotel_id",
            "joins_not_allowed_v1",
        ),
        (
            "SELECT adr FROM jy01_hotel_statistics_daily WHERE hotel_id=:hotel_id UNION SELECT adr FROM jl01_room_type_performance_daily",
            "subqueries_not_allowed",
        ),
        (
            "SELECT * FROM jy01_hotel_statistics_daily WHERE hotel_id=:hotel_id",
            "wildcard_projection_not_allowed",
        ),
    ],
)
def test_fact_sql_blocks_unsafe_or_unbounded_shapes(sql: str, reason: str) -> None:
    with pytest.raises(FactSqlBlocked) as exc_info:
        _prepare_fact_sql(sql)
    assert exc_info.value.reason == reason


def test_fact_sql_flags_sensitive_columns_before_execution() -> None:
    references = _sensitive_column_references(
        "SELECT guest_name, contact FROM jd01_booking_detail WHERE hotel_id=:hotel_id",
        ["hotel_id", "guest_name", "contact", "room_type_name"],
    )
    assert references == ["guest_name", "contact"]


def test_s8_daily_native_gap_is_marked_for_bounded_readonly_fallback() -> None:
    fake_router = SimpleNamespace(
        _detect_intent=lambda _message: "s8_promotion_display",
        _base_result=lambda _intent, role, output_profile=None: {
            "auth_role": role,
            "output_profile": output_profile,
        },
        agent_id_for_node=lambda _node: "agent-s8",
        render_feishu_output=lambda result, _profile: result,
        build_feishu_send_payload=lambda result, role=None: {
            "text": result.get("summary"),
            "role": role,
        },
    )

    wrapped = route_patch._wrap_s8_route(
        fake_router,
        lambda _message, *_args, **_kwargs: {"status": "unexpected_previous_route"},
    )
    result = wrapped(
        "今天的门店推广总共花了多少钱",
        role="owner",
        hotel_id="hotel-puyue",
        render=False,
    )

    assert result["status"] == "data_gap"
    assert result["blocked_reason"] == "s8_daily_granularity_unavailable"
    assert result["fallback_eligible"] is True
    assert result["fallback_type"] == "read_only_fact_sql"
    assert result["fallback_reason"] == "native_time_granularity_missing"
    assert result["continuation_allowed"] is True
    assert result["continuation_trigger"] == "继续查询"
    assert result["response_budget_seconds"] == 20
    assert result["write_performed"] is False
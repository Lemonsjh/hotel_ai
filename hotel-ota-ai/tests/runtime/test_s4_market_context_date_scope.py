from __future__ import annotations

from unittest.mock import patch

from runtime import feishu_command_router as router
from runtime import s4_market_heat_contract_patch as contract


def _run_market_context(market: dict) -> dict:
    contract._install_router_patch()
    with patch.object(router, "_capture_runtime_emit", return_value=market):
        return router._market_context_demo(
            role="operator",
            output_profile=None,
            db_path=":memory:",
            hotel_id="hotel-a",
        )


def test_s4_does_not_inherit_demo_date_when_market_query_has_none() -> None:
    result = _run_market_context({"status": "data_gap"})

    assert result["business_date"] is None
    assert result["data_business_date"] is None
    assert "demo_business_date" not in result


def test_s4_keeps_its_own_market_query_date() -> None:
    result = _run_market_context(
        {
            "status": "ok",
            "business_date": "2026-08-28",
            "data_business_date": "2026-08-28",
        }
    )

    assert result["business_date"] == "2026-08-28"
    assert result["data_business_date"] == "2026-08-28"
    assert "demo_business_date" not in result

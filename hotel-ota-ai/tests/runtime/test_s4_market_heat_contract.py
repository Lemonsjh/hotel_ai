from __future__ import annotations

from runtime import s4_market_heat_contract_patch as contract


def _s16_projection(ratio: float = 0.90) -> dict:
    return {
        "dynamic_diagnosis": {
            "meituan_market_proxy": {
                "current_estimated_market_orders": 203.2,
                "market_projection": {
                    "comparison_allowed": True,
                    "market_heat_calculation_status": "ok",
                    "projected_market_heat_ratio": ratio,
                    "market_heat_ratio": ratio,
                    "projected_market_orders": 260.76,
                    "projected_full_day": 260.76,
                    "current_market_orders": 203.2,
                    "baseline_market_orders": 290.7,
                    "elapsed_day_fraction": 0.779,
                    "market_status": "normal",
                    "market_orders_basis": (
                        "s16_linear_projected_full_day"
                    ),
                },
            }
        }
    }


def _event_only_context() -> dict:
    return {
        "status": "partial",
        "event_context": {
            "status": "ok",
            "local_event_count": 5,
            "event_heat_level": "low",
        },
        "regional_heat_context": {
            "status": "partial",
            "regional_heat_index": 45,
            "component_scores": {
                "event_heat": 45,
                "ota_conversion": None,
                "historical_same_period": None,
                "competitor_signal": None,
                "booking_progress": None,
            },
            "missing_fields": [
                "ota_conversion",
                "historical_same_period",
                "competitor_signal",
                "booking_progress",
            ],
        },
    }


def test_event_score_is_not_market_heat_or_demand_index() -> None:
    result = contract.annotate_market_context_result(
        _event_only_context(),
        _s16_projection(),
    )

    assert result["market_heat_ratio"] == 0.90
    assert result["market_heat_source"] == "S16"
    assert result["event_heat_score"] == 45
    assert result["market_heat_fallback_used"] is False
    assert result["regional_heat_context"]["display_label"] == (
        "周边事件单项分"
    )
    assert result["regional_heat_context"]["is_market_heat"] is False
    assert result["regional_heat_context"]["is_demand_index"] is False
    assert result["demand_index"] is None
    assert result["demand_index_status"] == "data_gap"


def test_market_heat_never_falls_back_to_event_score() -> None:
    result = contract.annotate_market_context_result(
        _event_only_context(),
        {"status": "data_gap"},
    )

    assert result["event_heat_score"] == 45
    assert result["market_heat_ratio"] is None
    assert result["market_status"] == "unavailable"
    assert result["market_heat_calculation_status"] == "unavailable"
    assert result["market_heat_fallback_used"] is False
    assert result["market_heat_event_score_fallback_allowed"] is False


def test_partial_environment_composite_is_not_market_heat() -> None:
    base = _event_only_context()
    base["regional_heat_context"]["component_scores"][
        "ota_conversion"
    ] = 62
    base["regional_heat_context"]["regional_heat_index"] = 53.5

    result = contract.annotate_market_context_result(
        base,
        _s16_projection(),
    )
    regional = result["regional_heat_context"]

    assert regional["display_label"] == "区域环境综合信号"
    assert regional["score_semantics"] == (
        "partial_environment_composite"
    )
    assert regional["is_market_heat"] is False
    assert regional["market_heat_eligible"] is False


def test_s4_text_separates_market_and_event_scores() -> None:
    result = contract.annotate_market_context_result(
        _event_only_context(),
        _s16_projection(),
    )
    text = contract.render_s4_market_text(result)

    assert "大盘热度：0.90" in text
    assert "周边事件单项分：45" in text
    assert "不代表大盘热度或需求指数" in text
    assert "大盘热度：45" not in text
    assert "市场热度：45" not in text
    assert "需求指数：45" not in text


def test_install_patches_prebound_router_reference() -> None:
    from runtime import feishu_command_router as router
    from runtime.decisions import calendar

    assert router.market_context is calendar.market_context
    assert "市场热度" in router.MARKET_CONTEXT_PHRASES
    assert "大盘热度" in router.MARKET_CONTEXT_PHRASES

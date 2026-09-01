from __future__ import annotations

import pytest

from runtime.s09_metric_fallback_patch import (
    apply_meituan_metric_fallback,
)


def _row(code: str, value, unit: str = "单") -> dict[str, object]:
    return {
        "id": 1,
        "metric_code": code,
        "metric_value": value,
        "metric_unit": unit,
        "snapshot_time": "2026-08-06 14:20:37",
    }


def _base(*, browse=204, pay=None) -> dict[str, object]:
    return {
        "platform": "meituan",
        "stages": {
            "exposure_uv": 1339,
            "browse_uv": browse,
            "pay_orders": pay,
            "source_exposure_to_browse_ratio": 204 / 1339,
            "source_browse_to_pay_ratio": None,
        },
        "data_gaps": ["missing_metric:second_stage"],
        "source_conflicts": [],
    }


def test_pay_order_falls_back_and_recomputes_second_conversion() -> None:
    result = apply_meituan_metric_fallback(
        _base(),
        [
            _row("FLOW_PAY_ORDER_CNT", None),
            _row("PAY_ORDER_CNT", 15),
        ],
    )
    stages = result["stages"]
    assert stages["pay_orders"] == 15
    assert stages["pay_orders_source"] == "PAY_ORDER_CNT"
    assert stages["pay_orders_fallback_used"] is True
    assert stages["browse_to_pay_ratio"] == pytest.approx(15 / 204)
    assert result["second_stage_quality"] == "stable"
    assert result["data_gaps"] == []


def test_browse_falls_back_and_both_ratios_are_recomputed() -> None:
    result = apply_meituan_metric_fallback(
        _base(browse=None, pay=15),
        [
            _row("FLOW_INTENTION_UV", None, "人"),
            _row("INTENTION_UV", 204, "人"),
        ],
    )
    stages = result["stages"]
    assert stages["browse_uv"] == 204
    assert stages["browse_uv_source"] == "INTENTION_UV"
    assert stages["exposure_to_browse_ratio"] == pytest.approx(204 / 1339)
    assert stages["browse_to_pay_ratio"] == pytest.approx(15 / 204)


def test_primary_values_remain_authoritative() -> None:
    result = apply_meituan_metric_fallback(
        _base(browse=200, pay=12),
        [
            _row("INTENTION_UV", 204, "人"),
            _row("PAY_ORDER_CNT", 15),
        ],
    )
    stages = result["stages"]
    assert stages["browse_uv"] == 200
    assert stages["pay_orders"] == 12
    assert stages["browse_uv_source"] == "FLOW_INTENTION_UV"
    assert stages["pay_orders_source"] == "FLOW_PAY_ORDER_CNT"
    assert result["metric_fallbacks"] == []

from __future__ import annotations

import pytest

from runtime.s09_baseline_classification_patch import (
    _history_baseline,
    _peer_second,
    _select_comparable,
    diagnose_platform,
)


def _day(
    business_date: str,
    *,
    first: float = 0.10,
    second: float = 0.05,
    browse: float = 100,
) -> dict[str, object]:
    return {
        "business_date": business_date,
        "stages": {
            "browse_uv": browse,
            "exposure_to_browse_ratio": first,
            "browse_to_pay_ratio": second,
        },
    }


def _meituan_item(
    *,
    current_first: float = 0.08,
    current_second: float = 0.03,
    peer_second: float = 0.04,
) -> dict[str, object]:
    return {
        "platform": "meituan",
        "algorithm_platform": "meituan",
        "daily": {
            "business_date": "2026-08-03",
            "stages": {
                "exposure_uv": 1000,
                "browse_uv": 100,
                "pay_orders": 3,
                "exposure_to_browse_ratio": current_first,
                "browse_to_pay_ratio": current_second,
            },
            "source_conflicts": [],
        },
        "daily_history": [
            _day("2026-07-27", first=0.10, second=0.05, browse=100),
            _day("2026-07-20", first=0.12, second=0.06, browse=120),
            _day("2026-07-13", first=0.09, second=0.04, browse=90),
            _day("2026-07-26", first=0.50, second=0.50, browse=500),
        ],
        "rolling_30d": {
            "stages": {"peer_browse_to_pay_ratio": peer_second},
            "source_conflicts": [],
        },
    }


def test_direct_daily_history_uses_same_weekday_without_all_history_mix() -> None:
    baseline = _history_baseline(_meituan_item())
    assert baseline["selected_dates"] == [
        "2026-07-13",
        "2026-07-20",
        "2026-07-27",
    ]
    assert baseline["sample_count"] == 3
    assert baseline["selected_tier"] == (
        "same_weekday_holiday_registry_unavailable"
    )
    assert baseline["maturity"] == "weak"
    assert baseline["first_p25"] == pytest.approx(0.095)


def test_no_all_history_fallback_when_only_opposite_week_type_exists() -> None:
    selected, tier = _select_comparable(
        [_day("2026-07-25"), _day("2026-07-26")],
        "2026-08-03",
    )
    assert selected == []
    assert tier == "unavailable"


def test_second_stage_weak_requires_history_p25_and_peer_index() -> None:
    weak = diagnose_platform(_meituan_item(peer_second=0.04))
    assert weak["second_stage_status"] == "weak_signal"
    assert weak["second_conversion_peer_index"] == pytest.approx(0.75)

    not_weak = diagnose_platform(_meituan_item(peer_second=0.034))
    assert not_weak["second_stage_status"] == "normal"
    assert not_weak["second_conversion_peer_index"] > 0.85


def test_low_maturity_cannot_claim_strong_or_weak_as_stable_fact() -> None:
    result = diagnose_platform(
        _meituan_item(
            current_first=0.20,
            current_second=0.08,
            peer_second=0.06,
        )
    )
    assert result["historical_baseline"]["maturity"] == "weak"
    assert result["first_stage_status"] == "strong_signal"
    assert result["second_stage_status"] == "strong_signal"


def test_source_rate_conflict_blocks_both_stage_classifications() -> None:
    item = _meituan_item()
    item["daily"]["source_conflicts"] = [
        "source_conflict:browse_to_pay"
    ]
    result = diagnose_platform(item)
    assert result["first_stage_status"] == "metric_conflict"
    assert result["second_stage_status"] == "metric_conflict"


def test_ctrip_daily_second_stage_does_not_use_30d_peer_filling_rate() -> None:
    item = {
        "platform": "ctrip",
        "algorithm_platform": "ctrip",
        "daily": {
            "business_date": "2026-08-03",
            "stages": {
                "list_exposure_count": 1000,
                "detail_visitor_count": 100,
                "submit_orders": 3,
                "list_to_detail_ratio": 0.08,
                "detail_to_submit_ratio": 0.03,
            },
        },
        "rolling_30d": {
            "stages": {
                "peer_detail_to_order_filling_ratio": 0.10,
            },
        },
    }
    assert _peer_second(item) is None

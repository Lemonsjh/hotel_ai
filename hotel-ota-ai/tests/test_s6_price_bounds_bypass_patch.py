from __future__ import annotations

import runtime.control_plane as control_plane
import runtime.decisions.pricing as pricing
from runtime.safety.guards import price_guard as shared_price_guard
from runtime.s6_price_bounds_bypass_patch import _S6_EXECUTION_ACTIVE, install


def _guard_kwargs(new_price: float) -> dict:
    return {
        "old_price": 100.0,
        "new_price": new_price,
        "floor_price": 90.0,
        "ceiling_price": 110.0,
        "max_increase_pct": 0.20,
        "max_decrease_pct": 0.20,
        "min_increase_pct": 0.01,
        "min_decrease_pct": 0.01,
        "require_old_price": True,
    }


def test_shared_guard_still_enforces_floor_and_ceiling() -> None:
    result = shared_price_guard(**_guard_kwargs(85.0))
    assert result["passed"] is False
    assert "below_floor_price" in result["violations"]


def test_pricing_guard_outside_s6_scope_keeps_bounds() -> None:
    install()
    result = pricing.price_guard(**_guard_kwargs(85.0))
    assert result["passed"] is False
    assert "below_floor_price" in result["violations"]


def test_s6_scope_ignores_bounds_but_keeps_directional_limits() -> None:
    install()
    token = _S6_EXECUTION_ACTIVE.set(True)
    try:
        within_change_limit = pricing.price_guard(**_guard_kwargs(95.0))
        over_change_limit = pricing.price_guard(**_guard_kwargs(70.0))
    finally:
        _S6_EXECUTION_ACTIVE.reset(token)

    assert within_change_limit["passed"] is True
    assert within_change_limit["violations"] == []
    assert within_change_limit["price_bounds_enforced"] is False
    assert within_change_limit["configured_floor_price_reference_only"] == 90.0
    assert within_change_limit["configured_ceiling_price_reference_only"] == 110.0
    assert within_change_limit["max_increase_pct"] == 0.10
    assert within_change_limit["max_decrease_pct"] == 0.10

    assert over_change_limit["passed"] is False
    assert "decrease_max_exceeded" in over_change_limit["violations"]
    assert "below_floor_price" not in over_change_limit["violations"]


def test_formal_price_approval_guard_ignores_bounds_only() -> None:
    install()
    within_change_limit = control_plane.price_guard(**_guard_kwargs(95.0))
    over_change_limit = control_plane.price_guard(**_guard_kwargs(70.0))

    assert within_change_limit["passed"] is True
    assert within_change_limit["price_bounds_mode"] == "temporarily_disabled"
    assert over_change_limit["passed"] is False
    assert "decrease_max_exceeded" in over_change_limit["violations"]
    assert "below_floor_price" not in over_change_limit["violations"]

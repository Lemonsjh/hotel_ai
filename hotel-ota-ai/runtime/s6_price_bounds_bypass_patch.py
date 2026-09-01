from __future__ import annotations

import sys
from contextvars import ContextVar
from functools import wraps
from typing import Any, Callable


VERSION = "s6-price-bounds-bypass.v1"
S6_SINGLE_CHANGE_HARD_CAP = 0.10
_INSTALLED = False
_S6_EXECUTION_ACTIVE: ContextVar[bool] = ContextVar(
    "hotel_ota_s6_price_bounds_bypass_active",
    default=False,
)


def _without_price_bounds(
    guard_fn: Callable[..., dict[str, Any]],
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run the existing price guard while temporarily ignoring floor/ceiling only."""
    configured_floor = kwargs.get("floor_price")
    configured_ceiling = kwargs.get("ceiling_price")
    relaxed = dict(kwargs)
    relaxed["floor_price"] = None
    relaxed["ceiling_price"] = None
    # S6 is the execution companion to S5: keep the same maximum movement
    # in both directions, regardless of legacy directional policy defaults.
    relaxed["max_increase_pct"] = S6_SINGLE_CHANGE_HARD_CAP
    relaxed["max_decrease_pct"] = S6_SINGLE_CHANGE_HARD_CAP
    relaxed["min_increase_pct"] = 0.0
    relaxed["min_decrease_pct"] = 0.0
    result = dict(guard_fn(*args, **relaxed))
    result.update(
        {
            "price_bounds_enforced": False,
            "price_bounds_mode": "temporarily_disabled",
            "configured_floor_price_reference_only": configured_floor,
            "configured_ceiling_price_reference_only": configured_ceiling,
            "price_bounds_patch_version": VERSION,
        }
    )
    return result


def install() -> None:
    """Disable only S6 floor/ceiling blocking while preserving all other safety checks.

    The authoritative price-guard policy is still required so directional min/max
    change limits remain available. S5 pricing logic and the shared global
    ``runtime.safety.guards.price_guard`` implementation are left untouched.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    import runtime.control_plane as control_plane
    import runtime.decisions.pricing as pricing

    if getattr(pricing, "_S6_PRICE_BOUNDS_BYPASS_V1", False):
        _INSTALLED = True
        return

    control_guard = control_plane.price_guard
    pricing_guard = pricing.price_guard
    original_execute_price = pricing.execute_price

    @wraps(control_guard)
    def control_plane_guard_without_bounds(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # control_plane has one price_guard call: formal S6 price approval creation.
        return _without_price_bounds(control_guard, *args, **kwargs)

    @wraps(pricing_guard)
    def pricing_guard_scoped(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if _S6_EXECUTION_ACTIVE.get():
            return _without_price_bounds(pricing_guard, *args, **kwargs)
        return pricing_guard(*args, **kwargs)

    @wraps(original_execute_price)
    def execute_price_with_bounds_disabled(*args: Any, **kwargs: Any) -> Any:
        token = _S6_EXECUTION_ACTIVE.set(True)
        try:
            return original_execute_price(*args, **kwargs)
        finally:
            _S6_EXECUTION_ACTIVE.reset(token)

    control_plane.price_guard = control_plane_guard_without_bounds
    pricing.price_guard = pricing_guard_scoped
    pricing.execute_price = execute_price_with_bounds_disabled

    # Some runtime modules import execute_price directly. If they were imported before
    # this patch installed, refresh those references so the S6 scope marker is applied.
    for module_name in ("runtime.feishu_command_router", "runtime.cli"):
        module = sys.modules.get(module_name)
        if module is not None and getattr(module, "execute_price", None) is original_execute_price:
            setattr(module, "execute_price", execute_price_with_bounds_disabled)

    control_plane._S6_PRICE_BOUNDS_BYPASS_V1 = True
    pricing._S6_PRICE_BOUNDS_BYPASS_V1 = True
    _INSTALLED = True

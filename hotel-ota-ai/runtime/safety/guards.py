from __future__ import annotations

import os
from typing import Any


def price_guard(
    *,
    old_price: float | None,
    new_price: float,
    floor_price: float | None,
    ceiling_price: float | None,
    single_change_limit_pct: float = 0.15,
    max_increase_pct: float | None = None,
    max_decrease_pct: float | None = None,
    min_increase_pct: float | None = None,
    min_decrease_pct: float | None = None,
    require_old_price: bool = False,
) -> dict[str, Any]:
    violations: list[str] = []
    max_increase = float(max_increase_pct if max_increase_pct is not None else single_change_limit_pct)
    max_decrease = float(max_decrease_pct if max_decrease_pct is not None else single_change_limit_pct)
    min_increase = float(min_increase_pct if min_increase_pct is not None else 0.0)
    min_decrease = float(min_decrease_pct if min_decrease_pct is not None else 0.0)
    if floor_price is not None and new_price < floor_price:
        violations.append("below_floor_price")
    if ceiling_price is not None and new_price > ceiling_price:
        violations.append("above_ceiling_price")
    if require_old_price and old_price in (None, 0):
        violations.append("old_price_required_for_live")
    if old_price:
        signed_change_pct = (new_price - old_price) / old_price
        change_pct = abs(signed_change_pct)
        if signed_change_pct == 0:
            violations.append("no_effective_change")
        elif signed_change_pct > 0:
            if signed_change_pct > max_increase:
                violations.append("increase_max_exceeded")
            elif signed_change_pct < min_increase:
                violations.append("increase_below_minimum")
        else:
            decrease_pct = abs(signed_change_pct)
            if decrease_pct > max_decrease:
                violations.append("decrease_max_exceeded")
            elif decrease_pct < min_decrease:
                violations.append("decrease_below_minimum")
    else:
        change_pct = None
        signed_change_pct = None
    return {
        "passed": not violations,
        "violations": violations,
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
        "signed_change_pct": round(signed_change_pct, 4) if signed_change_pct is not None else None,
        "single_change_limit_pct": single_change_limit_pct,
        "max_increase_pct": max_increase,
        "max_decrease_pct": max_decrease,
        "min_increase_pct": min_increase,
        "min_decrease_pct": min_decrease,
    }


def live_enabled(vendor: str) -> bool:
    env_key = f"{vendor.upper()}_ENABLE_LIVE"
    return os.environ.get(env_key) == "1"


def requires_approval(action_type: str) -> bool:
    return action_type in {"price_update", "quota_update", "room_quota_update", "promotion_update", "review_publish"}

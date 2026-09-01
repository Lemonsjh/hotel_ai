from __future__ import annotations

from typing import Any


DEMO_FRESHNESS_STATUS = {
    "freshness_status": "demo_data",
    "business_status": "demo_or_historical",
    "today_label_allowed": False,
}


def freshness_allows_today_label(payload: dict[str, Any] | None) -> bool:
    data = payload or {}
    return data.get("freshness_status") == "fresh" and data.get("business_status") in (None, "current")


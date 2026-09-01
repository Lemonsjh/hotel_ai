from __future__ import annotations

import os
from typing import Any

_INSTALLED = False
VERSION = "s15-s16-cache-freshness.v1"
MAX_CACHE_AGE_SECONDS = 300
TECHNICAL_VERSION = "s15-s16-digital-employee-technical-spec.v2"
DATA_VERSION = "s15-s16-data-correctness.v1"


def _valid_version(payload: dict[str, Any] | None) -> bool:
    if not payload or payload.get("status") != "ok":
        return False
    return bool(
        payload.get("technical_spec_analysis_version") == TECHNICAL_VERSION
        and payload.get("data_correctness_patch_version") == DATA_VERSION
        and payload.get("operating_analysis")
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Historical calculations remain cached briefly, but current sales facts
    # must not be reused for the whole business day.
    os.environ["HOTEL_OTA_S15_CACHE_TTL_SECONDS"] = str(MAX_CACHE_AGE_SECONDS)

    from runtime.decisions import baseline as baseline_decision
    from runtime.decisions import deviation as deviation_decision

    previous_cached = baseline_decision._cached_baseline
    if not getattr(previous_cached, "_S15_CACHE_FRESHNESS_V1", False):

        def cached(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            payload = previous_cached(*args, **kwargs)
            if not _valid_version(payload):
                return None
            if int(payload.get("cache_age_seconds") or 0) > MAX_CACHE_AGE_SECONDS:
                return None
            return payload

        cached._S15_CACHE_FRESHNESS_V1 = True  # type: ignore[attr-defined]
        baseline_decision._cached_baseline = cached

    previous_latest = deviation_decision._latest_baseline
    if not getattr(previous_latest, "_S16_BASELINE_VERSION_GATE_V1", False):

        def latest(
            db_path: str,
            hotel_id: str,
            business_date: str,
        ) -> dict[str, Any] | None:
            payload = previous_latest(db_path, hotel_id, business_date)
            return payload if _valid_version(payload) else None

        latest._S16_BASELINE_VERSION_GATE_V1 = True  # type: ignore[attr-defined]
        deviation_decision._latest_baseline = latest

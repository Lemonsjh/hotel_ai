from __future__ import annotations

import datetime as dt
import os
from typing import Any

_INSTALLED = False
VERSION = "s15-cache-materialization.v1"


def _cache_ttl_seconds() -> int:
    try:
        return max(
            int(os.environ.get("HOTEL_OTA_S15_CACHE_TTL_SECONDS", "86400")),
            0,
        )
    except ValueError:
        return 86400


def _materialize_if_missing(args: Any) -> bool:
    from runtime.common import DEFAULT_DB, now_local, today
    from runtime.decisions import baseline as baseline_decision
    from runtime.sales_progress import DirectSalesProgressRepository
    from runtime.sales_progress.calendar import load_calendar_contexts

    hotel_id = str(getattr(args, "hotel_id", "") or "")
    target_date = str(getattr(args, "date", None) or today())[:10]
    db_path = str(getattr(args, "db", None) or DEFAULT_DB)
    if not hotel_id or not target_date:
        return False
    cached = baseline_decision._cached_baseline(
        db_path,
        hotel_id,
        target_date,
        max_age_seconds=_cache_ttl_seconds(),
    )
    if cached is not None:
        return False

    repository = None
    try:
        repository = DirectSalesProgressRepository.from_environment(hotel_id)
        start_date = (
            dt.date.fromisoformat(target_date) - dt.timedelta(days=365)
        ).isoformat()
        date_contexts = load_calendar_contexts(
            db_path,
            start_date,
            target_date,
            target_date,
        )
        payload = baseline_decision.build_baseline(
            repository,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_datetime=now_local(),
            date_contexts=date_contexts,
        )
        if payload.get("status") != "ok":
            return False
        baseline_decision._persist(
            db_path,
            hotel_id,
            target_date,
            payload,
        )
        return True
    except Exception:
        # The original S16 path remains authoritative for the user-facing
        # data_gap. Cache prewarming must never convert a read failure into a
        # fabricated result or hide the original error contract.
        return False
    finally:
        if repository is not None:
            repository.close()


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.decisions import deviation as deviation_decision

    previous = deviation_decision.deviation
    if getattr(previous, "_S15_CACHE_MATERIALIZATION_V1", False):
        return

    def deviation(args: Any) -> None:
        demo_requested = bool(
            getattr(args, "use_generated_today", False)
            or getattr(args, "strict_generated_today", False)
            or os.environ.get("HOTEL_OTA_DEMO_MODE") == "1"
        )
        if not demo_requested:
            _materialize_if_missing(args)
        previous(args)

    deviation._S15_CACHE_MATERIALIZATION_V1 = True  # type: ignore[attr-defined]
    deviation_decision.deviation = deviation

    try:
        from runtime import feishu_command_router

        feishu_command_router.deviation = deviation
    except Exception:
        pass

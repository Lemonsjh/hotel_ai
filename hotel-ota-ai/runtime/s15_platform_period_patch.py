from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

_INSTALLED = False
VERSION = "s15-platform-period.v1"


def _day(value: Any) -> str:
    return str(value or "")[:10]


def _datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        result = value
    elif value in (None, ""):
        return None
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            result = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    return result.replace(tzinfo=None) if result.tzinfo else result


def _is_completed_daily_row(row: Mapping[str, Any]) -> bool:
    business = _day(row.get("business_date"))
    snapshot = _datetime(row.get("snapshot_time"))
    if not business or snapshot is None:
        return False
    try:
        business_date = dt.date.fromisoformat(business)
    except ValueError:
        return False
    return snapshot.date() > business_date


def _period_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    dates: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        day = _day(row.get("business_date"))
        if day:
            dates.setdefault(day, []).append(row)
    completed: list[str] = []
    partial: list[str] = []
    unknown: list[str] = []
    for day, day_rows in sorted(dates.items()):
        known = [row for row in day_rows if _datetime(row.get("snapshot_time"))]
        if not known:
            unknown.append(day)
        elif all(_is_completed_daily_row(row) for row in known):
            completed.append(day)
        else:
            partial.append(day)
    return {
        "all_dates": sorted(dates),
        "completed_dates": completed,
        "partial_dates": partial,
        "unknown_dates": unknown,
        "all_day_count": len(dates),
        "completed_day_count": len(completed),
        "partial_day_count": len(partial),
    }


def build_platform_reference(
    rows: Sequence[Mapping[str, Any]],
    *,
    target_date: str,
    date_contexts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the historical daily baseline from completed business days only."""

    from runtime.s15_platform_reference import (
        _build_platform_reference_unfiltered,
    )

    summary = _period_summary(rows)
    completed = [dict(row) for row in rows if _is_completed_daily_row(row)]
    result = dict(
        _build_platform_reference_unfiltered(
            completed,
            target_date=target_date,
            date_contexts=date_contexts,
        )
    )
    result.update(
        {
            "period_contract": "completed_daily_history_only",
            "history_all_day_count": summary["all_day_count"],
            "history_completed_day_count": summary["completed_day_count"],
            "history_partial_day_count": summary["partial_day_count"],
            "excluded_partial_dates": summary["partial_dates"],
            "excluded_unknown_dates": summary["unknown_dates"],
        }
    )
    return result


def _set_period_mismatch(axis: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(axis)
    if result.get("current") is not None:
        result["reference_ratio"] = result.get("ratio")
        result["ratio"] = None
        result["status"] = "period_mismatch"
        result["comparison_allowed"] = False
        result["comparison_reason"] = (
            "current_partial_day_cumulative_vs_completed_daily_history"
        )
    return result


def _wrap_operating_analysis(previous: Any) -> Any:
    if getattr(previous, "_S15_PLATFORM_PERIOD_V1", False):
        return previous

    def build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        result = dict(previous(*args, **kwargs))
        repository = args[0] if args else kwargs.get("repository")
        hotel_id = kwargs.get("hotel_id")
        target_date = _day(kwargs.get("target_date"))
        as_of_datetime = kwargs.get("as_of_datetime")
        current_rows: list[dict[str, Any]] = []
        if repository is not None and hotel_id and target_date and as_of_datetime:
            try:
                current_rows = list(
                    repository.ota_business_metrics(
                        "meituan",
                        str(hotel_id),
                        target_date,
                        target_date,
                        str(as_of_datetime),
                    )
                )
            except Exception:
                current_rows = []

        current_summary = _period_summary(current_rows)
        current_is_completed = bool(
            current_summary["completed_day_count"] > 0
            and current_summary["partial_day_count"] == 0
        )
        current_is_partial = bool(current_summary["partial_day_count"] > 0)
        reference = dict(result.get("platform_reference") or {})
        result["platform_period_alignment"] = {
            "current_period": (
                "completed_daily"
                if current_is_completed
                else "partial_day_cumulative"
                if current_is_partial
                else "unavailable"
            ),
            "baseline_period": "completed_daily",
            "current_snapshot_dates": current_summary["all_dates"],
            "history_all_day_count": reference.get("history_all_day_count"),
            "history_completed_day_count": reference.get(
                "history_completed_day_count"
            ),
            "history_partial_day_count": reference.get(
                "history_partial_day_count"
            ),
            "excluded_partial_dates": reference.get(
                "excluded_partial_dates"
            )
            or [],
            "direct_count_comparison_allowed": current_is_completed,
            "rate_comparison_allowed": current_is_completed,
            "reason": (
                None
                if current_is_completed
                else "current_partial_day_cumulative_vs_completed_daily_history"
                if current_is_partial
                else "current_platform_daily_fact_unavailable"
            ),
        }

        if current_is_partial:
            market = dict(result.get("market") or {})
            if market.get("estimated_market_orders") is not None:
                market["reference_market_heat_ratio"] = market.get(
                    "market_heat_ratio"
                )
                market["market_heat_ratio"] = None
                market["status"] = "period_mismatch"
                market["comparison_allowed"] = False
                market["comparison_reason"] = (
                    "current_partial_day_cumulative_vs_completed_daily_history"
                )
            result["market"] = market

            share = dict(result.get("market_share") or {})
            if share.get("current_estimated_market_share") is not None:
                share["reference_delta_pp"] = share.get("delta_pp")
                share["delta_pp"] = None
                share["status"] = "period_mismatch"
                share["comparison_allowed"] = False
                share["comparison_reason"] = (
                    "current_partial_day_cumulative_vs_completed_daily_history"
                )
            result["market_share"] = share

            result["browse"] = _set_period_mismatch(result.get("browse") or {})
            result["first_conversion"] = _set_period_mismatch(
                result.get("first_conversion") or {}
            )
            second = _set_period_mismatch(
                result.get("second_conversion") or {}
            )
            second["is_weak"] = False
            second["strong_judgment_allowed"] = False
            second["weak_reminder_allowed"] = False
            result["second_conversion"] = second

            lead = dict(result.get("lead_price") or {})
            if lead.get("current") is not None:
                lead["reference_ratio"] = lead.get("ratio")
                lead["ratio"] = None
                lead["status"] = "period_mismatch"
                lead["comparison_allowed"] = False
            result["lead_price"] = lead

            sales_diagnoses = [
                value
                for value in (result.get("diagnosis") or [])
                if str(value)
                in {
                    "sales_progress_unavailable",
                    "sales_on_track_or_ahead",
                    "sales_progress_slow",
                    "stale_current_sales_fact",
                }
            ]
            sales_diagnoses.append(
                "平台当前为日内累计，与历史完整日不可直接判强弱"
            )
            result["diagnosis"] = sales_diagnoses
            result["actions"] = [
                {
                    "action_type": "continue_observation",
                    "reason": (
                        "platform_current_partial_vs_completed_daily_history"
                    ),
                    "auto_executable": False,
                }
            ]

        result["platform_period_patch_version"] = VERSION
        return result

    build._S15_PLATFORM_PERIOD_V1 = True  # type: ignore[attr-defined]
    return build


def _append_period_note(base: str, payload: Mapping[str, Any]) -> str:
    analysis = payload.get("operating_analysis") or {}
    alignment = analysis.get("platform_period_alignment") or {}
    if not alignment:
        return base
    if alignment.get("current_period") == "partial_day_cumulative":
        note = [
            "",
            "平台日级周期对齐说明：",
            "- 当前美团指标是截至本次抓取时点的当日累计；历史基准只使用业务日结束后抓取的完整日数据。",
            "- 当前浏览、订单、大盘和份额不与完整日基准直接计算强弱；一转、二转仅展示当前比例与完整日参考，不进入动作判断。",
            f"- 历史原始覆盖 {alignment.get('history_all_day_count') or 0} 天，其中完整日 {alignment.get('history_completed_day_count') or 0} 天；排除日内未完成日期 "
            + "、".join(alignment.get("excluded_partial_dates") or [])
            + "。",
        ]
        return base + "\n" + "\n".join(note)
    return base


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import (
        s15_platform_reference,
        s15_s16_complete_output_patch,
        s15_s16_technical_spec_patch,
        s15_technical_analysis,
    )
    from runtime.sales_progress import baseline_service, deviation_service, presentation, service
    from runtime.decisions import baseline as baseline_decision, deviation as deviation_decision

    if not hasattr(
        s15_platform_reference, "_build_platform_reference_unfiltered"
    ):
        s15_platform_reference._build_platform_reference_unfiltered = (
            s15_platform_reference.build_platform_reference
        )
    s15_platform_reference.build_platform_reference = build_platform_reference
    s15_technical_analysis.build_platform_reference = build_platform_reference

    wrapped_analysis = _wrap_operating_analysis(
        s15_technical_analysis.build_s15_operating_analysis
    )
    s15_technical_analysis.build_s15_operating_analysis = wrapped_analysis
    s15_s16_technical_spec_patch.build_s15_operating_analysis = wrapped_analysis

    previous_build = baseline_service.build_baseline
    if not getattr(previous_build, "_S15_PLATFORM_PERIOD_BUILD_V1", False):

        def build_baseline(*args: Any, **kwargs: Any) -> dict[str, Any]:
            payload = dict(previous_build(*args, **kwargs))
            payload["platform_period_patch_version"] = VERSION
            return payload

        build_baseline._S15_PLATFORM_PERIOD_BUILD_V1 = True  # type: ignore[attr-defined]
        baseline_service.build_baseline = build_baseline
        service._build_baseline = build_baseline
        deviation_service.build_baseline = build_baseline
        baseline_decision.build_baseline = build_baseline

    previous_cached = baseline_decision._cached_baseline
    if not getattr(previous_cached, "_S15_PLATFORM_PERIOD_CACHE_V1", False):

        def cached(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
            payload = previous_cached(*args, **kwargs)
            if payload is None:
                return None
            return (
                payload
                if payload.get("platform_period_patch_version") == VERSION
                else None
            )

        cached._S15_PLATFORM_PERIOD_CACHE_V1 = True  # type: ignore[attr-defined]
        baseline_decision._cached_baseline = cached

    previous_latest = deviation_decision._latest_baseline
    if not getattr(previous_latest, "_S15_PLATFORM_PERIOD_LATEST_V1", False):

        def latest(
            db_path: str, hotel_id: str, business_date: str
        ) -> dict[str, Any] | None:
            payload = previous_latest(db_path, hotel_id, business_date)
            if payload is None:
                return None
            return (
                payload
                if payload.get("platform_period_patch_version") == VERSION
                else None
            )

        latest._S15_PLATFORM_PERIOD_LATEST_V1 = True  # type: ignore[attr-defined]
        deviation_decision._latest_baseline = latest

    previous_message = s15_s16_complete_output_patch.s15_message
    if not getattr(previous_message, "_S15_PLATFORM_PERIOD_MESSAGE_V1", False):

        def s15_message(payload: Mapping[str, Any]) -> str:
            return _append_period_note(previous_message(payload), payload)

        s15_message._S15_PLATFORM_PERIOD_MESSAGE_V1 = True  # type: ignore[attr-defined]
        s15_s16_complete_output_patch.s15_message = s15_message
        presentation.build_s15_user_message = s15_message

    previous_label = s15_s16_complete_output_patch.label
    if not getattr(previous_label, "_S15_PERIOD_LABEL_V1", False):

        def label(value: Any) -> str:
            if str(value) == "period_mismatch":
                return "周期不可比（当前日内累计/历史完整日）"
            return previous_label(value)

        label._S15_PERIOD_LABEL_V1 = True  # type: ignore[attr-defined]
        s15_s16_complete_output_patch.label = label

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping

_INSTALLED = False
VERSION = "s15-s16-prearrival-fact.v1"


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


def _unavailable_checkpoint_line(line: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(line)
    result.update(
        {
            "baseline_median": None,
            "baseline_p25": None,
            "baseline_p80": None,
            "delta_pp": None,
            "expected_sold": None,
            "room_gap": None,
            "status": "unavailable",
            "comparison_allowed": False,
            "comparison_reason": (
                "latest_fact_precedes_target_business_date"
            ),
        }
    )
    for key in (
        "capacity_progress_delta_pp",
        "capacity_expected_sold",
        "capacity_room_gap",
        "sales_progress_delta_pp",
        "expected_sold_at_hour",
        "checkpoint_room_gap",
    ):
        if key in result:
            result[key] = None
    return result


def _latest_snapshot(
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> dt.datetime | None:
    try:
        rows = repository.current_forecast(
            hotel_id, target_date, as_of_datetime
        )
    except Exception:
        return None
    snapshots = [
        _datetime(row.get("snapshot_time"))
        for row in rows
        if isinstance(row, Mapping)
    ]
    valid = [value for value in snapshots if value is not None]
    return max(valid) if valid else None


def _wrap_deviation(previous: Any) -> Any:
    if getattr(previous, "_S15_S16_PREARRIVAL_V1", False):
        return previous

    def build(*args: Any, **kwargs: Any) -> dict[str, Any]:
        report = dict(previous(*args, **kwargs))
        if report.get("status") not in {"ok", "partial"}:
            return report
        repository = args[0] if args else kwargs.get("repository")
        hotel_id = str(kwargs.get("hotel_id") or report.get("hotel_id") or "")
        target_date = str(
            kwargs.get("target_date") or report.get("target_date") or ""
        )[:10]
        as_of_datetime = str(
            kwargs.get("as_of_datetime") or report.get("as_of_datetime") or ""
        )
        if not repository or not hotel_id or not target_date or not as_of_datetime:
            return report
        snapshot = _latest_snapshot(
            repository, hotel_id, target_date, as_of_datetime
        )
        as_of = _datetime(as_of_datetime)
        try:
            target = dt.date.fromisoformat(target_date)
        except ValueError:
            return report
        if snapshot is None or snapshot.date() >= target:
            return report

        hotel = dict(report.get("hotel_result") or {})
        hotel["capacity_line"] = _unavailable_checkpoint_line(
            hotel.get("capacity_line") or {}
        )
        hotel["target_line"] = _unavailable_checkpoint_line(
            hotel.get("target_line") or {}
        )
        hotel["combined_diagnosis"] = (
            "prearrival_snapshot_not_same_day_progress"
        )
        report["hotel_result"] = hotel

        room_results: list[dict[str, Any]] = []
        for source in report.get("room_type_results") or []:
            room = dict(source)
            room["capacity_line"] = _unavailable_checkpoint_line(
                room.get("capacity_line") or {}
            )
            room["target_line"] = _unavailable_checkpoint_line(
                room.get("target_line") or {}
            )
            room["combined_diagnosis"] = (
                "prearrival_snapshot_not_same_day_progress"
            )
            room_results.append(room)
        report["room_type_results"] = room_results
        report["structure_summary"] = {
            "status": "unavailable",
            "reason": "prearrival_snapshot_not_same_day_progress",
            "room_type_count": len(room_results),
            "slow_room_type_count": 0,
            "fast_room_type_count": 0,
            "labels": [],
            "structure_labels": [],
            "progress_judgment_allowed": False,
        }
        report["structure_reconciliation"] = {
            "status": "not_applicable",
            "reason": "prearrival_snapshot_not_same_day_progress",
        }
        report["status"] = "partial"
        report["partial_reason"] = (
            "latest_current_fact_precedes_target_business_date"
        )
        report["current_fact_snapshot_time"] = snapshot.isoformat(sep=" ")
        report["current_fact_time_semantics"] = (
            "latest_prearrival_forecast_fact"
        )
        report["progress_judgment_allowed"] = False
        report["freshness_status"] = "stale_prearrival_fact"
        report["observed_hour"] = None
        if as_of is not None:
            report["checkpoint_gap_minutes"] = max(
                int((as_of - snapshot).total_seconds() // 60), 0
            )
        report["prearrival_fact_patch_version"] = VERSION
        return report

    build._S15_S16_PREARRIVAL_V1 = True  # type: ignore[attr-defined]
    return build


def _append_s16_note(base: str, report: Mapping[str, Any]) -> str:
    if report.get("current_fact_time_semantics") != (
        "latest_prearrival_forecast_fact"
    ):
        return base
    return (
        base
        + "\n\n数据时间语义：最新承诺已售事实抓取于 "
        + str(report.get("current_fact_snapshot_time") or "未知时间")
        + "，早于目标入住营业日。以上全店和房型已售/库存为最后已知事实；"
        "不冒充当前小时进度，不判定偏慢/偏快，不生成任何动作。"
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import runtime.sales_progress as sales_progress
    from runtime.sales_progress import deviation_service, presentation, service
    from runtime.decisions import deviation as deviation_decision
    from runtime import s15_s16_complete_output_patch

    wrapped = _wrap_deviation(deviation_service.build_deviation)
    deviation_service.build_deviation = wrapped
    service._build_deviation = wrapped
    sales_progress.build_deviation = service.build_deviation
    deviation_decision.build_deviation = service.build_deviation

    previous_message = s15_s16_complete_output_patch.s16_message
    if not getattr(previous_message, "_S15_S16_PREARRIVAL_MESSAGE_V1", False):

        def s16_message(report: Mapping[str, Any]) -> str:
            return _append_s16_note(previous_message(report), report)

        s16_message._S15_S16_PREARRIVAL_MESSAGE_V1 = True  # type: ignore[attr-defined]
        s15_s16_complete_output_patch.s16_message = s16_message
        presentation.build_s16_user_message = s16_message

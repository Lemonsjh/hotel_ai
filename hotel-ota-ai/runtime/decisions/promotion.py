from __future__ import annotations

import argparse

from runtime.adapters.database import database_template_result
from runtime.algorithms.s08_promotion_display import build_s8_promotion_display
from runtime.algorithms.s10_promotion_roi import build_s10_promotion_roi
from runtime.algorithms.s11_promotion_plan import build_s11_promotion_plan
from runtime.common import emit, today
from runtime.contracts import standard_envelope
from runtime.s08_promotion_display_source import query_s8_promotion_display
from runtime.s10_promotion_source import query_s10_promotion_performance


_S8_DISPLAY_BOUNDARY = {
    "delivery_owner": "S8",
    "delivery_channel": "feishu",
    "execution_supported": False,
    "task_creation_supported": False,
    "approval_supported": False,
    "ota_write_attempted": False,
    "boundary_reason": "s8_display_only",
}


def _emit_s8_display_result(payload: dict) -> None:
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    display = evidence.get("promotion_display")
    if isinstance(display, dict):
        for field in ("data_business_date", "data_snapshot_time"):
            if display.get(field) not in (None, ""):
                payload[field] = display[field]
    payload.update({"write_performed": False, "live_allowed": False, "execution_boundary": dict(_S8_DISPLAY_BOUNDARY)})
    emit(payload)


def _promotion_display_evidence(display: dict) -> dict:
    evidence = {"promotion_display": display}
    for field in ("data_business_date", "data_snapshot_time"):
        if display.get(field) not in (None, ""):
            evidence[field] = display[field]
    return evidence


def _emit_promotion_plan(args: argparse.Namespace) -> None:
    """S8: read and display only Meituan promotion performance data."""
    source_result = query_s8_promotion_display(args.hotel_id, as_of_time=getattr(args, "as_of_time", None))
    display = build_s8_promotion_display(source_result)
    evidence = _promotion_display_evidence(display)
    if display.get("status") == "data_gap":
        result = standard_envelope(status="data_gap", skill_id="S8", summary="推广通数据读取失败，未使用其他数据源或演示数据替代。", evidence=evidence, recommendations=[], actions=[], risk_level="low")
    elif display.get("source_status") == "no_rows":
        result = standard_envelope(status="ok", skill_id="S8", summary="当前最新快照没有可展示的推广通数据。", evidence=evidence, recommendations=[], actions=[], risk_level="low")
    else:
        result = standard_envelope(status="ok", skill_id="S8", summary=f"已读取并展示推广通近30天数据，共 {display.get('item_count', 0)} 个投放单元。", evidence=evidence, recommendations=[], actions=[], risk_level="low")
    _emit_s8_display_result(result)


def promotion_plan(args: argparse.Namespace) -> None:
    """Historical command name; S8 has display-only behavior."""
    _emit_promotion_plan(args)


def _rows(result: dict) -> list[dict]:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    values = payload.get("rows") or []
    return [dict(item) for item in values if isinstance(item, dict)]


def _s8_s11_view(display: dict) -> dict:
    """Normalize the S8 display contract for S11 consumption without changing S8."""
    copied = dict(display)
    copied["rows"] = [
        {
            **dict(item),
            "deterministic_display_metrics": {"roas": item.get("roas")},
        }
        for item in (display.get("items") or [])
        if isinstance(item, dict)
    ]
    return copied


def _s9_result(hotel_id: str, *, target_date: str, as_of_time: str | None) -> dict:
    from runtime import s09_traffic_conversion_real as s09_module

    metrics = database_template_result("ota_business_metrics", hotel_id, date=target_date, source_platform="meituan", as_of_time=as_of_time)
    payload = metrics.get("payload") if isinstance(metrics.get("payload"), dict) else {}
    rows = _rows(metrics)
    daily = s09_module.build_daily_platform("meituan", rows) if rows else {"status": "data_gap", "stages": {}}
    stages = daily.get("stages") if isinstance(daily.get("stages"), dict) else {}
    return {
        "status": daily.get("status") or ("ok" if metrics.get("status") == "ok" and rows else "data_gap"),
        "source_status": payload.get("source_status"),
        "business_date": payload.get("data_business_date") or target_date,
        "funnel": {
            "exposure_uv": stages.get("exposure_uv"),
            "intention_uv": stages.get("browse_uv"),
            "pay_order_count": stages.get("pay_orders"),
            "browse_conversion_rate": stages.get("exposure_to_browse_ratio"),
            "pay_conversion_rate": stages.get("browse_to_pay_ratio"),
        },
        "data_gaps": daily.get("data_gaps") or [],
        "source_conflicts": daily.get("source_conflicts") or [],
    }


def _s10_result(hotel_id: str, *, as_of_time: str | None) -> dict:
    performance = query_s10_promotion_performance(hotel_id, as_of_time=as_of_time)
    roi = build_s10_promotion_roi(performance_result=performance, as_of_time=as_of_time)
    return {"status": roi.get("status") or "data_gap", "promotion_roi": roi}


def _emit_s11_promotion_suggestion(args: argparse.Namespace) -> None:
    """S11: deterministic read-only PromotionPlan; never executes promotion changes."""
    hotel_id = str(args.hotel_id)
    target_date = str(getattr(args, "target_date", None) or getattr(args, "date", None) or today())[:10]
    as_of_time = getattr(args, "as_of_time", None)
    message = str(getattr(args, "message", None) or "")

    s8_source = query_s8_promotion_display(hotel_id, as_of_time=as_of_time)
    s8_result = _s8_s11_view(build_s8_promotion_display(s8_source))
    s9_result = _s9_result(hotel_id, target_date=target_date, as_of_time=as_of_time)
    s10_result = _s10_result(hotel_id, as_of_time=as_of_time)
    s15_result = getattr(args, "s15_result", None)
    if not isinstance(s15_result, dict):
        s15_result = {"status": "data_gap", "reason": "s15_result_not_supplied"}
    s16_result = getattr(args, "s16_result", None)
    if not isinstance(s16_result, dict):
        s16_result = {"status": "data_gap", "reason": "s16_result_not_supplied"}

    emit(
        build_s11_promotion_plan(
            hotel_id=hotel_id,
            message=message,
            target_date=target_date,
            as_of_time=as_of_time,
            s8_result=s8_result,
            s9_result=s9_result,
            s10_result=s10_result,
            s16_result=s16_result,
            s15_result=s15_result,
        )
    )


def promotion_roi(args: argparse.Namespace) -> None:
    performance = query_s10_promotion_performance(args.hotel_id, as_of_time=getattr(args, "as_of_time", None))
    roi = build_s10_promotion_roi(performance_result=performance, as_of_time=getattr(args, "as_of_time", None))
    payload = performance.get("payload") if isinstance(performance.get("payload"), dict) else {}
    has_records = any((detail.get("items") or []) for detail in (roi.get("platforms") or {}).values())
    emit(standard_envelope(status=roi.get("status") or "data_gap", skill_id="S10", summary=("已按平台推广表现计算来源归因观测值；这不是净利润或增量 ROI。" if has_records else "当前没有可用的酒店推广表现记录，未生成 ROI 结论。"), evidence={"promotion_roi": roi, "data_business_date": payload.get("data_business_date"), "data_snapshot_time": payload.get("data_snapshot_time")}, recommendations=["结合佣金、退款/取消和可比对照基线后，再评估净利润或增量 ROI。"], actions=[{"type": "roi_preview", "decision": "observe"}], risk_level="medium"))


def promotion_execute(args: argparse.Namespace) -> None:
    """Legacy command name; S11 is recommendation-only and performs no writes."""
    _emit_s11_promotion_suggestion(args)

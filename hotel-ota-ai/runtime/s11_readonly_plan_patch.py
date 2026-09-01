from __future__ import annotations

import contextvars
import datetime as dt
import os
import re
from types import SimpleNamespace
from typing import Any, Mapping

from runtime.common import DEFAULT_DB, emit


_INSTALLED = False
VERSION = "s11-readonly-plan-route.v4"
_CONTEXT: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "s11_readonly_route_context",
    default={},
)
_DEGRADED_SOURCE_STATUSES = {"", "unavailable", "data_gap", "blocked", "error"}
_PLATFORM_LABELS = {
    "meituan": "美团",
    "dianping": "大众点评",
    "ctrip": "携程",
    "qunar": "去哪儿",
    "tongcheng": "同程",
    "zhixing": "智行",
}
_SALES_STATUS_LABELS = {
    "ahead": "超前",
    "fast": "超前",
    "significant_fast": "明显超前",
    "normal": "正常",
    "on_track": "正常",
    "behind": "落后",
    "slow": "落后",
    "significant_slow": "明显落后",
    "severe_slow": "严重落后",
}
_PROMOTION_STATUS_LABELS = {
    "running": "投放中",
    "active": "投放中",
    "paused": "已暂停",
    "ended": "已结束",
}
_CAMPAIGN_ID_SUFFIX = re.compile(r"\s+\S*\d{6,}\S*$")


def _normalized(message: str) -> str:
    return re.sub(r"[\s，。！？、；：,.!?;:]+", "", str(message or "").lower())


def is_s11_readonly_intent(message: str) -> bool:
    text = _normalized(message)
    if not text:
        return False

    display_only = any(
        token in text
        for token in (
            "查看推广通数据",
            "看推广通数据",
            "展示推广通数据",
            "推广通数据展示",
        )
    )
    if display_only:
        return False

    if any(token in text for token in ("推广建议", "推广执行", "执行推广")):
        return True
    if re.search(r"(开启|打开|恢复|维持|保持|观察|暂停|关闭).{0,12}(计划|投放|广告)", text):
        return True
    if re.search(r"(计划|投放|广告).{0,12}(开启|打开|恢复|维持|保持|观察|暂停|关闭)", text):
        return True
    if re.search(r"预算.{0,12}(改|调|设|修改|调整)", text) or re.search(r"(改|调|设|修改|调整).{0,8}预算", text):
        return True
    if re.search(r"出价.{0,12}(改|调|设|修改|调整)", text) or re.search(r"(改|调|设|修改|调整).{0,8}出价", text):
        return True
    return False


def _target_date(message: str) -> str:
    text = str(message or "")
    match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?", text)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    today = dt.date.today()
    if "明天" in text:
        return (today + dt.timedelta(days=1)).isoformat()
    if "昨天" in text:
        return (today - dt.timedelta(days=1)).isoformat()
    return today.isoformat()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _observations(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in (plan.get("observation_metrics") or [])
        if isinstance(item, Mapping)
    ]


def _source_statuses(plan: Mapping[str, Any]) -> dict[str, str]:
    alignment = _mapping(plan.get("source_alignment"))
    sources = _mapping(alignment.get("sources"))
    return {str(key): str(value or "").strip().lower() for key, value in sources.items()}


def _source_ready(status: str) -> bool:
    return status not in _DEGRADED_SOURCE_STATUSES


def _fmt_number(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def _fmt_signed(value: Any, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return f"{_fmt_number(value)}{suffix}"
    sign = "+" if number > 0 else ""
    return f"{sign}{_fmt_number(number)}{suffix}"


def _plan_count(plan: Mapping[str, Any], statuses: Mapping[str, str]) -> tuple[int | None, str]:
    rows = [
        item
        for item in _observations(plan)
        if str(item.get("source") or "").upper() in {"S8", "S10"}
    ]
    seen: set[tuple[str, str, str]] = set()
    for item in rows:
        plan_id = str(item.get("plan_id") or "")
        launch_id = str(item.get("launch_id") or "")
        name = str(item.get("promotion_name") or item.get("plan_name") or item.get("launch_name") or "")
        key = ("plan", plan_id, "") if plan_id else ("launch", launch_id, "") if launch_id else ("name", name, "")
        seen.add(key)
    if seen:
        source = "S8 推广快照" if any(str(item.get("source") or "").upper() == "S8" for item in rows) else "S10 推广表现"
        return len(seen), source
    if _source_ready(str(statuses.get("S8") or statuses.get("s8") or "")):
        return 0, "S8 推广快照"
    return None, "未确认"


def _campaign_name(item: Mapping[str, Any], s8_names: Mapping[str, str], index: int) -> str:
    for value in (
        item.get("launch_name"),
        s8_names.get(str(item.get("launch_id") or "")),
        s8_names.get(str(item.get("plan_id") or "")),
        item.get("promotion_name"),
        item.get("plan_name"),
    ):
        name = _CAMPAIGN_ID_SUFFIX.sub("", str(value or "").strip())
        if name:
            return name
    return f"推广计划 {index}"


def _promotion_status(value: Any) -> str:
    raw = str(value or "").strip()
    return _PROMOTION_STATUS_LABELS.get(raw.lower(), raw)


def _promotion_window_summary(plan: Mapping[str, Any]) -> str:
    windows: list[tuple[str, str]] = []
    for item in _observations(plan):
        if str(item.get("source") or "").upper() != "S10":
            continue
        window = (
            str(item.get("period_start_date") or "")[:10],
            str(item.get("period_end_date") or "")[:10],
        )
        if window not in windows and any(window):
            windows.append(window)
    if not windows:
        return "统计窗口和抓取时间暂未提供"
    rendered = [
        "统计窗口 " + (f"{start} 至 {end}" if start and end else "未完整提供")
        for start, end in windows
    ]
    return "；".join(rendered)


def _promotion_observation_sections(plan: Mapping[str, Any]) -> dict[str, list[str]]:
    rows = _observations(plan)
    sections = {"operating": [], "performance": [], "traffic": []}
    s8_names: dict[str, str] = {}
    for item in rows:
        if str(item.get("source") or "").upper() != "S8":
            continue
        name = _CAMPAIGN_ID_SUFFIX.sub(
            "",
            str(item.get("launch_name") or item.get("promotion_name") or item.get("plan_name") or "").strip(),
        )
        if name:
            for key in (item.get("launch_id"), item.get("plan_id")):
                if key not in (None, ""):
                    s8_names[str(key)] = name

    s9 = next((item for item in rows if str(item.get("source") or "").upper() == "S9"), None)
    if s9:
        parts = []
        if s9.get("exposure_uv") not in (None, ""):
            parts.append(f"曝光 {_fmt_number(s9.get('exposure_uv'))}")
        if s9.get("intention_uv") not in (None, ""):
            parts.append(f"浏览 {_fmt_number(s9.get('intention_uv'))}")
        if s9.get("pay_order_count") not in (None, ""):
            parts.append(f"支付 {_fmt_number(s9.get('pay_order_count'))} 单")
        if parts:
            sections["traffic"].append("｜".join(parts))

    s10_rows = [item for item in rows if str(item.get("source") or "").upper() == "S10"]
    for index, item in enumerate(s10_rows, 1):
        name = _campaign_name(item, s8_names, index)
        parts = []
        status = _promotion_status(item.get("promotion_status"))
        if status:
            parts.append(status)
        if item.get("spend_amount") not in (None, ""):
            parts.append(f"花费 ¥{_fmt_number(item.get('spend_amount'))}")
        if item.get("booking_order_count") not in (None, ""):
            parts.append(f"归因订单 {_fmt_number(item.get('booking_order_count'))} 单")
        if item.get("observed_roas") not in (None, ""):
            parts.append(f"观测 ROAS {_fmt_number(item.get('observed_roas'))}")
        if item.get("cpa") not in (None, ""):
            parts.append(f"获客成本 ¥{_fmt_number(item.get('cpa'))}")
        if parts:
            sections["performance"].append(f"{name}：" + "｜".join(parts))

    if not s10_rows:
        for index, item in enumerate(
            (row for row in rows if str(row.get("source") or "").upper() == "S8"),
            1,
        ):
            name = _campaign_name(item, s8_names, index)
            parts = []
            if item.get("spend_amount") not in (None, ""):
                parts.append(f"花费 ¥{_fmt_number(item.get('spend_amount'))}")
            if item.get("roas") not in (None, ""):
                parts.append(f"观测 ROAS {_fmt_number(item.get('roas'))}")
            if parts:
                sections["performance"].append(f"{name}：" + "｜".join(parts))

    s16 = next((item for item in rows if str(item.get("source") or "").upper() == "S16"), None)
    if s16:
        parts = []
        raw_status = str(s16.get("sales_status") or "").strip().lower()
        if raw_status:
            parts.append(f"进度 {_SALES_STATUS_LABELS.get(raw_status, s16.get('sales_status'))}")
        if s16.get("actual_room_nights") not in (None, ""):
            parts.append(f"当前 {_fmt_number(s16.get('actual_room_nights'))} 间夜")
        if s16.get("checkpoint_target_room_nights") not in (None, ""):
            parts.append(f"时点目标 {_fmt_number(s16.get('checkpoint_target_room_nights'))} 间夜")
        if s16.get("sales_progress_delta_pp") not in (None, ""):
            parts.append(f"进度偏差 {_fmt_signed(s16.get('sales_progress_delta_pp'), 'pp')}")
        elif s16.get("checkpoint_room_gap") not in (None, ""):
            parts.append(f"时点差 {_fmt_signed(s16.get('checkpoint_room_gap'), ' 间夜')}")
        if s16.get("remaining_target_gap") not in (None, ""):
            parts.append(f"距最终目标 {_fmt_number(s16.get('remaining_target_gap'))} 间夜")
        if parts:
            sections["operating"].append("今日销售进度：" + "｜".join(parts))

    s15 = next((item for item in rows if str(item.get("source") or "").upper() == "S15"), None)
    if s15:
        parts = []
        if s15.get("target_room_nights") not in (None, ""):
            parts.append(f"最终目标 {_fmt_number(s15.get('target_room_nights'))} 间夜")
        if s15.get("sample_count") not in (None, ""):
            parts.append(f"历史样本 {_fmt_number(s15.get('sample_count'))} 天")
        sections["operating"].append("历史销售参考：" + "｜".join(parts))
    return sections


def _progress_reference_note(plan: Mapping[str, Any]) -> str:
    s16 = next(
        (item for item in _observations(plan) if str(item.get("source") or "").upper() == "S16"),
        None,
    )
    if not s16:
        return ""
    status = str(s16.get("sales_status") or "").strip().lower()
    if status in {"ahead", "fast", "significant_fast"}:
        return " S16 当前销售进度超前，不因单一进度信号自动加投；结合 S10 推广效果与 S15 经营基准判断维持或收缩，S9 仅作流量参考。"
    if status in {"behind", "slow", "significant_slow", "severe_slow"}:
        return " S16 当前销售进度落后，可提高推广关注优先级，但仍需结合 S10 推广效果与 S15 经营基准判断，S9 仅作流量参考。"
    return ""


def _recommendation(plan_count: int | None, plan: Mapping[str, Any]) -> str:
    if plan_count is None:
        base = (
            "当前无法确认推广计划数量，先补齐 S8 推广快照；不要把数据缺口当成 0。"
            "待 S10/S15/S16 正式证据完整后再形成投放取舍；S9 流量仅作辅助参考。"
        )
    elif plan_count == 0:
        base = (
            "当前未观测到进行中的推广计划。结合 S15 经营基准和 S16 当前进度判断是否存在推广需要；"
            "如需新增计划，再确认覆盖主力售卖房型，并在形成 S10 ROAS/CPA 观测后决定加投、减投或停止。"
        )
    else:
        base = (
            "核对推广计划覆盖对象与主力售卖房型是否一致；结合 S10 ROAS/CPA、S15 经营基准和 S16 销售进度"
            "决定维持、调整或停止，不把计划数量直接当作投放效果；S9 流量仅作为辅助参考。"
        )
    return base + _progress_reference_note(plan) + " S15 是经营证据之一，但任何单一 S15/S16 信号都不自动触发推广动作。"


def _adapt_s11_promotion_result(result: Mapping[str, Any]) -> dict[str, Any]:
    adapted = dict(result)
    plan = _mapping(adapted.get("promotion_plan"))
    if not plan:
        return adapted

    statuses = _source_statuses(plan)
    real_source_ready = any(_source_ready(value) for value in statuses.values())
    plan_count, plan_count_basis = _plan_count(plan, statuses)
    window = _mapping(plan.get("window"))
    target_date = str(window.get("target_date") or "")[:10] or None
    as_of_date = str(window.get("as_of_time") or "")[:10] or dt.date.today().isoformat()
    is_current_date = bool(target_date and target_date == as_of_date)
    channel = str(plan.get("channel") or "").strip().lower()
    platform_label = _PLATFORM_LABELS.get(channel, channel or "-")
    observation_sections = _promotion_observation_sections(plan)

    evidence = _mapping(adapted.get("evidence"))
    evidence["promotion_context"] = {
        "active_campaign_count": f"{plan_count} 个" if plan_count is not None else "无法确认",
        "campaign_platforms": [platform_label] if platform_label != "-" else [],
        "count_basis": plan_count_basis,
    }
    evidence["s10_promotion_observation"] = {
        "observations": observation_sections["performance"],
        "observation_contract": "S8/S10/S15/S16 formal evidence + S9 advisory traffic reference",
    }
    evidence["s11_operating_observation"] = {"observations": observation_sections["operating"]}
    evidence["s11_traffic_observation"] = {"observations": observation_sections["traffic"]}
    evidence["s11_promotion_window"] = _promotion_window_summary(plan)
    evidence["s11_source_alignment"] = _mapping(plan.get("source_alignment"))

    for key in ("demo_dataset_id", "demo_business_date", "demo_run_id"):
        adapted.pop(key, None)

    adapted.update(
        {
            "evidence": evidence,
            "summary": _recommendation(plan_count, plan),
            "data_source_type": "mysql_db" if real_source_ready else "unavailable",
            "source_mode": "mysql_runtime" if real_source_ready else "unavailable",
            "source_status": (
                "ok"
                if statuses and all(_source_ready(value) for value in statuses.values())
                else "partial"
                if real_source_ready
                else "data_gap"
            ),
            "business_date": target_date,
            "data_business_date": target_date if real_source_ready else None,
            "freshness_status": (
                "fresh" if real_source_ready and is_current_date else "date_scoped" if real_source_ready else "missing_real_data"
            ),
            "business_status": (
                "current" if real_source_ready and is_current_date else "historical_or_target_date" if real_source_ready else "not_evaluated"
            ),
            "today_label_allowed": bool(real_source_ready and is_current_date),
            "allow_demo_fallback": False,
            "allow_sample_evidence": False,
            "business_result_generated": bool(real_source_ready and adapted.get("status") != "data_gap"),
            "approval_data_allowed": False,
            "approval_preview_allowed": False,
            "formal_approval_allowed": False,
            "formal_approval_created": False,
            "live_allowed": False,
            "live_execution_count": 0,
            "blocked_reason": "read_only_runtime_formal_live_blocked" if real_source_ready else "s11_real_sources_data_gap",
        }
    )
    return adapted


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router

    previous_detect = router._detect_intent
    if not getattr(previous_detect, "_S11_READONLY_PLAN_V4", False):

        def detect_intent(message: str) -> str:
            if is_s11_readonly_intent(message):
                return "promotion_suggestion"
            return previous_detect(message)

        detect_intent._S11_READONLY_PLAN_V4 = True  # type: ignore[attr-defined]
        router._detect_intent = detect_intent

    previous_safe_route = router.safe_route_feishu_command
    if not getattr(previous_safe_route, "_S11_READONLY_PLAN_V4", False):

        def safe_route_feishu_command(*args: Any, **kwargs: Any):
            message = kwargs.get("message")
            if message in (None, "") and args:
                message = args[0]
            context = {
                "message": message,
                "db_path": kwargs.get("db_path"),
                "as_of_time": kwargs.get("as_of_time"),
            }
            token = _CONTEXT.set(context)
            try:
                return previous_safe_route(*args, **kwargs)
            finally:
                _CONTEXT.reset(token)

        safe_route_feishu_command._S11_READONLY_PLAN_V4 = True  # type: ignore[attr-defined]
        router.safe_route_feishu_command = safe_route_feishu_command

    previous_promotion_execute = router.promotion_execute
    if not getattr(previous_promotion_execute, "_S11_READONLY_PLAN_V4", False):

        def promotion_execute(args: Any) -> None:
            context = dict(_CONTEXT.get() or {})
            values = dict(vars(args)) if hasattr(args, "__dict__") else {}
            message = str(values.get("message") or context.get("message") or "")
            values["message"] = message
            values["target_date"] = str(
                values.get("target_date") or values.get("date") or _target_date(message)
            )[:10]
            if values.get("as_of_time") in (None, ""):
                values["as_of_time"] = context.get("as_of_time")

            db_path = (
                values.get("db")
                or context.get("db_path")
                or os.environ.get("HOTEL_OTA_DB")
                or DEFAULT_DB
            )
            values["db"] = str(db_path)
            hotel_id = str(values.get("hotel_id") or "")

            if not isinstance(values.get("s15_result"), dict):
                try:
                    values["s15_result"] = router._query_s15_baseline(
                        hotel_id=hotel_id,
                        target_stay_date=values["target_date"],
                        as_of_time=values.get("as_of_time"),
                        db_path=str(db_path),
                    )
                except Exception as exc:
                    values["s15_result"] = {
                        "status": "data_gap",
                        "reason": f"s15_read_failed:{exc.__class__.__name__}",
                    }

            if not isinstance(values.get("s16_result"), dict):
                try:
                    values["s16_result"] = router._query_s16_progress(
                        hotel_id=hotel_id,
                        target_stay_date=values["target_date"],
                        as_of_time=values.get("as_of_time"),
                        db_path=str(db_path),
                    )
                except Exception as exc:
                    values["s16_result"] = {
                        "status": "data_gap",
                        "reason": f"s16_read_failed:{exc.__class__.__name__}",
                    }

            raw_result = router._capture_runtime_emit(
                previous_promotion_execute,
                SimpleNamespace(**values),
            )
            emit(_adapt_s11_promotion_result(raw_result))

        promotion_execute._S11_READONLY_PLAN_V4 = True  # type: ignore[attr-defined]
        router.promotion_execute = promotion_execute

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable, Mapping

from runtime.s09_traffic_conversion_real import (
    S09DataGap,
    S09MySQLSource,
    build_s09_report,
    render_s09_report,
)
from runtime.s09_historical_checkpoint import (
    build_s09_checkpoint_report,
    build_s09_daily_history_report,
    render_s09_checkpoint_report,
    render_s09_daily_history_report,
)
from runtime.s12_reputation_real import (
    S12DataGap,
    S12MySQLSource,
    build_s12_report,
    render_s12_report,
)
from runtime.s12_daily_new_reviews import (
    build_s12_daily_new_reviews_report,
    render_s12_daily_new_reviews_report,
)
from runtime.safety.feishu_output import feishu_output_gate as evaluate_feishu_output_gate


_INSTALLED = False
_VERSION = "s01-s17-exact-route.v1"
SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8))
_REAL_REPORT_SCAFFOLD_FIELDS = (
    "demo_dataset_id",
    "demo_business_date",
    "generated_demo_run_id",
    "data_business_date",
    "business_date",
    "data_snapshot_time",
    "freshness_status",
    "business_status",
    "context_source",
    "run_context",
)

_STANDARD_ROUTE_PHRASES = {
    "S2": "经营快照",
    "S4": "环境行情感知",
    "S5": "收益建议",
    "S6": "调价预览",
    "S7": "竞对预警",
    "S10": "推广ROI",
    "S13": "待回复评论",
    "S14": "酒店运营诊断",
    "S15": "销售基准线",
    "S16": "进度诊断",
    "S17": "客户订单分析",
}

_ENTRY_CAPABILITIES = {
    "S1": {
        "intent": "control_configuration",
        "summary": "S1 顶层配置与权限已路由。可读取当前身份、成员角色、价格护栏、待处理配置申请和配置审计；配置变更仍需受控申请与确认。",
        "commands": ["我的身份", "价格护栏状态", "待处理配置申请", "配置审计摘要"],
    },
    "S3": {
        "intent": "message_center",
        "summary": "S3 消息中台已路由。该能力负责把经营快报、诊断、建议、审批状态和执行结果输出到飞书；裸 S3 不生成虚构业务数据。",
        "commands": ["经营快照", "销售进度", "待回复评论", "运行状态"],
    },
    "S8": {
        "intent": "promotion_planning",
        "summary": "S8 推广投放建议已路由。可基于流量、转化、活动和库存形成建议；建议不等于已投放，执行边界由 S8 交付流程处理。",
        "commands": ["S9", "推广建议", "S10"],
    },
    "S11": {
        "intent": "promotion_suggestion",
        "summary": "S11 推广建议已路由。它基于真实活动、商品价格和业务指标提供只读建议，不创建任务、不执行投放。",
        "commands": ["推广建议", "S8", "S10"],
    },
}

S09_PHRASES = (
    "流量与转化", "流量转化诊断", "漏斗诊断", "美团转化", "携程转化",
    "流量分析", "转化分析", "浏览人数", "曝光人数", "一转", "二转", "转化率",
)
_S09_HISTORY_DAYS_RE = re.compile(r"(?:近|最近)\s*([2-9]|[12]\d|30)\s*天")
_S09_CHECKPOINT_HOUR_RE = re.compile(r"(?:截至|截止到|截止|到)\s*([01]?\d|2[0-3])\s*(?:点|时)")
S12_PHRASES = ("口碑管理", "口碑诊断", "评价分析", "评论健康", "评价健康")
S12_DAILY_NEW_REVIEW_PHRASES = (
    "昨日新增了几条评论",
    "昨日新增几条评论",
    "昨天新增了几条评论",
    "昨天新增几条评论",
    "昨日新增评论",
    "昨天新增评论",
    "昨日评论数",
    "昨天评论数",
)
_S12_RECENT_NEW_REVIEW_RE = re.compile(
    r"(?:近|最近|最新|这|过去)\s*([23二两三])\s*天.*?(?:新增.*评论|评论.*新增|评论数)"
)
_S12_YESTERDAY_REVIEW_STAT_RE = re.compile(
    r"(?:昨天|昨日).{0,12}(?:好评|差评|未回复|回复率|评论|评价)"
)
_S12_RERUN_FOLLOWUP_RE = re.compile(
    r"^\s*(?:请|你)?\s*(?:重新|再)?\s*(?:执行|查询|查|跑)\s*(?:一下|下|一次)?\s*[。！？!?]?$"
)


def _strip_mentions(message: Any) -> str:
    text = str(message or "").strip()
    text = re.sub(r"@[^\s]+", " ", text)
    return " ".join(text.split()).strip()


def exact_skill_code(message: Any) -> tuple[str | None, str]:
    text = _strip_mentions(message)
    match = re.fullmatch(r"(?i)s0?(\d{1,2})(?:\s+(.*))?", text)
    if not match:
        return None, ""
    number = int(match.group(1))
    if number < 1 or number > 17:
        return None, ""
    return f"S{number}", str(match.group(2) or "").strip()


def route_target_for_code(code: str) -> dict[str, Any]:
    if code == "S9":
        return {"kind": "custom", "intent": "traffic_conversion"}
    if code == "S12":
        return {"kind": "custom", "intent": "reputation_management"}
    if code in _STANDARD_ROUTE_PHRASES:
        return {"kind": "rewrite", "message": _STANDARD_ROUTE_PHRASES[code]}
    if code in _ENTRY_CAPABILITIES:
        return {"kind": "entry", **_ENTRY_CAPABILITIES[code]}
    raise KeyError(code)


def _is_s09_message(message: Any) -> bool:
    code, _ = exact_skill_code(message)
    raw = str(message or "")
    return code == "S9" or any(phrase in raw for phrase in S09_PHRASES)


def _s09_checkpoint_request(message: Any) -> tuple[int, int] | None:
    raw = _strip_mentions(message)
    days = _S09_HISTORY_DAYS_RE.search(raw)
    hour = _S09_CHECKPOINT_HOUR_RE.search(raw)
    if not days or not hour or not _is_s09_message(raw):
        return None
    return int(days.group(1)), int(hour.group(1))


def _s09_history_days(message: Any) -> int | None:
    raw = _strip_mentions(message)
    match = _S09_HISTORY_DAYS_RE.search(raw)
    return int(match.group(1)) if match and _is_s09_message(raw) else None


def _is_s12_message(message: Any) -> bool:
    code, _ = exact_skill_code(message)
    raw = str(message or "")
    return code == "S12" or any(
        phrase in raw
        for phrase in (*S12_PHRASES, *S12_DAILY_NEW_REVIEW_PHRASES)
    )


def _s12_new_review_window_days(message: Any, reply_context: Any = None) -> int | None:
    raw = str(message or "")
    if any(phrase in raw for phrase in S12_DAILY_NEW_REVIEW_PHRASES) or _S12_YESTERDAY_REVIEW_STAT_RE.search(raw):
        return 1
    match = _S12_RECENT_NEW_REVIEW_RE.search(raw)
    if match:
        return {"2": 2, "二": 2, "两": 2, "3": 3, "三": 3}[match.group(1)]
    if _S12_RERUN_FOLLOWUP_RE.fullmatch(_strip_mentions(raw)):
        return _s12_new_review_window_days(reply_context)
    return None


def _is_s12_daily_new_reviews_message(
    message: Any,
    reply_context: Any = None,
) -> bool:
    return _s12_new_review_window_days(message, reply_context) is not None


def _message_from_call(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> str:
    return str(args[0] if args else kwargs.get("message") or "")


def _replace_message(args: tuple[Any, ...], kwargs: dict[str, Any], message: str) -> tuple[tuple[Any, ...], dict[str, Any]]:
    if args:
        return (message, *args[1:]), kwargs
    updated = dict(kwargs)
    updated["message"] = message
    return args, updated


def _as_of(value: Any) -> dt.datetime:
    text = str(value or "").strip()
    if text:
        try:
            parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
            return parsed.astimezone(SHANGHAI_TZ)
        except ValueError:
            pass
    return dt.datetime.now(SHANGHAI_TZ)


def _role(result: Mapping[str, Any], kwargs: Mapping[str, Any]) -> str:
    return str(result.get("personal_role") or result.get("auth_role") or kwargs.get("role") or "guest")


def _finish(router: Any, result: dict[str, Any], *, render: bool, compact: bool, role: str) -> dict[str, Any]:
    if render:
        rendered = router.render_feishu_output(result, result.get("output_profile"))
        payload = router.build_feishu_send_payload(result, role=role)
        if result.get("summary"):
            rendered = dict(rendered)
            payload = dict(payload)
            summary_text = str(result["summary"])
            rendered["text"] = summary_text
            rendered["template"] = f"{str(result.get('skill_id') or '').lower()}_deterministic"
            payload["text"] = summary_text
            if result.get("skill_id") == "S12":
                gate = evaluate_feishu_output_gate(
                    source="feishu",
                    content_kind="text",
                    message=summary_text,
                )
                if gate.get("status") == "ok":
                    payload["delivery_mode"] = "verbatim"
                    payload["model_rewrite_allowed"] = False
                    payload["content_source"] = "runtime_deterministic_s12"
                    rendered["delivery_mode"] = "verbatim"
                    rendered["model_rewrite_allowed"] = False
                else:
                    rendered["text"] = "您好，该内容不能通过飞书业务通道发送。"
                    payload["text"] = rendered["text"]
                    payload["send_allowed"] = False
        result["rendered"] = rendered
        result["send_payload"] = payload
    return router.compact_feishu_route_result(result) if compact else result


def _scaffold(original_safe: Callable[..., dict[str, Any]], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    scaffold_args, scaffold_kwargs = _replace_message(args, dict(kwargs), "身份")
    scaffold_kwargs["render"] = False
    scaffold_kwargs["compact"] = False
    return original_safe(*scaffold_args, **scaffold_kwargs)


def _resolved_hotel(scaffold: Mapping[str, Any], kwargs: Mapping[str, Any]) -> str | None:
    production = bool(kwargs.get("production_feishu", False))
    return scaffold.get("resolved_hotel_id") or scaffold.get("hotel_id") or (None if production else kwargs.get("hotel_id"))


def _entry_result(scaffold: dict[str, Any], *, code: str, entry: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(scaffold)
    result.pop("rendered", None)
    result.pop("send_payload", None)
    result.update(
        {
            "status": "ok",
            "skill_id": code,
            "intent": entry["intent"],
            "runtime_command": f"{code.lower()}-capability-entry",
            "summary": entry["summary"] + "\n可用入口：" + "、".join(entry["commands"]) + "。",
            "business_result_generated": False,
            "approval_data_allowed": False,
            "formal_approval_created": False,
            "live_allowed": False,
            "live_execution_count": 0,
            "route_contract_version": _VERSION,
        }
    )
    return result


def _custom_result(
    scaffold: dict[str, Any],
    *,
    code: str,
    hotel_id: str,
    as_of: dt.datetime,
    daily_new_reviews: bool = False,
    review_window_days: int = 1,
    s09_checkpoint: tuple[int, int] | None = None,
    s09_history_days: int | None = None,
) -> dict[str, Any]:
    result = dict(scaffold)
    for key in (*_REAL_REPORT_SCAFFOLD_FIELDS, "rendered", "send_payload"):
        result.pop(key, None)
    try:
        if code == "S9":
            source = S09MySQLSource.from_env(hotel_id=hotel_id)
            if s09_checkpoint:
                days, hour = s09_checkpoint
                report = build_s09_checkpoint_report(
                    hotel_id=hotel_id, as_of=as_of, source=source, days=days, checkpoint_hour=hour,
                )
                text = render_s09_checkpoint_report(report)
            elif s09_history_days:
                report = build_s09_daily_history_report(
                    hotel_id=hotel_id, as_of=as_of, source=source, days=s09_history_days,
                )
                text = render_s09_daily_history_report(report)
            else:
                report = build_s09_report(hotel_id=hotel_id, as_of=as_of, source=source)
                text = render_s09_report(report)
        elif daily_new_reviews:
            report = build_s12_daily_new_reviews_report(
                hotel_id=hotel_id,
                as_of=as_of,
                source=S12MySQLSource.from_env(hotel_id=hotel_id),
                days=review_window_days,
            )
            text = render_s12_daily_new_reviews_report(report)
        else:
            report = build_s12_report(hotel_id=hotel_id, as_of=as_of, source=S12MySQLSource.from_env(hotel_id=hotel_id))
            text = render_s12_report(report)
    except (S09DataGap, S12DataGap) as exc:
        report = {
            "status": "data_gap",
            "skill_id": code,
            "intent": "traffic_conversion" if code == "S9" else (
                "reputation_daily_new_reviews" if daily_new_reviews else "reputation_management"
            ),
            "hotel_id": hotel_id,
            "data_gaps": [str(exc)],
            "business_result_generated": False,
            "data_source_type": "unavailable",
            "approval_data_allowed": False,
            "live_allowed": False,
        }
        text = f"{code} {'流量与转化诊断' if code == 'S9' else '口碑管理'}暂不可用：{exc}。"
    result.update(report)
    if code == "S12" and daily_new_reviews:
        result.update(
            {
                "data_business_date": report.get("target_review_date"),
                "business_date": report.get("target_review_date"),
                "data_snapshot_time": report.get("as_of_datetime"),
                "freshness_status": "date_scoped" if report.get("business_result_generated") else "unavailable",
                "business_status": "date_scoped",
                "context_source": "mysql_runtime",
            }
        )
    result.update(
        {
            "summary": text,
            "user_message": text,
            "runtime_command": "s09-traffic-conversion --real-read-only" if code == "S9" else "s12-reputation-management --real-read-only",
            "resolved_hotel_id": hotel_id,
            "hotel_id": hotel_id,
            "route_contract_version": _VERSION,
            "formal_approval_created": False,
            "live_execution_count": 0,
        }
    )
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router

    router.PROTECTED_BUSINESS_INTENTS.update({"traffic_conversion", "reputation_management"})

    original_detect = router._detect_intent
    if not getattr(original_detect, "_s09_s12_real_route", False):
        def detect_intent(message: str) -> str:
            if _is_s09_message(message):
                return "traffic_conversion"
            if _is_s12_message(message):
                return "reputation_management"
            code, _ = exact_skill_code(message)
            if code:
                target = route_target_for_code(code)
                if target["kind"] == "entry":
                    return str(target["intent"])
                if target["kind"] == "rewrite":
                    return original_detect(str(target["message"]))
            return original_detect(message)

        detect_intent._s09_s12_real_route = True  # type: ignore[attr-defined]
        router._detect_intent = detect_intent

    original_safe: Callable[..., dict[str, Any]] = router.safe_route_feishu_command
    if getattr(original_safe, "_s01_s17_exact_route", False):
        return

    def safe_route_feishu_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
        message = _message_from_call(args, kwargs)
        code, suffix = exact_skill_code(message)
        is_custom_s09 = _is_s09_message(message)
        s09_checkpoint = _s09_checkpoint_request(message)
        s09_history_days = _s09_history_days(message)
        review_window_days = _s12_new_review_window_days(
            message,
            kwargs.get("reply"),
        )
        is_s12_daily_new_reviews = review_window_days is not None
        is_custom_s12 = _is_s12_message(message) or is_s12_daily_new_reviews

        if code in _STANDARD_ROUTE_PHRASES:
            mapped = _STANDARD_ROUTE_PHRASES[code]
            if suffix:
                mapped += " " + suffix
            new_args, new_kwargs = _replace_message(args, dict(kwargs), mapped)
            return original_safe(*new_args, **new_kwargs)

        if not code and not is_custom_s09 and not is_custom_s12:
            return original_safe(*args, **kwargs)

        requested_render = bool(kwargs.get("render", True))
        requested_compact = bool(kwargs.get("compact", False))
        scaffold = _scaffold(original_safe, args, dict(kwargs))
        role = _role(scaffold, kwargs)
        if scaffold.get("status") == "blocked":
            return _finish(router, scaffold, render=requested_render, compact=requested_compact, role=role)
        hotel_id = _resolved_hotel(scaffold, kwargs)
        if not hotel_id:
            scaffold.update(
                {
                    "status": "blocked",
                    "skill_id": code,
                    "blocked_reason": "missing_resolved_hotel_id",
                    "summary": "当前会话未解析到可信酒店范围，不能执行该能力。",
                    "business_result_generated": False,
                }
            )
            return _finish(router, scaffold, render=requested_render, compact=requested_compact, role=role)

        if code in _ENTRY_CAPABILITIES:
            result = _entry_result(scaffold, code=code, entry=_ENTRY_CAPABILITIES[code])
        else:
            custom_code = "S9" if is_custom_s09 or code == "S9" else "S12"
            result = _custom_result(
                scaffold,
                code=custom_code,
                hotel_id=str(hotel_id),
                as_of=_as_of(kwargs.get("as_of_time")),
                daily_new_reviews=is_s12_daily_new_reviews,
                review_window_days=review_window_days or 1,
                s09_checkpoint=s09_checkpoint,
                s09_history_days=s09_history_days,
            )
        return _finish(router, result, render=requested_render, compact=requested_compact, role=role)

    safe_route_feishu_command._s01_s17_exact_route = True  # type: ignore[attr-defined]
    router.safe_route_feishu_command = safe_route_feishu_command

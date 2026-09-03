from __future__ import annotations

import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from runtime.s13.contracts import RequestContext
from runtime.s13.repository import S13ControlRepository
from runtime.s13.service import S13Service
from runtime.s13.source import MemoryReviewSourceRepository, MySQLReviewSourceRepository, SourceDataGap
from runtime.s13.task_outbox import SQLiteReviewTaskOutbox


SHANGHAI_TZ = timezone(timedelta(hours=8))
REF_RE = re.compile(r"\bREV-[A-Za-z0-9_-]+\b")
REQ_RE = re.compile(r"\bREQ-[A-Za-z0-9_-]+\b")
PLATFORM_LABELS = {
    "meituan": "美团",
    "dianping": "大众点评",
    "ctrip": "携程",
    "qunar": "去哪儿",
    "tongcheng": "同程",
    "zhixing": "智行",
}
PLATFORM_DISPLAY_ORDER = ("meituan", "dianping", "ctrip", "qunar", "tongcheng", "zhixing")
PENDING_REVIEW_TERMS = ("待回复评论", "未回复评论")
LATEST_PENDING_REVIEW_TERMS = (
    "最新一条未回复评论",
    "最新的一条未回复评论",
    "最新未回复评论",
)
GENERATE_REPLY_TERMS = ("生成回复", "生成评论回复", "帮我写差评回复")
REPLY_STATUS_TERMS = ("回复任务状态", "评论回复任务状态")


def is_s13_message(message: str) -> bool:
    text = str(message or "")
    return bool(
        text.strip().lower() in {"s13", "s013"}
        or REF_RE.search(text)
        or REQ_RE.search(text)
        or any(term in text for term in PENDING_REVIEW_TERMS)
        or any(term in text for term in GENERATE_REPLY_TERMS)
        or any(term in text for term in REPLY_STATUS_TERMS)
        or any(
            phrase in text
            for phrase in (
                "人工回复",
                "编辑回复",
            )
        )
    )


def _parse_action(message: str) -> tuple[str, dict[str, str]]:
    text = str(message or "").strip()
    if text.lower() in {"s13", "s013"}:
        return "list_pending", {}
    ref_match = REF_RE.search(text)
    req_match = REQ_RE.search(text)
    if text.startswith("确认") and req_match:
        return "confirm", {"request_id": req_match.group(0)}
    if text.startswith("拒绝") and req_match:
        return "reject", {"request_id": req_match.group(0)}
    if text.startswith("取消") and req_match:
        return "cancel", {"request_id": req_match.group(0)}
    if text.startswith("重试") and req_match:
        return "retry", {"request_id": req_match.group(0)}
    if text.startswith("查询") and req_match:
        return "query_status", {"request_id": req_match.group(0)}
    if text.startswith("查询") and ref_match:
        return "query_status", {"review_ref": ref_match.group(0)}
    if any(term in text for term in REPLY_STATUS_TERMS):
        if req_match:
            return "query_status", {"request_id": req_match.group(0)}
        if ref_match:
            return "query_status", {"review_ref": ref_match.group(0)}
        return "status_help", {}
    if any(term in text for term in LATEST_PENDING_REVIEW_TERMS):
        return "latest_pending", {}
    if any(term in text for term in PENDING_REVIEW_TERMS):
        return "list_pending", {}
    if any(prefix in text for prefix in ("人工回复", "编辑回复")) and ref_match:
        marker = "：" if "：" in text else ":"
        content = text.split(marker, 1)[1].strip() if marker in text else ""
        return "submit_human_draft", {"review_ref": ref_match.group(0), "human_reply_content": content}
    if any(term in text for term in GENERATE_REPLY_TERMS):
        if ref_match:
            return "generate_draft", {"review_ref": ref_match.group(0)}
        return "list_pending", {}
    if ref_match:
        return "generate_draft", {"review_ref": ref_match.group(0)}
    return "unknown", {}


def _as_of(value: Any) -> datetime:
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
            return parsed.astimezone(SHANGHAI_TZ)
        except ValueError:
            pass
    return datetime.now(SHANGHAI_TZ)


def _blocked_base_result(base_result: dict[str, Any]) -> bool:
    return str(base_result.get("blocked_reason") or "") in {
        "tenant_scope_mismatch",
        "missing_required_feishu_auth_context",
        "group_chat_not_bound",
        "direct_message_hotel_membership_missing",
        "tenant_selection_required",
        "missing_trusted_business_chat_id",
    }


def _service(db_path: str, *, hotel_id: str, require_source: bool = True) -> S13Service:
    if require_source:
        source = MySQLReviewSourceRepository.from_env(hotel_id=hotel_id)
    else:
        try:
            source = MySQLReviewSourceRepository.from_env(hotel_id=hotel_id)
        except SourceDataGap:
            source = MemoryReviewSourceRepository([])
    return S13Service(
        control_repository=S13ControlRepository(db_path),
        source_repository=source,
        task_outbox=SQLiteReviewTaskOutbox(db_path),
    )


def _render(result: dict[str, Any]) -> str:
    status = result.get("status")
    action = result.get("action")
    if status == "data_gap":
        return "评论明细暂不可用，当前不能列出未回复评论或生成回复草稿。"
    if action == "status_help":
        return "回复任务状态需要任务或评论引用。请发送“查询 REQ-*”；也可以发送“查询 REV-*”查看对应评论回复状态。"
    if action == "latest_pending":
        item = next(iter(result.get("items") or []), None)
        if not item:
            return "当前没有可用的未回复评论，或评论明细尚未就绪。"
        platform = str(item.get("platform") or "-")
        label = PLATFORM_LABELS.get(platform, platform)
        score = item.get("star_rating")
        excerpt = item.get("redacted_excerpt") or "仅评分"
        return (
            f"最新未回复评论｜{label}｜{score if score not in (None, '') else '-'}分\n"
            f"评论时间：{item.get('review_time') or '-'}\n"
            f"内容：{excerpt}\n"
            f"如需起草回复，请发送：生成回复 {item.get('review_ref')}"
        )
    if action == "list_pending":
        items = result.get("items") or []
        if not items:
            return "当前没有可用的待回复评论，或评论明细数据尚未就绪。"
        counts = Counter(str(item.get("platform") or "unknown") for item in items)
        breakdown = [
            f"{PLATFORM_LABELS.get(platform, platform)}{counts[platform]}条"
            for platform in PLATFORM_DISPLAY_ORDER
            if counts.get(platform, 0) > 0
        ]
        for platform in sorted(set(counts) - set(PLATFORM_DISPLAY_ORDER)):
            breakdown.append(f"{PLATFORM_LABELS.get(platform, platform)}{counts[platform]}条")
        headline = f"待回复评论：共{len(items)}条"
        if breakdown:
            headline += f"（{'，'.join(breakdown)}）"
        lines = [headline]
        for index, item in enumerate(items, 1):
            excerpt = item.get("redacted_excerpt") or "仅评分"
            platform = str(item.get("platform") or "-")
            platform_label = PLATFORM_LABELS.get(platform, platform)
            lines.append(
                f"{index}. {platform_label}｜{item.get('star_rating') or '-'}分｜"
                f"{item.get('review_ref')}｜{excerpt}"
            )
        return "\n".join(lines)
    if result.get("draft_candidate"):
        draft = result["draft_candidate"]["draft"]
        platform = str(result.get("platform") or "-")
        platform_label = PLATFORM_LABELS.get(platform, platform)
        score = result.get("star_rating")
        original = result.get("redacted_excerpt") or "平台未提供正文（纯评分评论）"
        context = (
            f"原评论（脱敏）｜{platform_label}｜{score if score not in (None, '') else '-'}分\n"
            f"评论时间：{result.get('review_time') or '-'}\n"
            f"正文：{original}\n\n"
        )
        if result.get("copy_only"):
            return f"{context}回复草稿：\n{draft}\n\n当前平台仅支持复制草稿，不会写入回复任务。"
        request = result.get("confirmation") or {}
        return f"{context}回复草稿：\n{draft}\n\n确认提交请发送：确认 {request.get('request_id')}"
    if action in {"confirm", "retry"} and status == "ok" and (result.get("task") or {}).get("pending_readback_verified"):
        platform = str((result.get("task") or {}).get("platform") or result.get("platform") or "-")
        label = PLATFORM_LABELS.get(platform, platform)
        return f"{label}回复任务已写入 pending 并完成回读确认；S13 已完成，不等待或查询渠道执行。公开回复状态尚未验证。"
    if action == "query_status":
        task = result.get("task")
        confirmation = result.get("confirmation")
        if task:
            return f"回复任务状态：{task.get('status')}。该状态不代表 OTA 页面已公开回复。"
        if confirmation:
            return f"回复确认状态：{confirmation.get('status')}。"
    reason = result.get("blocked_reason") or status or "unknown"
    return f"S13 评论回复未执行：{reason}。"


def route_s13_message(
    message: str,
    base_result: dict[str, Any],
    *,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    if not is_s13_message(message):
        return base_result
    if _blocked_base_result(base_result):
        return base_result
    hotel_id = base_result.get("resolved_hotel_id") or kwargs.get("hotel_id") or base_result.get("hotel_id")
    role = base_result.get("auth_role") or base_result.get("user_role") or kwargs.get("user_role")
    principal = (
        base_result.get("principal_id")
        or kwargs.get("open_id")
        or kwargs.get("user_id")
        or kwargs.get("union_id")
    )
    if not hotel_id or not role or not principal:
        return {
            **base_result,
            "status": "blocked",
            "skill_id": "S13",
            "intent": "review_reply",
            "blocked_reason": "missing_trusted_s13_request_context",
            "business_result_generated": False,
            "send_payload": {
                "text": "S13 评论回复未执行：缺少可信酒店、角色或用户身份。",
                "card": None,
                "send_allowed": True,
                "delivery_mode": "verbatim",
                "model_rewrite_allowed": False,
            },
        }
    action, fields = _parse_action(message)
    if action == "unknown":
        return base_result
    context = RequestContext(
        hotel_id=str(hotel_id),
        principal_role=str(role),
        principal_ref=str(principal),
        as_of_datetime=_as_of(kwargs.get("as_of_datetime") or kwargs.get("as_of_time")),
    )
    if action == "status_help":
        result = {
            "status": "needs_reference",
            "action": action,
            "blocked_reason": "reply_status_reference_required",
            "data_gaps": [],
            "risk_flags": [],
        }
    else:
        try:
            service = _service(
                str(kwargs.get("db_path") or os.environ.get("HOTEL_OTA_DB", "data/runtime.sqlite")),
                hotel_id=str(hotel_id),
                require_source=action not in {"reject", "cancel", "query_status"},
            )
        except SourceDataGap as exc:
            result = {
                "status": "data_gap",
                "action": action,
                "blocked_reason": str(exc),
                "data_gaps": [str(exc)],
                "copy_only": False,
                "risk_flags": [],
            }
        else:
            if action == "list_pending":
                result = service.list_pending(context)
            elif action == "latest_pending":
                result = service.latest_pending(context)
            elif action == "generate_draft":
                result = service.generate_draft(context, review_ref=fields["review_ref"])
            elif action == "submit_human_draft":
                result = service.generate_draft(
                    context,
                    review_ref=fields["review_ref"],
                    human_reply_content=fields["human_reply_content"],
                )
            elif action == "confirm":
                result = service.confirm(context, request_id=fields["request_id"])
            elif action in {"reject", "cancel"}:
                result = service.reject_or_cancel(context, request_id=fields["request_id"], action=action)
            elif action == "retry":
                result = service.retry(context, request_id=fields["request_id"])
            else:
                result = service.query_status(context, request_id=fields.get("request_id"), review_ref=fields.get("review_ref"))
    text = _render(result)
    return {
        **base_result,
        **result,
        "skill_id": "S13",
        "intent": "review_reply",
        "summary": text,
        "business_result_generated": result.get("status") == "ok",
        "formal_approval_created": bool(result.get("confirmation")),
        "live_execution_count": 1 if (result.get("task") or {}).get("write_performed") else 0,
        "send_payload": {
            "text": text,
            "card": None,
            "send_allowed": True,
            "delivery_mode": "verbatim",
            "model_rewrite_allowed": False,
            "warnings": result.get("risk_flags") or result.get("data_gaps") or [],
        },
    }

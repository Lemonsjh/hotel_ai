from __future__ import annotations

import os
import re
from typing import Any, Callable, Mapping, Sequence

from runtime.common import now_local
from runtime.s08_promotion_display_source import _parse_mysql_dsn, query_s8_promotion_display


_INSTALLED = False
VERSION = "s11-promotion-execution.v3"
TASK_TABLE = "ota_promotion_control_task"
PLATFORM = "meituan"
ALLOWED_ACTIONS = {"pause", "recover"}
_EXECUTION_INTENT = "promotion_control_execute"
_QUESTION_OR_ADVISORY = ("建议", "是否", "应该", "要不要", "可以吗", "合适吗", "怎么看", "怎么")
_NEGATED_ACTIONS = (
    "不暂停",
    "不要暂停",
    "别暂停",
    "无需暂停",
    "不用暂停",
    "不恢复",
    "不要恢复",
    "别恢复",
    "无需恢复",
    "不用恢复",
)


class PromotionControlError(RuntimeError):
    pass


def _clean(value: Any) -> str:
    return str(value or "").strip()


def promotion_control_action(message: str) -> str | None:
    """Return an execution action only for an explicit positive pause/recover command."""
    text = _clean(message)
    if not text:
        return None
    if any(token in text for token in _QUESTION_OR_ADVISORY + _NEGATED_ACTIONS):
        return None
    has_pause = "暂停" in text
    has_recover = "恢复" in text
    if has_pause == has_recover:
        return None
    action = "pause" if has_pause else "recover"
    context = any(token in text for token in ("推广", "计划", "投放", "广告", "launch"))
    launch_like = bool(re.search(r"(?<![A-Za-z0-9])[A-Za-z0-9_-]{6,}(?![A-Za-z0-9])", text))
    if not context and not launch_like:
        return None
    return action


def _launch_label(row: Mapping[str, Any]) -> str:
    for key in ("launch_name", "plan_name", "promotion_name"):
        value = _clean(row.get(key))
        if value:
            return value
    return _clean(row.get("launch_id")) or "未命名推广计划"


def _latest_rows(hotel_id: str, *, as_of_time: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = query_s8_promotion_display(hotel_id, as_of_time=as_of_time)
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    if result.get("status") != "ok":
        raise PromotionControlError(str(result.get("reason") or "promotion_source_unavailable"))
    rows = [dict(row) for row in (payload.get("rows") or []) if isinstance(row, Mapping)]
    if not rows:
        raise PromotionControlError("promotion_launch_not_found")
    return rows, payload


def _id_visible(message: str, value: str) -> bool:
    if not value:
        return False
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(value)}(?![A-Za-z0-9])", message, re.IGNORECASE))


def resolve_unique_launch(
    *,
    hotel_id: str,
    message: str,
    as_of_time: str | None = None,
    rows: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve user text to exactly one current Meituan launch_id.

    launch_id is the only execution key. plan_id and human-readable names are
    lookup hints only and must be converted to one unique launch_id first.
    """
    source_payload: dict[str, Any] = {}
    if rows is None:
        source_rows, source_payload = _latest_rows(hotel_id, as_of_time=as_of_time)
    else:
        source_rows = [dict(row) for row in rows if isinstance(row, Mapping)]

    usable = [row for row in source_rows if _clean(row.get("launch_id"))]
    if not usable:
        return {
            "status": "data_gap",
            "reason": "promotion_source_launch_id_missing",
            "candidates": [],
        }

    matched = [row for row in usable if _id_visible(message, _clean(row.get("launch_id")))]
    matched_by = "launch_id"

    if not matched:
        matched = [row for row in usable if _id_visible(message, _clean(row.get("plan_id")))]
        matched_by = "plan_id_to_launch_id"

    if not matched:
        matched_by = "source_name_to_launch_id"
        matched = []
        for row in usable:
            names = {
                _clean(row.get(key))
                for key in ("launch_name", "plan_name", "promotion_name")
                if _clean(row.get(key))
            }
            if any(name in message for name in names):
                matched.append(row)

    by_launch: dict[str, dict[str, Any]] = {}
    for row in matched:
        launch_id = _clean(row.get("launch_id"))
        by_launch.setdefault(launch_id, row)

    candidates = [
        {
            "launch_id": launch_id,
            "name": _launch_label(row),
            "plan_id": row.get("plan_id"),
        }
        for launch_id, row in sorted(by_launch.items())
    ]
    if len(candidates) == 0:
        available: dict[str, dict[str, Any]] = {}
        for row in usable:
            launch_id = _clean(row.get("launch_id"))
            available.setdefault(
                launch_id,
                {"launch_id": launch_id, "name": _launch_label(row), "plan_id": row.get("plan_id")},
            )
        return {
            "status": "blocked",
            "reason": "promotion_launch_not_found",
            "candidates": list(available.values())[:10],
            "data_snapshot_time": source_payload.get("data_snapshot_time"),
        }
    if len(candidates) > 1:
        return {
            "status": "clarification_required",
            "reason": "promotion_identifier_maps_to_multiple_launch_ids",
            "candidates": candidates,
            "data_snapshot_time": source_payload.get("data_snapshot_time"),
        }

    chosen = candidates[0]
    return {
        "status": "resolved",
        "reason": None,
        "hotel_id": hotel_id,
        "platform": PLATFORM,
        "launch_id": chosen["launch_id"],
        "launch_name": chosen["name"],
        "plan_id": chosen.get("plan_id"),
        "matched_by": matched_by,
        "data_snapshot_time": source_payload.get("data_snapshot_time"),
    }


def _promotion_control_dsn(hotel_id: str | None = None) -> str:
    from runtime.adapters.database import resolve_hotel_dsn

    try:
        dsn = resolve_hotel_dsn(hotel_id, "HOTEL_OTA_PROMOTION_CONTROL_DSN")
    except RuntimeError as exc:
        raise PromotionControlError("promotion_control_dsn_not_configured") from exc
    if not dsn:
        raise PromotionControlError("promotion_control_dsn_not_configured")
    return dsn


def _write_pending_task(*, hotel_id: str, launch_id: str, action: str, dsn: str | None = None) -> int:
    if action not in ALLOWED_ACTIONS:
        raise PromotionControlError("unsupported_promotion_control_action")
    if not hotel_id or not launch_id:
        raise PromotionControlError("promotion_control_identity_required")
    try:
        import pymysql  # type: ignore
    except ImportError as exc:
        raise PromotionControlError("pymysql_not_installed") from exc

    kwargs = _parse_mysql_dsn(dsn or _promotion_control_dsn(hotel_id))
    kwargs["autocommit"] = False
    sql = (
        "INSERT INTO `ota_promotion_control_task` "
        "(`hotel_id`, `platform`, `launch_id`, `action`, `status`, `error_message`, `created_at`, `executed_at`) "
        "VALUES (%s, 'meituan', %s, %s, 'pending', NULL, NOW(), NULL)"
    )
    try:
        with pymysql.connect(**kwargs) as conn, conn.cursor() as cursor:
            cursor.execute(sql, (hotel_id, launch_id, action))
            task_id = int(cursor.lastrowid)
            conn.commit()
            return task_id
    except Exception as exc:
        raise PromotionControlError("promotion_control_task_insert_failed") from exc


def enqueue_promotion_control_task(
    *,
    hotel_id: str,
    message: str,
    action: str,
    as_of_time: str | None = None,
    rows: Sequence[Mapping[str, Any]] | None = None,
    writer: Callable[..., int] | None = None,
) -> dict[str, Any]:
    if action not in ALLOWED_ACTIONS:
        return {"status": "blocked", "reason": "unsupported_promotion_control_action", "write_performed": False}

    try:
        resolved = resolve_unique_launch(
            hotel_id=hotel_id,
            message=message,
            as_of_time=as_of_time,
            rows=rows,
        )
    except PromotionControlError as exc:
        return {"status": "blocked", "reason": str(exc), "action": action, "write_performed": False}
    if resolved.get("status") != "resolved":
        return {**resolved, "action": action, "write_performed": False}

    try:
        task_id = (writer or _write_pending_task)(
            hotel_id=hotel_id,
            launch_id=str(resolved["launch_id"]),
            action=action,
        )
    except PromotionControlError as exc:
        return {
            **resolved,
            "status": "blocked",
            "reason": str(exc),
            "action": action,
            "write_performed": False,
        }

    action_label = "暂停" if action == "pause" else "恢复"
    return {
        **resolved,
        "status": "pending",
        "reason": None,
        "task_id": task_id,
        "action": action,
        "task_status": "pending",
        "write_performed": True,
        "created_at": now_local(),
        "summary": (
            f"已创建美团推广{action_label}任务，任务 {task_id} 当前为 pending；"
            "尚未声明渠道侧已执行成功。"
        ),
    }


def _execution_summary(result: Mapping[str, Any], action: str) -> str:
    action_label = "暂停" if action == "pause" else "恢复"
    status = _clean(result.get("status"))
    if status == "clarification_required":
        candidates = [item for item in (result.get("candidates") or []) if isinstance(item, Mapping)]
        rendered = "；".join(
            f"{_clean(item.get('name')) or '未命名'}（launch_id={_clean(item.get('launch_id'))}）"
            for item in candidates[:10]
        )
        return f"同一标识匹配到多个美团推广实例，未创建{action_label}任务。请明确指定 launch_id：{rendered}"
    if status in {"blocked", "data_gap"}:
        return (
            f"未创建美团推广{action_label}任务：无法在当前酒店最新推广快照中唯一确认 launch_id"
            f"（{_clean(result.get('reason')) or 'unknown'}）。"
        )
    return _clean(result.get("summary"))


def _permission_block(router: Any, *, role: str, output_profile: str | None, reason: str, required: str) -> dict[str, Any]:
    try:
        return router._permission_blocked_result(
            intent=_EXECUTION_INTENT,
            role=role,
            output_profile=output_profile,
            blocked_reason=reason,
            required_permission=required,
            auth_status="unauthorized",
            self_claim_ignored=False,
        )
    except Exception:
        return {
            "status": "blocked",
            "intent": _EXECUTION_INTENT,
            "skill_id": "S11",
            "blocked_reason": reason,
            "required_permission": required,
            "write_performed": False,
        }


def _render_if_needed(router: Any, result: dict[str, Any], *, render: bool, role: str) -> dict[str, Any]:
    if render:
        result["rendered"] = router.render_feishu_output(result, result.get("output_profile"))
        result["send_payload"] = router.build_feishu_send_payload(result, role=role)
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router
    from runtime.safety.auth import build_auth_context, permission_gate, tenant_scope_gate

    previous_detect = router._detect_intent
    if not getattr(previous_detect, "_S11_PROMOTION_EXECUTION_V3", False):
        def detect_intent(message: str) -> str:
            if promotion_control_action(message):
                return _EXECUTION_INTENT
            return previous_detect(message)

        detect_intent._S11_PROMOTION_EXECUTION_V3 = True  # type: ignore[attr-defined]
        router._detect_intent = detect_intent

    try:
        router.PROTECTED_BUSINESS_INTENTS.add(_EXECUTION_INTENT)
    except Exception:
        pass

    previous_permission_action = router._permission_action_for_intent
    if not getattr(previous_permission_action, "_S11_PROMOTION_EXECUTION_V3", False):
        def permission_action(intent: str) -> str:
            if intent == _EXECUTION_INTENT:
                return "approve_live_action"
            return previous_permission_action(intent)

        permission_action._S11_PROMOTION_EXECUTION_V3 = True  # type: ignore[attr-defined]
        router._permission_action_for_intent = permission_action

    previous_route = router.route_feishu_command
    if getattr(previous_route, "_S11_PROMOTION_EXECUTION_V3", False):
        return

    def route_feishu_command(message: str, **kwargs: Any) -> dict[str, Any]:
        action = promotion_control_action(message)
        if action is None:
            return previous_route(message, **kwargs)

        role = str(kwargs.get("role") or "guest")
        output_profile = kwargs.get("output_profile")
        raw_hotel_id = _clean(kwargs.get("hotel_id"))
        raw_chat_id = kwargs.get("chat_id")
        chat_type = kwargs.get("chat_type")
        user_id = kwargs.get("user_id")
        open_id = kwargs.get("open_id")
        union_id = kwargs.get("union_id")
        auth_config = kwargs.get("auth_config")
        db_path = kwargs.get("db_path")
        render = bool(kwargs.get("render"))

        auth = build_auth_context(
            source="feishu",
            user_id=user_id,
            open_id=open_id,
            union_id=union_id,
            chat_id=raw_chat_id,
            chat_type=chat_type,
            user_role=role,
            config_path=auth_config,
            auth_db_path=db_path,
            requested_hotel_id=raw_hotel_id or None,
        )
        resolved_hotel_id = _clean(auth.get("resolved_hotel_id") or raw_hotel_id)
        tenant = tenant_scope_gate(auth, resolved_hotel_id or None)
        if not tenant.get("allowed"):
            result = _permission_block(
                router,
                role=role,
                output_profile=output_profile,
                reason=str(tenant.get("reason") or "tenant_scope_mismatch"),
                required="approve_live_action",
            )
            return _render_if_needed(router, result, render=render, role=role)

        gate = permission_gate(auth, "approve_live_action")
        if not gate.get("allowed"):
            result = _permission_block(
                router,
                role=str(auth.get("user_role") or role),
                output_profile=output_profile,
                reason=str(gate.get("reason") or "permission_denied:approve_live_action"),
                required="approve_live_action",
            )
            result.update({"personal_role": auth.get("user_role"), "hotel_id": resolved_hotel_id})
            return _render_if_needed(router, result, render=render, role=str(auth.get("user_role") or role))

        result = enqueue_promotion_control_task(
            hotel_id=resolved_hotel_id,
            message=message,
            action=action,
            as_of_time=kwargs.get("as_of_time"),
        )
        result["summary"] = _execution_summary(result, action)
        actual_role = str(auth.get("user_role") or role)
        result.update(
            {
                "intent": _EXECUTION_INTENT,
                "skill_id": "S11",
                "node_id": "N021",
                "runtime_command": f"promotion-control-task --action {action}",
                "hotel_id": resolved_hotel_id,
                "platform": PLATFORM,
                "auth_role": actual_role,
                "personal_role": actual_role,
                "auth_backend": auth.get("auth_backend"),
                "tenant_status": auth.get("tenant_status"),
                "output_profile": router.default_output_profile(actual_role, output_profile),
                "promotion_execute_allowed": True,
                "task_creation_supported": True,
                "channel_write_performed": False,
                "live_allowed": False,
                "live_execution_count": 0,
                "execution_boundary": "task_enqueue_only",
                "allowed_actions": sorted(ALLOWED_ACTIONS),
            }
        )
        return _render_if_needed(router, result, render=render, role=actual_role)

    route_feishu_command._S11_PROMOTION_EXECUTION_V3 = True  # type: ignore[attr-defined]
    router.route_feishu_command = route_feishu_command

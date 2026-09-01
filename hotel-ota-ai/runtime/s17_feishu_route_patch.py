from __future__ import annotations

import argparse
import re
from dataclasses import replace
from typing import Any, Callable

from runtime.safety.feishu_output import feishu_output_gate as evaluate_feishu_output_gate

_INSTALLED = False
_FORMAL_PHRASES = (
    "客户订单分析",
    "客户与订单结构分析",
    "客户/订单聚合分析",
    "客户订单结构分析",
    "订单与客户结构分析",
)
_CONTACT_GAP_REASONS = {
    "contact_semantic_unavailable_or_masked",
    "contact_hmac_secret_missing",
}
_REAL_S17_DEMO_SCAFFOLD_FIELDS = (
    "demo_dataset_id",
    "demo_business_date",
    "data_business_date",
    "business_date",
    "freshness_status",
    "business_status",
    "hotel_name",
)


def _strip_demo_scaffold_metadata(result: dict[str, Any]) -> dict[str, Any]:
    """Remove demo-only metadata inherited from the generic Feishu scaffold."""

    for key in _REAL_S17_DEMO_SCAFFOLD_FIELDS:
        result.pop(key, None)
    return result


def _is_s17_message(message: Any) -> bool:
    raw = str(message or "").strip()
    lowered = raw.lower()
    return bool(re.match(r"^s0?17(?:\s|$)", lowered)) or any(phrase in raw for phrase in _FORMAL_PHRASES)


def _explicit_demo(message: Any) -> bool:
    lowered = str(message or "").lower()
    return "demo" in lowered or "演示" in lowered


def _message_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    if args:
        return str(args[0] or "")
    return str(kwargs.get("message") or "")


def _finish_result(router: Any, result: dict[str, Any], *, render: bool, compact: bool, role: str) -> dict[str, Any]:
    if render:
        rendered = router.render_feishu_output(result, result.get("output_profile"))
        payload = router.build_feishu_send_payload(result, role=role)
        # S17 summary is a deterministic runtime fact body. The exact final
        # text must pass the real Feishu gate, then be delivered verbatim.
        if result.get("intent") == "customer_analysis" and result.get("summary"):
            rendered = dict(rendered)
            payload = dict(payload)
            summary_text = str(result["summary"])
            delivery_gate = evaluate_feishu_output_gate(
                source="feishu",
                content_kind="text",
                message=summary_text,
            )
            warnings = list(payload.get("warnings") or [])
            if delivery_gate.get("status") == "ok":
                rendered["text"] = summary_text
                rendered["template"] = "s17_customer_order_deterministic"
                payload["text"] = summary_text
            else:
                blocked_reason = str(delivery_gate.get("blocked_reason") or "feishu_output_blocked")
                warnings.append(f"feishu_output_gate:{blocked_reason}")
                rendered["text"] = "您好，该内容不能通过飞书业务通道发送。"
                payload["text"] = rendered["text"]
                payload["send_allowed"] = False
            payload["warnings"] = warnings
            payload["delivery_mode"] = "verbatim"
            payload["model_rewrite_allowed"] = False
            payload["content_source"] = "runtime_deterministic_s17"
            rendered["delivery_mode"] = "verbatim"
            rendered["model_rewrite_allowed"] = False
        result["rendered"] = rendered
        result["send_payload"] = payload
    return router.compact_feishu_route_result(result) if compact else result


def _install_customer_summary_patch(customer: Any) -> None:
    original = customer.render_s17_summary
    if getattr(original, "_s17_contact_reason_patch", False):
        return

    def render_s17_summary(payload: dict[str, Any]) -> str:
        safe_payload = dict(payload or {})
        safe_payload["data_gaps"] = [
            item for item in (safe_payload.get("data_gaps") or [])
            if str(item) not in _CONTACT_GAP_REASONS
        ]
        text = original(safe_payload)
        populations = safe_payload.get("populations") if isinstance(safe_payload.get("populations"), dict) else {}
        booking = populations.get("pms_booking_created") if isinstance(populations.get("pms_booking_created"), dict) else {}
        proxy = booking.get("contact_proxy") if isinstance(booking.get("contact_proxy"), dict) else {}
        reason = proxy.get("reason")
        if reason == "contact_semantic_unavailable_or_masked":
            line = (
                "联系人订单频次代理不可用：当前 contact 源值为脱敏值或字段语义不适用，"
                "因此按安全策略失败关闭；该状态不是普通的小样本隐私抑制。"
            )
        elif reason == "contact_hmac_secret_missing":
            line = (
                "联系人订单频次代理不可用：服务器尚未配置酒店域 HMAC Secret；"
                "原始联系人不会输出，也不会使用不安全的明文关联。"
            )
        else:
            return text

        lines = text.splitlines()
        boundary_index = next((index for index, value in enumerate(lines) if value.startswith("边界：")), len(lines))
        lines.insert(boundary_index, line)
        return "\n".join(lines)

    render_s17_summary._s17_contact_reason_patch = True  # type: ignore[attr-defined]
    customer.render_s17_summary = render_s17_summary


def _install_stateful_menu_patch(command_menu: Any) -> None:
    updated = []
    for command in command_menu.COMMANDS:
        if command.command_id == "9" and getattr(command, "skill_id", None) in {None, "S17"}:
            command = replace(
                command,
                command_id="14",
                title="客户与订单结构分析",
                usage="14",
            )
        updated.append(command)
    command_menu.COMMANDS = tuple(updated)
    command_menu.COMMAND_BY_ID = {command.command_id: command for command in command_menu.COMMANDS}

    metadata = dict(command_menu.COMMAND_V27_METADATA)
    old = metadata.pop("9", None)
    if old or "14" not in metadata:
        item = dict(old or {})
        item.update(
            {
                "intent": "customer_analysis",
                "node_id": "N014",
                "skill_id": "S17",
                "agent_id": "A2",
                "output_template": "business-summary",
                "supports_synthetic_today_demo": False,
            }
        )
        metadata["14"] = item
    command_menu.COMMAND_V27_METADATA = metadata

    original_parse = command_menu._parse_reply
    if not getattr(original_parse, "_s17_menu_alias_patch", False):
        def parse_reply(reply: str) -> tuple[str | None, list[str]]:
            command_id, tokens = original_parse(reply)
            return ("14" if command_id == "9" else command_id), tokens

        parse_reply._s17_menu_alias_patch = True  # type: ignore[attr-defined]
        command_menu._parse_reply = parse_reply


def _install_router_patch(router: Any, customer: Any) -> None:
    router.PROTECTED_BUSINESS_INTENTS.add("customer_analysis")
    router.NUMERIC_MENU_INTENTS["14"] = "customer_analysis"

    original_detect = router._detect_intent
    if not getattr(original_detect, "_s17_formal_route_patch", False):
        def detect_intent(message: str) -> str:
            if _is_s17_message(message):
                return "customer_analysis_demo" if _explicit_demo(message) else "customer_analysis"
            return original_detect(message)

        detect_intent._s17_formal_route_patch = True  # type: ignore[attr-defined]
        router._detect_intent = detect_intent

    original_safe: Callable[..., dict[str, Any]] = router.safe_route_feishu_command
    if getattr(original_safe, "_s17_formal_route_patch", False):
        return

    def safe_route_feishu_command(*args: Any, **kwargs: Any) -> dict[str, Any]:
        message = _message_from_call(args, kwargs)
        if not _is_s17_message(message) or _explicit_demo(message):
            return original_safe(*args, **kwargs)

        requested_render = bool(kwargs.get("render", True))
        requested_compact = bool(kwargs.get("compact", False))
        scaffold_kwargs = dict(kwargs)
        scaffold_kwargs["render"] = False
        scaffold_kwargs["compact"] = False
        scaffold = original_safe(*args, **scaffold_kwargs)

        if scaffold.get("status") == "blocked":
            role = str(scaffold.get("personal_role") or scaffold.get("auth_role") or kwargs.get("role") or "guest")
            return _finish_result(
                router,
                scaffold,
                render=requested_render,
                compact=requested_compact,
                role=role,
            )

        production_feishu = bool(kwargs.get("production_feishu", False))
        resolved_hotel_id = (
            scaffold.get("resolved_hotel_id")
            or scaffold.get("hotel_id")
            or (None if production_feishu else kwargs.get("hotel_id"))
        )
        if not resolved_hotel_id:
            scaffold.update(
                {
                    "status": "blocked",
                    "intent": "customer_analysis",
                    "blocked_reason": "missing_resolved_hotel_id",
                    "business_result_generated": False,
                    "summary": "当前飞书会话未解析到可验证的酒店范围，不能执行 S17 真实数据库查询。",
                }
            )
            role = str(scaffold.get("personal_role") or scaffold.get("auth_role") or kwargs.get("role") or "guest")
            return _finish_result(
                router,
                scaffold,
                render=requested_render,
                compact=requested_compact,
                role=role,
            )

        s17 = router._capture_runtime_emit(
            customer.customer_analysis,
            argparse.Namespace(
                hotel_id=str(resolved_hotel_id),
                period_start=None,
                period_end=None,
                as_of_time=kwargs.get("as_of_time"),
                minimum_cohort_size=None,
                max_output_cells=None,
                contact_lookup_value=None,
            ),
        )

        auth_fields = {
            key: scaffold.get(key)
            for key in (
                "auth_role",
                "personal_role",
                "auth_backend",
                "auth_status",
                "tenant_status",
                "identity_present",
                "chat_bound",
                "chat_type",
                "output_profile",
                "correlation_id",
            )
            if scaffold.get(key) is not None
        }
        result = dict(scaffold)
        result.pop("rendered", None)
        result.pop("send_payload", None)
        _strip_demo_scaffold_metadata(result)
        result.update(s17)
        result.update(auth_fields)
        result.update(
            {
                "intent": "customer_analysis",
                "node_id": "N014",
                "skill_id": "S17",
                "agent_id": router.agent_id_for_node("N014"),
                "runtime_command": "customer-analysis",
                "hotel_id": str(resolved_hotel_id),
                "resolved_hotel_id": str(resolved_hotel_id),
                "data_source_type": "real_database" if router.database_source_enabled() else "unavailable",
                "business_result_generated": s17.get("status") == "ok",
                "approval_data_allowed": False,
                "approval_preview_allowed": False,
                "formal_approval_allowed": False,
                "formal_approval_created": False,
                "live_allowed": False,
                "live_execution_count": 0,
                "production_feishu": production_feishu,
            }
        )
        if result.get("status") == "ok" and result.get("blocked_reason") == "demo_preview_allowed_formal_live_blocked":
            result["blocked_reason"] = "read_only_runtime_formal_live_blocked"

        role = str(result.get("personal_role") or result.get("auth_role") or kwargs.get("role") or "guest")
        return _finish_result(
            router,
            result,
            render=requested_render,
            compact=requested_compact,
            role=role,
        )

    safe_route_feishu_command._s17_formal_route_patch = True  # type: ignore[attr-defined]
    router.safe_route_feishu_command = safe_route_feishu_command


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router
    from runtime.decisions import command_menu, customer

    _install_customer_summary_patch(customer)
    _install_stateful_menu_patch(command_menu)
    _install_router_patch(router, customer)

    # Extend the already-installed S17 route with controlled real-guest
    # frequency lookup. Kept as a separate patch so the existing S17 contract
    # remains backward compatible.
    from runtime.s17_guest_frequency_patch import install as _install_guest_frequency_patch

    _install_guest_frequency_patch()

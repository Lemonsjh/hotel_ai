from __future__ import annotations

import argparse
import os
import sys
from typing import Any

_INSTALLED = False
_TARGETS = {
    "runtime.feishu_command_router",
    "runtime.feishu_output_renderer",
    "runtime.sales_progress.baseline_service",
}
_FAST_INTENTS = {"sales_baseline_demo", "progress_deviation_demo"}


def _direct_delivery(result: dict[str, Any], role: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    from runtime.safety.feishu_output import feishu_output_gate

    text = str(result.get("user_message") or result.get("summary") or "当前结果暂不可用。")
    try:
        limit = int(os.environ.get("HOTEL_OTA_S15_S16_TEXT_LIMIT", "6000"))
    except ValueError:
        limit = 6000
    warnings: list[str] = []
    if limit > 0 and len(text) > limit:
        suffix = "\n\n内容较长，已保留主要酒店、房型和数据质量结论。"
        text = text[: max(limit - len(suffix), 0)].rstrip() + suffix
        warnings.append("business_summary_truncated")
    gate = feishu_output_gate(source="feishu", content_kind="text", message=text)
    if gate.get("status") != "ok":
        text = "您好，当前业务摘要不能通过飞书业务通道发送。"
        warnings.append(f"feishu_output_gate:{gate.get('blocked_reason')}")
    profile = result.get("output_profile") or (
        "owner_business" if role in {"admin", "owner"} else "operator_workbench"
    )
    rendered = {
        "status": "ok" if gate.get("status") == "ok" else "blocked",
        "output_profile": profile,
        "text": text,
        "visible_fields": ["user_message"],
        "hidden_fields": ["internal_algorithm_fields"],
        "message_send_attempted": False,
        "template": (
            "s15_business_summary"
            if result.get("intent") == "sales_baseline_demo"
            else "s16_business_summary"
        ),
    }
    send_payload = {
        "text": text,
        "card": None,
        "send_allowed": gate.get("status") == "ok",
        "output_profile": profile,
        "warnings": warnings,
        "data_source_type": result.get("data_source_type"),
        "freshness_status": result.get("freshness_status"),
    }
    return rendered, send_payload


def _patch_renderer(module: Any) -> None:
    if getattr(module, "_S15_S16_BUSINESS_OUTPUT_PATCHED", False):
        return
    original_render = module.render_feishu_output
    original_send = module.build_feishu_send_payload

    def render_feishu_output(
        result: dict[str, Any], output_profile: str | None = None
    ) -> dict[str, Any]:
        if result.get("intent") in _FAST_INTENTS and result.get("user_message"):
            rendered, _ = _direct_delivery(result, result.get("auth_role"))
            if output_profile:
                rendered["output_profile"] = output_profile
            return rendered
        return original_render(result, output_profile)

    def build_feishu_send_payload(
        result: dict[str, Any], role: str | None = None
    ) -> dict[str, Any]:
        if result.get("intent") in _FAST_INTENTS and result.get("user_message"):
            _, send_payload = _direct_delivery(result, role)
            return send_payload
        return original_send(result, role)

    module.render_feishu_output = render_feishu_output
    module.build_feishu_send_payload = build_feishu_send_payload
    module._S15_S16_BUSINESS_OUTPUT_PATCHED = True


def _direct_real_result(
    module: Any,
    message: str,
    original_route: Any,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    intent = module._detect_intent(message)
    probe_kwargs = dict(kwargs)
    probe_kwargs.update({"render": False, "force_feishu_auth": True})
    auth_probe = original_route("身份", *args, **probe_kwargs)
    resolved_hotel_id = auth_probe.get("resolved_hotel_id") or auth_probe.get("hotel_id")
    if auth_probe.get("status") in {"blocked", "data_gap"} or not resolved_hotel_id:
        return original_route(message, *args, **kwargs)

    role = (
        auth_probe.get("personal_role")
        or auth_probe.get("auth_role")
        or kwargs.get("role")
        or "guest"
    )
    output_profile = auth_probe.get("output_profile") or module.default_output_profile(
        role, kwargs.get("output_profile")
    )
    time_context = module.resolve_request_as_of_time(
        message, explicit_as_of_time=kwargs.get("as_of_time")
    )
    target_date = str(
        time_context.get("target_business_date") or module.now_local()[:10]
    )[:10]
    requested_as_of = time_context.get("as_of_time")
    if time_context.get("as_of_time_source") == "request_clock":
        requested_as_of = None
    from runtime.common import DEFAULT_DB

    db_path = kwargs.get("db_path") or os.environ.get("HOTEL_OTA_DB") or DEFAULT_DB

    if intent == "sales_baseline_demo":
        from runtime.decisions.baseline import baseline
        from runtime.sales_progress.presentation import attach_s15_user_view

        raw = module._capture_runtime_emit(
            baseline,
            argparse.Namespace(
                hotel_id=str(resolved_hotel_id),
                date=target_date,
                as_of_time=requested_as_of,
                db=db_path,
            ),
        )
        business = dict(raw.get("baseline") or raw)
        business = attach_s15_user_view(business)
        node_id, skill_id, command = (
            "N010",
            "S15",
            "baseline --real-field-single-pass",
        )
    else:
        from runtime.decisions.deviation import deviation
        from runtime.sales_progress.presentation import attach_s16_user_view

        business = module._capture_runtime_emit(
            deviation,
            argparse.Namespace(
                hotel_id=str(resolved_hotel_id),
                date=target_date,
                as_of_time=requested_as_of,
                use_generated_today=False,
                strict_generated_today=False,
                db=db_path,
            ),
        )
        business = attach_s16_user_view(business)
        node_id, skill_id, command = (
            "N011",
            "S16",
            "deviation --real-field-single-pass",
        )

    result = module._base_result(intent, role=role, output_profile=output_profile)
    result.update(business)
    status = str(business.get("status") or "data_gap")
    result.update(
        {
            "status": status,
            "intent": intent,
            "node_id": node_id,
            "skill_id": skill_id,
            "runtime_command": command,
            "hotel_id": str(resolved_hotel_id),
            "resolved_hotel_id": str(resolved_hotel_id),
            "auth_role": role,
            "personal_role": role,
            "auth_backend": auth_probe.get("auth_backend"),
            "tenant_status": auth_probe.get("tenant_status"),
            "output_profile": output_profile,
            "data_source_type": "real_database",
            "freshness_status": business.get("freshness_status") or "as_of_bounded",
            "business_result_generated": status in {"ok", "partial"},
            "approval_data_allowed": False,
            "formal_approval_allowed": False,
            "live_allowed": False,
            "formal_approval_created": False,
            "live_execution_count": 0,
            "allow_demo_fallback": False,
            "allow_sample_evidence": False,
            "production_feishu": True,
            "blocked_reason": (
                "read_only_runtime_formal_live_blocked"
                if status in {"ok", "partial"}
                else business.get("reason") or "real_business_data_unavailable"
            ),
            "execution_count": 1,
            "dependency_runs": [],
        }
    )
    if kwargs.get("render"):
        rendered, send_payload = _direct_delivery(result, role)
        result["rendered"] = rendered
        result["send_payload"] = send_payload
    return result


def _patch_router(module: Any) -> None:
    if getattr(module, "_S15_S16_FAST_ROUTE_PATCHED", False):
        return
    original_route = module.route_feishu_command

    def route_feishu_command(
        message: str, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        intent = module._detect_intent(message)
        force_feishu_auth = bool(kwargs.get("force_feishu_auth"))
        explicit_demo = bool(module._explicit_demo_requested(message))
        if force_feishu_auth and intent in _FAST_INTENTS and not explicit_demo:
            return _direct_real_result(module, message, original_route, args, kwargs)
        return original_route(message, *args, **kwargs)

    module.route_feishu_command = route_feishu_command
    module._S15_S16_FAST_ROUTE_PATCHED = True


def _patch_baseline_service(module: Any) -> None:
    if getattr(module, "_S15_ROOM_NAME_PATCHED", False):
        return
    original_sales_lines = module._sales_lines

    def _sales_lines(  # type: ignore[no-untyped-def]
        selected_dates, hourly, room_daily_rows, hotel_daily_rows
    ):
        hotel, rooms = original_sales_lines(
            selected_dates, hourly, room_daily_rows, hotel_daily_rows
        )
        names: dict[str, str] = {}
        for facts in hourly.values():
            for fact in facts:
                room_id = fact.get("room_type_id")
                room_name = fact.get("room_type_name")
                if room_id and room_name:
                    names.setdefault(str(room_id), str(room_name))
        for room_id, room in rooms.items():
            if names.get(str(room_id)):
                room.setdefault("room_type_name", names[str(room_id)])
        return hotel, rooms

    module._sales_lines = _sales_lines
    module._S15_ROOM_NAME_PATCHED = True


def _apply_patch(module: Any) -> None:
    if module.__name__ == "runtime.feishu_command_router":
        _patch_router(module)
    elif module.__name__ == "runtime.feishu_output_renderer":
        _patch_renderer(module)
    elif module.__name__ == "runtime.sales_progress.baseline_service":
        _patch_baseline_service(module)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import live_contract_patch as live_patch

    live_patch._TARGETS.update(_TARGETS)
    original_apply = live_patch._apply_patch
    if not getattr(original_apply, "_S15_S16_COMBINED_PATCH", False):

        def combined_apply(module: Any) -> None:
            original_apply(module)
            _apply_patch(module)

        combined_apply._S15_S16_COMBINED_PATCH = True  # type: ignore[attr-defined]
        live_patch._apply_patch = combined_apply

    for name in list(_TARGETS):
        loaded = sys.modules.get(name)
        if loaded is not None:
            live_patch._apply_patch(loaded)

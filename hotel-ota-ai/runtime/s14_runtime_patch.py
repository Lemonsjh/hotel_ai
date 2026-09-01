from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

_INSTALLED = False
SHANGHAI_TZ = timezone(timedelta(hours=8))
_TARGETS = {
    "runtime.storage",
    "runtime.cli",
    "runtime.feishu_command_router",
}

_S14_OPERATION_PHRASES = (
    "OTA运营诊断",
    "OTA 运营诊断",
    "综合运营诊断",
    "本店运营诊断",
    "本店OTA诊断",
    "本店 OTA诊断",
    "本店OTA运营诊断",
    "本店 OTA运营诊断",
    "运行S14",
    "运行 S14",
    "跑一下S14",
    "跑一下 S14",
    "查看S14",
    "查看 S14",
    "S14诊断",
    "s14诊断",
)
_S14_TOKEN_RE = re.compile(r"(?<![a-z0-9_-])s14(?![a-z0-9_-])", re.IGNORECASE)


def _normalize_s14_database_message(message: str) -> str:
    """Route formal S14 requests directly to the production diagnosis path.

    Formal S14 no longer has an Excel/source-selection branch. Any request
    identified as S14 is normalized to the same database-backed operation.
    """
    text = str(message or "")
    lowered = text.lower()
    if "s14-ext" in lowered:
        return text
    if "demo" in lowered or "演示" in text:
        return text

    requested = (
        bool(_S14_TOKEN_RE.search(text))
        or any(phrase in text for phrase in _S14_OPERATION_PHRASES)
        or "s14 diagnosis" in lowered
    )
    if not requested:
        return text
    return "综合运营诊断"


def _patch_storage(module: Any) -> None:
    if getattr(module, "_S14_CAPABILITY_RESULTS_PATCHED", False):
        return
    from runtime.capability_results import (
        ensure_capability_result_schema_conn,
        find_latest_capability_result,
        latest_s14_diagnosis_run,
        list_capability_results_for_request,
        resolve_organization_id,
        save_capability_result,
        save_s14_diagnosis_run,
    )

    original_init_schema = module.init_schema

    def init_schema(conn):  # type: ignore[no-untyped-def]
        result = original_init_schema(conn)
        ensure_capability_result_schema_conn(conn)
        conn.commit()
        return result

    module.init_schema = init_schema
    module.save_capability_result = save_capability_result
    module.find_latest_capability_result = find_latest_capability_result
    module.list_capability_results_for_request = list_capability_results_for_request
    module.save_s14_diagnosis_run = save_s14_diagnosis_run
    module.latest_s14_diagnosis_run = latest_s14_diagnosis_run
    module.resolve_organization_id = resolve_organization_id
    module._S14_CAPABILITY_RESULTS_PATCHED = True


def _patch_cli(module: Any) -> None:
    if getattr(module, "_S14_BUNDLE_CLI_PATCHED", False):
        return
    from runtime.s14_bundle_builder import run_s14_cli

    original_main = module.main

    def main(argv: list[str] | None = None) -> int:
        args = list(sys.argv[1:] if argv is None else argv)
        if "s14-diagnosis" not in args:
            return original_main(argv)
        command_index = args.index("s14-diagnosis")
        global_args = args[:command_index]
        s14_args = args[command_index + 1 :]
        if "--demo" in global_args:
            module.emit(
                {
                    "status": "data_gap",
                    "skill_id": "S14",
                    "reason": "demo_mode_not_allowed_for_formal_s14",
                    "source_policy": "versioned_capability_results_only",
                    "business_result_generated": False,
                    "direct_execution_allowed": False,
                    "live_allowed": False,
                }
            )
            return 0
        if "--db" in global_args:
            index = global_args.index("--db")
            if index + 1 < len(global_args):
                s14_args = ["--db", global_args[index + 1], *s14_args]
        result = run_s14_cli(s14_args, default_db=module.DEFAULT_DB)
        module.emit(result)
        return 0 if result.get("status") in {
            "ok",
            "partial",
            "conflict",
            "data_gap",
        } else 1

    module.main = main
    module._S14_BUNDLE_CLI_PATCHED = True


def _request_as_of(value: Any) -> datetime:
    now = datetime.now(SHANGHAI_TZ)
    text = str(value or "").strip()
    if not text:
        return now
    if "T" in text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
            return parsed.astimezone(SHANGHAI_TZ)
        except ValueError:
            return now
    try:
        hour, minute = text.split(":", 1)
        return now.replace(
            hour=int(hour),
            minute=int(minute),
            second=0,
            microsecond=0,
        )
    except (TypeError, ValueError):
        return now


def _patch_router(module: Any) -> None:
    if getattr(module, "_S14_BUNDLE_ROUTER_PATCHED", False):
        return
    from runtime.capability_results import resolve_organization_id
    from runtime.common import DEFAULT_DB
    from runtime.s14_bundle_builder import (
        build_and_run_s14,
        is_s14_operation_message,
        render_s14_feishu_text,
    )

    original_route = module.route_feishu_command
    original_safe_route = module.safe_route_feishu_command

    def maybe_run(
        message: str,
        result: dict[str, Any],
        *,
        kwargs: dict[str, Any],
        compact: bool,
    ) -> dict[str, Any]:
        if not is_s14_operation_message(message):
            return result
        if result.get("skill_id") == "S14" and result.get("diagnosis_run_id"):
            return result
        if result.get("status") in {"blocked", "unauthorized"}:
            return result
        blocked_reason = str(result.get("blocked_reason") or "")
        if blocked_reason in {
            "tenant_scope_mismatch",
            "missing_required_feishu_auth_context",
            "group_chat_not_bound",
            "direct_message_hotel_membership_missing",
            "tenant_selection_required",
        }:
            return result

        hotel_id = (
            result.get("resolved_hotel_id")
            or kwargs.get("hotel_id")
            or result.get("hotel_id")
        )
        if not hotel_id:
            return result

        db_path = str(kwargs.get("db_path") or DEFAULT_DB)
        organization_id = (
            result.get("organization_id")
            or result.get("org_id")
            or kwargs.get("organization_id")
            or resolve_organization_id(db_path, str(hotel_id))
        )
        # S14 is a new request, so its business date must come from the
        # request clock (or an explicit date in the message), never from the
        # placeholder result produced before capability collection.  The
        # latter can carry an old demo/menu date and would otherwise mix a
        # historical bundle into a current production diagnosis.
        time_context = module.resolve_request_as_of_time(
            message,
            explicit_as_of_time=kwargs.get("as_of_datetime") or kwargs.get("as_of_time"),
        )
        as_of = _request_as_of(time_context.get("as_of_time"))
        target_business_date = str(
            time_context.get("target_business_date") or as_of.date().isoformat()
        )[:10]
        diagnosis = build_and_run_s14(
            organization_id=organization_id,
            hotel_id=str(hotel_id),
            target_business_date=target_business_date,
            as_of_datetime=as_of.isoformat(timespec="seconds"),
            db_path=db_path,
        )
        text = render_s14_feishu_text(diagnosis)
        output_profile = (
            result.get("output_profile")
            or kwargs.get("output_profile")
            or "owner_business"
        )
        merged = {
            **result,
            **diagnosis,
            "intent": "operation_diagnosis",
            "skill_id": "S14",
            "hotel_id": str(hotel_id),
            "resolved_hotel_id": str(hotel_id),
            "summary": text,
            "runtime_command": (
                "python runtime/hotel_ota_runtime.py s14-diagnosis "
                "--hotel-id <resolved_hotel_id>"
            ),
            "send_payload": {
                "text": text,
                "card": None,
                "send_allowed": True,
                "output_profile": output_profile,
                "warnings": diagnosis.get("data_limitations") or [],
                "data_source_type": "versioned_capability_results",
                "freshness_status": (
                    "fresh"
                    if diagnosis.get("status") == "ok"
                    else diagnosis.get("status")
                ),
            },
            "output_profile": output_profile,
            "business_result_generated": bool(
                diagnosis.get("business_result_generated")
            ),
            "formal_approval_created": False,
            "live_execution_count": 0,
        }
        merged.pop("blocked_reason", None)
        if compact and hasattr(module, "compact_feishu_route_result"):
            return module.compact_feishu_route_result(merged)
        return merged

    def route_feishu_command(message: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        normalized_message = _normalize_s14_database_message(message)
        result = original_route(normalized_message, *args, **kwargs)
        return maybe_run(
            normalized_message,
            result,
            kwargs=kwargs,
            compact=False,
        )

    def safe_route_feishu_command(
        message: str, *args: Any, **kwargs: Any
    ) -> dict[str, Any]:
        normalized_message = _normalize_s14_database_message(message)
        result = original_safe_route(normalized_message, *args, **kwargs)
        return maybe_run(
            normalized_message,
            result,
            kwargs=kwargs,
            compact=bool(kwargs.get("compact")),
        )

    module.route_feishu_command = route_feishu_command
    module.safe_route_feishu_command = safe_route_feishu_command
    module._S14_BUNDLE_ROUTER_PATCHED = True


def _apply_patch(module: Any) -> None:
    if module.__name__ == "runtime.storage":
        _patch_storage(module)
    elif module.__name__ == "runtime.cli":
        _patch_cli(module)
    elif module.__name__ == "runtime.feishu_command_router":
        _patch_router(module)


def install() -> None:
    """Extend the existing runtime import patcher without replacing its loader."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import live_contract_patch as live_patch

    live_patch._TARGETS.update(_TARGETS)
    original_apply = live_patch._apply_patch
    if not getattr(original_apply, "_S14_COMBINED_PATCH", False):

        def combined_apply(module: Any) -> None:
            original_apply(module)
            _apply_patch(module)

        combined_apply._S14_COMBINED_PATCH = True  # type: ignore[attr-defined]
        live_patch._apply_patch = combined_apply

    for name in list(_TARGETS):
        loaded = sys.modules.get(name)
        if loaded is not None:
            live_patch._apply_patch(loaded)

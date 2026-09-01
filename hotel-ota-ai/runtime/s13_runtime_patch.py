from __future__ import annotations

import sys
from contextlib import closing
from typing import Any


_INSTALLED = False
_TARGETS = {
    "runtime.storage",
    "runtime.cli",
    "runtime.feishu_command_router",
    "runtime.safety.auth",
    "runtime.s13.service",
}


def _patch_storage(module: Any) -> None:
    if getattr(module, "_S13_CONTROL_SCHEMA_PATCHED", False):
        return
    from runtime.s13.repository import S13ControlRepository

    original_init_schema = module.init_schema

    def init_schema(conn):  # type: ignore[no-untyped-def]
        result = original_init_schema(conn)
        S13ControlRepository.ensure_schema_conn(conn)
        conn.commit()
        return result

    module.init_schema = init_schema
    module._S13_CONTROL_SCHEMA_PATCHED = True


def _patch_cli(module: Any) -> None:
    if getattr(module, "_S13_CLI_PATCHED", False):
        return
    from runtime.s13.cli import S13_COMMANDS, run_s13_cli

    original_main = module.main

    def main(argv: list[str] | None = None) -> int:
        args = list(sys.argv[1:] if argv is None else argv)
        command = next((name for name in S13_COMMANDS if name in args), None)
        if command is None:
            return original_main(argv)
        command_index = args.index(command)
        global_args = args[:command_index]
        s13_args = args[command_index:]
        if "--db" in global_args:
            index = global_args.index("--db")
            if index + 1 < len(global_args):
                s13_args = ["--db", global_args[index + 1], *s13_args]
        result = run_s13_cli(s13_args, default_db=getattr(module, "DEFAULT_DB", None))
        module.emit(result)
        return 0 if result.get("status") in {
            "ok",
            "partial",
            "blocked",
            "data_gap",
            "active_conflict",
            "already_handled",
            "write_failed",
        } else 1

    module.main = main
    module._S13_CLI_PATCHED = True


def _patch_router(module: Any) -> None:
    if getattr(module, "_S13_ROUTER_PATCHED", False):
        return
    from runtime.s13.feishu import is_s13_message, route_s13_message

    original_route = module.route_feishu_command
    original_safe_route = module.safe_route_feishu_command

    def route_feishu_command(message: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_route(message, *args, **kwargs)
        if not is_s13_message(message):
            return result
        if result.get("skill_id") == "S13" and result.get("intent") == "review_reply":
            return result
        return route_s13_message(message, result, kwargs=kwargs)

    def safe_route_feishu_command(message: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = original_safe_route(message, *args, **kwargs)
        if not is_s13_message(message):
            return result
        if result.get("skill_id") == "S13" and result.get("intent") == "review_reply":
            return result
        patched = route_s13_message(message, result, kwargs=kwargs)
        if kwargs.get("compact") and hasattr(module, "compact_feishu_route_result"):
            return module.compact_feishu_route_result(patched)
        return patched

    module.route_feishu_command = route_feishu_command
    module.safe_route_feishu_command = safe_route_feishu_command
    module._S13_ROUTER_PATCHED = True


def _patch_auth(module: Any) -> None:
    if getattr(module, "_S13_PERMISSION_PATCHED", False):
        return
    roles = list(getattr(module, "ROLES", ()))
    if "viewer" not in roles:
        roles.append("viewer")
    module.ROLES = tuple(roles)
    tenant_roles = list(getattr(module, "TENANT_MEMBER_ROLES", ()))
    if "viewer" not in tenant_roles:
        tenant_roles.append("viewer")
    module.TENANT_MEMBER_ROLES = tuple(tenant_roles)
    permissions = module.PERMISSIONS_BY_ROLE
    permissions.setdefault("viewer", set())
    s13_permissions = {
        "review_reply_list",
        "review_reply_draft",
        "review_reply_confirm",
        "review_reply_status",
        "review_reply_retry",
    }
    permissions.setdefault("admin", set()).update(s13_permissions)
    permissions.setdefault("owner", set()).update(s13_permissions)
    permissions.setdefault("operator", set()).update(s13_permissions)
    action_map = module.ACTION_TO_PERMISSION
    action_map.update(
        {
            "review_reply_list": "review_reply_list",
            "review_reply_draft": "review_reply_draft",
            "review_reply_confirm": "review_reply_confirm",
            "review_reply_status": "review_reply_status",
            "review_reply_retry": "review_reply_retry",
            "review_reply_task": "review_reply_confirm",
        }
    )
    module._S13_PERMISSION_PATCHED = True


def _patch_service(module: Any) -> None:
    if getattr(module, "_S13_IDEMPOTENT_REPLAY_PATCHED", False):
        return
    service_class = module.S13Service
    original_confirm = service_class.confirm
    original_retry = service_class.retry

    def _replay(service, context, request_id: str):  # type: ignore[no-untyped-def]
        request = service.control.get_request(request_id)
        if not request or request.get("status") != "confirmed":
            return None
        if request.get("hotel_id") != context.hotel_id:
            result = module._base_output("confirm", status="blocked")
            result["blocked_reason"] = "hotel_scope_mismatch"
            return result
        with closing(service.control.connect()) as conn:
            ref_row = conn.execute(
                "SELECT review_id FROM s13_review_refs WHERE ref_hash=?",
                (request["review_ref_hash"],),
            ).fetchone()
            attempt = conn.execute(
                "SELECT operation, reconciliation_status FROM s13_write_attempts WHERE request_id=? ORDER BY created_at DESC LIMIT 1",
                (request_id,),
            ).fetchone()
        if not ref_row:
            result = module._base_output("confirm", status="data_gap")
            result.update({"blocked_reason": "review_ref_state_missing", "data_gaps": ["review_ref_state_missing"]})
            return result
        task = service.outbox.read_by_unique(
            hotel_id=context.hotel_id,
            platform=str(request["platform"]),
            review_id=str(ref_row["review_id"]),
        )
        if not task:
            result = module._base_output("confirm", status="write_failed")
            result.update({"platform": request.get("platform"), "blocked_reason": "confirmed_task_readback_missing"})
            return result
        operation = str(attempt["operation"] if attempt else "insert")
        retry_mode = "cas_update" if operation == "cas_retry" else None
        action = "retry" if retry_mode else "confirm"
        result = service._confirmed_output(
            request,
            task,
            retry_mode=retry_mode,
            reconciliation_status="recovered",
        )
        result["action"] = action
        result["idempotent_replay"] = True
        result["task"].update(
            {
                "write_performed": False,
                "affected_rows": 0,
                "pending_readback_verified": bool(
                    task.status == "pending"
                    and task.reply_content == request["reply_content"]
                ),
                "reconciliation_status": "recovered",
                "idempotency_verified": True,
            }
        )
        return result

    def confirm(service, context, *, request_id: str):  # type: ignore[no-untyped-def]
        replay = _replay(service, context, request_id)
        return replay if replay is not None else original_confirm(service, context, request_id=request_id)

    def retry(service, context, *, request_id: str):  # type: ignore[no-untyped-def]
        replay = _replay(service, context, request_id)
        return replay if replay is not None else original_retry(service, context, request_id=request_id)

    service_class.confirm = confirm
    service_class.retry = retry
    module._S13_IDEMPOTENT_REPLAY_PATCHED = True


def _apply_patch(module: Any) -> None:
    if module.__name__ == "runtime.storage":
        _patch_storage(module)
    elif module.__name__ == "runtime.cli":
        _patch_cli(module)
    elif module.__name__ == "runtime.feishu_command_router":
        _patch_router(module)
    elif module.__name__ == "runtime.safety.auth":
        _patch_auth(module)
    elif module.__name__ == "runtime.s13.service":
        _patch_service(module)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import live_contract_patch as live_patch

    live_patch._TARGETS.update(_TARGETS)
    original_apply = live_patch._apply_patch
    if not getattr(original_apply, "_S13_COMBINED_PATCH", False):
        def combined_apply(module: Any) -> None:
            original_apply(module)
            _apply_patch(module)

        combined_apply._S13_COMBINED_PATCH = True  # type: ignore[attr-defined]
        live_patch._apply_patch = combined_apply

    for name in list(_TARGETS):
        loaded = sys.modules.get(name)
        if loaded is not None:
            live_patch._apply_patch(loaded)

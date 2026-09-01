from __future__ import annotations

import argparse
import json
from pathlib import Path

from runtime.adapters.beyondh import beyondh_call, build_beyondh_request
from runtime.adapters.database import DB_KINDS, INSPECT_MODES, TEMPLATES, database_inspect, database_query, database_template_result
from runtime.adapters.dindanll import (
    build_dindanll_request,
    normalize_dindanll_inventory_sample,
    normalize_dindanll_order_sample,
    normalize_dindanll_price_sample,
)
from runtime.adapters.meituan import build_meituan_request, normalize_meituan_price_sample, normalize_meituan_room_count_sample
from runtime.adapters.zhiting_price_task_outbox import read_price_task_status
from runtime.approval_guard import validate_demo_safe_approval_payload
from runtime.common import DEFAULT_DB, emit, parse_json_input, redacted_request, source_meta
from runtime.contracts import validate_contract
from runtime.decisions.baseline import baseline
from runtime.decisions.calendar import calendar_query, calendar_sync, event_bridge_check, event_discover, market_context
from runtime.decisions.command_menu import command_menu_cancel, command_menu_reply, command_menu_start
from runtime.decisions.competition import competition_alert
from runtime.decisions.customer import customer_analysis
from runtime.decisions.daily_alignment import jy01_rs01_alignment
from runtime.decisions.demand import demand_index, snapshot
from runtime.decisions.deviation import deviation
from runtime.decisions.ota_health import conversion_diagnosis, ota_health
from runtime.decisions.pricing import baseline_price, execute_price, expected_occupancy, revenue_decision
from runtime.decisions.promotion import promotion_execute, promotion_plan, promotion_roi
from runtime.decisions.reputation import reputation_diagnosis
from runtime.decisions.tasks import frontdesk_tasks
from runtime.demo_today_generator import generate_today_demo
from runtime.demo_mode import demo_chain, demo_node
from runtime.experience.experience_promoter import promote_candidate
from runtime.experience.experience_replay import replay_candidate
from runtime.experience.experience_reviewer import review_candidate
from runtime.experience.experience_store import find_candidate, list_candidates, upsert_candidate
from runtime.feishu_command_router import safe_route_feishu_command
from runtime.market_sources import event_bridge_status, load_market_source_config, market_source_diagnostics
from runtime.safety.auth import ACTION_TO_PERMISSION, ROLES, bootstrap_active_auth, build_auth_context, permission_gate, role_map_migration_preview
from runtime.safety.feishu_output import feishu_output_gate as evaluate_feishu_output_gate
from runtime.s14_operation_diagnosis import diagnose_s14_excel_file, diagnose_s14_mysql_template_result
from runtime.storage import approval_create, approval_get, approval_mark as storage_approval_mark, init_db, log_api, seed_demo


AUTH_SOURCES = ["feishu", "cli", "cron", "manual_test"]


def add_auth_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--auth-source", choices=AUTH_SOURCES, default="manual_test")
    parser.add_argument("--user-id")
    parser.add_argument("--open-id")
    parser.add_argument("--union-id")
    parser.add_argument("--chat-id")
    parser.add_argument("--chat-type", choices=["group", "p2p"])
    parser.add_argument("--user-role", choices=list(ROLES))
    parser.add_argument("--auth-config")


def add_menu_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", choices=AUTH_SOURCES, default="feishu")
    parser.add_argument("--user-id")
    parser.add_argument("--open-id")
    parser.add_argument("--union-id")
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--chat-type", choices=["group", "p2p"])
    parser.add_argument("--user-role", choices=list(ROLES))
    parser.add_argument("--auth-config")


def auth_context_from_args(args: argparse.Namespace) -> dict:
    return build_auth_context(
        source=getattr(args, "auth_source", getattr(args, "source", "manual_test")),
        user_id=getattr(args, "user_id", None),
        open_id=getattr(args, "open_id", None),
        union_id=getattr(args, "union_id", None),
        chat_id=getattr(args, "chat_id", None),
        chat_type=getattr(args, "chat_type", None),
        user_role=getattr(args, "user_role", None),
        config_path=getattr(args, "auth_config", None),
        auth_db_path=getattr(args, "db", None),
    )


def auth_bootstrap_sync(args: argparse.Namespace) -> None:
    result = bootstrap_active_auth(args.db, config_path=args.auth_config)
    emit({
        **result,
        "writes_json": False,
        "live_execution_count": 0,
        "formal_approval_created": False,
    })


def auth_check(args: argparse.Namespace) -> None:
    auth_context = auth_context_from_args(args)
    gate = permission_gate(auth_context, args.action, dry_run=args.dry_run)
    feishu_diagnostics = None
    if auth_context.get("source") == "feishu":
        feishu_diagnostics = {
            "config_loaded": auth_context.get("reason") not in {"auth_config_not_found", "auth_config_invalid_json"},
            "chat_allowed": auth_context.get("reason") != "chat_not_allowed" and bool(auth_context.get("feishu_chat_id")),
            "user_matched": bool(auth_context.get("matched_by")),
            "matched_by": auth_context.get("matched_by"),
            "role": auth_context.get("user_role"),
            "auth_status": auth_context.get("auth_status"),
            "reason": auth_context.get("reason"),
            "identity_present": bool(
                auth_context.get("feishu_open_id")
                or auth_context.get("feishu_user_id")
                or auth_context.get("feishu_union_id")
            ),
        }
    redacted_auth_context = {
        "source": auth_context.get("source"),
        "auth_status": auth_context.get("auth_status"),
        "reason": auth_context.get("reason"),
        "user_role": auth_context.get("user_role"),
        "matched_by": auth_context.get("matched_by"),
        "matched_role_name": auth_context.get("matched_role_name"),
        "identity_warning": auth_context.get("identity_warning"),
        "feishu_user_id": "set" if auth_context.get("feishu_user_id") else None,
        "feishu_open_id": "set" if auth_context.get("feishu_open_id") else None,
        "feishu_union_id": "set" if auth_context.get("feishu_union_id") else None,
        "feishu_chat_id": "set" if auth_context.get("feishu_chat_id") else None,
        "permissions": auth_context.get("permissions") or [],
    }
    emit(
        {
            "status": "ok" if gate["allowed"] else "blocked",
            "skill": args.skill,
            "action": args.action,
            "dry_run": args.dry_run,
            "required_permission": gate["required_permission"],
            "allowed": gate["allowed"],
            "reason": gate["reason"],
            "auth_context": redacted_auth_context,
            "feishu_auth_diagnostics": feishu_diagnostics,
        }
    )


def role_map_preview(args: argparse.Namespace) -> None:
    emit(role_map_migration_preview(args.auth_config))


def price_task_history(args: argparse.Namespace) -> None:
    emit(
        read_price_task_status(
            args.db,
            channel_source=args.channel_source,
            hotel_name=getattr(args, "hotel_name", None),
            business_date=getattr(args, "business_date", None),
            source_decision_id=getattr(args, "source_decision_id", None),
        )
    )


def approval_create_checked(args: argparse.Namespace) -> None:
    auth_context = auth_context_from_args(args)
    gate = permission_gate(auth_context, "create_approval")
    if not gate["allowed"]:
        emit({"status": "blocked", "reason": gate["reason"], "auth_context": auth_context})
        return
    payload = parse_json_input(args.payload)
    payload["hotel_id"] = args.hotel_id
    requester_id = (
        auth_context.get("feishu_open_id")
        or auth_context.get("feishu_user_id")
        or auth_context.get("feishu_union_id")
        or args.requested_by
    )
    args.requested_by = requester_id
    args.payload = json.dumps(payload, ensure_ascii=False)
    payload_gate = validate_demo_safe_approval_payload(payload, args.action_type)
    if not payload_gate["allowed"]:
        emit(
            {
                "status": "blocked",
                "reason": payload_gate["reason"],
                "approval_required": False,
                "template_id": payload_gate.get("template_id"),
                "auth_context": auth_context,
                "payload_gate": payload_gate,
            }
        )
        return
    approval_create(args)


def approval_mark_checked(args: argparse.Namespace) -> None:
    auth_context = auth_context_from_args(args)
    gate = permission_gate(auth_context, "approve_live_action")
    if not gate["allowed"]:
        emit({"status": "blocked", "reason": gate["reason"], "auth_context": auth_context})
        return
    approval = approval_get(args.db, args.approval_id)
    if approval is None:
        emit({"status": "not_found", "approval_id": args.approval_id})
        return
    approver_id = (
        auth_context.get("feishu_open_id")
        or auth_context.get("feishu_user_id")
        or auth_context.get("feishu_union_id")
        or args.user
    )
    # admin/owner 可自审批(用户设计);仅对非 admin/owner 拦自审批(其本来也过不了 permission_gate)。
    if (
        args.approve
        and approval.get("requested_by")
        and approval.get("requested_by") == approver_id
        and auth_context.get("user_role") not in {"admin", "owner"}
    ):
        emit({"status": "blocked", "reason": "self_approval_not_allowed", "approval_id": args.approval_id})
        return
    args.user = approver_id
    storage_approval_mark(args)


def adapter_request(args: argparse.Namespace) -> None:
    biz = parse_json_input(args.biz_content, getattr(args, "biz_content_b64", None))
    adapter = args.adapter
    if adapter == "beyondh":
        if not args.method:
            emit({"status": "error", "message": "--method is required for beyondh"})
            return
        request_body = build_beyondh_request(args.method, biz)
        request = {
            "method": "POST",
            "url": "BEYONDH_BASE_URL",
            "content_type": "application/json",
            "headers": {"Content-Type": "application/json"},
            "body": request_body,
        }
        source = source_meta("beyondh", args.channel_source or "pms", "beyondh_api", "write_dry_run", "manual_required")
        method = args.method
    elif adapter == "meituan":
        if not args.path:
            emit({"status": "error", "message": "--path is required for meituan"})
            return
        request = build_meituan_request(args.path, biz, args.business_id)
        source = source_meta("meituan", args.channel_source or "meituan", "meituan_api", "write_dry_run", "manual_required")
        method = args.path
    elif adapter == "dindanll":
        if not args.path:
            emit({"status": "error", "message": "--path is required for dindanll"})
            return
        request = build_dindanll_request(args.path, biz)
        source = source_meta("dindanll", args.channel_source or "pms", "dindanll_api", "write_dry_run", "manual_required")
        method = args.path
    else:
        emit({"status": "error", "message": f"unsupported adapter: {adapter}"})
        return

    summary = {
        **source,
        "adapter": adapter,
        "request": redacted_request(request),
        "dry_run": True,
        "live_call": False,
    }
    if not args.no_log:
        log_api(args.hotel_id, method, summary, {"dry_run": True}, "dry_run", args.db)
    emit({"status": "dry_run", "summary": summary, "contract_validation": validate_contract(summary)})


def normalize_sample(args: argparse.Namespace) -> None:
    normalizers = {
        "meituan-price": normalize_meituan_price_sample,
        "meituan-room-count": normalize_meituan_room_count_sample,
        "dindanll-price": normalize_dindanll_price_sample,
        "dindanll-inventory": normalize_dindanll_inventory_sample,
        "dindanll-order": normalize_dindanll_order_sample,
    }
    payload = normalizers[args.sample]()
    emit({"status": "ok", "sample": args.sample, "payload": payload, "contract_validation": validate_contract(payload)})


def feishu_output_gate(args: argparse.Namespace) -> None:
    emit(
        evaluate_feishu_output_gate(
            source=args.source,
            content_kind=args.content_kind,
            message=args.message,
            filename=args.filename,
            artifact_kind=args.artifact_kind,
        )
    )


def feishu_route(args: argparse.Namespace) -> None:
    member_info = None
    if getattr(args, "member_info_json", None):
        member_info = json.loads(args.member_info_json)
    emit(
        safe_route_feishu_command(
            args.message,
            role=args.user_role,
            output_profile=args.output_profile,
            db_path=args.db,
            render=args.render,
            hotel_id=args.hotel_id,
            account_id=args.account_id,
            chat_id=args.chat_id,
            chat_type=args.chat_type,
            user_id=args.user_id,
            open_id=args.open_id,
            union_id=args.union_id,
            auth_config=args.auth_config,
            use_command_menu=args.use_command_menu,
            reply=args.reply,
            use_generated_today=args.use_generated_today,
            demo_data_dir=args.demo_data_dir,
            trusted_runtime_role=args.trusted_runtime_role,
            full_json_requested=args.full_json,
            production_feishu=args.production_feishu,
            compact=not args.full_json or not args.trusted_runtime_role,
            as_of_time=args.as_of_time,
            s14_source_config=args.s14_source_config,
            member_info=member_info,
        )
    )


def s14_diagnosis(args: argparse.Namespace) -> None:
    if args.source_mode == "excel":
        if not args.excel_path:
            emit({"status": "data_gap", "node_id": "N009", "skill_id": "S14", "source_mode": "excel", "missing_fields": ["excel_path"], "publisher_status": "not_configured"})
            return
        emit(diagnose_s14_excel_file(args.excel_path, hotel_id=args.hotel_id, report_dir=args.report_dir))
        return
    template = database_template_result("operation_diagnosis", args.hotel_id, date=args.period_end)
    emit(diagnose_s14_mysql_template_result(template, hotel_id=args.hotel_id, report_dir=args.report_dir))


def s14_ext_diagnosis(args: argparse.Namespace) -> None:
    emit(
        {
            "status": "deprecated",
            "intent": "s14_ext_diagnosis",
            "blocked_reason": "s14_ext_migrated_to_independent_service",
            "summary": "第三方营销诊断已迁移到独立服务，本项目不再处理该入口。",
            "business_result_generated": False,
            "live_allowed": False,
            "approval_data_allowed": False,
            "runtime_command": None,
        }
    )


def _read_openclaw_context_policy() -> dict:
    root = Path(__file__).resolve().parents[1]
    example_path = root / "config" / "openclaw.example.json"
    manifest_path = root / "manifests" / "openclaw_context_manifest.yaml"
    policy = {
        "example_config_path": "config/openclaw.example.json",
        "context_manifest_path": "manifests/openclaw_context_manifest.yaml",
        "example_config_exists": example_path.exists(),
        "openclaw_context_manifest_exists": manifest_path.exists(),
        "server_config_verified": False,
        "server_config_note": "Template only; verify the live OpenClaw service config separately.",
    }
    if example_path.exists():
        try:
            payload = json.loads(example_path.read_text(encoding="utf-8"))
            defaults = (payload.get("agents") or {}).get("defaults") or {}
            agents = (payload.get("agents") or {}).get("list") or []
            chief = agents[0] if agents else {}
            policy.update(
                {
                    "example_default_context_injection": defaults.get("contextInjection"),
                    "example_chief_context_injection": chief.get("contextInjection"),
                    "example_default_bootstrap_total_max_chars": defaults.get("bootstrapTotalMaxChars"),
                    "example_chief_bootstrap_total_max_chars": chief.get("bootstrapTotalMaxChars"),
                    "example_chief_skills_prompt_max_chars": (chief.get("skillsLimits") or {}).get("maxSkillsPromptChars"),
                }
            )
        except Exception as exc:  # pragma: no cover - defensive env diagnostics
            policy.update({"example_config_parse_status": "error", "example_config_error": exc.__class__.__name__})
    if manifest_path.exists():
        text = manifest_path.read_text(encoding="utf-8")
        in_root_context = False
        read_first_count = 0
        for line in text.splitlines():
            if line.startswith("root_context_files:"):
                in_root_context = True
                continue
            if in_root_context:
                if line.startswith("  - "):
                    read_first_count += 1
                elif line and not line.startswith(" "):
                    break
        policy["read_first_file_count"] = read_first_count
    return policy


def _resolve_database_dsn_env_for_env_check(mapping_config_path: str | None, profile_name: str | None) -> dict:
    """Resolve the active database DSN env var without exposing the DSN value."""
    import os

    status = {
        "profile": profile_name,
        "required_dsn_env": "HOTEL_OTA_DB_DSN",
        "status": "missing",
        "mapping_config_loaded": False,
        "profile_valid": True,
    }
    if mapping_config_path:
        try:
            payload = json.loads(Path(mapping_config_path).read_text(encoding="utf-8-sig"))
            profiles = payload.get("profiles") or {}
            selected = profile_name or payload.get("default_profile")
            profile = profiles.get(selected) or {}
            if selected:
                status["profile"] = selected
            if selected and selected not in profiles:
                status["status"] = "profile_missing"
                status["profile_valid"] = False
                status["mapping_config_loaded"] = True
                return status
            if isinstance(profile, dict) and profile.get("dsn_env"):
                status["required_dsn_env"] = str(profile["dsn_env"])
            status["mapping_config_loaded"] = True
        except Exception as exc:  # pragma: no cover - env diagnostics must not crash
            status["mapping_config_error"] = exc.__class__.__name__
    dsn_env = str(status["required_dsn_env"])
    status["status"] = "set" if os.environ.get(dsn_env) else "missing"
    return status


def env_check(args: argparse.Namespace) -> None:
    import os

    def safe_env_output_key(key: str) -> str:
        replacements = {
            "HOTEL_OTA_EVENT_BRIDGE_TOKEN": "HOTEL_OTA_EVENT_BRIDGE_CREDENTIAL",
        }
        return replacements.get(key, key)

    keys = [
        "HOTEL_OTA_DB",
        "HOTEL_OTA_LOG_DIR",
        "HOTEL_OTA_ENV",
        "HOTEL_OTA_REQUIRE_VERIFIED_ROLE",
        "HOTEL_OTA_AUTH_CONFIG",
        "HOTEL_OTA_DB_SOURCE_ENABLE",
        "HOTEL_OTA_DB_KIND",
        "HOTEL_OTA_DB_MAPPING_CONFIG",
        "HOTEL_OTA_DB_PROFILE",
        "HOTEL_OTA_DB_READONLY",
        "HOTEL_OTA_FEISHU_DEBUG",
        "HOTEL_OTA_FEISHU_FINAL_GATE_REQUIRED",
        "HOTEL_OTA_FEISHU_ALLOW_FILE_EXPORT",
        "HOTEL_OTA_FEISHU_ALLOW_CONFIG_EXPORT",
        "HOTEL_OTA_FEISHU_ALLOW_RAW_DATA_EXPORT",
        "HOTEL_OTA_MARKET_SOURCE_CONFIG",
        "HOTEL_OTA_S14_SOURCE_CONFIG",
        "HOTEL_OTA_PRICE_TASK_WRITE_ENABLE",
        "HOTEL_OTA_PRICE_TASK_REQUIRE_CONFIRM",
        "HOTEL_OTA_PRICE_TASK_ALLOWED_CHANNELS",
        "HOTEL_OTA_PRICE_TASK_DB_KIND",
        "HOTEL_OTA_PRICE_TASK_DB_DSN",
        "HOLIDAY_SOURCE_PROVIDER",
        "APISBO_HOLIDAY_BASE_URL",
        "HOTEL_OTA_EVENT_BRIDGE_TOKEN",
        "BEYONDH_ENABLE_LIVE",
        "MEITUAN_ENABLE_LIVE",
        "DINDANLL_ENABLE_LIVE",
    ]
    values = {key: os.environ.get(key) for key in keys}
    database_source_enabled = values.get("HOTEL_OTA_DB_SOURCE_ENABLE") == "1"
    live_flags = {
        "BEYONDH_ENABLE_LIVE": values.get("BEYONDH_ENABLE_LIVE"),
        "MEITUAN_ENABLE_LIVE": values.get("MEITUAN_ENABLE_LIVE"),
        "DINDANLL_ENABLE_LIVE": values.get("DINDANLL_ENABLE_LIVE"),
    }
    live_flags_explicit = all(flag not in (None, "") for flag in live_flags.values())
    live_flags_disabled = all((flag or "0") == "0" for flag in live_flags.values())
    direct_api_live_enabled = any((flag or "0") == "1" for flag in live_flags.values())
    price_task_write_enabled = values.get("HOTEL_OTA_PRICE_TASK_WRITE_ENABLE", "0") == "1"
    price_task_requires_confirm = (values.get("HOTEL_OTA_PRICE_TASK_REQUIRE_CONFIRM") or "1") == "1"
    price_task_db_kind = values.get("HOTEL_OTA_PRICE_TASK_DB_KIND") or values.get("HOTEL_OTA_DB_KIND") or "sqlite"
    verified_role_enforced = values.get("HOTEL_OTA_REQUIRE_VERIFIED_ROLE") == "1"
    safety_ok = (
        values.get("HOTEL_OTA_ENV", "production") == "production"
        and values.get("HOTEL_OTA_FEISHU_DEBUG", "0") == "0"
        and values.get("HOTEL_OTA_FEISHU_FINAL_GATE_REQUIRED", "1") == "1"
        and values.get("HOTEL_OTA_FEISHU_ALLOW_FILE_EXPORT", "0") == "0"
        and values.get("HOTEL_OTA_FEISHU_ALLOW_CONFIG_EXPORT", "0") == "0"
        and values.get("HOTEL_OTA_FEISHU_ALLOW_RAW_DATA_EXPORT", "0") == "0"
        and live_flags_disabled
        and price_task_requires_confirm
        and verified_role_enforced
    )
    auth_config = values.get("HOTEL_OTA_AUTH_CONFIG")
    mapping_config = values.get("HOTEL_OTA_DB_MAPPING_CONFIG")
    database_dsn_status = _resolve_database_dsn_env_for_env_check(mapping_config, values.get("HOTEL_OTA_DB_PROFILE"))
    if database_dsn_status["required_dsn_env"] not in values:
        values[database_dsn_status["required_dsn_env"]] = os.environ.get(database_dsn_status["required_dsn_env"])
    missing = [safe_env_output_key(key) for key, value in values.items() if value in (None, "")]
    market_source_config = values.get("HOTEL_OTA_MARKET_SOURCE_CONFIG")
    s14_source_config = values.get("HOTEL_OTA_S14_SOURCE_CONFIG")
    db_path = values.get("HOTEL_OTA_DB")
    log_dir = values.get("HOTEL_OTA_LOG_DIR")
    path_status = {
        "auth_config_exists": bool(auth_config and os.path.exists(auth_config)),
        "db_mapping_config_exists": bool(mapping_config and os.path.exists(mapping_config)),
        "market_source_config_exists": bool(market_source_config and os.path.exists(market_source_config)),
        "s14_source_config_exists": bool(s14_source_config and os.path.exists(s14_source_config)),
        "db_path_parent_exists": bool(db_path and os.path.exists(os.path.dirname(db_path) or ".")),
        "log_dir_exists": bool(log_dir and os.path.isdir(log_dir)),
    }
    market_config = load_market_source_config(market_source_config)
    market_diagnostics = market_source_diagnostics(market_config)
    event_bridge_diagnostics = event_bridge_status(market_config)
    must_fix = []
    if not safety_ok:
        must_fix.append("production_safety_env_not_locked")
    if values.get("HOTEL_OTA_FEISHU_FINAL_GATE_REQUIRED") != "1":
        must_fix.append("gateway_final_gate_requirement_not_set")
    if direct_api_live_enabled:
        must_fix.append("direct_api_live_enabled_deprecated_use_price_task_outbox")
    if not price_task_requires_confirm:
        must_fix.append("price_task_confirmation_not_required")
    if not verified_role_enforced:
        must_fix.append("verified_role_not_enforced")
    if not path_status["auth_config_exists"]:
        must_fix.append("auth_config_missing_or_unreadable")
    if database_source_enabled:
        if values.get("HOTEL_OTA_DB_READONLY") != "1":
            must_fix.append("database_readonly_not_enforced")
        if values.get("HOTEL_OTA_DB_KIND") in {"mysql", "postgres"}:
            if not database_dsn_status.get("profile_valid", True):
                must_fix.append("database_profile_missing_or_invalid")
            if database_dsn_status.get("status") != "set":
                must_fix.append("database_dsn_missing")
            if not path_status["db_mapping_config_exists"]:
                must_fix.append("database_mapping_config_missing_or_unreadable")
    else:
        must_fix.append("database_source_disabled_for_commercial")
    if not path_status["db_path_parent_exists"]:
        must_fix.append("sqlite_parent_dir_missing")
    if not path_status["log_dir_exists"]:
        must_fix.append("log_dir_missing")
    commercial_blockers = [item for item in must_fix if item != "database_source_disabled_for_commercial"]
    if commercial_blockers:
        readiness_stage = "commercial_blocked"
    elif not database_source_enabled:
        readiness_stage = "internal_demo_only"
    else:
        readiness_stage = "commercial_data_ready"
    emit(
        {
            "status": "ok" if safety_ok else "warning",
            "database_source_status": "enabled" if database_source_enabled else "database_source_disabled",
            "safety_status": "production_locked" if safety_ok else "check_environment",
            "readiness_stage": readiness_stage,
            "must_fix_before_commercial": must_fix,
            "path_status": path_status,
            "market_source_status": market_diagnostics,
            "event_bridge_status": event_bridge_diagnostics,
            "database_dsn_status": database_dsn_status,
            "live_execution_status": (
                "direct_api_deprecated_disabled_safe"
                if live_flags_disabled
                else "direct_api_deprecated_enabled_blocked"
            ),
            "direct_api_execution_status": (
                "deprecated_disabled_safe"
                if live_flags_disabled
                else "deprecated_enabled_blocked"
            ),
            "price_task_outbox_status": {
                "write_enabled": price_task_write_enabled,
                "require_confirm": price_task_requires_confirm,
                "allowed_channels": values.get("HOTEL_OTA_PRICE_TASK_ALLOWED_CHANNELS") or "ctrip,meituan",
                "db_kind": price_task_db_kind,
                "ready_for_task_write": price_task_write_enabled and price_task_requires_confirm and not direct_api_live_enabled,
            },
            "price_task_write_status": (
                "enabled"
                if price_task_write_enabled and price_task_requires_confirm and not direct_api_live_enabled
                else ("missing_config" if not price_task_requires_confirm else "disabled")
            ),
            "openclaw_context_policy": _read_openclaw_context_policy(),
            "missing_keys": missing,
            "env": {safe_env_output_key(key): ("set" if value else "missing") for key, value in values.items()},
        }
    )


def experience_candidates(args: argparse.Namespace) -> None:
    candidates = list_candidates(getattr(args, "store", None), hotel_id=getattr(args, "hotel_id", None), db_path=args.db)
    emit(
        {
            "status": "ok",
            "hotel_id": getattr(args, "hotel_id", None),
            "candidate_count": len(candidates),
            "candidates": candidates,
            "approval_data_allowed": False,
            "live_allowed": False,
            "production_rule_modified": False,
        }
    )


def experience_review(args: argparse.Namespace) -> None:
    candidate = find_candidate(args.candidate_id, getattr(args, "store", None), hotel_id=getattr(args, "hotel_id", None), db_path=args.db)
    result = review_candidate(candidate, approve=bool(args.approve), reviewer=args.reviewer)
    if result.get("candidate"):
        upsert_candidate(result["candidate"], db_path=args.db, hotel_id=getattr(args, "hotel_id", None))
    emit(result)


def experience_replay(args: argparse.Namespace) -> None:
    candidate = find_candidate(args.candidate_id, getattr(args, "store", None), hotel_id=getattr(args, "hotel_id", None), db_path=args.db)
    emit(replay_candidate(candidate))


def experience_promote(args: argparse.Namespace) -> None:
    candidate = find_candidate(args.candidate_id, getattr(args, "store", None), hotel_id=getattr(args, "hotel_id", None), db_path=args.db)
    replay = replay_candidate(candidate)
    result = promote_candidate(candidate, replay_result=replay, dry_run=not bool(args.apply))
    if result.get("status") in {"manual_change_request", "ready_for_manual_merge"}:
        updated = dict(candidate)
        updated["status"] = "promoted"
        updated["promoted_to"] = result.get("change_request_id")
        upsert_candidate(updated, db_path=args.db, hotel_id=getattr(args, "hotel_id", None))
    emit(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hotel OTA OpenClaw runtime helper")
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--demo", action="store_true", help="Use demo fixtures and block formal approval/live execution.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db").set_defaults(func=init_db)
    sub.add_parser("seed-demo").set_defaults(func=seed_demo)

    p = sub.add_parser("generate-today-demo")
    p.add_argument("--business-date", help="Synthetic business date in YYYY-MM-DD. Defaults to local today.")
    p.add_argument("--seed", type=int, help="Deterministic generation seed.")
    p.add_argument(
        "--profile",
        default="normal",
        choices=["normal", "low_occupancy", "high_demand", "competitor_price_drop", "bad_reviews", "promotion_needed"],
    )
    p.add_argument("--hotel-id", default="puyue-demo", help="Synthetic dataset tenant identifier.")
    p.add_argument("--write-db", action="store_true", help="Write only to the SQLite demo DB path.")
    p.add_argument("--write-fixtures", action="store_true", help="Write generated fixtures under examples/demo_data/generated by default.")
    p.add_argument("--dry-run", action="store_true", help="Generate metadata without writing fixtures or SQLite.")
    p.add_argument("--output-dir", help="Generated fixture output directory.")
    p.set_defaults(func=generate_today_demo)

    p = sub.add_parser("experience-candidates")
    p.add_argument("--hotel-id")
    p.add_argument("--store")
    p.set_defaults(func=experience_candidates)

    p = sub.add_parser("experience-review")
    p.add_argument("--candidate-id", required=True)
    p.add_argument("--hotel-id")
    p.add_argument("--reviewer", default="manual_reviewer")
    p.add_argument("--store")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--approve", action="store_true")
    group.add_argument("--reject", action="store_true")
    p.set_defaults(func=experience_review)

    p = sub.add_parser("experience-replay")
    p.add_argument("--candidate-id", required=True)
    p.add_argument("--hotel-id")
    p.add_argument("--store")
    p.set_defaults(func=experience_replay)

    p = sub.add_parser("experience-promote")
    p.add_argument("--candidate-id", required=True)
    p.add_argument("--hotel-id")
    p.add_argument("--store")
    p.add_argument("--apply", action="store_true", help="Return manual-rule-change readiness only; never writes production rules.")
    p.set_defaults(func=experience_promote)

    p = sub.add_parser("demo-chain")
    p.add_argument("--scenario", default="SC01", help="Registered scenario id, for example SC01.")
    p.add_argument("--all", action="store_true", help="Run all registered demo chains SC01-SC10.")
    p.add_argument("--allow-placeholder", action="store_true", help="Allow explicit placeholder demo fixtures for development only.")
    p.add_argument("--use-generated-today", action="store_true", help="Read the latest synthetic_today_demo snapshots from SQLite.")
    p.add_argument("--strict-generated-today", action="store_true", help="Return data_gap instead of falling back to static demo fixtures when synthetic today data is missing.")
    p.add_argument("--demo-data-dir", help="Demo data directory label for run context diagnostics.")
    p.add_argument("--as-of-time", help="Explicit HH:MM checkpoint for time-aware demo results.")
    p.set_defaults(func=demo_chain)

    p = sub.add_parser("demo-node")
    p.add_argument("--node", default="N001", help="Registered node id, for example N022.")
    p.add_argument("--all", action="store_true", help="Run all registered demo node fixtures N001-N022.")
    p.add_argument("--allow-placeholder", action="store_true", help="Allow explicit placeholder demo fixtures for development only.")
    p.add_argument("--use-generated-today", action="store_true", help="Read the latest synthetic_today_demo snapshots from SQLite.")
    p.add_argument("--strict-generated-today", action="store_true", help="Return data_gap instead of falling back to static demo fixtures when synthetic today data is missing.")
    p.add_argument("--demo-data-dir", help="Demo data directory label for run context diagnostics.")
    p.add_argument("--as-of-time", help="Explicit HH:MM checkpoint for time-aware demo results.")
    p.set_defaults(func=demo_node)

    p = sub.add_parser("auth-check")
    p.add_argument("--source", choices=AUTH_SOURCES, default="manual_test")
    p.add_argument("--user-id")
    p.add_argument("--open-id")
    p.add_argument("--union-id")
    p.add_argument("--chat-id", required=True)
    p.add_argument("--user-role", choices=list(ROLES))
    p.add_argument("--auth-config")
    p.add_argument("--skill", default="unknown")
    p.add_argument("--action", choices=sorted(ACTION_TO_PERMISSION), required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=auth_check)

    p = sub.add_parser("role-map-preview")
    p.add_argument("--auth-config", required=True)
    p.set_defaults(func=role_map_preview)

    p = sub.add_parser("auth-bootstrap-sync")
    p.add_argument("--auth-config", required=True)
    p.set_defaults(func=auth_bootstrap_sync)

    p = sub.add_parser("snapshot")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--source", default="sample")
    p.set_defaults(func=snapshot)

    p = sub.add_parser("baseline")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=baseline)

    p = sub.add_parser("jy01-rs01-alignment")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=jy01_rs01_alignment)

    p = sub.add_parser("deviation")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.add_argument("--as-of-time")
    p.add_argument("--use-generated-today", action="store_true")
    p.add_argument("--strict-generated-today", action="store_true")
    p.set_defaults(func=deviation)

    p = sub.add_parser("revenue-decision")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--channel", default="Mtop")
    p.add_argument("--begin-date")
    p.add_argument("--end-date")
    p.add_argument("--activity-discount-factors", help="Comma-separated OTA activity factors, e.g. 0.9,0.95")
    p.add_argument("--pms-price", type=float, help="PMS price reference only; never used as OTA execution target.")
    p.add_argument("--as-of-time", help="Explicit HH:MM checkpoint for demo revenue decisions.")
    p.add_argument("--use-generated-today", action="store_true")
    p.add_argument("--strict-generated-today", action="store_true")
    p.set_defaults(func=revenue_decision)

    p = sub.add_parser("expected-occupancy")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.add_argument("--as-of-time")
    p.set_defaults(func=expected_occupancy)

    p = sub.add_parser("baseline-price")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=baseline_price)

    p = sub.add_parser("demand-index")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=demand_index)

    p = sub.add_parser("calendar-sync")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--seed-file")
    p.add_argument("--market-source-config")
    p.add_argument("--hotel-id")
    p.add_argument("--holiday-provider")
    p.add_argument("--sync-remote-holidays", action="store_true")
    p.set_defaults(func=calendar_sync)

    p = sub.add_parser("calendar-query")
    p.add_argument("--date", required=True)
    p.set_defaults(func=calendar_query)

    p = sub.add_parser("market-context")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.add_argument(
        "--weather-provider",
        default="weather_mcp",
        choices=["weather_mcp", "wttr_http", "weather_fixture", "amap_api", "qweather_api", "openclaw_weather", "manual_weather", "manual", "sample", "wttr_mcp"],
    )
    p.add_argument("--weather-fixture")
    p.add_argument("--calendar-fixture")
    p.add_argument("--operating-fixture")
    p.add_argument("--progress-fixture")
    p.add_argument("--market-source-config")
    p.set_defaults(func=market_context)

    p = sub.add_parser("event-discover")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date-range", required=True)
    p.add_argument("--fixture-file")
    p.add_argument("--market-source-config")
    p.set_defaults(func=event_discover)

    p = sub.add_parser("event-bridge-check")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date", required=True)
    p.add_argument("--market-source-config")
    p.set_defaults(func=event_bridge_check)

    p = sub.add_parser("ota-health")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=ota_health)

    p = sub.add_parser("s14-diagnosis")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--source-mode", choices=["excel", "mysql"], required=True)
    p.add_argument("--excel-path")
    p.add_argument("--period-start")
    p.add_argument("--period-end")
    p.add_argument("--report-dir")
    p.set_defaults(func=s14_diagnosis)

    p = sub.add_parser("s14-ext-diagnosis")
    p.add_argument("--hotel-id", default="third-party-demo")
    p.add_argument("--source-mode", choices=["demo", "excel", "mysql"], default="demo")
    p.add_argument("--excel-path")
    p.add_argument("--period-start")
    p.add_argument("--period-end")
    p.add_argument("--report-dir")
    p.set_defaults(func=s14_ext_diagnosis)

    p = sub.add_parser("conversion-diagnosis")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=conversion_diagnosis)

    p = sub.add_parser("competition-alert")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=competition_alert)

    p = sub.add_parser("frontdesk-tasks")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.set_defaults(func=frontdesk_tasks)

    p = sub.add_parser("customer-analysis")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--period-start")
    p.add_argument("--period-end")
    p.add_argument("--as-of-time")
    p.add_argument("--minimum-cohort-size", type=int)
    p.add_argument("--max-output-cells", type=int)
    p.add_argument("--contact-lookup-value")
    p.set_defaults(func=customer_analysis)

    p = sub.add_parser("reputation-diagnosis")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=reputation_diagnosis)

    p = sub.add_parser("promotion-plan")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=promotion_plan)

    p = sub.add_parser("promotion-roi")
    p.add_argument("--hotel-id", required=True)
    p.set_defaults(func=promotion_roi)

    p = sub.add_parser("promotion-execute")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--approval-id")
    p.add_argument("--approved-by")
    p.add_argument("--approver-role", choices=["admin", "owner", "operator", "frontdesk", "guest"])
    p.add_argument("--dry-run", action="store_true", default=True)
    p.add_argument("--live", dest="dry_run", action="store_false")
    add_auth_args(p)
    p.set_defaults(func=promotion_execute)

    p = sub.add_parser("beyondh-call")
    p.add_argument("--hotel-id")
    p.add_argument("--method", required=True)
    p.add_argument("--biz-content", default="{}")
    p.add_argument("--biz-content-b64")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-log", action="store_true")
    p.add_argument("--timeout", type=int, default=20)
    p.set_defaults(func=beyondh_call)

    p = sub.add_parser("adapter-request")
    p.add_argument("--hotel-id")
    p.add_argument("--adapter", choices=["beyondh", "meituan", "dindanll"], required=True)
    p.add_argument("--method")
    p.add_argument("--path")
    p.add_argument("--biz-content", default="{}")
    p.add_argument("--biz-content-b64")
    p.add_argument("--business-id", type=int, default=57)
    p.add_argument("--channel-source")
    p.add_argument("--no-log", action="store_true")
    p.set_defaults(func=adapter_request)

    p = sub.add_parser("database-query")
    p.add_argument("--db-kind", choices=list(DB_KINDS), required=True)
    p.add_argument("--template", choices=list(TEMPLATES), required=True)
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--date")
    p.add_argument("--as-of-time")
    p.add_argument("--source-platform")
    p.add_argument("--profile")
    p.add_argument("--mapping-config")
    p.add_argument("--dsn")
    p.add_argument("--sql", help="Rejected by design. Use --template instead.")
    p.set_defaults(func=database_query)

    p = sub.add_parser("database-inspect")
    p.add_argument("--db-kind", choices=list(DB_KINDS), required=True)
    p.add_argument("--mode", choices=list(INSPECT_MODES), required=True)
    p.add_argument("--profile")
    p.add_argument("--mapping-config")
    p.add_argument("--dsn")
    p.add_argument("--table")
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=database_inspect)

    p = sub.add_parser("normalize-sample")
    p.add_argument(
        "--sample",
        choices=["meituan-price", "meituan-room-count", "dindanll-price", "dindanll-inventory", "dindanll-order"],
        required=True,
    )
    p.set_defaults(func=normalize_sample)

    p = sub.add_parser("feishu-output-gate")
    p.add_argument("--source", default="feishu")
    p.add_argument("--content-kind", choices=["text", "file", "artifact"], default="text")
    p.add_argument("--message", default="")
    p.add_argument("--filename")
    p.add_argument("--artifact-kind")
    p.set_defaults(func=feishu_output_gate)

    p = sub.add_parser("feishu-route")
    p.add_argument("--message", required=True)
    p.add_argument("--user-role", choices=list(ROLES), default="guest")
    p.add_argument("--output-profile", choices=["developer_debug", "owner_business", "operator_workbench", "frontdesk_task", "guest_limited"])
    p.add_argument("--render", action="store_true")
    p.add_argument("--hotel-id", help="Optional tenant selection for a V3 direct message; group chat uses its bound hotel.")
    p.add_argument("--account-id", help="Trusted inbound Feishu bot account ID; production routes validate its hotel scope.")
    p.add_argument("--chat-id")
    p.add_argument("--chat-type", choices=["group", "p2p"])
    p.add_argument("--user-id")
    p.add_argument("--open-id")
    p.add_argument("--union-id")
    p.add_argument("--auth-config")
    p.add_argument("--use-command-menu", action="store_true")
    p.add_argument("--reply")
    p.add_argument("--use-generated-today", action="store_true")
    p.add_argument("--demo-data-dir")
    p.add_argument("--as-of-time", help="Explicit HH:MM checkpoint for time-aware Feishu route testing.")
    p.add_argument("--s14-source-config", help="Private S14 registered source config. Feishu messages may only use source keys from this file.")
    p.add_argument("--member-info-json", help="JSON array returned by trusted Feishu member-info lookup for the current chat.")
    p.add_argument(
        "--production-feishu",
        action="store_true",
        help="Require gateway identity authentication and reject local role override flags.",
    )
    p.add_argument(
        "--trusted-runtime-role",
        action="store_true",
        help="Trust --user-role for local maintenance/tests without Feishu identity context. Do not use for gateway traffic.",
    )
    p.add_argument("--full-json", action="store_true", help="Return full diagnostic JSON for local server debugging only.")
    p.set_defaults(func=feishu_route)

    p = sub.add_parser("command-menu-start")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--message", default="菜单")
    add_menu_identity_args(p)
    p.set_defaults(func=command_menu_start)

    p = sub.add_parser("command-menu-reply")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--reply", required=True)
    add_menu_identity_args(p)
    p.set_defaults(func=command_menu_reply)

    p = sub.add_parser("command-menu-cancel")
    add_menu_identity_args(p)
    p.set_defaults(func=command_menu_cancel)

    p = sub.add_parser("env-check")
    p.set_defaults(func=env_check)

    p = sub.add_parser("execute-price")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--hotel-name")
    p.add_argument("--room-type-id", required=True)
    p.add_argument("--room-type-name")
    p.add_argument("--ota-product-id", help="按商品精确调价:只写该 OTA 商品,不灌给同房型其他商品(团购/钟点)")
    p.add_argument("--channel", default="Mtop")
    p.add_argument("--channel-source", choices=["meituan", "ctrip", "Mtop", "美团", "携程"])
    p.add_argument("--normal-price", type=float, required=True)
    p.add_argument("--weekend-price", type=float)
    p.add_argument("--business-date")
    p.add_argument("--source-decision-id")
    p.add_argument("--begin-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--approved-by")
    p.add_argument("--approval-id")
    p.add_argument("--approver-role", choices=["admin", "owner", "operator", "frontdesk", "guest"])
    p.add_argument("--old-price", type=float)
    p.add_argument("--floor-price", type=float)
    p.add_argument("--ceiling-price", type=float)
    p.add_argument("--activity-discount-factors", help="Comma-separated OTA activity factors, e.g. 0.9,0.95")
    p.add_argument("--pms-price", type=float, help="PMS price reference only; never used as OTA execution target.")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-log", action="store_true")
    p.add_argument("--timeout", type=int, default=20)
    add_auth_args(p)
    p.set_defaults(func=execute_price)

    p = sub.add_parser("price-task-history")
    p.add_argument("--channel-source", required=True, choices=["meituan", "ctrip"])
    p.add_argument("--hotel-name")
    p.add_argument("--business-date")
    p.add_argument("--source-decision-id")
    p.set_defaults(func=price_task_history)

    p = sub.add_parser("approval-create")
    p.add_argument("--hotel-id", required=True)
    p.add_argument("--action-type", required=True)
    p.add_argument("--requested-by", required=True)
    p.add_argument("--payload", required=True)
    add_auth_args(p)
    p.set_defaults(func=approval_create_checked)

    p = sub.add_parser("approval-mark")
    p.add_argument("--approval-id", required=True)
    p.add_argument("--user", required=True)
    add_auth_args(p)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--approve", action="store_true")
    group.add_argument("--reject", action="store_true")
    p.set_defaults(func=approval_mark_checked)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except Exception as exc:
        emit({"status": "error", "error": type(exc).__name__, "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import datetime as dt
import json
import uuid
from contextlib import closing
from dataclasses import dataclass
from typing import Any

from runtime.common import emit, json_dumps, now_local
from runtime.safety.auth import build_auth_context, permission_gate
from runtime.safety.feishu_output import feishu_output_gate
from runtime.storage import connect


MENU_TTL_MINUTES = 5
ACTIVE_MENU_STATUSES = ("active", "awaiting_params")
MENU_CONTRACT_VERSION = "production-menu-2026-08-11"


@dataclass(frozen=True)
class MenuCommand:
    command_id: str
    title: str
    permission_action: str
    risk_level: str
    readonly: bool
    dry_run: bool
    approval_required: bool
    usage: str
    intent: str | None = None
    node_id: str | None = None
    skill_id: str | None = None
    agent_id: str | None = None
    scenario_id: str | None = None
    output_template: str | None = None
    supports_synthetic_today_demo: bool = False


# Keep this list aligned with MENU.md and NUMERIC_MENU_INTENTS in
# runtime.feishu_command_router. Number 5 remains retired from the visible menu.
COMMANDS: tuple[MenuCommand, ...] = (
    MenuCommand("1", "经营快照 / 日报", "view_diagnosis", "low", True, False, False, "1", "run_s02_demo", "N005", "S2", "A1", output_template="business-summary"),
    MenuCommand("2", "销售基准线", "view_diagnosis", "low", True, False, False, "2", "sales_baseline_demo", "N010", "S15", "A2", output_template="business-summary"),
    MenuCommand("3", "进度诊断", "view_diagnosis", "low", True, False, False, "3", "progress_deviation_demo", "N011", "S16", "A2", output_template="business-summary"),
    MenuCommand("4", "环境行情", "view_diagnosis", "low", True, False, False, "4", "market_context_demo", "N006", "S4", "A1", output_template="business-summary"),
    MenuCommand("6", "竞对监控", "view_diagnosis", "low", True, False, False, "6", "competition_alert", "N007", "S7", output_template="business-summary"),
    MenuCommand("7", "口碑评价", "view_diagnosis", "low", True, False, False, "7", "reputation_demo", "N008", "S12", output_template="business-summary"),
    MenuCommand("8", "评论回复", "run_recommendation", "medium", True, False, False, "8", "review_reply_draft", "N017", "S13", output_template="business-summary"),
    MenuCommand("9", "收益建议", "run_recommendation", "medium", True, False, False, "9", "revenue_decision_demo", "N015", "S5", "A3", output_template="approval-request"),
    MenuCommand("10", "调价 dry-run", "create_dry_run", "high", False, True, False, "10", "price_execution_dry_run", "N016", "S6", "A4", output_template="approval-request"),
    MenuCommand("11", "推广数据", "run_recommendation", "medium", True, False, False, "11", "promotion_suggestion", "N021", "S11", output_template="business-summary"),
    MenuCommand("12", "推广 ROI", "run_recommendation", "medium", True, False, False, "12", "roi_demo", "N013", "S10", output_template="business-summary"),
    MenuCommand("13", "流量转化专项", "view_diagnosis", "low", True, False, False, "13", "traffic_peak_demo", "N020", "S9", "A2", output_template="business-summary"),
    MenuCommand("14", "客户订单分析", "view_diagnosis", "medium", True, False, False, "14", "customer_analysis_demo", "N014", "S17", "A2", output_template="business-summary"),
    MenuCommand("15", "运行状态", "view_diagnosis", "low", True, False, False, "15", "runtime_status", output_template="system-health"),
)

# Number 5 is intentionally absent from COMMANDS, but retained as a hidden
# compatibility shortcut so existing users/scripts are not broken.
LEGACY_COMMANDS: tuple[MenuCommand, ...] = (
    MenuCommand("5", "已退役｜原经营诊断复盘", "view_diagnosis", "low", True, False, False, "5", "ota_diagnosis_demo", "N009", "S14", output_template="business-summary"),
)

COMMAND_BY_ID = {command.command_id: command for command in (*COMMANDS, *LEGACY_COMMANDS)}
COMMAND_V27_METADATA = {
    command.command_id: {
        "intent": command.intent,
        "node_id": command.node_id,
        "skill_id": command.skill_id,
        "agent_id": command.agent_id,
        "output_template": command.output_template,
        "supports_synthetic_today_demo": command.supports_synthetic_today_demo,
    }
    for command in (*COMMANDS, *LEGACY_COMMANDS)
}


def _schema(db_path: str) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS command_menus (
                  menu_id TEXT PRIMARY KEY,
                  chat_id TEXT NOT NULL,
                  starter_open_id TEXT NOT NULL,
                  starter_role TEXT NOT NULL,
                  hotel_id TEXT NOT NULL,
                  status TEXT NOT NULL,
                  selected_command_id TEXT,
                  expires_at TEXT NOT NULL,
                  payload_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_command_menus_chat_status
                  ON command_menus(chat_id, status, expires_at);
                CREATE INDEX IF NOT EXISTS idx_command_menus_owner_status
                  ON command_menus(chat_id, starter_open_id, status, expires_at);
                """
            )


def _expires_at() -> str:
    return (dt.datetime.now() + dt.timedelta(minutes=MENU_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")


def _is_expired(expires_at: str) -> bool:
    return expires_at < now_local()


def _starter_id(args: argparse.Namespace) -> str | None:
    return getattr(args, "open_id", None) or getattr(args, "user_id", None) or getattr(args, "union_id", None)


def _auth_context(args: argparse.Namespace) -> dict[str, Any]:
    return build_auth_context(
        source=getattr(args, "source", "feishu"),
        user_id=getattr(args, "user_id", None),
        open_id=getattr(args, "open_id", None),
        union_id=getattr(args, "union_id", None),
        chat_id=getattr(args, "chat_id", None),
        chat_type=getattr(args, "chat_type", None),
        user_role=getattr(args, "user_role", None),
        config_path=getattr(args, "auth_config", None),
    )


def _command_public(command: MenuCommand) -> dict[str, Any]:
    payload = {
        "id": command.command_id,
        "title": command.title,
        "permission": command.permission_action,
        "risk_level": command.risk_level,
        "readonly": command.readonly,
        "dry_run": command.dry_run,
        "approval_required": command.approval_required,
        "usage": command.usage,
    }
    payload.update(COMMAND_V27_METADATA[command.command_id])
    return payload


def _available_commands(auth_context: dict[str, Any]) -> list[MenuCommand]:
    available: list[MenuCommand] = []
    for command in COMMANDS:
        gate = permission_gate(auth_context, command.permission_action, dry_run=command.dry_run)
        if gate["allowed"]:
            available.append(command)
    return available


def _menu_message(commands: list[MenuCommand], expires_at: str) -> str:
    lines = ["您好，可以回复以下编号执行任务："]
    lines.extend(f"{command.command_id}. {command.title}" for command in commands)
    lines.append("0. 取消当前菜单")
    lines.append(f"有效期至：{expires_at}")
    return "\n".join(lines)


def _insert_menu(args: argparse.Namespace, auth_context: dict[str, Any], commands: list[MenuCommand]) -> tuple[str, str]:
    menu_id = f"menu-{dt.datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    expires_at = _expires_at()
    now = now_local()
    starter_id = _starter_id(args) or ""
    payload = {
        "menu_contract_version": MENU_CONTRACT_VERSION,
        "available_command_ids": [command.command_id for command in commands],
    }
    with closing(connect(args.db)) as conn:
        with conn:
            conn.execute(
                """
                UPDATE command_menus
                SET status='cancelled', updated_at=?
                WHERE chat_id=? AND starter_open_id=? AND status IN ('active','awaiting_params')
                """,
                (now, args.chat_id, starter_id),
            )
            conn.execute(
                """
                INSERT INTO command_menus
                  (menu_id, chat_id, starter_open_id, starter_role, hotel_id, status, selected_command_id, expires_at, payload_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'active', NULL, ?, ?, ?, ?)
                """,
                (
                    menu_id,
                    args.chat_id,
                    starter_id,
                    auth_context.get("user_role", "guest"),
                    args.hotel_id,
                    expires_at,
                    json_dumps(payload),
                    now,
                    now,
                ),
            )
    return menu_id, expires_at


def _latest_menu_for_owner(db_path: str, chat_id: str, starter_id: str) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM command_menus
            WHERE chat_id=? AND starter_open_id=? AND status IN ('active','awaiting_params')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id, starter_id),
        ).fetchone()
    return dict(row) if row else None


def _latest_menu_in_chat(db_path: str, chat_id: str) -> dict[str, Any] | None:
    with closing(connect(db_path)) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM command_menus
            WHERE chat_id=? AND status IN ('active','awaiting_params')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (chat_id,),
        ).fetchone()
    return dict(row) if row else None


def _update_menu(db_path: str, menu_id: str, *, status: str, selected_command_id: str | None = None) -> None:
    with closing(connect(db_path)) as conn:
        with conn:
            conn.execute(
                "UPDATE command_menus SET status=?, selected_command_id=COALESCE(?, selected_command_id), updated_at=? WHERE menu_id=?",
                (status, selected_command_id, now_local(), menu_id),
            )


def _parse_reply(reply: str) -> tuple[str | None, list[str]]:
    parts = str(reply or "").strip().split()
    while parts and parts[0].startswith("@"):
        parts.pop(0)
    if not parts:
        return None, []
    return parts[0], parts[1:]


def _menu_contract_is_current(menu: dict[str, Any]) -> bool:
    try:
        payload = json.loads(str(menu.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        return False
    return payload.get("menu_contract_version") == MENU_CONTRACT_VERSION


def _route_selected_command(args: argparse.Namespace, command: MenuCommand) -> dict[str, Any]:
    # Local import avoids a module-import cycle: feishu_command_router imports
    # this menu module, while menu replies must re-enter the canonical numeric
    # route so Skill execution and rendering stay exactly on the existing path.
    from runtime.feishu_command_router import route_feishu_command

    return route_feishu_command(
        command.command_id,
        role=str(getattr(args, "user_role", None) or "guest"),
        output_profile=getattr(args, "output_profile", None),
        db_path=getattr(args, "db", None),
        render=False,
        hotel_id=getattr(args, "hotel_id", None),
        chat_id=getattr(args, "chat_id", None),
        chat_type=getattr(args, "chat_type", None),
        user_id=getattr(args, "user_id", None),
        open_id=getattr(args, "open_id", None),
        union_id=getattr(args, "union_id", None),
        auth_config=getattr(args, "auth_config", None),
        use_command_menu=False,
        reply=None,
        use_generated_today=bool(getattr(args, "use_generated_today", False)),
        demo_data_dir=getattr(args, "demo_data_dir", None),
        force_feishu_auth=bool(getattr(args, "force_feishu_auth", False)),
        as_of_time=getattr(args, "as_of_time", None),
        s14_source_config=getattr(args, "s14_source_config", None),
        member_info=getattr(args, "member_info", None),
    )


def command_menu_start(args: argparse.Namespace) -> None:
    _schema(args.db)
    auth_context = _auth_context(args)
    starter_id = _starter_id(args)
    if not starter_id:
        emit(
            {
                "status": "blocked",
                "blocked_reason": "missing_menu_owner_identity",
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    if auth_context.get("auth_status") != "authorized":
        emit(
            {
                "status": "blocked",
                "blocked_reason": auth_context.get("reason", "permission_denied"),
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    commands = _available_commands(auth_context)
    if not commands:
        emit(
            {
                "status": "blocked",
                "blocked_reason": "no_available_commands_for_role",
                "template_id": "permission-denied",
                "starter_role": auth_context.get("user_role"),
                "auth_context": auth_context,
            }
        )
        return
    menu_id, expires_at = _insert_menu(args, auth_context, commands)
    message = _menu_message(commands, expires_at)
    gate = feishu_output_gate(source=args.source, content_kind="text", message=message)
    emit(
        {
            "status": "ok" if gate.get("status") == "ok" else "blocked",
            "menu_id": menu_id,
            "expires_at": expires_at,
            "starter_role": auth_context.get("user_role"),
            "available_commands": [_command_public(command) for command in commands],
            "selected_command": None,
            "execution_status": "waiting_for_reply",
            "blocked_reason": gate.get("blocked_reason"),
            "template_id": "command-menu" if gate.get("status") == "ok" else gate.get("template_id"),
            "message": message if gate.get("status") == "ok" else None,
            "auth_context": auth_context,
        }
    )


def command_menu_reply(args: argparse.Namespace) -> None:
    _schema(args.db)
    auth_context = _auth_context(args)
    starter_id = _starter_id(args)
    if not starter_id:
        emit(
            {
                "status": "blocked",
                "blocked_reason": "missing_menu_owner_identity",
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    if auth_context.get("auth_status") != "authorized":
        emit(
            {
                "status": "blocked",
                "blocked_reason": auth_context.get("reason", "permission_denied"),
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    menu = _latest_menu_for_owner(args.db, args.chat_id, starter_id)
    if not menu:
        other_menu = _latest_menu_in_chat(args.db, args.chat_id)
        emit(
            {
                "status": "blocked",
                "menu_id": other_menu.get("menu_id") if other_menu else None,
                "starter_role": auth_context.get("user_role"),
                "selected_command": None,
                "execution_status": "blocked",
                "blocked_reason": "menu_owner_mismatch" if other_menu else "no_active_menu",
                "template_id": "command-menu-error",
                "auth_context": auth_context,
            }
        )
        return
    if _is_expired(menu["expires_at"]):
        _update_menu(args.db, menu["menu_id"], status="expired")
        emit(
            {
                "status": "blocked",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": menu["starter_role"],
                "selected_command": None,
                "execution_status": "blocked",
                "blocked_reason": "menu_expired",
                "template_id": "command-menu-error",
                "auth_context": auth_context,
            }
        )
        return
    if not _menu_contract_is_current(menu):
        _update_menu(args.db, menu["menu_id"], status="cancelled")
        emit(
            {
                "status": "blocked",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": menu["starter_role"],
                "selected_command": None,
                "execution_status": "blocked",
                "blocked_reason": "menu_contract_changed_reopen_menu",
                "template_id": "command-menu-error",
                "auth_context": auth_context,
            }
        )
        return

    command_id, _tokens = _parse_reply(args.reply)
    if command_id == "0":
        _update_menu(args.db, menu["menu_id"], status="cancelled", selected_command_id="0")
        emit(
            {
                "status": "ok",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": menu["starter_role"],
                "selected_command": {"id": "0", "title": "取消当前菜单"},
                "execution_status": "cancelled",
                "blocked_reason": None,
                "template_id": "command-menu-cancelled",
                "auth_context": auth_context,
            }
        )
        return

    command = COMMAND_BY_ID.get(command_id or "")
    if not command:
        emit(
            {
                "status": "blocked",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": menu["starter_role"],
                "selected_command": None,
                "execution_status": "blocked",
                "blocked_reason": "unknown_menu_command",
                "template_id": "command-menu-error",
                "auth_context": auth_context,
            }
        )
        return

    gate = permission_gate(auth_context, command.permission_action, dry_run=command.dry_run)
    if not gate["allowed"]:
        emit(
            {
                "status": "blocked",
                "menu_id": menu["menu_id"],
                "expires_at": menu["expires_at"],
                "starter_role": auth_context.get("user_role"),
                "selected_command": _command_public(command),
                "execution_status": "blocked",
                "blocked_reason": gate["reason"],
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return

    _update_menu(args.db, menu["menu_id"], status="executed", selected_command_id=command.command_id)
    emit(_route_selected_command(args, command))


def command_menu_cancel(args: argparse.Namespace) -> None:
    _schema(args.db)
    auth_context = _auth_context(args)
    starter_id = _starter_id(args)
    if not starter_id:
        emit(
            {
                "status": "blocked",
                "blocked_reason": "missing_menu_owner_identity",
                "template_id": "permission-denied",
                "auth_context": auth_context,
            }
        )
        return
    menu = _latest_menu_for_owner(args.db, args.chat_id, starter_id)
    if not menu:
        emit(
            {
                "status": "ok",
                "menu_id": None,
                "starter_role": auth_context.get("user_role"),
                "execution_status": "no_active_menu",
                "blocked_reason": None,
                "template_id": "command-menu-cancelled",
                "auth_context": auth_context,
            }
        )
        return
    _update_menu(args.db, menu["menu_id"], status="cancelled", selected_command_id="0")
    emit(
        {
            "status": "ok",
            "menu_id": menu["menu_id"],
            "expires_at": menu["expires_at"],
            "starter_role": auth_context.get("user_role"),
            "execution_status": "cancelled",
            "blocked_reason": None,
            "template_id": "command-menu-cancelled",
            "auth_context": auth_context,
        }
    )

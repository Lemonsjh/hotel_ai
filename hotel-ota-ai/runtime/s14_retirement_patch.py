from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable


_INSTALLED = False
VERSION = "s14-production-retirement.v2"
RETIRED_INTENT = "s14_retired"
RETIRED_REASON = "s14_retired_from_production_feishu"
EXT_MIGRATED_REASON = "s14_ext_migrated_to_independent_service"
MENU_PATH = Path(__file__).resolve().parents[1] / "MENU.md"
DIAGNOSIS_BOT_CONFIG_ENV = "HOTEL_OTA_DIAGNOSIS_BOT_CONFIG"
DEFAULT_DIAGNOSIS_BOT_CONFIG = Path("/etc/hotel-ota-ai/diagnosis-bot-map.json")

_S14_TOKEN_RE = re.compile(r"(?<![a-z0-9_-])s14(?![a-z0-9_-])", re.IGNORECASE)
_S14_SOURCE_RE = re.compile(r"(?<![a-z0-9_-])s14\s+source\s*=", re.IGNORECASE)

_MAIN_S14_PHRASES = (
    "OTA运营诊断",
    "OTA 运营诊断",
    "酒店运营诊断",
    "综合运营诊断",
    "综合诊断",
    "完整经营分析",
    "完整运营分析",
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
    "昨日复盘",
    "昨天复盘",
    "近7天诊断",
    "近 7 天诊断",
    "近30天诊断",
    "近 30 天诊断",
    "自然月诊断",
    "月度运营诊断",
    "经营日报",
    "运营日报",
    "经营报告",
    "运营报告",
)

_MENU_TERMS = {"菜单", "能力菜单", "酒店数字员工菜单", "menu"}


def _strip_mentions(message: Any) -> str:
    text = str(message or "").strip()
    text = re.sub(r"@[^\s]+", " ", text)
    return " ".join(text.split()).strip()


def _normalized(message: Any) -> str:
    text = _strip_mentions(message).lower()
    return re.sub(r"[\s，。！？、；：,.!?;:]+", "", text)


def _is_menu_request(message: Any) -> bool:
    return _normalized(message) in {_normalized(item) for item in _MENU_TERMS}


def _is_s14_ext_request(message: Any) -> bool:
    text = _strip_mentions(message)
    lowered = text.lower()
    return bool(
        "s14-ext" in lowered
        or "s14 ext" in lowered
        or _S14_SOURCE_RE.search(text)
    )


def _is_numeric_five(message: Any) -> bool:
    return _strip_mentions(message) == "5"


def _is_main_s14_request(message: Any) -> bool:
    if _is_s14_ext_request(message):
        return False
    text = _strip_mentions(message)
    lowered = text.lower()
    return bool(
        _S14_TOKEN_RE.search(text)
        or "s14 diagnosis" in lowered
        or any(phrase in text for phrase in _MAIN_S14_PHRASES)
    )


def _menu_text() -> str:
    try:
        return MENU_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return (
            "🏨 酒店数字员工｜能力菜单\n\n"
            "1｜经营快照\n2｜销售基准线\n3｜进度诊断\n4｜环境行情\n"
            "6｜竞对监控\n7｜口碑评价\n8｜评论回复\n9｜收益建议\n"
            "10｜调价 dry-run\n11｜推广数据\n12｜推广 ROI\n"
            "13｜流量转化专项\n14｜客户订单分析\n15｜运行状态\n\n"
            "编号 5 已停用且不再复用。"
        )


def _diagnosis_bot_config_path() -> Path:
    configured = str(os.environ.get(DIAGNOSIS_BOT_CONFIG_ENV) or "").strip()
    return Path(configured) if configured else DEFAULT_DIAGNOSIS_BOT_CONFIG


def _configured_diagnosis_bot(router: Any, kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve an explicitly configured diagnosis bot for the trusted group only.

    The runtime never guesses bot membership from names or message text.  A bot
    is considered available only when the private group mapping contains the
    exact normalized chat id with active status and a non-empty display name.
    """
    chat_id = router.normalize_feishu_chat_id(kwargs.get("chat_id"))
    if not chat_id:
        return None
    try:
        with _diagnosis_bot_config_path().open("r", encoding="utf-8") as handle:
            config = json.load(handle)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return None

    rows = config.get("group_chat_bots") if isinstance(config, dict) else None
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        mapped_chat_id = router.normalize_feishu_chat_id(row.get("chat_id"))
        bot_name = str(row.get("bot_name") or "").strip()
        status = str(row.get("status") or "active").strip().lower()
        if mapped_chat_id == chat_id and bot_name and status == "active":
            return {"chat_id": chat_id, "bot_name": bot_name}
    return None


def _direct_result(
    router: Any,
    *,
    intent: str,
    role: str,
    output_profile: str | None,
    status: str,
    summary: str,
    blocked_reason: str | None,
    data_source_type: str,
) -> dict[str, Any]:
    result = router._base_result(intent, role=role, output_profile=output_profile)
    result.update(
        {
            "status": status,
            "intent": intent,
            "summary": summary,
            "user_message": summary,
            "blocked_reason": blocked_reason,
            "business_result_generated": False,
            "data_source_type": data_source_type,
            "freshness_status": "not_applicable",
            "runtime_command": None,
            "skill_id": None,
            "node_id": None,
            "agent_id": None,
            "scenario_id": None,
            "approval_data_allowed": False,
            "formal_approval_created": False,
            "formal_approval_allowed": False,
            "live_allowed": False,
            "live_execution_count": 0,
            "fallback_used": False,
            "route_contract_version": VERSION,
        }
    )
    return result


def _finish(router: Any, result: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    role = str(kwargs.get("role") or result.get("auth_role") or "guest")
    if kwargs.get("render", True):
        text = str(result.get("summary") or "")
        profile = result.get("output_profile") or router.default_output_profile(role, kwargs.get("output_profile"))
        result["rendered"] = {
            "status": "ok" if result.get("status") == "ok" else result.get("status"),
            "output_profile": profile,
            "text": text,
            "visible_fields": ["summary"],
            "hidden_fields": [],
            "message_send_attempted": False,
            "template": "capability_menu" if result.get("intent") == "menu" else "capability_retired",
        }
        result["send_payload"] = {
            "text": text,
            "card": None,
            "send_allowed": True,
            "output_profile": profile,
            "warnings": [],
            "data_source_type": result.get("data_source_type"),
            "freshness_status": result.get("freshness_status"),
        }
    if kwargs.get("compact") and hasattr(router, "compact_feishu_route_result"):
        return router.compact_feishu_route_result(result)
    return result


def _menu_result(router: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    role = str(kwargs.get("role") or "guest")
    result = _direct_result(
        router,
        intent="menu",
        role=role,
        output_profile=kwargs.get("output_profile"),
        status="ok",
        summary=_menu_text(),
        blocked_reason=None,
        data_source_type="static_capability_menu",
    )
    return _finish(router, result, kwargs)


def _retired_result(router: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    role = str(kwargs.get("role") or "guest")
    handoff = _configured_diagnosis_bot(router, kwargs)
    if handoff:
        bot_name = str(handoff["bot_name"])
        summary = (
            "S14 主运营诊断已从本酒店数字员工停用。"
            f"当前群已配置独立综合诊断机器人「{bot_name}」，请在群内 @{bot_name} 并发送「综合诊断」。"
        )
    else:
        summary = (
            "S14 主运营诊断已从本酒店数字员工停用。"
            "当前群未配置独立综合诊断机器人，因此暂时无法转接综合诊断；请联系管理员配置该机器人。"
        )
    result = _direct_result(
        router,
        intent=RETIRED_INTENT,
        role=role,
        output_profile=kwargs.get("output_profile"),
        status="blocked",
        summary=summary,
        blocked_reason=RETIRED_REASON,
        data_source_type="not_applicable",
    )
    result["diagnosis_bot_configured"] = bool(handoff)
    if handoff:
        result["diagnosis_bot_name"] = handoff["bot_name"]
    return _finish(router, result, kwargs)


def _ext_result(router: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    role = str(kwargs.get("role") or "guest")
    result = _direct_result(
        router,
        intent="s14_source_request",
        role=role,
        output_profile=kwargs.get("output_profile"),
        status="data_gap",
        summary=(
            "第三方 OTA HTML 诊断报告已迁移到独立 S14-EXT 服务；"
            "本酒店数字员工不再执行该报告能力。"
        ),
        blocked_reason=EXT_MIGRATED_REASON,
        data_source_type="external_service",
    )
    return _finish(router, result, kwargs)


def _patch_menu_surfaces(router: Any) -> None:
    # Remove slot 5 from every runtime-owned menu source.  Do not renumber the
    # remaining stable IDs; old conversations therefore cannot accidentally
    # reinterpret 5 as another write-capable command.
    router.NUMERIC_MENU_INTENTS.pop("5", None)

    from runtime.decisions import command_menu

    command_menu.COMMANDS = tuple(
        command for command in command_menu.COMMANDS if command.command_id != "5"
    )
    command_menu.COMMAND_BY_ID = {
        command.command_id: command for command in command_menu.COMMANDS
    }
    command_menu.COMMAND_V27_METADATA.pop("5", None)


def _patch_detector(router: Any) -> None:
    previous = router._detect_intent
    if getattr(previous, "_S14_PRODUCTION_RETIRED_V1", False):
        return

    def detect_intent(message: str) -> str:
        if _is_s14_ext_request(message):
            return "s14_source_request"
        if _is_numeric_five(message) or _is_main_s14_request(message):
            return RETIRED_INTENT
        if _is_menu_request(message):
            return "menu"
        return previous(message)

    detect_intent._S14_PRODUCTION_RETIRED_V1 = True  # type: ignore[attr-defined]
    router._detect_intent = detect_intent


def _patch_routes(router: Any) -> None:
    previous_route: Callable[..., dict[str, Any]] = router.route_feishu_command
    previous_safe: Callable[..., dict[str, Any]] = router.safe_route_feishu_command

    if not getattr(previous_route, "_S14_PRODUCTION_RETIRED_V1", False):
        def route_feishu_command(message: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            if _is_menu_request(message):
                return _menu_result(router, dict(kwargs))
            if _is_s14_ext_request(message):
                return _ext_result(router, dict(kwargs))
            if _is_numeric_five(message) or _is_main_s14_request(message):
                return _retired_result(router, dict(kwargs))
            return previous_route(message, *args, **kwargs)

        route_feishu_command._S14_PRODUCTION_RETIRED_V1 = True  # type: ignore[attr-defined]
        router.route_feishu_command = route_feishu_command

    if not getattr(previous_safe, "_S14_PRODUCTION_RETIRED_V1", False):
        def safe_route_feishu_command(message: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            if _is_menu_request(message):
                return _menu_result(router, dict(kwargs))
            if _is_s14_ext_request(message):
                return _ext_result(router, dict(kwargs))
            if _is_numeric_five(message) or _is_main_s14_request(message):
                return _retired_result(router, dict(kwargs))
            return previous_safe(message, *args, **kwargs)

        safe_route_feishu_command._S14_PRODUCTION_RETIRED_V1 = True  # type: ignore[attr-defined]
        router.safe_route_feishu_command = safe_route_feishu_command


def _patch_orchestrator(router: Any) -> None:
    from runtime import skill_orchestrator

    previous = skill_orchestrator.run_skill_with_dependencies
    if getattr(previous, "_S14_PRODUCTION_RETIRED_V1", False):
        router.run_skill_with_dependencies = previous
        return

    def run_skill_with_dependencies(*args: Any, **kwargs: Any) -> dict[str, Any]:
        target_skill = str(kwargs.get("target_skill") or "")
        if target_skill == "S14_OPERATION_DIAGNOSIS":
            return {
                "target_skill": target_skill,
                "hotel_id": str(kwargs.get("hotel_id") or ""),
                "dependency_runs": [],
                "final_result": None,
                "blocked": True,
                "blocked_reason": RETIRED_REASON,
                "retirement_contract_version": VERSION,
            }
        return previous(*args, **kwargs)

    run_skill_with_dependencies._S14_PRODUCTION_RETIRED_V1 = True  # type: ignore[attr-defined]
    skill_orchestrator.run_skill_with_dependencies = run_skill_with_dependencies
    # feishu_command_router imported the function directly, so replace that
    # pre-bound reference as well.
    router.run_skill_with_dependencies = run_skill_with_dependencies


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router

    _patch_menu_surfaces(router)
    _patch_detector(router)
    _patch_routes(router)
    _patch_orchestrator(router)
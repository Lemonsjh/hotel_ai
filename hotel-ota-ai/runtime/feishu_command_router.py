from __future__ import annotations

import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
from typing import Any
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from runtime.agent_mapping_loader import agent_id_for_node
from runtime.common import DEFAULT_LOG_DIR, hotel_log_dir, json_dumps, now_local
from runtime.decisions.command_menu import command_menu_reply, command_menu_start
from runtime.decisions.calendar import market_context
from runtime.decisions.baseline import baseline
from runtime.decisions.competition import competition_alert
from runtime.decisions.deviation import deviation
from runtime.decisions.pricing import execute_price
from runtime.decisions.promotion import promotion_execute
from runtime.decisions.realtime_occupancy import build_realtime_occupancy
from runtime.algorithms.run_context import build_run_context
from runtime.algorithms.s2_operating_views import build_s2_operating_views, load_s2_optional_results
from runtime.algorithms.s5_real_candidates import build_s5_real_candidates
from runtime.algorithms.s10_promotion_roi import build_s10_promotion_roi
from runtime.s10_promotion_source import query_s10_promotion_performance
from runtime.demo_facts import business_snapshot, demo_run_id, demo_safety_flags, execution_preview, load_demo_manifest
from runtime.demo_mode import build_all_demo_chains_result, build_all_demo_nodes_result, build_demo_node_result
from runtime.demo_today_generator import generate_today_demo_result
from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.adapters.normalized_query import is_price_task_mapping_ready
from runtime.feishu_output_renderer import build_feishu_send_payload, default_output_profile, render_feishu_output
from runtime.historical_room_type_performance import build_historical_room_type_performance
from runtime.priceable_products import list_priceable_products
from runtime.safety.auth import (
    build_auth_context,
    load_auth_config,
    normalize_feishu_chat_id,
    permission_gate,
    resolve_feishu_business_chat_id,
    tenant_scope_gate,
)
from runtime.skill_orchestrator import run_skill_with_dependencies
from runtime.control_plane import (
    build_tenant_management_read_model,
    cancel_chat_binding_request,
    cancel_chat_role_change_request,
    cancel_chat_configuration_request,
    confirm_chat_binding_request,
    confirm_chat_role_change_request,
    confirm_chat_configuration_request,
    create_chat_binding_request,
    create_chat_join_request,
    create_chat_role_change_request,
    create_chat_configuration_request,
    resolve_price_guard_policy,
)
from runtime.storage import connect, init_schema
from runtime.s6_confirmation import claim_confirmation, create_confirmation, finish_confirmation, record_rejected_preview
from runtime.s6_price_bounds_bypass_patch import S6_SINGLE_CHANGE_HARD_CAP
from runtime.safety.approvals import validate_approval_payload
from runtime.safety.payload_hash import price_execution_payload, price_execution_payload_hash
from runtime.time_context import resolve_request_as_of_time


_S6_NET_PREVIEW_CACHE_TTL_SECONDS = 30.0
_S6_NET_PREVIEW_ACTIVITY_CACHE: dict[
    tuple[str, str, str], tuple[float, dict[str, Any], dict[str, Any]]
] = {}


def _base_result(intent: str, *, role: str, output_profile: str | None = None) -> dict[str, Any]:
    return {
        "run_id": demo_run_id(intent),
        "intent": intent,
        "generated_by_runtime": True,
        "source": "feishu",
        "data_source_type": "unavailable",
        "freshness_status": "missing_real_data",
        "business_status": "not_loaded",
        "today_label_allowed": False,
        "approval_data_allowed": False,
        "formal_approval_allowed": False,
        "live_allowed": False,
        "formal_approval_created": False,
        "live_execution_count": 0,
        "auth_role": role,
        "output_profile": default_output_profile(role, output_profile),
        "blocked_reason": "business_data_not_loaded",
    }


S14_EXT_MIGRATED_SUMMARY = "第三方营销诊断已迁移到独立服务，本项目不再处理该入口。"


def _s14_ext_migrated_result(intent: str, *, role: str, output_profile: str | None = None) -> dict[str, Any]:
    result = _base_result(intent, role=role, output_profile=output_profile)
    result.update(
        {
            "status": "data_gap",
            "intent": intent,
            "summary": S14_EXT_MIGRATED_SUMMARY,
            "blocked_reason": "s14_ext_migrated_to_independent_service",
            "business_result_generated": False,
            "runtime_command": None,
            "live_allowed": False,
            "approval_data_allowed": False,
            "external_isolated": False,
            "suggested_actions": ["请在独立 S14-EXT 营销诊断服务中处理 Excel 上传、临时库或第三方报告生成。"],
        }
    )
    return result


def _contains_any(message: str, needles: list[str]) -> bool:
    return any(needle and needle in message for needle in needles)


_HISTORICAL_ROOM_TYPE_PERIOD_RE = re.compile(r"(?:最近|近|过去)\s*(\d{1,3})\s*(?:天|日)")
_HISTORICAL_ROOM_TYPE_TERMS = ("房型", "房间类型")
_HISTORICAL_ROOM_TYPE_METRIC_TERMS = ("出租率", "入住率", "occ", "adr", "成交价", "成交价格", "实际成交价")


def _historical_room_type_performance_days(message: str) -> int | None:
    """Recognize an explicit historical room-type OCC / realized-price request."""
    raw = str(message or "")
    lowered = raw.lower()
    matched = _HISTORICAL_ROOM_TYPE_PERIOD_RE.search(raw)
    if not matched or not any(term in raw for term in _HISTORICAL_ROOM_TYPE_TERMS):
        return None
    if not any(term in raw or term in lowered for term in _HISTORICAL_ROOM_TYPE_METRIC_TERMS):
        return None
    days = int(matched.group(1))
    return days if 1 <= days <= 90 else None


EXPLICIT_DEMO_TERMS = ("demo", "演示", "完整演示", "演示链路", "跑一遍演示", "节点演示")
DEMO_HOTEL_ID_PATTERN = re.compile(r"(?<![a-z0-9_-])[a-z0-9][a-z0-9_-]*-demo(?![a-z0-9_-])", re.IGNORECASE)
EXPLICIT_CURRENT_HOTEL_TERMS = ("本酒店", "本店", "当前酒店", "当前门店", "本门店")
GENERIC_HOTEL_MENTION_PATTERN = re.compile(
    r"(?:[\u4e00-\u9fff]{2,}(?:酒店|宾馆|民宿|门店))|(?:[a-z0-9][a-z0-9_-]*\s*(?:酒店|hotel))",
    re.IGNORECASE,
)


def _explicit_demo_requested(message: str) -> bool:
    text = str(message or "").lower()
    return any(term.lower() in text for term in EXPLICIT_DEMO_TERMS)


def _requested_demo_hotel_id(message: str) -> bool:
    return bool(DEMO_HOTEL_ID_PATTERN.search(str(message or "")))


def _demo_manifest_hotel_id() -> str:
    try:
        return str(load_demo_manifest().get("hotel_id") or "demo-hotel")
    except Exception:
        return "demo-hotel"


def _requested_other_hotel_name(message: str, resolved_hotel_id: str | None) -> bool:
    if not resolved_hotel_id:
        return False
    raw_text = str(message or "")
    text = raw_text.lower()
    resolved = str(resolved_hotel_id).strip().lower()
    if _requested_demo_hotel_id(raw_text):
        return True
    if resolved and re.search(rf"(?<![a-z0-9_-]){re.escape(resolved)}(?![a-z0-9_-])", text):
        return False
    if any(term in raw_text for term in EXPLICIT_CURRENT_HOTEL_TERMS):
        return False
    return bool(GENERIC_HOTEL_MENTION_PATTERN.search(raw_text))


PROTECTED_BUSINESS_INTENTS = {
    "historical_room_type_performance",
    "run_s02",
    "run_s02_demo",
    "sales_baseline_demo",
    "progress_deviation_demo",
    "market_context_demo",
    "business_calendar",
    "operation_diagnosis",
    "ota_diagnosis_demo",
    "competitor_demo",
    "competition_alert",
    "reputation_demo",
    "demo_node_all",
    "demo_chain_all",
    "full_chain_demo",
    "owner_today_demo",
    "operator_full_demo",
    "frontdesk_today_tasks",
    "revenue_decision",
    "revenue_decision_demo",
    "roi_decision",
    "roi_demo",
    "traffic_peak_demo",
    "customer_analysis_demo",
    "review_reply_draft",
    "review_publish_request",
    "experience_candidates",
    "developer_detail",
    "seed_demo",
    "member_role_status",
    "price_guard_status",
    "priceable_product_list",
    "price_execution_confirm",
    "pending_configuration_requests",
    "configuration_audit_summary",
    "identity",
    "auth_path_explanation",
    "chat_configuration_request",
    "chat_configuration_confirm",
    "chat_configuration_cancel",
    "chat_binding_request",
    "chat_binding_confirm",
    "chat_binding_cancel",
    "chat_binding_status",
    "chat_role_join_request",
    "chat_role_change_request",
    "chat_role_change_confirm",
    "chat_role_change_cancel",
    "chat_role_named_request",
}

ISOLATED_EXTERNAL_REPORT_INTENTS = {
    "third_party_report_preview",
    "s14_source_request",
}

TENANT_AUTH_REQUIRED_ISOLATED_INTENTS = {
    "third_party_report_preview",
    "s14_source_request",
}


NUMERIC_MENU_INTENTS = {
    "1": "run_s02_demo",
    "2": "sales_baseline_demo",
    "3": "progress_deviation_demo",
    "4": "market_context_demo",
    "5": "ota_diagnosis_demo",
    "6": "competition_alert",
    "7": "reputation_demo",
    "8": "review_reply_draft",
    "9": "revenue_decision_demo",
    "10": "price_execution_dry_run",
    "11": "promotion_suggestion",
    "12": "roi_demo",
    "13": "traffic_peak_demo",
    "14": "customer_analysis_demo",
    "15": "runtime_status",
    "16": "seed_demo",
    "17": "model_config_request",
}


NODE_DEMO_INTENTS = {
    "sales_baseline_demo": "N010",
    "progress_deviation_demo": "N011",
    "market_context_demo": "N006",
    "ota_diagnosis_demo": "N009",
    "competitor_demo": "N007",
    "competition_alert": "N007",
    "reputation_demo": "N008",
    "revenue_decision_demo": "N015",
    "roi_demo": "N013",
    "traffic_peak_demo": "N020",
    "customer_analysis_demo": "N014",
}


NODE_DEMO_RUNTIME_COMMANDS = {
    intent: f"--demo demo-node --node {node_id}"
    for intent, node_id in NODE_DEMO_INTENTS.items()
}

DEMO_FALLBACK_INTENTS = {
    "run_s02_demo",
    "sales_baseline_demo",
    "progress_deviation_demo",
    "competitor_demo",
    "reputation_demo",
    "revenue_decision_demo",
    "roi_demo",
    "traffic_peak_demo",
    "customer_analysis_demo",
    "review_reply_draft",
    "owner_today_demo",
    "operator_full_demo",
    "frontdesk_today_tasks",
}

PROGRESS_DIAGNOSIS_PHRASES = [
    "进度诊断",
    "进度偏差",
    "今日进度",
    "当前进度",
    "进度情况",
    "完成率",
    "今日完成率",
    "现在完成多少",
    "完成了多少",
    "目标完成了吗",
    "离目标差多少",
    "还差多少",
    "还差几间",
    "还差几间夜",
    "缺口多少",
    "当前缺口",
    "进度落后吗",
    "今天落后了吗",
    "进度风险",
    "冲刺进度",
    "下午进度",
    "晚高峰前进度",
    "16点进度",
    "18点进度",
    "今天卖房进度",
    "今天间夜进度",
]

# “大盘热度” is the S16 demand-pace index, not S4's weather/event market
# context.  Keep this before the broad S4 market-intent matching.
MARKET_HEAT_PHRASES = (
    "大盘热度",
    "大盘冷不冷",
    "大盘是冷是热",
)

HOURLY_SALES_PHRASES = [
    "分时实际销售",
    "分时销售",
    "分时已售",
    "小时销售",
    "小时已售",
    "每小时卖了多少",
    "按小时看进度",
    "小时进度",
    "分时进度",
    "分时销售曲线",
    "实际销售曲线",
    "订单分时",
    "间夜分时",
    "今天各小时销售",
    "今天每小时订单",
    "实际小时累计",
    "小时累计间夜",
]

BUSINESS_SNAPSHOT_PHRASES = [
    "\u5b9e\u65f6\u51fa\u79df\u7387",
    "\u5f53\u524d\u51fa\u79df\u7387",
    "\u51fa\u79df\u7387",
    "\u5165\u4f4f\u7387",
    "\u7ecf\u8425\u5feb\u7167",
    "\u4eca\u65e5\u7ecf\u8425",
    "当前已售",
    "已售多少",
    "今日已售",
    "现在已售",
    "现在卖了多少",
    "今天卖了多少间",
    "今天卖了多少间夜",
    "出租率",
    "入住率",
    "当前出租率",
    "可售多少",
    "剩余多少房",
    "房态",
    "经营快照",
    "今日经营",
    "今天经营状况",
    "平均房价",
    "每间可售收入",
]

BASELINE_PHRASES = [
    "销售目标",
    "今日目标",
    "目标间夜",
    "目标出租率",
    "基准线",
    "销售基准线",
    "小时目标",
    "目标曲线",
    "今日目标曲线",
    "每小时目标",
    "16点目标",
    "18点目标",
    "晚高峰目标",
]

STATUS_SOURCE_PHRASES = [
    "当前模式",
    "当前什么模式",
    "现在什么模式",
    "数据日期",
    "现在用什么数据",
    "当前数据源",
    "是不是演示模式",
    "用的是今天数据吗",
    "synthetic数据有吗",
    "sqlite数据生效了吗",
    "为什么还是旧数据",
    "db_source_enable影响吗",
    "当前环境",
    "live开了吗",
]

BUSINESS_CALENDAR_PHRASES = [
    "\u4e1a\u52a1\u65e5\u5386",
    "\u8282\u5047\u65e5\u65e5\u5386",
    "\u6d3b\u52a8\u65e5\u5386",
    "\u5468\u8fb9\u6d3b\u52a8",
    "\u5546\u5708\u70ed\u5ea6",
    "\u5929\u6c14\u5f71\u54cd",
    "\u8282\u5047\u65e5",
    "\u6d3b\u52a8\u65e5",
    "\u5468\u8fb9\u6f14\u51fa",
    "\u9644\u8fd1\u6d3b\u52a8",
]

MANAGEMENT_READ_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("member_role_status", ("\u6210\u5458\u89d2\u8272\u72b6\u6001", "\u4eba\u5458\u89d2\u8272\u72b6\u6001", "\u89d2\u8272\u72b6\u6001", "\u6210\u5458\u6743\u9650\u72b6\u6001")),
    ("price_guard_status", ("\u623f\u578b\u4ef7\u683c\u62a4\u680f\u72b6\u6001", "\u4ef7\u683c\u62a4\u680f\u72b6\u6001", "\u4ef7\u683c\u8fb9\u754c\u72b6\u6001", "\u623f\u578b\u4ef7\u683c\u8fb9\u754c\u72b6\u6001", "\u5f53\u524d\u8c03\u4ef7\u7684\u6da8\u8dcc\u5e45\u6700\u5927\u6700\u5c0f\u503c", "\u5f53\u524d\u6da8\u8dcc\u5e45", "\u6700\u5927\u6da8\u5e45", "\u6700\u5c0f\u6da8\u5e45", "\u623f\u578b\u62a4\u680f")),
    ("pending_configuration_requests", ("\u5f85\u5904\u7406\u914d\u7f6e\u7533\u8bf7", "\u5f85\u5904\u7406\u914d\u7f6e", "\u914d\u7f6e\u7533\u8bf7\u72b6\u6001")),
    ("configuration_audit_summary", ("\u914d\u7f6e\u5ba1\u8ba1\u6458\u8981", "\u914d\u7f6e\u53d8\u66f4\u5ba1\u8ba1", "\u5ba1\u8ba1\u6458\u8981")),
)

PRICEABLE_PRODUCT_PHRASES = (
    "可调价商品",
    "可调价的商品",
    "可调价格商品",
    "可以进行调价的商品",
    "哪些商品可以调价",
    "哪些商品能调价",
    "商品可以调价",
    "可调价产品",
    "可调价的产品",
    "当前可调价商品",
    "查询可调价商品",
    "查看OTA商品价格",
    "OTA商品价格",
    "商品当前价格",
)

OTA_PRODUCT_PLATFORM_TERMS = {
    "meituan": ("美团", "meituan"),
    "ctrip": ("携程", "ctrip"),
}

MEMBER_ROLE_STATUS_PHRASES = (
    "查询当前所有人身份",
    "查询群里所有人身份",
    "查询所有人权限",
    "验一下群里所有人的权限",
    "当前群成员权限",
    "当前群角色",
    "当前酒店成员",
)

AUTH_PATH_PHRASES = (
    "你从哪查",
    "验权路径",
    "鉴权路径",
    "不应该从 sqlite 查吗",
    "你怎么验权",
    "权限从哪来",
)

MARKET_CONTEXT_PHRASES = (
    "s4",
    "S4",
    "s04",
    "S04",
    "行情",
    "市场行情",
    "环境行情",
    "环境行情感知",
    "行情感知",
)

IDENTITY_PHRASES = (
    "我是谁",
    "我的身份",
    "我能做什么",
    "我的权限",
    "身份",
    "你是谁",
)


def _self_claim_detected(message: str) -> bool:
    raw = message or ""
    text = raw.lower()
    return _contains_any(
        raw,
        [
            "\u6211\u662f\u7ba1\u7406\u5458",
            "\u6211\u662f\u8001\u677f",
            "\u6211\u662f\u8fd0\u8425",
            "\u6211\u662f\u524d\u53f0",
            "\u91cd\u65b0\u8bfb\u53d6\u6743\u9650",
            "\u91cd\u65b0\u5224\u65ad\u6743\u9650",
        ],
    ) or any(term in text for term in ["i am admin", "i'm admin", "as admin"])


def _config_change_request_detected(message: str) -> bool:
    raw = message or ""
    text = raw.lower()
    target_terms = [
        "hotel_ota_db_source_enable",
        "db_source_enable",
        "max_single_change_pct",
        "sqlite",
        "fixture",
        "\u6da8\u4ef7\u6700\u9ad8\u5e45\u5ea6",
        "\u6700\u5927\u6da8\u5e45",
        "\u6700\u9ad8\u5e45\u5ea6",
        "\u4ef7\u683c\u8fb9\u754c",
        "\u4ef7\u683c\u62a4\u680f",
        "\u623f\u578b\u4ef7\u683c",
        "\u5ba1\u6279\u89c4\u5219",
        "\u73af\u5883\u53d8\u91cf",
        "\u6570\u636e\u6e90\u5f00\u5173",
    ]
    change_verbs = [
        "\u5e2e\u6211\u628a",
        "\u8bbe\u7f6e",
        "\u8bbe\u4e3a",
        "\u8c03\u6574",
        "\u4fee\u6539",
        "\u66f4\u6539",
        "\u5f00\u542f",
        "\u5173\u95ed",
        "\u5207\u6362",
        "\u5199\u5165",
        "\u66f4\u65b0",
        "set ",
        "change ",
        "enable ",
        "disable ",
    ]
    return any(term in text or term in raw for term in target_terms) and any(verb in text or verb in raw for verb in change_verbs)


_CHAT_CONFIRMATION_RE = re.compile(r"^\s*确认\s+(CFG-[A-Z0-9]+)\s*$", re.IGNORECASE)
_CHAT_CANCELLATION_RE = re.compile(r"^\s*取消\s+(CFG-[A-Z0-9]+)\s*$", re.IGNORECASE)
_CHAT_ROLE_CONFIRMATION_RE = re.compile(r"^\s*确认\s+(ROLE-[A-Z0-9]+)\s*$", re.IGNORECASE)
_CHAT_ROLE_CANCELLATION_RE = re.compile(r"^\s*取消\s+(ROLE-[A-Z0-9]+)\s*$", re.IGNORECASE)
_CHAT_BIND_CONFIRMATION_RE = re.compile(r"^\s*确认\s+(BIND-[A-Z0-9]+)\s*$", re.IGNORECASE)
_CHAT_BIND_CANCELLATION_RE = re.compile(r"^\s*取消\s+(BIND-[A-Z0-9]+)\s*$", re.IGNORECASE)
_CHAT_BIND_REQUEST_RE = re.compile(
    r"^\s*(?:绑定当前会话到酒店|绑定当前私聊到酒店|将当前私聊绑定到酒店|绑定当前群到酒店|将当前群绑定到酒店)\s+([A-Za-z0-9_-]+)\s*$",
    re.IGNORECASE,
)
_ROLE_WORDS_RE = r"owner|业主|老板|运营|前台|operator|frontdesk"
_CHAT_JOIN_RE = re.compile(rf"^\s*申请加入酒店(?:\s*({_ROLE_WORDS_RE}))?\s*$", re.IGNORECASE)
_CHAT_ROLE_CHANGE_RE = re.compile(rf"^\s*(授予|撤销)\s+([A-Za-z0-9_-]+)\s*(?:为)?\s*({_ROLE_WORDS_RE})\s*$", re.IGNORECASE)


def _normalize_requested_role_text(value: str | None) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"owner", "业主", "老板"}:
        return "owner"
    if text in {"frontdesk", "前台", "鍓嶅彴"}:
        return "frontdesk"
    if text in {"operator", "运营", "杩愯惀"}:
        return "operator"
    return None


def _chat_request_id(message: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.match(message or "")
    return match.group(1).upper() if match else None


def _chat_binding_payload(message: str) -> dict[str, str] | None:
    raw = message or ""
    match = _CHAT_BIND_REQUEST_RE.match(raw)
    if match:
        return {"operation": "bind", "hotel_id": match.group(1)}
    if re.match(r"^\s*解绑当前会话\s*$", raw):
        return {"operation": "unbind", "hotel_id": ""}
    return None


def _s14_source_key(message: str) -> str | None:
    match = re.search(r"\bsource\s*=\s*([A-Za-z0-9_-]+)\b", message or "", re.IGNORECASE)
    return match.group(1) if match else None


def _chat_price_guard_payload(message: str) -> dict[str, Any] | None:
    raw = message or ""
    room = re.search(r"(?:房型|room[_ ]?type)\s*[:：]?\s*([A-Za-z0-9_-]+)", raw, re.IGNORECASE)
    floor = re.search(r"底价\s*[:：]?\s*[￥¥]?\s*(\d+(?:\.\d+)?)", raw)
    ceiling = re.search(r"(?:顶价|封顶价)\s*[:：]?\s*[￥¥]?\s*(\d+(?:\.\d+)?)", raw)
    minimum = re.search(r"最小(?:单次)?(?:涨跌幅|涨幅|跌幅)\s*(?:为|是|=|：|:)?\s*(\d+(?:\.\d+)?)\s*%", raw)
    maximum = re.search(r"最大(?:单次)?(?:涨跌幅|涨幅|跌幅)\s*(?:为|是|=|：|:)?\s*(\d+(?:\.\d+)?)\s*%", raw)
    if not all((room, floor, ceiling, minimum, maximum)):
        return None
    return {
        "room_type_id": room.group(1).upper(),
        "floor_price": float(floor.group(1)),
        "ceiling_price": float(ceiling.group(1)),
        "min_increase_pct": float(minimum.group(1)) / 100,
        "min_decrease_pct": float(minimum.group(1)) / 100,
        "max_increase_pct": float(maximum.group(1)) / 100,
        "max_decrease_pct": float(maximum.group(1)) / 100,
    }


def _chat_join_requested_role(message: str) -> str | None:
    text = (message or "").strip().lower()
    if not (text.startswith("申请加入") or text.startswith("申请成为")):
        return None
    for word in ("owner", "业主", "老板", "frontdesk", "前台", "operator", "运营"):
        if word in text:
            return _normalize_requested_role_text(word)
    return "operator"


def _chat_role_confirmation_payload(message: str) -> dict[str, str | None] | None:
    match = re.match(
        rf"^\s*\u786e\u8ba4\s+(ROLE-[A-Z0-9]+)(?:\s*\u4e3a\s*({_ROLE_WORDS_RE}))?\s*$",
        message or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    requested = (match.group(2) or "").lower()
    return {
        "request_id": match.group(1).upper(),
        "requested_role": _normalize_requested_role_text(requested) if requested else None,
    }


def _chat_role_change_payload(message: str) -> dict[str, str] | None:
    match = _CHAT_ROLE_CHANGE_RE.match(message or "")
    if not match:
        return None
    operation = "grant" if match.group(1) == "授予" else "revoke"
    role = _normalize_requested_role_text(match.group(3)) or "operator"
    return {"operation": operation, "principal_id": match.group(2), "role": role}


def _chat_role_named_request(message: str) -> bool:
    text = (message or "").strip()
    return bool(re.match(r"^\s*(?:\u628a|\u5c06).+(?:\u8bbe\u4e3a|\u8bbe\u7f6e\u4e3a).+(?:\u8fd0\u8425|\u524d\u53f0)\s*$", text))


# Compatibility layer for real UTF-8 Feishu messages.  Earlier test fixtures
# include mojibake strings from historical Windows console output; keep them,
# but make production Chinese input the primary path.
_CHAT_CONFIRMATION_RE = re.compile(r"^\s*(?:确认|纭)\s+(CFG-[A-Z0-9]+)\s*$", re.IGNORECASE)
_CHAT_CANCELLATION_RE = re.compile(r"^\s*(?:取消|鍙栨秷)\s+(CFG-[A-Z0-9]+)\s*$", re.IGNORECASE)
_CHAT_ROLE_CANCELLATION_RE = re.compile(r"^\s*(?:取消|鍙栨秷)\s+(ROLE-[A-Z0-9]+)\s*$", re.IGNORECASE)


def _chat_price_guard_payload(message: str) -> dict[str, Any] | None:
    raw = message or ""
    room = re.search(r"(?:房型|鎴垮瀷|room[_ ]?type)\s*[:：]?\s*([A-Za-z0-9_-]+)", raw, re.IGNORECASE)
    floor = re.search(r"(?:底价|搴曚环)\s*[:：]?\s*[¥￥]?\s*(\d+(?:\.\d+)?)", raw)
    ceiling = re.search(r"(?:顶价|封顶价|椤朵环|灏侀《浠?)\s*[:：]?\s*[¥￥]?\s*(\d+(?:\.\d+)?)", raw)
    minimum = re.search(r"(?:最小|最低|鏈€灏?)(?:单次)?(?:涨跌幅|涨幅|跌幅|娑ㄨ穼骞?|娑ㄥ箙|璺屽箙)\s*(?:为|是|=|：|:)?\s*(\d+(?:\.\d+)?)\s*%", raw)
    maximum = re.search(r"(?:最大|最高|鏈€澶?)(?:单次)?(?:涨跌幅|涨幅|跌幅|娑ㄨ穼骞?|娑ㄥ箙|璺屽箙)\s*(?:为|是|=|：|:)?\s*(\d+(?:\.\d+)?)\s*%", raw)
    if not all((room, floor, ceiling, minimum, maximum)):
        return None
    return {
        "room_type_id": room.group(1).upper(),
        "floor_price": float(floor.group(1)),
        "ceiling_price": float(ceiling.group(1)),
        "min_increase_pct": float(minimum.group(1)) / 100,
        "min_decrease_pct": float(minimum.group(1)) / 100,
        "max_increase_pct": float(maximum.group(1)) / 100,
        "max_decrease_pct": float(maximum.group(1)) / 100,
    }


def _chat_join_requested_role(message: str) -> str | None:
    text = (message or "").strip().lower()
    if not (text.startswith("申请加入") or text.startswith("申请成为") or text.startswith("鐢宠鍔犲叆") or text.startswith("鐢宠鎴愪负")):
        return None
    for word in ("owner", "业主", "老板", "frontdesk", "前台", "鍓嶅彴", "operator", "运营", "杩愯惀"):
        if word in text:
            return _normalize_requested_role_text(word)
    return "operator"


def _chat_role_change_payload(message: str) -> dict[str, str] | None:
    match = re.match(
        rf"^\s*(授予|撤销|鎺堜簣|鎾ら攢)\s+([A-Za-z0-9_-]+)\s*(?:为|爲|涓?)?\s*({_ROLE_WORDS_RE}|杩愯惀|鍓嶅彴)\s*$",
        message or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    operation = "revoke" if match.group(1) in {"撤销", "鎾ら攢"} else "grant"
    role = _normalize_requested_role_text(match.group(3)) or "operator"
    return {"operation": operation, "principal_id": match.group(2), "role": role}


def _chat_role_named_payload(message: str) -> dict[str, str] | None:
    text = (message or "").strip()
    real_match = re.match(
        rf"^\s*(?:将|把)\s*(?P<target>.+?)\s*(?:分配角色|设置为|设为|改成|改为)\s*(?P<role>{_ROLE_WORDS_RE})\s*$",
        text,
        re.IGNORECASE,
    )
    if real_match:
        return {
            "target": real_match.group("target").strip(),
            "role": _normalize_requested_role_text(real_match.group("role")) or "operator",
            "operation": "grant",
        }
    match = re.match(
        rf"^\s*(?:帮我)?(?:把|将)\s*(?P<target>.+?)\s*(?:的)?(?:身份|角色)?\s*(?:换成|改成|设置为|设为|设成|改为)\s*(?P<role>{_ROLE_WORDS_RE})\s*$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return {
        "target": match.group("target").strip(),
        "role": _normalize_requested_role_text(match.group("role")) or "operator",
        "operation": "grant",
    }


def _chat_role_named_request(message: str) -> bool:
    return _chat_role_named_payload(message) is not None


def _control_plane_actor(auth_context: dict[str, Any], chat_id: str) -> dict[str, Any]:
    return {
        "principal_id": auth_context.get("principal_id"),
        "role": auth_context.get("user_role"),
        "hotel_ids": auth_context.get("authorized_hotel_ids") or [],
        "resolved_hotel_id": auth_context.get("resolved_hotel_id"),
        "chat_id": chat_id,
        "global_admin": bool(auth_context.get("global_admin")),
    }


def _chat_binding_actor_for_target(auth_context: dict[str, Any], db_path: str | None, hotel_id: str, chat_id: str) -> dict[str, Any]:
    actor = _control_plane_actor(auth_context, chat_id)
    if actor.get("global_admin") or actor.get("role") in {"admin", "owner"}:
        return actor
    principal_id = auth_context.get("principal_id")
    if not db_path or not principal_id or not hotel_id:
        return actor
    try:
        with contextlib.closing(connect(db_path)) as conn:
            init_schema(conn)
            row = conn.execute(
                "SELECT role FROM hotel_memberships WHERE principal_id=? AND hotel_id=? AND status='active'",
                (principal_id, hotel_id),
            ).fetchone()
    except Exception:
        return actor
    if row:
        actor["role"] = row["role"]
        actor["resolved_hotel_id"] = hotel_id
        hotel_ids = set(actor.get("hotel_ids") or [])
        hotel_ids.add(hotel_id)
        actor["hotel_ids"] = sorted(hotel_ids)
    return actor


def _resolve_named_role_target(db_path: str | None, *, hotel_id: str | None, target: str, member_info: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    target_text = str(target or "").strip()
    if not db_path or not hotel_id or not target_text:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}
    ambiguous_terms = {"群里的一个人", "群里一个人", "某个人", "某某", "那个人", "一个人"}
    if target_text in ambiguous_terms:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}
    try:
        with contextlib.closing(sqlite3.connect(db_path)) as conn:
            conn.row_factory = sqlite3.Row
            exact = conn.execute(
                "SELECT principal_id FROM auth_principals WHERE principal_id=? AND status='active'",
                (target_text,),
            ).fetchall()
            if exact:
                candidates = exact
            else:
                candidates = conn.execute(
                    """
                    SELECT DISTINCT p.principal_id
                    FROM auth_principals p
                    JOIN hotel_memberships m ON m.principal_id=p.principal_id
                    WHERE m.hotel_id=? AND m.status='active' AND p.status='active'
                      AND (p.display_name=? OR p.alias=? OR p.name_snapshot=?)
                    """,
                    (hotel_id, target_text, target_text, target_text),
                ).fetchall()
    except Exception:
        return {"status": "blocked", "reason": "role_membership_target_not_found"}
    if len(candidates) != 1:
        matches: list[dict[str, Any]] = []
        for item in member_info or []:
            names = {
                str(item.get("name") or "").strip(),
                str(item.get("display_name") or "").strip(),
                str(item.get("nickname") or "").strip(),
            }
            if target_text in names:
                matches.append(item)
        if len(matches) != 1:
            return {"status": "blocked", "reason": "member_info_match_not_unique" if matches else "role_membership_target_not_found"}
        identity = matches[0]
        open_id_value = str(identity.get("open_id") or "").strip() or None
        user_id_value = str(identity.get("user_id") or "").strip() or None
        union_id_value = str(identity.get("union_id") or "").strip() or None
        if not (open_id_value or user_id_value or union_id_value):
            return {"status": "blocked", "reason": "member_info_identity_missing"}
        principal_id = f"feishu:{_safe_hash(open_id_value or user_id_value or union_id_value)}"
        timestamp = now_local()
        try:
            with contextlib.closing(connect(db_path)) as conn:
                with conn:
                    init_schema(conn)
                    existing = conn.execute(
                        "SELECT principal_id FROM auth_principals WHERE open_id=? OR user_id=? OR union_id=? LIMIT 1",
                        (open_id_value, user_id_value, union_id_value),
                    ).fetchone()
                    if existing:
                        principal_id = str(existing["principal_id"])
                    else:
                        conn.execute(
                            "INSERT INTO auth_principals (principal_id, open_id, user_id, union_id, display_name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'candidate', ?, ?)",
                            (principal_id, open_id_value, user_id_value, union_id_value, target_text, timestamp, timestamp),
                        )
        except Exception:
            return {"status": "blocked", "reason": "member_info_candidate_persist_failed"}
        return {"status": "ok", "principal_id": principal_id, "source": "member_info"}
    return {"status": "ok", "principal_id": str(candidates[0]["principal_id"])}


def _chat_binding_status(db_path: str | None, chat_id: str | None) -> dict[str, Any]:
    chat_id = normalize_feishu_chat_id(chat_id)
    if not db_path or not chat_id:
        return {"status": "data_gap", "reason": "chat_id_missing", "chat_bound": False}
    try:
        with contextlib.closing(connect(db_path)) as conn:
            init_schema(conn)
            row = conn.execute(
                "SELECT hotel_id, chat_type, status FROM chat_bindings WHERE chat_id=? ORDER BY updated_at DESC LIMIT 1",
                (chat_id,),
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT hotel_id, 'group' AS chat_type, status FROM group_chat_bindings WHERE chat_id=? ORDER BY updated_at DESC LIMIT 1",
                    (chat_id,),
                ).fetchone()
    except Exception:
        return {"status": "data_gap", "reason": "chat_binding_status_unavailable", "chat_bound": False}
    if not row or row["status"] != "active":
        return {"status": "ok", "chat_bound": False, "binding_status": "unbound"}
    return {
        "status": "ok",
        "chat_bound": True,
        "binding_status": "active",
        "hotel_id": row["hotel_id"],
        "resolved_hotel_id": row["hotel_id"],
        "chat_type": row["chat_type"],
    }


def _chat_request_expiry() -> str:
    try:
        ttl_minutes = int(os.environ.get("HOTEL_OTA_CHAT_REQUEST_TTL_MINUTES", "15"))
    except ValueError:
        ttl_minutes = 15
    return (datetime.fromisoformat(now_local()) + timedelta(minutes=max(ttl_minutes, 1))).isoformat(timespec="seconds")


def _permission_action_for_intent(intent: str) -> str:
    if intent == "chat_role_join_request":
        return "view_diagnosis"
    if intent == "chat_role_change_confirm":
        return "confirm_configuration_change"
    if intent == "chat_role_change_cancel":
        return "request_configuration_change"
    if intent == "chat_role_change_request":
        return "request_configuration_change"
    if intent == "chat_role_named_request":
        return "request_configuration_change"
    if intent == "chat_binding_confirm":
        return "confirm_configuration_change"
    if intent in {"chat_binding_request", "chat_binding_cancel", "chat_binding_status"}:
        return "request_configuration_change"
    if intent == "chat_configuration_confirm":
        return "confirm_configuration_change"
    if intent in {"chat_configuration_request", "chat_configuration_cancel"}:
        return "request_configuration_change"
    if intent in {name for name, _ in MANAGEMENT_READ_INTENTS}:
        return "view_hotel_controls"
    if intent == "price_execution_dry_run":
        return "price_update"
    if intent == "price_execution_confirm":
        return "enqueue_price_task"
    if intent in {"revenue_decision", "revenue_decision_demo", "roi_decision", "promotion_suggestion", "review_reply_draft", "third_party_report_preview"}:
        return "run_recommendation"
    if intent == "frontdesk_today_tasks":
        return "view_frontdesk_task"
    if intent == "seed_demo":
        return "manage_safety_config"
    return "view_diagnosis"


def _identity_context_supplied(*, chat_id: str | None, user_id: str | None, open_id: str | None, union_id: str | None, auth_config: str | None) -> bool:
    return bool(chat_id or user_id or open_id or union_id or auth_config)


def _has_complete_feishu_identity_context(
    *,
    chat_id: str | None,
    chat_type: str | None,
    user_id: str | None,
    open_id: str | None,
    union_id: str | None,
    auth_config: str | None,
) -> bool:
    chat_resolution = resolve_feishu_business_chat_id(chat_id)
    return bool(chat_resolution.get("chat_id") and (user_id or open_id or union_id or auth_config))


def _numeric_menu_intent(message: str) -> str | None:
    parts = str(message or "").strip().split()
    while parts and parts[0].startswith("@"):
        parts.pop(0)
    if len(parts) != 1:
        return None
    return NUMERIC_MENU_INTENTS.get(parts[0])


def _numeric_menu_tokens(message: str) -> list[str]:
    raw = str(message or "").strip()
    if not raw:
        return []
    parts = [part for part in re.split(r"[\s,，、;；]+", raw) if part]
    while parts and parts[0].startswith("@"):
        parts.pop(0)
    if len(parts) <= 1:
        return []
    if all(part in NUMERIC_MENU_INTENTS for part in parts):
        return parts
    return []


def _new_correlation_id() -> str:
    return f"fs-{uuid.uuid4().hex[:12]}"


def _safe_hash(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _classify_route_exception(exc: Exception) -> str:
    if isinstance(exc, KeyError):
        return "template_render_error"
    if isinstance(exc, json.JSONDecodeError):
        return "runtime_json_error"
    return "runtime_route_error"


def _safe_error_result(
    *,
    exc: Exception,
    role: str,
    output_profile: str | None,
    correlation_id: str,
    intent: str = "feishu_route_error",
    runtime_command: str = "feishu-route",
) -> dict[str, Any]:
    error_code = _classify_route_exception(exc)
    message = f"请求处理失败，已生成诊断编号 {correlation_id}。请稍后重试，或把该编号给维护人员排查。"
    return {
        "run_id": demo_run_id("feishu-route-error"),
        "intent": intent,
        "status": "error",
        "error_code": error_code,
        "correlation_id": correlation_id,
        "safe_user_message": message,
        "summary": message,
        "runtime_command": runtime_command,
        "generated_by_runtime": True,
        "source": "feishu",
        "auth_role": role,
        "output_profile": default_output_profile(role, output_profile),
        "blocked_reason": error_code,
        "data_source_type": "unavailable",
        "freshness_status": "unavailable",
        "approval_data_allowed": False,
        "formal_approval_allowed": False,
        "formal_approval_created": False,
        "live_allowed": False,
        "live_execution_count": 0,
        "error_class": type(exc).__name__,
        "debug_summary": error_code,
        "rendered": {
            "status": "ok",
            "output_profile": "system_status",
            "text": message,
            "visible_fields": ["status", "summary", "blocked_reason", "correlation_id"],
            "hidden_fields": ["error_class", "debug_summary"],
            "message_send_attempted": False,
            "template": "system_health",
        },
        "send_payload": {
            "text": message,
            "card": None,
            "send_allowed": True,
            "output_profile": "system_status",
            "warnings": [error_code],
            "data_source_type": "unavailable",
            "freshness_status": "unavailable",
        },
    }


COMPACT_ROUTE_KEYS = {
    "intent",
    "status",
    "error_code",
    "correlation_id",
    "output_profile",
    "node_id",
    "mode",
    "context_source",
    "data_source_type",
    "freshness_status",
    "business_date",
    "holiday_source",
    "event_source",
    "weather_source",
    "regional_heat_source",
    "market_context_status",
    "event_discovery_reason",
    "weather_reason",
    "regional_heat_missing_fields",
    "data_business_date",
    "demo_business_date",
    "as_of_time",
    "total_nodes",
    "passed_nodes",
    "failed_nodes",
    "total_scenarios",
    "passed_scenarios",
    "failed_scenarios",
    "failed_scenario_ids",
    "covered_nodes",
    "uncovered_nodes",
    "formal_approval_created",
    "business_result_generated",
    "approval_data_allowed",
    "approval_preview_allowed",
    "formal_approval_allowed",
    "live_allowed",
    "live_execution_count",
    "blocked_reason",
    "trusted_runtime_role_required",
    "identity_context_required",
    "requested_intents",
    "multi_intent_limit",
    "safe_user_message",
    "summary",
    "context_warnings",
    "generated_demo_run_id",
    "fallback_used",
    "chat_bound",
    "binding_status",
    "hotel_id",
    "resolved_hotel_id",
    "chat_type",
}


def _compact_run_context(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    keys = [
        "context_source",
        "use_generated_today",
        "requested_generated_today",
        "fallback_used",
        "generated_demo_run_id",
        "generated_at",
        "business_date",
        "data_source_type",
        "freshness_status",
        "demo_dataset_id",
        "context_warnings",
    ]
    return {key: value.get(key) for key in keys if key in value}


def compact_feishu_route_result(result: dict[str, Any]) -> dict[str, Any]:
    compact = {key: result[key] for key in COMPACT_ROUTE_KEYS if key in result}
    compact["compact_result"] = True
    run_context = _compact_run_context(result.get("run_context"))
    if run_context:
        compact["run_context"] = run_context
    if "send_payload" in result:
        compact["send_payload"] = result["send_payload"]
    if "rendered" in result:
        rendered = result["rendered"] or {}
        compact["rendered"] = {
            key: rendered.get(key)
            for key in ["status", "output_profile", "template", "message_send_attempted"]
            if key in rendered
        }
    if "sub_results" in result:
        compact["sub_results"] = result["sub_results"]
    return compact


def _compact_output_chars(result: dict[str, Any]) -> int:
    try:
        return len(json_dumps(compact_feishu_route_result(result)))
    except Exception:
        send_payload = result.get("send_payload") if isinstance(result, dict) else None
        text = send_payload.get("text") if isinstance(send_payload, dict) else ""
        return len(str(text))


def _write_route_log(result: dict[str, Any], *, started_at: float, chat_id: str | None, open_id: str | None, user_id: str | None) -> None:
    try:
        log_path = os.environ.get("HOTEL_OTA_FEISHU_ROUTE_LOG")
        if log_path:
            path = Path(log_path)
        else:
            # 多酒店：按 result 中的 resolved_hotel_id 分目录；未解析到酒店（如璞悦旧路径）则用默认目录。
            log_dir = hotel_log_dir(result.get("resolved_hotel_id"), purpose="feishu-route")
            path = Path(log_dir) / "feishu-route.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": now_local(),
            "correlation_id": result.get("correlation_id"),
            "intent": result.get("intent"),
            "status": result.get("status"),
            "error_code": result.get("error_code"),
            "runtime_command": result.get("runtime_command"),
            "duration_ms": int((time.perf_counter() - started_at) * 1000),
            "output_chars": _compact_output_chars(result),
            "context_source": result.get("context_source"),
            "chat_hash": _safe_hash(chat_id),
            "open_hash": _safe_hash(open_id),
            "user_hash": _safe_hash(user_id),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json_dumps(record) + "\n")
    except Exception:
        return


_SECRET_RE = re.compile(r"(?i)(token|secret|password|key)\s*[:=]\s*[^,\s]+")


def _redact_message_text(message: str | None) -> str:
    if not message:
        return ""
    text = _SECRET_RE.sub(lambda m: f"{m.group(1)}=***", str(message))
    return text[:240]


def _record_feishu_audit(
    *,
    db_path: str | None,
    message: str,
    result: dict[str, Any],
    chat_id: str | None,
    chat_type: str | None,
    open_id: str | None,
    user_id: str | None,
    union_id: str | None,
) -> None:
    if not db_path or not chat_id:
        return
    try:
        timestamp = now_local()
        sender = open_id or user_id or union_id
        with contextlib.closing(connect(db_path)) as conn:
            with conn:
                init_schema(conn)
                binding = conn.execute(
                    "SELECT hotel_id, status FROM chat_bindings WHERE chat_id=? ORDER BY updated_at DESC LIMIT 1",
                    (chat_id,),
                ).fetchone()
                bound_hotel_id = binding["hotel_id"] if binding and binding["status"] == "active" else None
                binding_status = binding["status"] if binding else "unbound"
                conn.execute(
                    """
                    INSERT INTO feishu_chat_registry
                      (chat_id_hash, chat_type, bound_hotel_id, binding_status, first_seen_at, last_seen_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chat_id_hash) DO UPDATE SET chat_type=excluded.chat_type, bound_hotel_id=excluded.bound_hotel_id, binding_status=excluded.binding_status, last_seen_at=excluded.last_seen_at
                    """,
                    (_safe_hash(chat_id), chat_type or "unknown", bound_hotel_id, binding_status, timestamp, timestamp),
                )
                rendered = result.get("rendered") if isinstance(result.get("rendered"), dict) else {}
                send_payload = result.get("send_payload") if isinstance(result.get("send_payload"), dict) else {}
                conn.execute(
                    """
                    INSERT INTO feishu_message_audit
                      (audit_id, event_id, correlation_id, chat_id_hash, sender_identity_hash, message_text_redacted, intent, auth_backend, auth_status, tenant_status, role, blocked_reason, renderer_template, send_allowed, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"fsa-{uuid.uuid4().hex}",
                        result.get("event_id"),
                        result.get("correlation_id"),
                        _safe_hash(chat_id),
                        _safe_hash(sender),
                        _redact_message_text(message) if os.environ.get("HOTEL_OTA_FEISHU_AUDIT_RAW_TEXT") == "1" else _redact_message_text(message),
                        result.get("intent"),
                        result.get("auth_backend"),
                        result.get("auth_status") or ("authorized" if result.get("status") != "blocked" else "blocked"),
                        result.get("tenant_status"),
                        result.get("personal_role") or result.get("auth_role"),
                        result.get("blocked_reason") or result.get("reason"),
                        rendered.get("template"),
                        1 if send_payload.get("text") else 0,
                        timestamp,
                    ),
                )
    except Exception:
        return


def _summarize_sub_result(menu_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "menu_id": menu_id,
        "intent": result.get("intent"),
        "status": result.get("status"),
        "node_id": result.get("node_id"),
        "runtime_command": result.get("runtime_command"),
        "data_source_type": result.get("data_source_type"),
        "business_date": result.get("business_date") or result.get("data_business_date") or result.get("demo_business_date"),
        "error_code": result.get("error_code"),
        "correlation_id": result.get("correlation_id"),
        "blocked_reason": result.get("blocked_reason"),
    }


def _route_multi_intent(
    tokens: list[str],
    *,
    role: str,
    output_profile: str | None,
    db_path: str | None,
    render: bool,
    hotel_id: str,
    chat_id: str | None,
    chat_type: str | None,
    user_id: str | None,
    open_id: str | None,
    union_id: str | None,
    auth_config: str | None,
    use_generated_today: bool,
    demo_data_dir: str | None,
    trusted_runtime_role: bool,
    production_feishu: bool = False,
    correlation_id: str,
) -> dict[str, Any]:
    if len(tokens) > 3:
        result = _base_result("multi_intent_too_many", role=role, output_profile=output_profile)
        result.update(
            {
                "status": "blocked",
                "correlation_id": correlation_id,
                "requested_intents": tokens,
                "multi_intent_limit": 3,
                "runtime_command": "multi-intent",
                "summary": "一次最多处理 3 个菜单编号，请拆成多条消息或只发送 1-3 个编号。",
                "blocked_reason": "too_many_menu_items_in_one_message",
            }
        )
    else:
        sub_results = []
        for token in tokens:
            try:
                routed = safe_route_feishu_command(
                    token,
                    role=role,
                    output_profile=output_profile,
                    db_path=db_path,
                    render=False,
                    hotel_id=hotel_id,
                    chat_id=chat_id,
                    chat_type=chat_type,
                    user_id=user_id,
                    open_id=open_id,
                    union_id=union_id,
                    auth_config=auth_config,
                    use_generated_today=use_generated_today,
                    demo_data_dir=demo_data_dir,
                    trusted_runtime_role=trusted_runtime_role,
                    production_feishu=production_feishu,
                    compact=True,
                )
            except Exception as exc:
                routed = _safe_error_result(
                    exc=exc,
                    role=role,
                    output_profile=output_profile,
                    correlation_id=_new_correlation_id(),
                    intent=NUMERIC_MENU_INTENTS.get(token, "unknown"),
                    runtime_command=f"multi-intent:{token}",
                )
            summarized = _summarize_sub_result(token, routed)
            if production_feishu:
                summarized["data_source_type"] = summarized.get("data_source_type") or "unavailable"
                if summarized["data_source_type"] == "unavailable":
                    summarized["business_date"] = None
            sub_results.append(summarized)
        statuses = {str(item.get("status")) for item in sub_results}
        if statuses == {"blocked"}:
            parent_status = "blocked"
            blocked_reason = "all_sub_intents_blocked"
        elif statuses == {"data_gap"}:
            parent_status = "data_gap"
            blocked_reason = "all_sub_intents_data_gap"
        elif statuses & {"blocked", "error"}:
            parent_status = "partial"
            blocked_reason = "partial_multi_intent_result"
        else:
            parent_status = "ok"
            blocked_reason = "demo_preview_allowed_formal_live_blocked"
        result = _base_result("multi_intent_summary", role=role, output_profile=output_profile)
        result.update(
            {
                "status": parent_status,
                "correlation_id": correlation_id,
                "requested_intents": tokens,
                "sub_results": sub_results,
                "runtime_command": "multi-intent",
                "summary": "；".join(
                    f"{item['menu_id']}={item.get('intent')}:{item.get('status')}" for item in sub_results
                ),
                "blocked_reason": blocked_reason,
            }
        )
        if production_feishu:
            result.update(
                {
                    "hotel_id": None,
                    "hotel_name": None,
                    "data_business_date": None,
                    "data_source_type": "unavailable",
                    "freshness_status": "missing_real_data",
                    "business_status": "not_evaluated",
                    "allow_demo_fallback": False,
                    "allow_sample_evidence": False,
                    "approval_data_allowed": False,
                    "approval_preview_allowed": False,
                    "formal_approval_allowed": False,
                    "live_allowed": False,
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                    "business_result_generated": False,
                    "production_feishu": True,
                }
            )
            result.pop("demo_dataset_id", None)
            result.pop("demo_business_date", None)
    if render:
        result["rendered"] = render_feishu_output(result, result.get("output_profile"))
        result["send_payload"] = build_feishu_send_payload(result, role=role)
    return result


def _permission_blocked_result(
    *,
    intent: str,
    role: str,
    output_profile: str | None,
    blocked_reason: str,
    required_permission: str | None = None,
    auth_status: str | None = None,
    self_claim_ignored: bool = False,
) -> dict[str, Any]:
    result = _base_result(intent, role=role, output_profile=output_profile)
    result.update(
        {
            "status": "blocked",
            "blocked_reason": blocked_reason,
            "required_permission": required_permission,
            "auth_status": auth_status,
            "self_claim_ignored": self_claim_ignored,
            "business_result_generated": False,
            "permission_source": "feishu_role_map_or_explicit_runtime_role",
            "identity_diagnostics_redacted": True,
        }
    )
    if blocked_reason in {
        "missing_required_chat_id",
        "missing_trusted_business_chat_id",
        "missing_business_chat_id",
        "missing_feishu_identity",
        "chat_not_allowed",
        "chat_not_bound_to_hotel",
        "tenant_selection_required",
        "tenant_scope_mismatch",
        "missing_resolved_hotel_id",
    }:
        result["hotel_id"] = None
        result["hotel_name"] = None
    return result


def _production_no_demo_fallback_result(
    *,
    intent: str,
    role: str,
    output_profile: str | None,
    reason: str = "production_real_data_required",
) -> dict[str, Any]:
    base_intent = "run_s02" if intent == "run_s02_demo" else intent
    result = _base_result(base_intent, role=role, output_profile=output_profile)
    result.update(
        {
            "status": "data_gap",
            "blocked_reason": reason,
            "business_result_generated": False,
            "data_source_type": "unavailable",
            "freshness_status": "missing_real_data",
            "context_source": "production_feishu_no_demo_fallback",
            "allow_demo_fallback": False,
            "allow_sample_evidence": False,
            "today_label_allowed": False,
            "formal_approval_created": False,
            "formal_approval_allowed": False,
            "live_allowed": False,
            "live_execution_count": 0,
            "summary": "生产飞书请求未明确要求演示，当前缺少可用真实数据，不能回退 demo/sample 生成业务结论。",
        }
    )
    return result


def _production_snapshot_result(
    *,
    hotel_id: str,
    role: str,
    output_profile: str | None,
    target_business_date: str,
    as_of_time: str | None = None,
) -> dict[str, Any]:
    result = _base_result("run_s02", role=role, output_profile=output_profile)
    if not database_source_enabled():
        result.update(
            {
                "status": "data_gap",
                "node_id": "N005",
                "skill_id": "S2",
                "agent_id": agent_id_for_node("N005"),
                "runtime_command": "snapshot",
                "data_source_type": "unavailable",
                "freshness_status": "missing_date",
                "today_label_allowed": False,
                "blocked_reason": "database_source_disabled",
                "summary": "Production data source is disabled. This request will not fall back to demo/sample data unless demo is explicitly requested.",
            }
        )
        return result
    business_date = str(target_business_date)[:10]
    db_result = database_template_result("operating_snapshot", hotel_id, date=business_date, as_of_time=as_of_time)
    payload = db_result.get("payload") if isinstance(db_result.get("payload"), dict) else {}
    source_status = payload.get("source_status")
    status = "ok" if db_result.get("status") == "ok" and source_status in {None, "ok"} else "data_gap"
    freshness_status = payload.get("freshness_status") or db_result.get("freshness_status") or "missing_date"
    pms_s2_contract = payload.get("s2_contract") == "pms_room_type_forecast_v1"
    optional_results = load_s2_optional_results(
        database_template_result, hotel_id=hotel_id, business_date=business_date, as_of_time=as_of_time
    ) if status == "ok" else {}
    operating_views = build_s2_operating_views(operating_payload=payload, optional_results=optional_results)
    realtime_occupancy: dict[str, Any] = {}
    realtime_blocked_reason: str | None = None
    if status == "ok" and business_date and not pms_s2_contract:
        reservations = database_template_result("reservation_snapshot", hotel_id, date=business_date, as_of_time=as_of_time)
        stayovers = database_template_result("stayover_snapshot", hotel_id, date=business_date)
        room_status = database_template_result("room_status_snapshot", hotel_id, date=business_date)
        reservation_payload = reservations.get("payload") if isinstance(reservations.get("payload"), dict) else {}
        stayover_payload = stayovers.get("payload") if isinstance(stayovers.get("payload"), dict) else {}
        realtime_operating_payload = dict(payload)
        room_status_payload = room_status.get("payload") if isinstance(room_status.get("payload"), dict) else {}
        room_status_rows = room_status_payload.get("rows") or []
        if room_status.get("status") == "ok" and room_status_rows:
            realtime_operating_payload["rows"] = room_status_rows
            row_count = room_status_payload.get("row_count") or room_status_payload.get("filtered_row_count") or len(room_status_rows)
            if row_count and int(row_count) >= int(float(realtime_operating_payload.get("total_rooms") or 0)):
                realtime_operating_payload["total_rooms"] = row_count
            if room_status_payload.get("data_snapshot_time"):
                realtime_operating_payload["data_snapshot_time"] = room_status_payload.get("data_snapshot_time")
        if reservations.get("status") == "ok" and stayovers.get("status") == "ok":
            realtime_occupancy = build_realtime_occupancy(
                operating_payload=realtime_operating_payload,
                reservation_payload=reservation_payload,
                stayover_payload=stayover_payload,
                business_date=str(business_date),
                as_of_time=as_of_time,
            )
            if realtime_occupancy.get("status") != "ok":
                status = "data_gap"
                realtime_blocked_reason = realtime_occupancy.get("reason") or "realtime_occupancy_data_gap"
        else:
            status = "data_gap"
            realtime_blocked_reason = "realtime_occupancy_required_sources_missing"
    core_metrics = {
        "total_rooms": payload.get("total_rooms") or payload.get("room_count"),
        "sold_rooms": payload.get("sold_rooms"),
        "committed_sold_rooms": payload.get("committed_sold_rooms"),
        "physical_occupied_rooms": payload.get("physical_occupied_rooms"),
        "physical_occupancy_rate": payload.get("physical_occupancy_rate"),
        "sold_room_nights_today": payload.get("sold_room_nights_today") or payload.get("room_nights") or payload.get("sold_rooms"),
        "sold_orders_today": payload.get("sold_orders_today") or payload.get("orders_today"),
        "occupancy_rate": payload.get("occupancy_rate"),
        "adr": payload.get("adr"),
        "revpar": payload.get("revpar"),
    }
    result.update(
        {
            "status": status,
            "node_id": "N005",
            "skill_id": "S2",
            "agent_id": agent_id_for_node("N005"),
            "runtime_command": "snapshot",
            "hotel_id": hotel_id,
            "business_result_generated": status == "ok",
            "data_source_type": db_result.get("data_source_type") or "mysql_db",
            "source_mode": db_result.get("source_mode") or "mysql_runtime",
            "source_status": source_status,
            "freshness_status": freshness_status,
            "business_date": business_date,
            "data_business_date": business_date,
            "data_snapshot_time": payload.get("data_snapshot_time"),
            "s2_contract": payload.get("s2_contract"),
            "today_label_allowed": freshness_status == "fresh",
            "core_metrics": core_metrics,
            "operating_views": operating_views,
            "total_rooms": core_metrics["total_rooms"],
            "sold_rooms": core_metrics["sold_rooms"],
            "sold_room_nights_today": core_metrics["sold_room_nights_today"],
            "sold_orders_today": core_metrics["sold_orders_today"],
            "occupancy_rate": core_metrics["occupancy_rate"] if pms_s2_contract else realtime_occupancy.get("actual_occupancy_rate") if realtime_occupancy.get("status") == "ok" else None,
            "formula_version": "pms_room_type_forecast_committed_sales_v1" if pms_s2_contract else realtime_occupancy.get("formula_version"),
            "actual_numerator_rooms": None if pms_s2_contract else realtime_occupancy.get("actual_numerator_rooms"),
            "denominator_rooms": core_metrics["total_rooms"] if pms_s2_contract else realtime_occupancy.get("denominator_rooms"),
            "actual_occupancy_rate": None if pms_s2_contract else realtime_occupancy.get("actual_occupancy_rate"),
            "occupancy_rate_source": "pms_committed_sales" if pms_s2_contract else realtime_occupancy.get("occupancy_rate_source"),
            "physical_occupied_rooms": core_metrics["physical_occupied_rooms"],
            "physical_occupancy_rate": core_metrics["physical_occupancy_rate"],
            "kf11_occupied_rooms": None if pms_s2_contract else realtime_occupancy.get("kf11_occupied_rooms"),
            "kf11_formula_gap_rooms": None if pms_s2_contract else realtime_occupancy.get("kf11_formula_gap_rooms"),
            "occupancy_numerator_components": realtime_occupancy.get("numerator_components"),
            "occupancy_reservation_adjustment_components": realtime_occupancy.get("reservation_adjustment_components"),
            "occupancy_denominator_components": realtime_occupancy.get("denominator_components"),
            "duplicate_risk": realtime_occupancy.get("duplicate_risk"),
            "missing_formula_components": realtime_occupancy.get("missing_formula_components"),
            "adr": core_metrics["adr"],
            "revpar": core_metrics["revpar"],
            "risk_flags": payload.get("risk_flags") or db_result.get("risk_flags") or [],
            "blocked_reason": "read_only_runtime_formal_live_blocked" if status == "ok" else realtime_blocked_reason,
            "formal_approval_created": False,
            "live_execution_count": 0,
        }
    )
    if status != "ok":
        result["blocked_reason"] = realtime_blocked_reason or payload.get("source_status") or db_result.get("reason") or "production_snapshot_data_gap"
        result["business_result_generated"] = False
    return result


def _safe_auth_context_blocked_result(
    *,
    message: str,
    intent: str,
    role: str,
    output_profile: str | None,
    correlation_id: str,
    render: bool,
) -> dict[str, Any]:
    base_intent = "run_s02" if intent == "run_s02_demo" else intent
    result = _permission_blocked_result(
        intent=base_intent,
        role=role,
        output_profile=output_profile,
        blocked_reason="missing_required_feishu_auth_context",
        required_permission=_permission_action_for_intent(intent),
        auth_status="invalid_context",
        self_claim_ignored=_self_claim_detected(message),
    )
    result.update(
        {
            "correlation_id": correlation_id,
            "runtime_command": "feishu-route:blocked-missing-auth-context",
            "trusted_runtime_role_required": True,
            "identity_context_required": ["chat_id", "open_id_or_user_id_or_union_id_or_auth_config"],
        }
    )
    if render:
        result["rendered"] = render_feishu_output(result, result.get("output_profile"))
        result["send_payload"] = build_feishu_send_payload(result, role=role)
    return result


def _full_json_blocked_result(
    *,
    role: str,
    output_profile: str | None,
    correlation_id: str,
    render: bool,
) -> dict[str, Any]:
    result = _permission_blocked_result(
        intent="local_debug_full_json",
        role=role,
        output_profile=output_profile,
        blocked_reason="full_json_requires_trusted_runtime_role",
        required_permission="local_runtime_debug",
        auth_status="invalid_context",
    )
    result.update(
        {
            "correlation_id": correlation_id,
            "runtime_command": "feishu-route:blocked-full-json",
            "local_debug_only": True,
            "trusted_runtime_role_required": True,
        }
    )
    if render:
        result["rendered"] = render_feishu_output(result, result.get("output_profile"))
        result["send_payload"] = build_feishu_send_payload(result, role=role)
    return result


def _developer_debug_blocked_result(
    *,
    role: str,
    output_profile: str | None,
    correlation_id: str,
    render: bool,
) -> dict[str, Any]:
    result = _permission_blocked_result(
        intent="developer_detail",
        role="guest",
        output_profile="guest_limited",
        blocked_reason="developer_debug_local_only",
        required_permission="local_runtime_debug",
        auth_status="not_available_in_production_feishu",
    )
    result.update(
        {
            "correlation_id": correlation_id,
            "runtime_command": "feishu-route:blocked-developer-debug",
            "local_debug_only": True,
            "business_result_generated": False,
        }
    )
    if render:
        result["rendered"] = render_feishu_output(result, result.get("output_profile"))
        result["send_payload"] = build_feishu_send_payload(result, role="guest")
    return result


def _production_role_override_blocked_result(
    *,
    role: str,
    output_profile: str | None,
    correlation_id: str,
    render: bool,
) -> dict[str, Any]:
    result = _permission_blocked_result(
        intent="feishu_auth_configuration",
        role="guest",
        output_profile=output_profile,
        blocked_reason="production_feishu_disallows_role_override",
        required_permission="feishu_role_map_authentication",
        auth_status="invalid_context",
    )
    result.update(
        {
            "correlation_id": correlation_id,
            "runtime_command": "feishu-route:blocked-production-role-override",
            "production_feishu": True,
            "trusted_runtime_role_allowed": False,
            "safe_user_message": "您好，生产飞书请求必须由网关身份和角色表自动鉴权。",
        }
    )
    if render:
        result["rendered"] = render_feishu_output(result, result.get("output_profile"))
        result["send_payload"] = build_feishu_send_payload(result, role="guest")
    return result


def _detect_intent(message: str) -> str:
    text = (message or "").lower()
    raw = message or ""
    if _chat_request_id(raw, _CHAT_BIND_CONFIRMATION_RE):
        return "chat_binding_confirm"
    if _chat_request_id(raw, _CHAT_BIND_CANCELLATION_RE):
        return "chat_binding_cancel"
    if raw.strip() == "查看当前会话绑定":
        return "chat_binding_status"
    if _chat_binding_payload(raw):
        return "chat_binding_request"
    if _s14_source_key(raw) and ("s14" in text or "ota" in text or "\u8bca\u65ad" in raw):
        return "s14_source_request"
    if _chat_role_confirmation_payload(raw):
        return "chat_role_change_confirm"
    if _chat_request_id(raw, _CHAT_ROLE_CANCELLATION_RE):
        return "chat_role_change_cancel"
    if _chat_join_requested_role(raw) is not None:
        return "chat_role_join_request"
    if _chat_role_change_payload(raw):
        return "chat_role_change_request"
    if _chat_role_named_request(raw):
        return "chat_role_named_request"
    if _chat_request_id(raw, _CHAT_CONFIRMATION_RE):
        return "chat_configuration_confirm"
    if _chat_request_id(raw, _CHAT_CANCELLATION_RE):
        return "chat_configuration_cancel"
    if re.fullmatch(r"\s*确认(?:调价|执行调价)?(?:\s+PRC-[A-Za-z0-9]+)?\s*", raw, re.IGNORECASE):
        return "price_execution_confirm"
    if raw.strip() in {"\u786e\u8ba4\u6267\u884c", "\u786e\u8ba4\u6267\u884c\u8c03\u4ef7"}:
        return "price_execution_confirm"
    if _chat_price_guard_payload(raw):
        return "chat_configuration_request"
    if _contains_any(raw, list(MEMBER_ROLE_STATUS_PHRASES)) or (
        _contains_any(raw, ["查询", "验一下", "当前群", "当前酒店"])
        and _contains_any(raw, ["身份", "权限", "角色", "成员"])
    ):
        return "member_role_status"
    if _contains_any(raw, list(AUTH_PATH_PHRASES)) or (
        _contains_any(raw, ["sqlite", "SQLite", "权限", "验权", "鉴权"])
        and _contains_any(raw, ["从哪", "怎么", "路径", "查"])
    ):
        return "auth_path_explanation"
    if _contains_any(raw, list(MARKET_HEAT_PHRASES)):
        return "progress_deviation_demo"
    if raw.strip() in MARKET_CONTEXT_PHRASES or _contains_any(raw, list(MARKET_CONTEXT_PHRASES)):
        return "market_context_demo"
    if _contains_any(raw, list(IDENTITY_PHRASES)) or "who are you" in text:
        return "identity"
    if _contains_any(raw, ["上传Excel", "上传 Excel", "上传Excel诊断", "上传 Excel 诊断", "S14 Excel", "OTA诊断Excel", "OTA 诊断 Excel"]):
        return "s14_source_request"
    numeric_intent = _numeric_menu_intent(raw)
    if numeric_intent:
        return numeric_intent
    legacy_demo = _contains_any(raw, ["\u5a55", "\u59af"])
    legacy_enter = _contains_any(raw, ["\u6769", "\u5bee"])
    legacy_price = _contains_any(raw, ["\u748b"])
    if _config_change_request_detected(raw):
        return "config_change_request"
    if _s6_batch_room_price_change(raw) is not None:
        return "price_execution_dry_run"
    if _contains_any(raw, list(PRICEABLE_PRODUCT_PHRASES)):
        return "priceable_product_list"
    for intent, phrases in MANAGEMENT_READ_INTENTS:
        if _contains_any(raw, list(phrases)):
            return intent
    if _contains_any(raw, PROGRESS_DIAGNOSIS_PHRASES) or _contains_any(raw, HOURLY_SALES_PHRASES):
        return "progress_deviation_demo"
    if _historical_room_type_performance_days(raw) is not None:
        return "historical_room_type_performance"
    if _contains_any(raw, BUSINESS_SNAPSHOT_PHRASES) or any(term in text for term in ["adr", "revpar"]):
        return "run_s02_demo"
    if _contains_any(raw, BASELINE_PHRASES):
        return "sales_baseline_demo"
    if _contains_any(raw, BUSINESS_CALENDAR_PHRASES):
        return "business_calendar"
    if _contains_any(raw.lower(), STATUS_SOURCE_PHRASES) or _contains_any(
        text,
        ["runtime status", "health status", "current mode", "env status", "db_source_enable"],
    ):
        return "runtime_status"
    if _contains_any(
        text,
        ["runtime status", "health status", "current mode", "env status"],
    ) or _contains_any(
        raw,
        [
            "\u73b0\u5728\u4ec0\u4e48\u6a21\u5f0f",
            "\u5f53\u524d\u4ec0\u4e48\u6a21\u5f0f",
            "\u5f53\u524d\u6a21\u5f0f",
            "\u6570\u636e\u65e5\u671f",
            "\u8fd0\u884c\u72b6\u6001",
            "\u7cfb\u7edf\u72b6\u6001",
            "\u73af\u5883\u72b6\u6001",
        ],
    ):
        return "runtime_status"
    if _contains_any(text, ["ping", "health ping", "hello"]) or _contains_any(raw, ["\u5728\u5417", "\u4f60\u597d", "\u5065\u5eb7\u68c0\u67e5"]):
        return "health_ping"
    if _config_change_request_detected(raw):
        return "config_change_request"
    if _contains_any(text, ["model", "provider", "flash"]) or _contains_any(raw, ["\u6a21\u578b", "\u5207\u6362"]):
        return "model_config_request"
    if _contains_any(
        text,
        [
            "git status",
            "git stash",
            "git clean",
            "rollback",
            "reset --hard",
            "write code",
            "modify code",
            "systemctl",
            "service restart",
            "restart gateway",
            "restart openclaw",
        ],
    ) or _contains_any(
        raw,
        [
            "\u56de\u6eda",
            "\u4fee\u6539\u4ee3\u7801",
            "\u5199\u4ee3\u7801",
            "\u63d0\u4ea4\u4ee3\u7801",
            "\u67e5\u770b\u6e90\u7801",
            "\u8f93\u51fa\u914d\u7f6e\u6587\u4ef6",
            "\u8f93\u51fa\u6570\u636e\u5e93\u8fde\u63a5\u4e32",
            "\u6570\u636e\u5e93\u8fde\u63a5\u4e32",
        ],
    ):
        return "maintenance_safety_refusal"
    if _contains_any(raw, ["\u81ea\u67e5", "\u5b9a\u65f6\u4efb\u52a1", "\u7f51\u5173"]) or _contains_any(text, ["self check", "cron", "gateway"]):
        return "self_check"
    if _contains_any(raw, ["\u53d1\u5e03\u8bc4\u8bba", "\u53d1\u8bc4\u8bba", "\u76f4\u63a5\u53d1\u5e03"]) and _contains_any(raw, ["\u8bc4\u8bba", "\u56de\u590d"]):
        return "review_publish_request"
    if _contains_any(raw, ["\u8bc4\u8bba\u56de\u590d", "\u5dee\u8bc4\u56de\u590d", "\u751f\u6210\u8bc4\u8bba", "\u56de\u590d\u8349\u7a3f"]):
        return "review_reply_draft"
    if _contains_any(raw, ["\u8001\u677f\u89c6\u89d2", "\u8001\u677f\u770b"]):
        return "owner_today_demo"
    if _contains_any(raw, ["\u8fd0\u8425\u89c6\u89d2", "\u8fd0\u8425\u770b"]):
        return "operator_full_demo"
    if _contains_any(raw, ["\u524d\u53f0\u89c6\u89d2", "\u524d\u53f0\u4efb\u52a1", "\u524d\u53f0\u770b"]):
        return "frontdesk_today_tasks"
    if _contains_any(raw, ["\u63a8\u5e7f\u5efa\u8bae", "\u751f\u6210\u63a8\u5e7f"]):
        return "promotion_suggestion"
    if _contains_any(raw, ["\u7ade\u5bf9", "\u7ade\u4e89\u76d1\u63a7", "\u7ade\u54c1", "\u540c\u884c\u4ef7\u683c", "\u7ade\u4e89\u5708", "\u7ade\u4e89\u5206\u6790", "\u7ade\u4e89\u5bf9\u624b", "\u5e02\u573a\u7ade\u6001"]):
        return "competition_alert"
    if _contains_any(raw, ["\u83dc\u5355", "\u547d\u4ee4\u83dc\u5355", "\u947f"]) or "menu" in text or "command menu" in text:
        return "menu"
    if _contains_any(raw, ["\u8eab\u4efd", "\u4f60\u662f\u8c01", "\u6d63"]) or "who are you" in text:
        return "identity"
    if _contains_any(raw, ["\u5f00\u53d1\u8005\u8be6\u60c5"]) or "developer detail" in text or (_contains_any(raw, ["\u5bee"]) and _contains_any(raw, ["\u8a07"])):
        return "developer_detail"
    if (_contains_any(raw, ["\u6f14\u793a\u6a21\u5f0f"]) and _contains_any(raw, ["\u8fdb\u5165", "\u5f00\u542f"])) or (legacy_demo and legacy_enter):
        return "enter_demo_mode"
    if (
        "seed-demo" in text
        or "generate-today-demo" in text
        or ("generate" in text and "demo" in text)
        or _contains_any(
            raw,
            [
                "\u704c\u5165\u6f14\u793a\u6570\u636e",
                "\u751f\u6210\u6f14\u793a\u6570\u636e",
                "\u751f\u6210\u4eca\u65e5",
                "\u4eca\u65e5\u5408\u6210",
                "\u5408\u6210 demo",
                "\u5408\u6210\u6f14\u793a",
            ],
        )
    ):
        return "seed_demo"
    if "n001" in text or "n001-n022" in text or _contains_any(raw, ["\u68c0\u67e5N", "\u8282\u70b9"]):
        return "demo_node_all"
    if "sc01" in text or "sc01-sc10" in text or _contains_any(raw, ["\u573a\u666f", "\u94fe\u8def"]):
        return "demo_chain_all"
    if _contains_any(raw, ["\u5b8c\u6574\u6f14\u793a", "\u5168\u94fe\u8def"]) or "full chain" in text:
        return "full_chain_demo"
    if _s5_ota_product_id(raw) and _s6_net_target_price(raw) is not None:
        return "price_execution_dry_run"
    if _s5_ota_product_id(raw) and _s6_target_price(raw) is not None and _contains_any(
        raw,
        ["调价", "挂牌价", "目标价", "执行价", "售价"],
    ):
        return "price_execution_dry_run"
    if "s02" in text or _contains_any(raw, ["\u7ecf\u8425\u5feb\u7167"]):
        return "run_s02_demo" if ("demo" in text or _contains_any(raw, ["\u6f14\u793a"]) or legacy_demo) else "run_s02"
    if (_contains_any(raw, ["\u8c03\u4ef7"]) or legacy_price) and ("dry-run" in text or _contains_any(raw, ["\u9884\u89c8", "\u6267\u884c\u9884\u89c8"]) or _contains_any(raw, ["\u68f0"])):
        return "price_execution_dry_run"
    if (_contains_any(raw, ["\u8c03\u4ef7"]) or legacy_price) and "live" in text:
        return "live_execution_request"
    if _contains_any(raw, ["\u672c\u5e97OTA\u8bca\u65ad", "\u672c\u5e97 OTA\u8bca\u65ad", "OTA\u8fd0\u8425\u8bca\u65ad"]):
        return "ota_diagnosis_demo" if _explicit_demo_requested(raw) else "operation_diagnosis"
    if "roi" in text or _contains_any(raw, ["\u6295\u4ea7\u6bd4", "\u63a8\u5e7f\u503c\u4e0d\u503c", "\u5e7f\u544a\u6548\u679c", "\u63a8\u5e7f\u6548\u679c"]):
        return "roi_decision"
    if _contains_any(raw, ["\u8c03\u4ef7", "\u6536\u76ca"]) or legacy_price or "revenue" in text:
        return "revenue_decision_demo" if _explicit_demo_requested(raw) else "revenue_decision"
    if _contains_any(raw, ["\u63a8\u5e7f\u6267\u884c", "\u8c03\u6574\u51fa\u4ef7", "\u5173\u95ed\u5e7f\u544a", "\u6253\u5f00\u5e7f\u544a"]):
        return "promotion_suggestion"
    if _contains_any(raw, ["\u7b2c\u4e09\u65b9", "S14\u8bca\u65ad", "\u8fd0\u8425\u8bca\u65ad\u62a5\u544a", "OTA\u8bca\u65ad\u62a5\u544a", "\u8bca\u65ad\u62a5\u544a"]) or "html" in text or "ota report" in text:
        return "third_party_report_preview"
    if _contains_any(raw, ["\u7ecf\u9a8c"]) or "experience" in text:
        return "experience_candidates"
    return "menu"


def _priceable_product_platform(message: str) -> str | None:
    raw = message or ""
    matched = [
        platform
        for platform, terms in OTA_PRODUCT_PLATFORM_TERMS.items()
        if _contains_any(raw, list(terms))
    ]
    return matched[0] if len(matched) == 1 else None


S5_OTA_PRODUCT_ID_PATTERN = re.compile(r"(?:--ota-product-id\s+|(?:ota[_ -]?product[_ -]?id|商品ID)\s*[:：=]?\s*)([A-Za-z0-9_-]+)", re.IGNORECASE)
S6_TARGET_PRICE_PATTERN = re.compile(
    r"(?:--target-price\s+|(?:target[_ -]?price|listing[_ -]?price|"
    r"目标(?:挂牌)?价|挂牌价|OTA(?:挂牌)?价|执行价|售价|"
    r"调至|调到|降至|降到|升至|升到|涨至|涨到|改为|价格)"
    r"\s*[:：=]?\s*[¥￥]?\s*)(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
S6_NET_TARGET_PRICE_PATTERNS = (
    re.compile(r"(?:net[_ -]?revenue|\u51c0\u6536(?:\u9884\u4f30)?)(?:\u76ee\u6807(?:\u4ef7)?|\u4ef7\u683c)?\s*[:\uff1a=]\s*[\u00a5\uffe5]?(\d+(?:\.\d+)?)", re.IGNORECASE),
    re.compile(r"(?:net[_ -]?revenue|\u51c0\u6536(?:\u9884\u4f30)?)[^\n]{0,48}?(?:target|\u76ee\u6807(?:\u4ef7)?|\u8c03\u81f3|\u964d\u81f3|\u5347\u81f3|\u6539\u4e3a|\u5230)\s*[\u00a5\uffe5]?(\d+(?:\.\d+)?)", re.IGNORECASE),
)
S6_DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
S6_BATCH_ROOM_PRICE_CHANGE_PATTERN = re.compile(
    r"(?:每(?:个|间)房型|全部房型|所有房型|全部商品|所有商品)\s*"
    r"(?:的)?\s*(?:挂牌价|价格)?\s*(?:都|统一)?\s*"
    r"(?P<direction>下降|降低|降价|下调|上调|涨价|提高)\s*[¥￥]?\s*"
    r"(?P<amount>\d+(?:\.\d+)?)\s*元?",
    re.IGNORECASE,
)


def _s5_ota_product_id(message: str) -> str | None:
    matched = S5_OTA_PRODUCT_ID_PATTERN.search(message or "")
    if matched:
        return matched.group(1)
    parenthesized = re.search(r"[\(\uff08]\s*(\d{6,})\s*[\)\uff09]", message or "")
    return parenthesized.group(1) if parenthesized else None


def _s6_target_price(message: str) -> float | None:
    matched = S6_TARGET_PRICE_PATTERN.search(message or "")
    return float(matched.group(1)) if matched else None


def _whole_yuan(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _s6_batch_target_listing_price(current_price: float, *, direction: str, amount: float) -> float:
    """Apply a whole-yuan channel target without rejecting a batch request."""
    current = Decimal(str(current_price))
    delta = Decimal(str(amount))
    target = current - delta if direction == "decrease" else current + delta
    rounding = ROUND_FLOOR if direction == "decrease" else ROUND_CEILING
    return float(target.quantize(Decimal("1"), rounding=rounding))


def _s6_net_target_price(message: str) -> float | None:
    for pattern in S6_NET_TARGET_PRICE_PATTERNS:
        matched = pattern.search(message or "")
        if matched:
            return float(matched.group(1))
    return None


def _s6_target_stay_date(message: str, default: str) -> str:
    matched = S6_DATE_PATTERN.search(message or "")
    return matched.group(1) if matched else default


def _s6_batch_room_price_change(message: str) -> tuple[str, float] | None:
    """Return a listing-price delta for a controlled per-room-type request."""
    matched = S6_BATCH_ROOM_PRICE_CHANGE_PATTERN.search(message or "")
    if not matched:
        return None
    amount = float(matched.group("amount"))
    if not amount.is_integer() or amount <= 0:
        return None
    direction = matched.group("direction")
    return ("decrease" if direction in {"下降", "降低", "降价", "下调"} else "increase", amount)


def _query_s16_progress(*, hotel_id: str, target_stay_date: str, as_of_time: str | None, db_path: str | None) -> dict[str, Any]:
    return _capture_runtime_emit(
        deviation,
        argparse.Namespace(
            hotel_id=hotel_id,
            date=target_stay_date,
            as_of_time=as_of_time,
            db=db_path,
            use_generated_today=False,
            strict_generated_today=False,
        ),
    )


def _query_s15_baseline(*, hotel_id: str, target_stay_date: str, as_of_time: str | None, db_path: str | None) -> dict[str, Any]:
    # S15 is a historical baseline for the target date.  Its own 15-minute
    # cache is safe to reuse; S16 separately receives the live as-of time.
    return _capture_runtime_emit(
        baseline,
        argparse.Namespace(
            hotel_id=hotel_id,
            date=target_stay_date,
            as_of_time=None,
            db=db_path,
            force_rebuild=False,
        ),
    )


def _query_s16_after_s15(
    *,
    s15_result: dict[str, Any],
    hotel_id: str,
    target_stay_date: str,
    as_of_time: str | None,
    db_path: str | None,
) -> dict[str, Any]:
    # S15 and S16 are independent evidence inputs for S5.  S16 may still
    # return a useful live checkpoint result when the historical baseline is
    # unavailable, so do not short-circuit it here.
    del s15_result
    return _query_s16_progress(
        hotel_id=hotel_id,
        target_stay_date=target_stay_date,
        as_of_time=as_of_time,
        db_path=db_path,
    )


def _s6_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) == 1.0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


_S6_HOUR_ROOM_NAME_RE = re.compile(
    r"(?:\u949f\u70b9|\u5c0f\u65f6)\s*\u623f"
    r"|(?<!\d)(?:[1-9]|1[0-2])\s*(?:\u5c0f\u65f6|hour)",
    re.IGNORECASE,
)


def _s6_is_hour_room(row: dict[str, Any]) -> bool:
    if _s6_truthy(row.get("is_hour_room")):
        return True
    return bool(_S6_HOUR_ROOM_NAME_RE.search(str(row.get("ota_product_name") or "")))


def _s6_direct_product_snapshot(
    *, hotel_id: str, product_id: str, target_date: str, as_of_time: str | None, requested_channel: str | None
) -> dict[str, Any]:
    """Minimal S6 input: exact product observation plus its target-date availability."""
    # Price observation and PMS availability are independent reads. Starting
    # both together removes one database round trip from every manual S6 run.
    with ThreadPoolExecutor(max_workers=2) as executor:
        source_future = executor.submit(
            database_template_result,
            "ota_price_mapping",
            hotel_id,
            date=target_date,
            as_of_time=as_of_time,
            source_platform=requested_channel,
            ota_product_id=product_id,
        )
        operating_future = executor.submit(
            database_template_result,
            "operating_snapshot",
            hotel_id,
            date=target_date,
            as_of_time=as_of_time,
        )
        source = source_future.result()
        operating = operating_future.result()
    payload = source.get("payload") if isinstance(source.get("payload"), dict) else {}
    if source.get("status") != "ok" or payload.get("source_status") not in {None, "ok"}:
        return {"status": "data_gap", "blocked_reason": payload.get("source_status") or source.get("reason") or "ota_price_mapping_unavailable"}
    rows = payload.get("price_snapshots") or payload.get("rows") or []
    row = next((item for item in rows if isinstance(item, dict) and str(item.get("ota_product_id")) == product_id), None)
    if not row:
        return {"status": "data_gap", "blocked_reason": "requested_ota_product_not_observed"}
    channel = str(row.get("channel") or row.get("source_platform") or "").lower()
    if requested_channel and channel != requested_channel:
        return {"status": "blocked", "blocked_reason": "ota_product_channel_mismatch"}
    try:
        current_price = float(row.get("current_price") if row.get("current_price") is not None else row.get("ota_sale_price"))
    except (TypeError, ValueError):
        return {"status": "data_gap", "blocked_reason": "current_price_missing"}
    if row.get("price_editable_flag") is False or str(row.get("price_editable_flag") or "").strip().lower() in {"0", "false", "no", "n"}:
        return {"status": "blocked", "blocked_reason": "platform_price_not_editable"}
    name = str(row.get("ota_product_name") or "").lower()
    if _s6_is_hour_room(row):
        return {"status": "blocked", "blocked_reason": "hour_room_not_supported_for_s6"}
    if _s6_truthy(row.get("is_super_deal")) or "超级团购" in name or "super deal" in name:
        return {"status": "blocked", "blocked_reason": "super_deal_not_supported_for_s6"}
    if not row.get("mapping_id"):
        return {"status": "blocked", "blocked_reason": "pms_room_type_mapping_missing"}
    mapping = is_price_task_mapping_ready({**row, "source_platform": channel})
    if not mapping.get("ready_for_price_task"):
        return {"status": "blocked", "blocked_reason": mapping.get("blocked_reason") or "price_task_mapping_not_ready"}
    room_type_id = row.get("room_type_id")
    operating_payload = operating.get("payload") if isinstance(operating.get("payload"), dict) else {}
    rooms = operating_payload.get("room_type_forecasts") or []
    room = next((item for item in rooms if isinstance(item, dict) and str(item.get("room_type_id")) == str(room_type_id)), None)
    if not room:
        return {"status": "data_gap", "blocked_reason": "room_type_availability_unavailable"}
    try:
        if float(room.get("available_rooms")) <= 0:
            return {"status": "blocked", "blocked_reason": "room_type_sold_out_or_closed"}
    except (TypeError, ValueError):
        return {"status": "data_gap", "blocked_reason": "room_type_availability_unavailable"}
    snapshot_time = row.get("snapshot_time") or payload.get("data_snapshot_time")
    if not snapshot_time:
        return {"status": "data_gap", "blocked_reason": "price_observation_snapshot_missing"}
    return {
        "status": "ok",
        "candidate": {
            **row, "channel": channel, "current_price": current_price,
            "room_type_id": room_type_id, "room_type_name": row.get("room_type_name") or room.get("room_type_name"),
            "price_observation_snapshot_time": snapshot_time,
            "s6_task_mapping_ready": True, "s6_task_mapping_trust_basis": mapping.get("mapping_trust_basis"),
        },
    }


def _s6_reverse_net_target(
    *,
    candidate: dict[str, Any],
    hotel_id: str,
    target_date: str,
    as_of_time: str | None,
    target_net_revenue: float,
) -> dict[str, Any]:
    """Convert a requested Meituan net-revenue target to the listing price."""
    if str(candidate.get("channel") or "").lower() != "meituan":
        return {"status": "blocked", "blocked_reason": "net_revenue_target_channel_not_supported"}

    from runtime.s5_product_net_revenue_patch import (
        MEMBER_EXPECTED_FACTOR,
        apply_s5_product_net_revenue,
    )

    # The two activity reads have no dependency on each other. Running them in
    # parallel removes one remote database round trip from an explicit S6
    # net-target preview while keeping the exact same fresh-data checks.
    with ThreadPoolExecutor(max_workers=2) as executor:
        summary_future = executor.submit(
            database_template_result,
            "ota_activity_summary",
            hotel_id,
            as_of_time=as_of_time,
        )
        detail_future = executor.submit(
            database_template_result,
            "ota_activity_product_detail",
            hotel_id,
            as_of_time=as_of_time,
        )
        summary = summary_future.result()
        detail = detail_future.result()
    enriched = apply_s5_product_net_revenue(
        {"candidates": [dict(candidate)], "target_stay_date": target_date, "as_of_time": as_of_time},
        price_result={"status": "ok", "payload": {"source_status": "ok", "price_snapshots": [candidate]}},
        activity_summary_result=summary,
        activity_detail_result=detail,
    )
    product = (enriched.get("candidates") or [{}])[0]
    if product.get("s5_net_revenue_calculation_status") != "ok":
        return {
            "status": "data_gap",
            "blocked_reason": "net_revenue_conversion_unavailable",
            "reason": product.get("s5_net_revenue_calculation_reason"),
        }
    try:
        commission = float(product["commission_rate"])
        activity_factor = float(product["combined_activity_factor"])
        member_factor = float(product.get("member_expected_factor") or MEMBER_EXPECTED_FACTOR)
        multiplier = (1.0 - commission) * activity_factor * member_factor
        current_net_revenue = float(product["estimated_hotel_revenue"])
        current_listing_price = float(product["current_price"])
        if multiplier <= 0 or current_net_revenue <= 0 or current_listing_price <= 0:
            raise ValueError("invalid multiplier")
        net_change_ratio = float(target_net_revenue) / current_net_revenue
        # With fixed commission/activity/member factors, the net-revenue and
        # listing-price changes must have the same ratio. Use that ratio on the
        # current listing price, then recheck the complete net formula below.
        execution_price = _whole_yuan(current_listing_price * net_change_ratio)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return {"status": "data_gap", "blocked_reason": "net_revenue_conversion_unavailable"}
    return {
        "status": "ok",
        "candidate": product,
        "execution_price": execution_price,
        "requested_net_revenue_target": float(target_net_revenue),
        "net_revenue_target": round(execution_price * multiplier, 2),
        "net_revenue_current": current_net_revenue,
        "net_revenue_multiplier": multiplier,
        "member_expected_factor": member_factor,
        "net_revenue_change_pct": net_change_ratio - 1.0,
        "net_revenue_after_conversion": round(execution_price * multiplier, 2),
    }


def _s6_listing_net_preview(
    *,
    candidate: dict[str, Any],
    hotel_id: str,
    target_date: str,
    as_of_time: str | None,
    execution_price: float,
) -> dict[str, Any]:
    """Calculate S6's informational net-revenue preview for a listing target."""
    from runtime.s5_product_net_revenue_patch import apply_s5_product_net_revenue

    cache_key = (hotel_id, target_date, str(as_of_time or "")[:16])
    cached = _S6_NET_PREVIEW_ACTIVITY_CACHE.get(cache_key)
    if cached and time.monotonic() - cached[0] <= _S6_NET_PREVIEW_CACHE_TTL_SECONDS:
        summary, detail = cached[1], cached[2]
    else:
        with ThreadPoolExecutor(max_workers=2) as executor:
            summary_future = executor.submit(
                database_template_result,
                "ota_activity_summary",
                hotel_id,
                as_of_time=as_of_time,
            )
            detail_future = executor.submit(
                database_template_result,
                "ota_activity_product_detail",
                hotel_id,
                as_of_time=as_of_time,
            )
            summary = summary_future.result()
            detail = detail_future.result()
        _S6_NET_PREVIEW_ACTIVITY_CACHE[cache_key] = (
            time.monotonic(),
            summary,
            detail,
        )
    enriched = apply_s5_product_net_revenue(
        {"candidates": [dict(candidate)], "target_stay_date": target_date, "as_of_time": as_of_time},
        price_result={"status": "ok", "payload": {"source_status": "ok", "price_snapshots": [candidate]}},
        activity_summary_result=summary,
        activity_detail_result=detail,
    )
    product = (enriched.get("candidates") or [{}])[0]
    if product.get("s5_net_revenue_calculation_status") != "ok":
        return {
            "status": "unavailable",
            "candidate": product,
            "reason": product.get("s5_net_revenue_calculation_reason"),
        }
    try:
        multiplier = (
            (1.0 - float(product["commission_rate"]))
            * float(product["combined_activity_factor"])
            * float(product["member_expected_factor"])
        )
        current = float(product["estimated_hotel_revenue"])
        if multiplier <= 0 or current <= 0:
            raise ValueError("invalid multiplier")
    except (KeyError, TypeError, ValueError):
        return {"status": "unavailable", "candidate": product, "reason": "net_revenue_conversion_unavailable"}
    return {
        "status": "ok",
        "candidate": product,
        "net_revenue_current": current,
        "net_revenue_target": round(float(execution_price) * multiplier, 2),
        "net_revenue_multiplier": multiplier,
    }


def _build_s6_real_dry_run(
    *,
    message: str,
    hotel_id: str,
    db_path: str | None,
    as_of_time: str | None,
    auth_config: str | None,
    chat_id: str | None,
    chat_type: str | None,
    user_id: str | None,
    open_id: str | None,
    union_id: str | None,
    role: str,
    requester_id: str | None = None,
    product_id_override: str | None = None,
    target_price_override: float | None = None,
    create_confirmation_token: bool = True,
    candidate_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Produce an S6 preview from the selected real OTA product without writing a task."""
    product_id = product_id_override or _s5_ota_product_id(message)
    target_date = _s6_target_stay_date(message, (as_of_time or now_local())[:10])
    base = {
        "intent": "price_execution_dry_run",
        "skill_id": "S6",
        "node_id": "N016",
        "runtime_command": "s6-price-dry-run --real-product",
        "data_source_type": "mysql_db",
        "live_allowed": False,
    }
    if not product_id:
        return {
            **base,
            "status": "blocked",
            "blocked_reason": "price_task_requires_ota_product_id",
            "next_required_action": "provide_ota_product_id",
            "target_stay_date": target_date,
        }

    if candidate_override is not None:
        candidate = dict(candidate_override)
    else:
        direct = _s6_direct_product_snapshot(
            hotel_id=hotel_id, product_id=product_id, target_date=target_date, as_of_time=as_of_time,
            requested_channel=_priceable_product_platform(message),
        )
        candidate = direct.get("candidate")
        if not isinstance(candidate, dict):
            return {**base, "status": direct.get("status") or "data_gap", "blocked_reason": direct.get("blocked_reason") or "requested_ota_product_not_observed"}

    net_target = _s6_net_target_price(message)
    net_conversion: dict[str, Any] | None = None
    if net_target is not None:
        net_conversion = _s6_reverse_net_target(
            candidate=candidate,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_time=as_of_time,
            target_net_revenue=net_target,
        )
        if net_conversion.get("status") != "ok":
            return {
                **base,
                "status": net_conversion.get("status") or "data_gap",
                "blocked_reason": net_conversion.get("blocked_reason") or "net_revenue_conversion_unavailable",
                "selected_product": candidate,
            }
        candidate = dict(net_conversion["candidate"])
        target_price = float(net_conversion["execution_price"])
    else:
        target_price = target_price_override if target_price_override is not None else _s6_target_price(message)
    if target_price is None:
        return {
            **base,
            "status": "data_gap",
            "blocked_reason": "target_price_required_for_direct_s6",
            "selected_product": candidate,
        }
    if not float(target_price).is_integer():
        return {
            **base,
            "status": "blocked",
            "blocked_reason": "target_listing_price_must_be_whole_yuan",
            "selected_product": candidate,
            "target_stay_date": target_date,
        }
    target_price = float(target_price)
    listing_net_preview: dict[str, Any] | None = None
    if net_conversion is None:
        listing_net_preview = _s6_listing_net_preview(
            candidate=candidate,
            hotel_id=hotel_id,
            target_date=target_date,
            as_of_time=as_of_time,
            execution_price=target_price,
        )
        if isinstance(listing_net_preview.get("candidate"), dict):
            candidate = dict(listing_net_preview["candidate"])

    preview = _capture_runtime_emit(
        execute_price,
        argparse.Namespace(
            db=db_path or ":memory:", hotel_id=hotel_id,
            room_type_id=candidate.get("room_type_id"), room_type_name=candidate.get("room_type_name"),
            hotel_name=candidate.get("hotel_name") or candidate.get("hotel_display_name"),
            channel=candidate.get("channel"), channel_source=candidate.get("channel"),
            ota_product_id=product_id, normal_price=target_price, weekend_price=None,
            begin_date=target_date, end_date=target_date, business_date=target_date,
            approved_by=None, approval_id=None, approver_role=None, old_price=candidate.get("current_price"),
            floor_price=None, ceiling_price=None, activity_discount_factors=None, pms_price=None,
            dry_run=True, no_log=True, timeout=20, auth_source="feishu", user_id=user_id,
            open_id=open_id, union_id=union_id, chat_id=chat_id, chat_type=chat_type,
            user_role=role, auth_config=auth_config, requested_by=None,
            source_decision_id=(candidate.get("decision_ref") or {}).get("decision_id"),
        ),
    )
    result = {
        **preview,
        **base,
        "runtime_command": "s6-price-dry-run --real-product",
        "data_source_type": "mysql_db",
        "business_date": target_date,
        "execution_price": target_price,
        "floor_price": candidate.get("floor_price"),
        "ceiling_price": candidate.get("ceiling_price"),
        "channel_source": candidate.get("channel"),
        "ota_product_id": product_id,
        "ota_product_name": candidate.get("ota_product_name"),
        "freshness_status": candidate.get("price_observation_snapshot_time") and "fresh" or "not_available",
        "approval_data_allowed": True,
        "selected_product": candidate,
        "upstream_decision_ref": None,
        "s5_candidate_generated_now": False,
        "not_bound_to_s5_decision": True,
        "direct_product_validation": True,
        "input_price_mode": "net_revenue_target" if net_conversion else "listing_price_target",
        "target_stay_date": target_date,
        "formal_approval_created": False,
        "live_execution_count": 0,
    }
    if net_conversion:
        result.update(net_conversion)
    elif listing_net_preview and listing_net_preview.get("status") == "ok":
        result.update(
            {
                "net_revenue_current": listing_net_preview["net_revenue_current"],
                "net_revenue_target": listing_net_preview["net_revenue_target"],
                "net_revenue_multiplier": listing_net_preview["net_revenue_multiplier"],
                "net_revenue_preview_status": "ok",
            }
        )
    elif listing_net_preview:
        result["net_revenue_preview_status"] = "unavailable"
        result["net_revenue_preview_reason"] = listing_net_preview.get("reason")
    try:
        actual_change_pct = (float(target_price) / float(candidate["current_price"])) - 1.0
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        actual_change_pct = None
    cap = S6_SINGLE_CHANGE_HARD_CAP
    within_single_change_cap = actual_change_pct is not None and abs(actual_change_pct) <= cap
    confirmation_db_path = _s6_confirmation_db_path(db_path)
    if create_confirmation_token and result.get("status") == "dry_run" and result.get("freshness_status") == "fresh" and within_single_change_cap:
        trusted_hotel_name = _trusted_s6_hotel_name(confirmation_db_path, hotel_id)
        if not trusted_hotel_name:
            result["confirmation_unavailable_reason"] = "trusted_hotel_name_unavailable"
            return result
        confirmation = create_confirmation(
            confirmation_db_path,
            hotel_id=hotel_id,
            chat_id=chat_id,
            requester_id=requester_id or open_id or user_id or union_id,
            payload={
                "requester_id": requester_id or open_id or user_id or union_id,
                "hotel_name": trusted_hotel_name,
                "room_type_id": candidate.get("room_type_id"), "room_type_name": candidate.get("room_type_name"),
                "channel": candidate.get("channel"), "ota_product_id": product_id,
                "ota_product_name": candidate.get("ota_product_name"), "old_price": candidate.get("current_price"),
                "target_price": target_price, "target_stay_date": target_date,
                "input_price_mode": result["input_price_mode"],
                "net_revenue_target": result.get("net_revenue_target"),
                "net_revenue_current": result.get("net_revenue_current"),
                "net_revenue_multiplier": result.get("net_revenue_multiplier"),
                "data_snapshot_time": candidate.get("price_observation_snapshot_time"),
                "preview_guard_policy": result.get("price_guard_policy"),
                "source_decision_id": f"S6D-{uuid.uuid4().hex[:16].upper()}",
            },
        )
        if confirmation.get("status") == "pending":
            result.update({
                "confirmation_id": confirmation["confirmation_id"], "confirmation_expires_at": confirmation["expires_at"],
                "confirmation_command": f"确认调价 {confirmation['confirmation_id']}",
            })
        else:
            result["confirmation_unavailable_reason"] = confirmation.get("reason")
    elif create_confirmation_token and result.get("freshness_status") == "fresh":
        reason = str(result.get("blocked_reason") or result.get("reason") or "s6_preview_not_confirmable")
        if actual_change_pct is not None and actual_change_pct > cap:
            reason = "s6_single_change_increase_limit_exceeded"
        elif actual_change_pct is not None and actual_change_pct < -cap:
            reason = "s6_single_change_decrease_limit_exceeded"
        rejection = {
            "reason": reason,
            "current_price": candidate.get("current_price"),
            "target_price": target_price,
            "actual_change_pct": actual_change_pct,
            "max_increase_pct": cap,
            "max_decrease_pct": cap,
            "net_revenue_current": result.get("net_revenue_current"),
            "net_revenue_target": result.get("net_revenue_target"),
        }
        result["confirmation_blocked_reason"] = reason
        result["confirmation_blocked_details"] = rejection
        if reason.startswith("s6_single_change_"):
            result["preview_validation_status"] = result.get("status")
            result["status"] = "dry_run"
        record_rejected_preview(
            confirmation_db_path,
            hotel_id=hotel_id,
            chat_id=chat_id,
            requester_id=requester_id or open_id or user_id or union_id,
            payload=rejection,
        )
    return result


def _s6_batch_standard_products(
    *, hotel_id: str, target_date: str, as_of_time: str | None, requested_channel: str | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Select every safe, distinct full-day OTA product for batch preview."""
    with ThreadPoolExecutor(max_workers=2) as executor:
        source_future = executor.submit(
            database_template_result, "ota_price_mapping", hotel_id, date=target_date,
            as_of_time=as_of_time, source_platform=requested_channel,
        )
        operating_future = executor.submit(
            database_template_result, "operating_snapshot", hotel_id, date=target_date, as_of_time=as_of_time,
        )
        source = source_future.result()
        operating = operating_future.result()
    payload = source.get("payload") if isinstance(source.get("payload"), dict) else {}
    if source.get("status") != "ok" or payload.get("source_status") not in {None, "ok"}:
        return [], [payload.get("source_status") or source.get("reason") or "ota_price_mapping_unavailable"]
    operating_payload = operating.get("payload") if isinstance(operating.get("payload"), dict) else {}
    rooms = {
        str(room.get("room_type_id")): room
        for room in operating_payload.get("room_type_forecasts") or []
        if isinstance(room, dict) and room.get("room_type_id") is not None
    }
    selected_by_product: dict[str, dict[str, Any]] = {}
    excluded: list[str] = []
    for row in payload.get("price_snapshots") or payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        product_id = str(row.get("ota_product_id") or "").strip()
        room_type_id = str(row.get("room_type_id") or "").strip()
        if not product_id or not room_type_id:
            excluded.append("product_or_room_type_missing")
            continue
        channel = str(row.get("channel") or row.get("source_platform") or "").lower()
        if requested_channel and channel != requested_channel:
            continue
        name = str(row.get("ota_product_name") or "").lower()
        if _s6_is_hour_room(row):
            excluded.append("hour_room")
            continue
        if _s6_truthy(row.get("is_super_deal")) or "超级团购" in name or "super deal" in name:
            excluded.append("super_deal")
            continue
        if row.get("price_editable_flag") is False or str(row.get("price_editable_flag") or "").lower() in {"0", "false", "no", "n"}:
            excluded.append("not_editable")
            continue
        # A room_type_id carried by the OTA row is not proof of a PMS mapping.
        # S6 writes must be backed by an exact mapping-table record.
        if not row.get("mapping_id"):
            excluded.append("pms_room_type_mapping_missing")
            continue
        mapping = is_price_task_mapping_ready({**row, "source_platform": channel})
        if not mapping.get("ready_for_price_task"):
            excluded.append("mapping_not_ready")
            continue
        try:
            current_price = float(row.get("current_price") if row.get("current_price") is not None else row.get("ota_sale_price"))
            if float((rooms.get(room_type_id) or {}).get("available_rooms")) <= 0:
                excluded.append("no_available_rooms")
                continue
        except (TypeError, ValueError):
            excluded.append("price_or_inventory_missing")
            continue
        snapshot_time = row.get("snapshot_time") or payload.get("data_snapshot_time")
        if not snapshot_time:
            excluded.append("price_snapshot_missing")
            continue
        room = rooms.get(room_type_id) or {}
        selected_by_product[product_id] = {
            **row, "channel": channel, "current_price": current_price,
            "room_type_name": row.get("room_type_name") or room.get("room_type_name"),
            "price_observation_snapshot_time": snapshot_time,
            "s6_task_mapping_ready": True, "s6_task_mapping_trust_basis": mapping.get("mapping_trust_basis"),
        }
    return list(selected_by_product.values()), excluded


def _build_s6_batch_dry_run(
    *, message: str, hotel_id: str, db_path: str | None, as_of_time: str | None, auth_config: str | None,
    chat_id: str | None, chat_type: str | None, user_id: str | None, open_id: str | None, union_id: str | None,
    role: str, requester_id: str | None = None,
) -> dict[str, Any]:
    """Preview a fixed listing-price change for every eligible OTA product."""
    change = _s6_batch_room_price_change(message)
    target_date = _s6_target_stay_date(message, (as_of_time or now_local())[:10])
    base = {
        "intent": "price_execution_dry_run", "skill_id": "S6", "node_id": "N016",
        "runtime_command": "s6-price-dry-run --real-product", "data_source_type": "mysql_db",
        "live_allowed": False, "batch_dry_run": True, "business_date": target_date,
    }
    if change is None:
        return {**base, "status": "blocked", "blocked_reason": "batch_listing_price_change_must_be_whole_yuan"}
    direction, amount = change
    products, excluded = _s6_batch_standard_products(
        hotel_id=hotel_id, target_date=target_date, as_of_time=as_of_time,
        requested_channel=_priceable_product_platform(message),
    )
    if not products:
        return {
            **base,
            "status": "data_gap",
            "blocked_reason": "no_eligible_standard_ota_products",
            "excluded_product_reasons": excluded,
        }
    first_target = _s6_batch_target_listing_price(
        float(products[0]["current_price"]), direction=direction, amount=amount
    )
    # Prime the shared 30-second activity cache before worker threads start.
    # Without this, every worker can observe the empty cache and duplicate the
    # same two activity reads.
    _s6_listing_net_preview(
        candidate=products[0], hotel_id=hotel_id, target_date=target_date, as_of_time=as_of_time,
        execution_price=first_target,
    )

    def preview(row: dict[str, Any]) -> dict[str, Any]:
        try:
            current = float(row.get("current_price") if row.get("current_price") is not None else row.get("ota_sale_price"))
            target = _s6_batch_target_listing_price(current, direction=direction, amount=amount)
        except (TypeError, ValueError):
            return {"status": "data_gap", "blocked_reason": "current_price_missing", "selected_product": row}
        if target <= 0:
            return {"status": "blocked", "blocked_reason": "target_listing_price_must_be_positive", "selected_product": row}
        return _build_s6_real_dry_run(
            message=message, hotel_id=hotel_id, db_path=db_path, as_of_time=as_of_time, auth_config=auth_config,
            chat_id=chat_id, chat_type=chat_type, user_id=user_id, open_id=open_id, union_id=union_id, role=role,
            requester_id=requester_id, product_id_override=str(row["ota_product_id"]), target_price_override=target,
            create_confirmation_token=False, candidate_override=row,
        )

    with ThreadPoolExecutor(max_workers=min(8, len(products))) as executor:
        previews = list(executor.map(preview, products))
    snapshot_times = sorted(
        {
            str((item.get("selected_product") or {}).get("price_observation_snapshot_time") or "")
            for item in previews
        }
        - {""}
    )
    confirmable_items = [
        item
        for item in previews
        if item.get("status") == "dry_run" and not item.get("confirmation_blocked_reason")
    ]
    result: dict[str, Any] = {
        **base, "status": "dry_run", "batch_direction": direction, "batch_change_amount": amount,
        "batch_items": previews, "excluded_products": excluded, "eligible_product_count": len(previews),
        "confirmable_product_count": len(confirmable_items),
        "freshness_status": "fresh" if snapshot_times else "not_available",
        "business_status": "current",
        "data_business_date": target_date,
        "data_snapshot_time": snapshot_times[-1] if snapshot_times else None,
        "blocked_reason": "dry_run_preview_only",
        "approval_data_allowed": True,
        "formal_approval_allowed": False,
        "live_allowed": False,
    }
    if not confirmable_items:
        result["confirmation_blocked_reason"] = "batch_has_no_confirmable_products"
        return result
    trusted_hotel_name = _trusted_s6_hotel_name(_s6_confirmation_db_path(db_path), hotel_id)
    if not trusted_hotel_name:
        result["confirmation_unavailable_reason"] = "trusted_hotel_name_unavailable"
        return result
    requester = requester_id or open_id or user_id or union_id
    items = []
    for item in confirmable_items:
        product = item.get("selected_product") or {}
        items.append({
            "requester_id": requester, "hotel_name": trusted_hotel_name,
            "room_type_id": product.get("room_type_id"), "room_type_name": product.get("room_type_name"),
            "channel": product.get("channel"), "ota_product_id": product.get("ota_product_id"),
            "ota_product_name": product.get("ota_product_name"), "old_price": product.get("current_price"),
            "target_price": item.get("execution_price"), "target_stay_date": target_date,
            "input_price_mode": "listing_price_target", "net_revenue_target": item.get("net_revenue_target"),
            "net_revenue_current": item.get("net_revenue_current"), "net_revenue_multiplier": item.get("net_revenue_multiplier"),
            "data_snapshot_time": product.get("price_observation_snapshot_time"),
            "preview_guard_policy": item.get("price_guard_policy"),
            "source_decision_id": f"S6B-{uuid.uuid4().hex[:16].upper()}",
        })
    confirmation = create_confirmation(
        _s6_confirmation_db_path(db_path), hotel_id=hotel_id, chat_id=chat_id, requester_id=requester,
        payload={"requester_id": requester, "batch_items": items, "batch_direction": direction, "batch_change_amount": amount},
    )
    if confirmation.get("status") == "pending":
        result.update({
            "confirmation_id": confirmation["confirmation_id"], "confirmation_expires_at": confirmation["expires_at"],
            "confirmation_command": f"确认调价 {confirmation['confirmation_id']}",
        })
    else:
        result["confirmation_unavailable_reason"] = confirmation.get("reason")
    return result


_EMIT_CAPTURE_LOCK = threading.Lock()


def _capture_runtime_emit(func: Any, namespace: argparse.Namespace) -> dict[str, Any]:
    buffer = io.StringIO()
    # redirect_stdout mutates the global sys.stdout and is NOT thread-safe.
    # _build_s6_batch_dry_run calls this concurrently via ThreadPoolExecutor,
    # so serialize captures to keep execute_price JSON from leaking into the
    # runtime's own stdout (which corrupts the CLI/plugin JSON envelope).
    with _EMIT_CAPTURE_LOCK:
        with contextlib.redirect_stdout(buffer):
            func(namespace)
    output = buffer.getvalue().strip()
    if not output:
        return {"status": "error", "message": "runtime_command_returned_empty_output"}
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        return {"status": "error", "message": f"runtime_command_returned_invalid_json:{exc.msg}"}


def _s6_confirmation_token(message: str) -> str | None:
    matched = re.search(r"\b(PRC-[A-Za-z0-9]+)\b", message or "", re.IGNORECASE)
    return matched.group(1).upper() if matched else None


def _s6_confirmation_db_path(db_path: str | None) -> str | None:
    """Use the same SQLite control plane for preview tokens and later confirmation."""
    return db_path or os.environ.get("HOTEL_OTA_DB")


def _trusted_s6_hotel_name(db_path: str | None, hotel_id: str) -> str | None:
    """Return a task label; trusted ``hotel_id`` remains the tenant boundary."""
    if not hotel_id:
        return None
    row = None
    if db_path:
        try:
            with connect(db_path) as conn:
                init_schema(conn)
                row = conn.execute(
                    "SELECT name FROM hotels WHERE hotel_id=? LIMIT 1",
                    (str(hotel_id),),
                ).fetchone()
        except (OSError, sqlite3.Error):
            pass
    name = str(row["name"] or "").strip() if row else ""
    return name if name and not re.search(r"(?:\bdemo\b|演示)", name, re.IGNORECASE) else str(hotel_id)


def _create_s5_candidate_confirmations(
    result: dict[str, Any],
    *,
    hotel_id: str,
    db_path: str | None,
    chat_id: str | None,
    requester_id: str | None,
) -> None:
    """Create short-lived S6 confirmations only for executable S5 recommendations."""
    if result.get("freshness_status") != "fresh":
        return
    confirmation_db_path = _s6_confirmation_db_path(db_path)
    trusted_hotel_name = _trusted_s6_hotel_name(confirmation_db_path, hotel_id)
    created_count = 0
    for candidate in result.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        if (
            candidate.get("eligibility") != "eligible_for_s6_dry_run"
            or not candidate.get("auto_execution_eligible")
            or not candidate.get("s6_task_mapping_ready")
        ):
            continue
        try:
            old_price = float(candidate["current_price"])
            target_price = float(candidate["execution_price"])
            change_pct = (target_price / old_price) - 1.0
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        if abs(change_pct) > S6_SINGLE_CHANGE_HARD_CAP:
            continue
        product_id = str(candidate.get("ota_product_id") or "").strip()
        room_type_id = str(candidate.get("room_type_id") or "").strip()
        channel = str(candidate.get("channel") or "").strip()
        snapshot_time = candidate.get("price_observation_snapshot_time") or result.get("data_snapshot_time")
        if not product_id or not room_type_id or not channel or not snapshot_time:
            continue
        if not trusted_hotel_name:
            candidate["s6_confirmation_unavailable_reason"] = "trusted_hotel_name_unavailable"
            continue
        confirmation = create_confirmation(
            confirmation_db_path,
            hotel_id=hotel_id,
            chat_id=chat_id,
            requester_id=requester_id,
            payload={
                "requester_id": requester_id,
                "hotel_name": trusted_hotel_name,
                "room_type_id": room_type_id,
                "room_type_name": candidate.get("room_type_name"),
                "channel": channel,
                "ota_product_id": product_id,
                "ota_product_name": candidate.get("ota_product_name"),
                "old_price": old_price,
                "target_price": target_price,
                "target_stay_date": candidate.get("target_stay_date") or result.get("target_stay_date"),
                "input_price_mode": "s5_recommendation",
                "net_revenue_current": candidate.get("estimated_hotel_revenue"),
                "net_revenue_target": candidate.get("proposed_estimated_hotel_revenue"),
                "data_snapshot_time": snapshot_time,
                "preview_guard_policy": {
                    "policy_id": candidate.get("price_guard_policy_id"),
                    "version": candidate.get("price_guard_policy_version"),
                    "source": candidate.get("price_guard_source"),
                    "max_increase_pct": candidate.get("max_increase_pct"),
                    "max_decrease_pct": candidate.get("max_decrease_pct"),
                    "min_increase_pct": candidate.get("min_increase_pct"),
                    "min_decrease_pct": candidate.get("min_decrease_pct"),
                },
                "source_decision_id": (candidate.get("decision_ref") or {}).get("decision_id"),
            },
        )
        if confirmation.get("status") == "pending":
            candidate.update(
                {
                    "s6_confirmation_id": confirmation["confirmation_id"],
                    "s6_confirmation_command": f"确认调价 {confirmation['confirmation_id']}",
                    "s6_confirmation_expires_at": confirmation["expires_at"],
                }
            )
            created_count += 1
        else:
            candidate["s6_confirmation_unavailable_reason"] = confirmation.get("reason")
    result["s6_confirmation_ready_count"] = created_count


def _s6_current_price_matches(*, hotel_id: str, payload: dict[str, Any]) -> bool:
    """Fast price-only check kept separate from the full product safety recheck."""
    source = database_template_result("ota_price_mapping", hotel_id, source_platform=payload.get("channel"))
    rows = ((source.get("payload") or {}).get("price_snapshots") or (source.get("payload") or {}).get("rows") or [])
    for row in rows:
        if str(row.get("ota_product_id")) != str(payload.get("ota_product_id")):
            continue
        try:
            value = row.get("current_price") if row.get("current_price") is not None else row.get("ota_sale_price")
            return abs(float(value) - float(payload["old_price"])) < 0.005
        except (TypeError, ValueError):
            return False
    return False


def _write_s6_batch_confirmation_fast(
    *, confirmation_id: str, payload: dict[str, Any], hotel_id: str, db_path: str | None,
    auth_context: dict[str, Any], auth_config: str | None, chat_id: str | None, chat_type: str | None,
    user_id: str | None, open_id: str | None, union_id: str | None,
) -> dict[str, Any]:
    """Write the immutable, prevalidated batch preview as independent outbox tasks."""
    confirmation_db_path = _s6_confirmation_db_path(db_path)
    items = [item for item in payload.get("batch_items") or [] if isinstance(item, dict)]
    if not items:
        finish_confirmation(confirmation_db_path, confirmation_id, completed=False)
        return {"status": "blocked", "intent": "price_execution_confirm", "skill_id": "S6", "node_id": "N016", "blocked_reason": "batch_items_missing"}

    for item in items:
        if not isinstance(item.get("preview_guard_policy"), dict):
            finish_confirmation(confirmation_db_path, confirmation_id, completed=False)
            return {
                "status": "blocked", "intent": "price_execution_confirm", "skill_id": "S6", "node_id": "N016",
                "blocked_reason": "preview_guard_evidence_missing",
                "confirmation_id": confirmation_id,
            }
    outcomes = []
    for item in items:
        child = create_confirmation(
            confirmation_db_path, hotel_id=hotel_id, chat_id=chat_id,
            requester_id=payload.get("requester_id"), payload=item,
        )
        if child.get("status") != "pending":
            outcomes.append({"status": "blocked", "reason": child.get("reason")})
            break
        outcome = _write_s6_confirmation_fast(
            message=f"确认调价 {child['confirmation_id']}", hotel_id=hotel_id, db_path=db_path,
            auth_context=auth_context, auth_config=auth_config, chat_id=chat_id, chat_type=chat_type,
            user_id=user_id, open_id=open_id, union_id=union_id,
        )
        outcomes.append(outcome)
        if outcome.get("status") != "queued":
            break
    queued_count = sum(1 for outcome in outcomes if outcome.get("status") == "queued")
    completed = queued_count == len(items)
    # Once any outbox task is created, do not leave the batch token reusable.
    finish_confirmation(confirmation_db_path, confirmation_id, completed=completed or queued_count > 0)
    if completed:
        return {
            "status": "queued", "execute_status": "PENDING", "intent": "price_task_outbox_write", "skill_id": "S6", "node_id": "N016",
            "confirmation_id": confirmation_id, "batch_write": True, "task_count": queued_count,
            "plugin_waited": False,
        }
    return {
        "status": "blocked", "intent": "price_task_outbox_write", "skill_id": "S6", "node_id": "N016",
        "blocked_reason": "batch_task_write_incomplete", "confirmation_id": confirmation_id,
        "queued_count": queued_count, "task_count": len(items), "plugin_waited": False,
    }


def _write_s6_confirmation_fast(
    *, message: str, hotel_id: str, db_path: str | None, auth_context: dict[str, Any], auth_config: str | None,
    chat_id: str | None, chat_type: str | None, user_id: str | None, open_id: str | None, union_id: str | None,
) -> dict[str, Any]:
    """Confirm a stored preview and return as soon as the outbox reports PENDING."""
    actor = auth_context.get("principal_id")
    confirmation_db_path = _s6_confirmation_db_path(db_path)
    claimed = claim_confirmation(
        confirmation_db_path, confirmation_id=_s6_confirmation_token(message), hotel_id=hotel_id, chat_id=chat_id, actor_id=actor
    )
    if claimed.get("status") != "claimed":
        return {"intent": "price_execution_confirm", "skill_id": "S6", "node_id": "N016", **claimed}
    confirmation_id = str(claimed["confirmation_id"])
    payload = claimed["payload"]
    if isinstance(payload.get("batch_items"), list):
        return _write_s6_batch_confirmation_fast(
            confirmation_id=confirmation_id, payload=payload, hotel_id=hotel_id, db_path=db_path,
            auth_context=auth_context, auth_config=auth_config, chat_id=chat_id, chat_type=chat_type,
            user_id=user_id, open_id=open_id, union_id=union_id,
        )
    trusted_hotel_name = _trusted_s6_hotel_name(confirmation_db_path, hotel_id)
    if not trusted_hotel_name:
        finish_confirmation(confirmation_db_path, confirmation_id, completed=False)
        return {
            "status": "blocked", "intent": "price_execution_confirm", "skill_id": "S6", "node_id": "N016",
            "blocked_reason": "trusted_hotel_name_unavailable", "confirmation_id": confirmation_id,
        }
    preview_policy = payload.get("preview_guard_policy")
    if not isinstance(preview_policy, dict):
        finish_confirmation(confirmation_db_path, confirmation_id, completed=False)
        return {
            "status": "blocked", "intent": "price_execution_confirm", "skill_id": "S6", "node_id": "N016",
            "blocked_reason": "preview_guard_evidence_missing", "confirmation_id": confirmation_id,
        }
    execution_payload = price_execution_payload(
        hotel_id=hotel_id, room_type_id=payload["room_type_id"], channel=payload["channel"],
        ota_product_id=payload["ota_product_id"], normal_price=payload["target_price"], old_price=payload["old_price"],
        price_guard_policy_id=preview_policy.get("policy_id"), begin_date=payload["target_stay_date"], end_date=payload["target_stay_date"],
        max_increase_pct=preview_policy.get("max_increase_pct"), max_decrease_pct=preview_policy.get("max_decrease_pct"),
        min_increase_pct=preview_policy.get("min_increase_pct"), min_decrease_pct=preview_policy.get("min_decrease_pct"),
        freshness_status="fresh", guard_version=preview_policy.get("version"),
    )
    approval_payload = {
        **execution_payload, "approved_payload_hash": price_execution_payload_hash(execution_payload),
        "price_guard_policy_version": preview_policy.get("version"),
        "dry_run_summary": f"S6 preview {payload['old_price']}->{payload['target_price']}",
        "data_business_date": payload["target_stay_date"], "data_snapshot_time": payload["data_snapshot_time"],
        "freshness_status": "fresh", "business_status": "current", "data_source_type": "mysql_db",
        "prevalidated_preview": True,
    }
    validity = validate_approval_payload(approval_payload, "price_update")
    if not validity.get("allowed"):
        finish_confirmation(confirmation_db_path, confirmation_id, completed=False)
        return {"status": "blocked", "intent": "price_execution_confirm", "skill_id": "S6", "node_id": "N016", "blocked_reason": validity["reason"]}
    approval_id = f"appr-{uuid.uuid4().hex[:20]}"
    with connect(confirmation_db_path or ":memory:") as conn:
        init_schema(conn)
        timestamp = now_local()
        conn.execute(
            "INSERT INTO approvals (approval_id, hotel_id, action_type, status, requested_by, approved_by, payload_json, created_at, updated_at) VALUES (?, ?, 'price_update', 'approved', ?, ?, ?, ?, ?)",
            (approval_id, hotel_id, payload.get("requester_id"), actor, json.dumps(approval_payload, ensure_ascii=False), timestamp, timestamp),
        )
    outcome = _capture_runtime_emit(
        execute_price,
        argparse.Namespace(
            db=confirmation_db_path, hotel_id=hotel_id, room_type_id=payload["room_type_id"], room_type_name=payload.get("room_type_name"),
            hotel_name=trusted_hotel_name, channel=payload["channel"], channel_source=payload["channel"],
            ota_product_id=payload["ota_product_id"], ota_product_name=payload.get("ota_product_name"),
            normal_price=payload["target_price"], weekend_price=None, begin_date=payload["target_stay_date"], end_date=payload["target_stay_date"],
            business_date=payload["target_stay_date"], approved_by=actor, approval_id=approval_id,
            approver_role=auth_context.get("user_role"), old_price=payload["old_price"], floor_price=None, ceiling_price=None,
            activity_discount_factors=None, pms_price=None, dry_run=False, no_log=True, timeout=5, auth_source="feishu",
            user_id=user_id, open_id=open_id, union_id=union_id, chat_id=chat_id, chat_type=chat_type, user_role=auth_context.get("user_role"),
            auth_config=auth_config, requested_by=payload.get("requester_id"), source_decision_id=payload.get("source_decision_id"),
            prevalidated_confirmation=True, prevalidated_policy=preview_policy,
        ),
    )
    queued = outcome.get("status") == "queued"
    finish_confirmation(confirmation_db_path, confirmation_id, completed=queued)
    return {
        **outcome, "intent": "price_task_outbox_write", "skill_id": "S6", "node_id": "N016",
        "confirmation_id": confirmation_id, "approval_id": approval_id, "plugin_waited": False,
    }


def _live_flag_status() -> dict[str, Any]:
    flags = {
        "BEYONDH_ENABLE_LIVE": os.environ.get("BEYONDH_ENABLE_LIVE"),
        "MEITUAN_ENABLE_LIVE": os.environ.get("MEITUAN_ENABLE_LIVE"),
        "DINDANLL_ENABLE_LIVE": os.environ.get("DINDANLL_ENABLE_LIVE"),
    }
    return {
        "live_flags_explicit": all(value not in (None, "") for value in flags.values()),
        "live_flags_disabled": all((value or "0") == "0" for value in flags.values()),
        "live_flag_values": {key: "set" if value not in (None, "") else "missing" for key, value in flags.items()},
    }


def _runtime_status(
    *,
    role: str,
    output_profile: str | None,
    db_path: str | None = None,
    hotel_id: str | None = None,
    production_feishu: bool = False,
) -> dict[str, Any]:
    flags = _live_flag_status()
    if production_feishu:
        context = {
            "context_source": "production_feishu_runtime_status",
            "fallback_used": False,
            "business_date": None,
            "data_source_type": "unavailable",
            "freshness_status": "missing_real_data",
            "generated_demo_run_id": None,
        }
        demo_chain_context_date = None
        snapshot_default_date = None
        summary = (
            "Production Feishu status reports runtime and configuration state only; "
            "business dates require a real data-backed business query."
        )
        suggested_next_step = "Run a real-data business query or database-inspect; production Feishu never uses demo dates as fallback."
    else:
        resolved_hotel_id = hotel_id or _demo_manifest_hotel_id()
        context = build_run_context(db_path=db_path or os.environ.get("HOTEL_OTA_DB", ""), hotel_id=resolved_hotel_id)
        static_manifest = load_demo_manifest()
        demo_chain_context_date = context.get("business_date")
        snapshot_default_date = static_manifest.get("demo_business_date")
        summary = (
            f"Demo chain context date: {demo_chain_context_date}; snapshot fallback date: {snapshot_default_date}; "
            f"context_source={context.get('context_source')}; fallback_used={bool(context.get('fallback_used'))}."
        )
        suggested_next_step = "演示今日数据请先生成 synthetic demo，再运行完整演示；只有接入真实经营数据时才启用 DB source。"
    result = _base_result("runtime_status", role=role, output_profile=output_profile)
    result.update(
        {
            "status": "ok" if flags["live_flags_disabled"] else "warning",
            "runtime_command": "env-check",
            "environment_scope": "gateway_process_env_or_current_cli_env",
            "gateway_env_note": "Feishu gateway environment may differ from an interactive shell; check inside openclaw-gateway before production use.",
            "demo_mode_env": os.environ.get("HOTEL_OTA_DEMO_MODE", "0"),
            "database_source_status": "enabled" if os.environ.get("HOTEL_OTA_DB_SOURCE_ENABLE") == "1" else "disabled",
            "context_source": context.get("context_source"),
            "fallback_used": bool(context.get("fallback_used")),
            "allow_demo_fallback": not production_feishu,
            "demo_chain_context_date": demo_chain_context_date,
            "snapshot_default_date": snapshot_default_date,
            "business_date": demo_chain_context_date,
            "data_source_type": context.get("data_source_type"),
            "freshness_status": context.get("freshness_status"),
            "generated_demo_run_id": context.get("generated_demo_run_id"),
            "db_source_enable_required_for_demo": False,
            "db_source_enable_note": "DB source 只影响真实经营数据读取；生产飞书不会用 demo/sample/synthetic/static fixture 兜底。",
            "summary": summary,
            "suggested_next_step": suggested_next_step,
            **flags,
        }
    )
    return result


def _business_calendar(*, role: str, output_profile: str | None, db_path: str | None, hotel_id: str) -> dict[str, Any]:
    calendar_db_path = db_path or os.environ.get("HOTEL_OTA_DB") or str(Path(tempfile.gettempdir()) / "hotel-ota-business-calendar.sqlite")
    market = _capture_runtime_emit(
        market_context,
        argparse.Namespace(
            db=calendar_db_path,
            hotel_id=hotel_id,
            date=None,
            weather_provider="weather_mcp",
            weather_fixture=None,
            operating_fixture=None,
            progress_fixture=None,
            market_source_config=None,
        ),
    )
    result = _base_result("business_calendar", role=role, output_profile=output_profile)
    calendar_context = market.get("calendar_context") or {}
    event_context = market.get("event_context") or {}
    weather_context = market.get("weather_context") or {}
    regional_heat_context = market.get("regional_heat_context") or {}
    display_status = "ok" if calendar_context else market.get("status", "data_gap")
    result.update(
        {
            "status": display_status,
            "runtime_command": "market-context",
            "market_context_status": market.get("status"),
            "business_date": market.get("business_date") or calendar_context.get("business_date"),
            "calendar_context": calendar_context,
            "weather_context": weather_context,
            "event_context": event_context,
            "regional_heat_context": regional_heat_context,
            "holiday_source": market.get("holiday_source") or calendar_context.get("source") or "builtin_project_seed",
            "event_source": market.get("event_source") or event_context.get("event_source") or event_context.get("source"),
            "weather_source": market.get("weather_source") or weather_context.get("source"),
            "regional_heat_source": market.get("regional_heat_source")
            or regional_heat_context.get("regional_heat_source")
            or regional_heat_context.get("source"),
            "event_discovery_reason": event_context.get("reason"),
            "weather_reason": weather_context.get("reason"),
            "regional_heat_missing_fields": regional_heat_context.get("missing_fields") or [],
            "summary": "Business calendar is generated by runtime market-context; holiday seed is separate from external weather/events/heat sources.",
        }
    )
    return result


def _market_context_demo(*, role: str, output_profile: str | None, db_path: str | None, hotel_id: str) -> dict[str, Any]:
    market_db_path = db_path or os.environ.get("HOTEL_OTA_DB") or str(Path(tempfile.gettempdir()) / "hotel-ota-market-context.sqlite")
    market = _capture_runtime_emit(
        market_context,
        argparse.Namespace(
            db=market_db_path,
            hotel_id=hotel_id,
            date=None,
            weather_provider="market_source",
            weather_fixture=None,
            operating_fixture=None,
            progress_fixture=None,
            market_source_config=None,
        ),
    )
    event_context = market.get("event_context") or {}
    weather_context = market.get("weather_context") or {}
    regional_heat_context = market.get("regional_heat_context") or {}
    result = _base_result("market_context_demo", role=role, output_profile=output_profile)
    result.update(
        {
            "status": market.get("status", "data_gap"),
            "blocked_reason": market.get("blocked_reason") or market.get("reason") or "tenant_context_not_found",
            "runtime_command": "market-context",
            "node_id": "N006",
            "skill_id": "S4",
            "hotel_id": hotel_id,
            "resolved_hotel_id": hotel_id,
            "business_date": market.get("business_date"),
            "data_source_type": market.get("data_source_type") or "market_runtime",
            "freshness_status": market.get("freshness_status") or "partial",
            "context_source": market.get("context_source") or "runtime_market_context",
            "weather_context": weather_context,
            "event_context": event_context,
            "regional_heat_context": regional_heat_context,
            "weather_source": market.get("weather_source") or weather_context.get("source"),
            "event_source": market.get("event_source") or event_context.get("event_source") or event_context.get("source"),
            "regional_heat_source": market.get("regional_heat_source") or regional_heat_context.get("source"),
            "display_location": weather_context.get("display_location") or market.get("display_location"),
            "event_heat_level": event_context.get("event_heat_level"),
            "direct_price_trigger_allowed": False,
            "summary": "S4 market context is generated by runtime market-context from configured market-source providers.",
        }
    )
    return result


SKILL_DEPENDENCY_NODE_MAP = {
    "S2_OPERATING_SNAPSHOT": "N005",
    "S4_MARKET_CONTEXT": "N006",
    "S15_SALES_BASELINE": "N010",
    "S16_PROGRESS_DEVIATION": "N011",
    "S5_REVENUE_DECISION": "N015",
}


def _build_skill_dependency_chain(
    *,
    target_skill: str,
    hotel_id: str,
    db_path: str | None,
    use_generated_today: bool,
    demo_data_dir: str | None,
    time_context: dict[str, Any],
) -> dict[str, Any]:
    def runner(skill: str, run_hotel_id: str, context: dict[str, Any]) -> dict[str, Any]:
        if skill == "OTA_PRICE_MAPPING":
            return {
                "status": "ok",
                "skill": skill,
                "source_status": "ok",
                "context_source": "controlled_price_mapping_check",
            }
        node_id = SKILL_DEPENDENCY_NODE_MAP.get(skill)
        if not node_id:
            return {"status": "blocked", "reason": "skill_dependency_runner_missing", "skill": skill}
        node = build_demo_node_result(
            node_id,
            db_path=db_path,
            hotel_id=run_hotel_id,
            use_generated_today=use_generated_today,
            demo_data_dir=demo_data_dir,
            **time_context,
        )
        result = node.get("node_result") if isinstance(node.get("node_result"), dict) else node
        return {**result, "skill": skill, "node_id": node_id}

    return run_skill_with_dependencies(
        target_skill=target_skill,
        hotel_id=hotel_id,
        context={},
        runner=runner,
    )


def _apply_skill_dependency_chain(result: dict[str, Any], chain: dict[str, Any]) -> None:
    result["orchestrated_target_skill"] = chain.get("target_skill")
    result["dependency_runs"] = chain.get("dependency_runs") or []
    if chain.get("blocked") and chain.get("final_result") is None:
        result.update(
            {
                "status": "data_gap",
                "blocked_reason": chain.get("blocked_reason") or "dependency_blocked",
                "blocking_dependency": chain.get("blocking_dependency"),
                "business_result_generated": False,
            }
        )


def _health_ping(*, role: str, output_profile: str | None) -> dict[str, Any]:
    result = _base_result("health_ping", role=role, output_profile=output_profile)
    result.update(
        {
            "status": "ok",
            "runtime_command": "health-ping",
            "summary": "Runtime reachable. Feishu can show status, demo chains, and dry-run previews; it does not grant live execution.",
            "environment_scope": "feishu_gateway_runtime",
        }
    )
    return result


def _maintenance_refusal(*, role: str, output_profile: str | None) -> dict[str, Any]:
    result = _base_result("maintenance_safety_refusal", role=role, output_profile=output_profile)
    result.update(
        {
            "status": "blocked",
            "runtime_command": "maintenance-action",
            "blocked_reason": "feishu_chat_cannot_modify_code_or_run_git_operations",
            "allowed_next_step": "Use local Codex or an approved maintenance workflow. Feishu only returns status and dry-run previews.",
            "code_modified": False,
            "git_operation_executed": False,
        }
    )
    return result


def _model_config_refusal(*, role: str, output_profile: str | None) -> dict[str, Any]:
    result = _base_result("model_config_request", role=role, output_profile=output_profile)
    result.update(
        {
            "status": "blocked",
            "runtime_command": "model-config",
            "blocked_reason": "feishu_business_chat_cannot_change_model_config",
            "model_config_changed": False,
            "allowed_next_step": "Use an approved admin maintenance workflow for model configuration changes.",
        }
    )
    return result


def _config_change_refusal(*, role: str, output_profile: str | None) -> dict[str, Any]:
    result = _base_result("config_change_request", role=role, output_profile=output_profile)
    result.update(
        {
            "status": "blocked",
            "runtime_command": "config-change-request",
            "blocked_reason": "feishu_business_chat_cannot_modify_runtime_config",
            "blocked_reasons": [
                "feishu_chat_cannot_change_env_or_runtime_config",
                "config_change_requires_admin_maintenance_workflow",
                "demo_data_never_changes_production_config",
            ],
            "summary": "配置变更请求已阻断；飞书业务会话只能查看业务含义、生成维护申请或 dry-run diff，不能直接修改环境变量、SQLite、fixture 或价格安全边界。",
            "next_steps": "演示链路不需要打开真实 DB source；如需启用真实经营数据源，请管理员走服务器维护流程并重启 Gateway。",
            "config_change_applied": False,
            "sqlite_written": False,
            "env_changed": False,
            "fixture_changed": False,
            "formal_approval_created": False,
            "live_execution_count": 0,
            "internal_paths_redacted": True,
            "table_schema_redacted": True,
        }
    )
    return result


def _route_command_menu(
    *,
    message: str,
    role: str,
    output_profile: str | None,
    db_path: str | None,
    hotel_id: str,
    chat_id: str | None,
    chat_type: str | None,
    user_id: str | None,
    open_id: str | None,
    union_id: str | None,
    auth_config: str | None,
    reply: str | None,
) -> dict[str, Any]:
    result = _base_result("command_menu", role=role, output_profile=output_profile)
    if not chat_id or not (open_id or user_id or union_id):
        result.update(
            {
                "status": "ok",
                "stateful_menu_available": False,
                "runtime_command": "command-menu-start",
                "blocked_reason": "missing_chat_or_user_identity_for_stateful_menu",
                "summary": "Static menu returned; pass chat_id and open_id/user_id/union_id for stateful command menu.",
            }
        )
        return result
    namespace = argparse.Namespace(
        db=db_path or ":memory:",
        hotel_id=hotel_id,
        message=message,
        reply=reply or message,
        source="feishu",
        user_id=user_id,
        open_id=open_id,
        union_id=union_id,
        chat_id=chat_id,
        chat_type=chat_type,
        user_role=role,
        auth_config=auth_config,
    )
    routed = _capture_runtime_emit(command_menu_reply if reply else command_menu_start, namespace)
    result.update(routed)
    result["runtime_command"] = "command-menu-reply" if reply else "command-menu-start"
    result["stateful_menu_available"] = True
    return result


def _apply_demo_node_result(
    result: dict[str, Any],
    node: dict[str, Any],
    *,
    intent: str,
    runtime_command: str,
) -> None:
    node_result = node.get("node_result") or {}
    result.update(node)
    result.update(node_result)
    result["intent"] = intent
    result["runtime_command"] = runtime_command
    result["node_result"] = node_result
    result["run_context"] = node.get("run_context")
    result["context_source"] = (node.get("run_context") or {}).get("context_source")
    result["data_source_type"] = node_result.get("data_source_type") or node.get("data_source_type")
    result["freshness_status"] = node_result.get("freshness_status") or node.get("freshness_status")


def route_feishu_command(
    message: str,
    *,
    role: str = "guest",
    output_profile: str | None = None,
    db_path: str | None = None,
    render: bool = False,
    hotel_id: str | None = None,
    account_id: str | None = None,
    chat_id: str | None = None,
    chat_type: str | None = None,
    user_id: str | None = None,
    open_id: str | None = None,
    union_id: str | None = None,
    auth_config: str | None = None,
    use_command_menu: bool = False,
    reply: str | None = None,
    use_generated_today: bool = False,
    demo_data_dir: str | None = None,
    force_feishu_auth: bool = False,
    as_of_time: str | None = None,
    s14_source_config: str | None = None,
    member_info: list[dict[str, Any]] | None = None,
    expected_hotel_id: str | None = None,
) -> dict[str, Any]:
    raw_chat_id = chat_id
    explicit_auth_db_path = db_path
    chat_id = normalize_feishu_chat_id(chat_id)
    intent = _detect_intent(message)
    demo_time_context = resolve_request_as_of_time(message, explicit_as_of_time=as_of_time)
    demo_runtime_time_context = {
        key: demo_time_context[key]
        for key in ("as_of_time", "as_of_time_source")
        if key in demo_time_context
    }
    base_intent = "run_s02" if intent == "run_s02_demo" else intent
    result = _base_result(base_intent, role=role, output_profile=output_profile)
    auth_context: dict[str, Any] | None = None
    result["raw_message_kind"] = "natural_language"
    if intent in ISOLATED_EXTERNAL_REPORT_INTENTS:
        result = _s14_ext_migrated_result(intent, role=role, output_profile=output_profile)
        if render:
            result["rendered"] = render_feishu_output(result, result.get("output_profile"))
            result["send_payload"] = build_feishu_send_payload(result, role=role)
        return result
    if intent == "chat_role_join_request":
        requested_role = _chat_join_requested_role(message)
        if not chat_id or not (open_id or user_id or union_id) or chat_type == "direct":
            result = _permission_blocked_result(
                intent=intent,
                role="guest",
                output_profile=output_profile,
                blocked_reason="join_request_requires_bound_group_and_identity",
                required_permission="view_diagnosis",
                auth_status="invalid_context",
                self_claim_ignored=False,
            )
        else:
            request = create_chat_join_request(
                db_path or ":memory:",
                hotel_id=hotel_id,
                chat_id=chat_id,
                identity={"open_id": open_id, "user_id": user_id, "union_id": union_id},
                requested_role=requested_role or "operator",
            )
            result.update(request)
            result.update(
                {
                    "intent": intent,
                    "runtime_command": "chat-role-join-request",
                    "summary": "加入酒店申请已提交，尚未获得业务权限。请由本酒店 owner 或全局管理员确认。",
                    "config_change_applied": False,
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                }
            )
        if render:
            result["rendered"] = render_feishu_output(result, result.get("output_profile"))
            result["send_payload"] = build_feishu_send_payload(result, role="guest")
        return result
    if intent in {"chat_binding_request", "chat_binding_confirm", "chat_binding_cancel", "chat_binding_status"}:
        auth_context = build_auth_context(
            source="feishu",
            user_id=user_id,
            open_id=open_id,
            union_id=union_id,
            chat_id=raw_chat_id,
            chat_type=chat_type,
            user_role=role,
            config_path=auth_config,
            auth_db_path=explicit_auth_db_path,
            requested_hotel_id=hotel_id,
        )
        actor = _control_plane_actor(auth_context, chat_id or "")
        role = auth_context.get("user_role") or role
        result["auth_role"] = role
        result["output_profile"] = default_output_profile(role, output_profile)
        result["auth_backend"] = auth_context.get("auth_backend")
        result["tenant_status"] = auth_context.get("tenant_status")
        if intent == "chat_binding_status":
            result.update(_chat_binding_status(db_path, chat_id))
            result.update({"intent": intent, "runtime_command": "chat-binding-status"})
        elif auth_context.get("auth_status") not in {"authorized", "unauthorized"} or not auth_context.get("principal_id"):
            result = _permission_blocked_result(
                intent=intent,
                role="guest",
                output_profile=output_profile,
                blocked_reason=auth_context.get("reason") or "missing_feishu_identity",
                required_permission=_permission_action_for_intent(intent),
                auth_status=auth_context.get("auth_status"),
                self_claim_ignored=False,
            )
        elif intent == "chat_binding_request":
            payload = _chat_binding_payload(message)
            if not payload or not chat_id:
                result.update({"status": "blocked", "intent": intent, "reason": "chat_binding_payload_or_chat_missing"})
            else:
                target_hotel = payload.get("hotel_id") or auth_context.get("resolved_hotel_id") or hotel_id
                binding_actor = _chat_binding_actor_for_target(auth_context, db_path, str(target_hotel or ""), chat_id)
                request = create_chat_binding_request(
                    db_path or ":memory:",
                    hotel_id=str(target_hotel or ""),
                    chat_id=chat_id,
                    chat_type=chat_type or "unknown",
                    requester=binding_actor,
                    operation=payload["operation"],
                    expires_at=_chat_request_expiry(),
                )
                result.update(request)
                result.update(
                    {
                        "intent": intent,
                        "runtime_command": "chat-binding-request",
                        "summary": (
                            f"会话绑定申请已创建，尚未生效。申请编号：{request.get('request_id')}。"
                            f"确认命令：确认 {request.get('request_id')}。"
                        ),
                    }
                )
        elif intent == "chat_binding_confirm":
            request_id = _chat_request_id(message, _CHAT_BIND_CONFIRMATION_RE)
            confirmation = confirm_chat_binding_request(
                db_path or ":memory:",
                request_id=request_id or "",
                actor=actor,
                chat_id=chat_id or "",
                chat_type=chat_type or "unknown",
            )
            result.update(confirmation)
            result.update(
                {
                    "intent": intent,
                    "runtime_command": "chat-binding-confirm",
                    "summary": "会话绑定已确认并写入 SQLite Active Chat Binding。" if confirmation.get("status") == "confirmed" else "会话绑定未确认，请检查状态、权限、会话和有效期。",
                }
            )
        else:
            request_id = _chat_request_id(message, _CHAT_BIND_CANCELLATION_RE)
            cancellation = cancel_chat_binding_request(
                db_path or ":memory:",
                request_id=request_id or "",
                actor=actor,
                chat_id=chat_id or "",
            )
            result.update(cancellation)
            result.update({"intent": intent, "runtime_command": "chat-binding-cancel"})
        result.update(
            {
                "personal_role": auth_context.get("user_role"),
                "auth_backend": auth_context.get("auth_backend"),
                "tenant_status": auth_context.get("tenant_status"),
                "identity_present": bool(auth_context.get("principal_id") or open_id or user_id or union_id),
                "formal_approval_created": False,
                "live_execution_count": 0,
            }
        )
        if render:
            result["rendered"] = render_feishu_output(result, result.get("output_profile"))
            result["send_payload"] = build_feishu_send_payload(result, role=auth_context.get("user_role") or role)
        return result
    if (intent in PROTECTED_BUSINESS_INTENTS or force_feishu_auth) and (
        role == "guest" or _identity_context_supplied(chat_id=chat_id, user_id=user_id, open_id=open_id, union_id=union_id, auth_config=auth_config)
    ):
        action = _permission_action_for_intent(intent)
        auth_context = build_auth_context(
            source="feishu",
            user_id=user_id,
            open_id=open_id,
            union_id=union_id,
            chat_id=raw_chat_id,
            chat_type=chat_type,
            user_role=role,
            config_path=auth_config,
            auth_db_path=explicit_auth_db_path,
            requested_hotel_id=hotel_id,
        )
        resolved_auth_hotel_id = auth_context.get("resolved_hotel_id") or hotel_id
        if expected_hotel_id and resolved_auth_hotel_id != expected_hotel_id:
            result = _permission_blocked_result(
                intent=base_intent, role="guest", output_profile=output_profile,
                blocked_reason="bot_account_hotel_mismatch",
                required_permission=_permission_action_for_intent(intent),
                auth_status=auth_context.get("auth_status"), self_claim_ignored=False,
            )
            if render:
                result["rendered"] = render_feishu_output(result, result.get("output_profile"))
                result["send_payload"] = build_feishu_send_payload(result, role="guest")
            return result
        tenant_gate = tenant_scope_gate(auth_context, resolved_auth_hotel_id)
        if not tenant_gate["allowed"]:
            result = _permission_blocked_result(
                intent=base_intent,
                role=role,
                output_profile=output_profile,
                blocked_reason=tenant_gate["reason"],
                required_permission=_permission_action_for_intent(intent),
                auth_status=auth_context.get("auth_status"),
                self_claim_ignored=_self_claim_detected(message),
            )
            result.update(
                {
                    "personal_role": auth_context.get("user_role"),
                    "auth_backend": auth_context.get("auth_backend"),
                    "tenant_status": auth_context.get("tenant_status"),
                    "identity_present": bool(auth_context.get("principal_id") or open_id or user_id or union_id),
                    "chat_bound": bool(auth_context.get("resolved_hotel_id")),
                }
            )
            if render:
                result["rendered"] = render_feishu_output(result, result.get("output_profile"))
                result["send_payload"] = build_feishu_send_payload(result, role=role)
            return result
        gate = permission_gate(auth_context, action, dry_run=intent in {"price_execution_dry_run", "promotion_execute_dry_run"})
        if not gate["allowed"]:
            auth_reason = auth_context.get("reason")
            blocked_reason = (
                auth_reason
                if auth_reason in {
                    "missing_required_chat_id",
                    "missing_business_chat_id",
                    "missing_feishu_identity",
                    "chat_not_allowed",
                    "chat_not_bound_to_hotel",
                    "tenant_scope_mismatch",
                    "user_not_hotel_member",
                    "unknown_tenant",
                }
                else gate["reason"]
            )
            result = _permission_blocked_result(
                intent=base_intent,
                role=role,
                output_profile=output_profile,
                blocked_reason=blocked_reason,
                required_permission=gate.get("required_permission"),
                auth_status=auth_context.get("auth_status"),
                self_claim_ignored=_self_claim_detected(message),
            )
            result.update(
                {
                    "personal_role": auth_context.get("user_role"),
                    "auth_backend": auth_context.get("auth_backend"),
                    "tenant_status": auth_context.get("tenant_status"),
                    "identity_present": bool(auth_context.get("principal_id") or open_id or user_id or union_id),
                    "chat_bound": bool(auth_context.get("resolved_hotel_id")),
                }
            )
            if render:
                result["rendered"] = render_feishu_output(result, result.get("output_profile"))
                result["send_payload"] = build_feishu_send_payload(result, role=role)
            return result
        role = auth_context.get("user_role") or role
        hotel_id = auth_context.get("resolved_hotel_id") or hotel_id
        result["auth_role"] = role
        result["resolved_hotel_id"] = hotel_id
        result["hotel_id"] = hotel_id
        result["auth_backend"] = auth_context.get("auth_backend")
        result["tenant_status"] = auth_context.get("tenant_status")
        result["personal_role"] = role
        result["output_profile"] = default_output_profile(role, output_profile)

    if force_feishu_auth and (intent in PROTECTED_BUSINESS_INTENTS or intent in TENANT_AUTH_REQUIRED_ISOLATED_INTENTS) and not hotel_id:
        result = _permission_blocked_result(
            intent=base_intent,
            role=role,
            output_profile=output_profile,
            blocked_reason="missing_resolved_hotel_id",
            required_permission=_permission_action_for_intent(intent),
            auth_status=(auth_context or {}).get("auth_status", "invalid_context"),
            self_claim_ignored=_self_claim_detected(message),
        )
        result.update(
            {
                "personal_role": (auth_context or {}).get("user_role"),
                "auth_backend": (auth_context or {}).get("auth_backend"),
                "tenant_status": (auth_context or {}).get("tenant_status"),
                "identity_present": bool((auth_context or {}).get("principal_id") or open_id or user_id or union_id),
                "chat_bound": bool((auth_context or {}).get("resolved_hotel_id")),
            }
        )
        if render:
            result["rendered"] = render_feishu_output(result, result.get("output_profile"))
            result["send_payload"] = build_feishu_send_payload(result, role=role)
        return result

    if force_feishu_auth and _requested_demo_hotel_id(message):
        result = _permission_blocked_result(
            intent=base_intent,
            role=role,
            output_profile=output_profile,
            blocked_reason="demo_hotel_not_allowed_in_production_feishu",
            required_permission=_permission_action_for_intent(intent),
            auth_status=(auth_context or {}).get("auth_status", "authorized"),
            self_claim_ignored=_self_claim_detected(message),
        )
        result.update(
            {
                "resolved_hotel_id": hotel_id,
                "business_result_generated": False,
                "allow_demo_fallback": False,
                "allow_sample_evidence": False,
                "summary": "生产飞书请求不能查询 demo hotel；请使用当前会话绑定酒店或在本地测试环境运行演示。",
            }
        )
        if render:
            result["rendered"] = render_feishu_output(result, result.get("output_profile"))
            result["send_payload"] = build_feishu_send_payload(result, role=role)
        return result

    if force_feishu_auth and _requested_other_hotel_name(message, hotel_id) and not _explicit_demo_requested(message):
        result = _permission_blocked_result(
            intent=base_intent,
            role=role,
            output_profile=output_profile,
            blocked_reason="unknown_tenant",
            required_permission=_permission_action_for_intent(intent),
            auth_status=(auth_context or {}).get("auth_status", "authorized"),
            self_claim_ignored=_self_claim_detected(message),
        )
        result.update(
            {
                "resolved_hotel_id": hotel_id,
                "business_result_generated": False,
                "allow_demo_fallback": False,
                "allow_sample_evidence": False,
                "summary": "生产飞书请求中的酒店名没有通过受控 alias registry 或租户配置解析，不能静默回退当前酒店或 demo 酒店。",
            }
        )
        if render:
            result["rendered"] = render_feishu_output(result, result.get("output_profile"))
            result["send_payload"] = build_feishu_send_payload(result, role=role)
        return result

    if force_feishu_auth and intent in DEMO_FALLBACK_INTENTS and not _explicit_demo_requested(message):
        if intent == "run_s02_demo" and database_source_enabled():
            intent = "run_s02"
            base_intent = "run_s02"
        elif intent == "revenue_decision_demo" and database_source_enabled():
            # Numeric menu 9 predates the real S5 route.  In production it must
            # use exact-hotel read-only evidence, not fail closed as a demo.
            intent = "revenue_decision"
            base_intent = "revenue_decision"
        elif intent == "ota_diagnosis_demo":
            # Menu 5 is retained as a local demo entry, but production Feishu
            # must compose S14 from real, versioned capability results.
            intent = "operation_diagnosis"
            base_intent = "operation_diagnosis"
        else:
            result = _production_no_demo_fallback_result(intent=intent, role=role, output_profile=output_profile)
            result.update(
                {
                    "intent": base_intent,
                    "hotel_id": hotel_id,
                    "resolved_hotel_id": hotel_id,
                    "auth_backend": (auth_context or {}).get("auth_backend"),
                    "tenant_status": (auth_context or {}).get("tenant_status"),
                    "personal_role": (auth_context or {}).get("user_role") or role,
                }
            )
            if render:
                result["rendered"] = render_feishu_output(result, result.get("output_profile"))
                result["send_payload"] = build_feishu_send_payload(result, role=role)
            return result

    hotel_id = hotel_id or _demo_manifest_hotel_id()

    # Stateful menus are opt-in. Authentication and V3 tenant resolution must
    # complete before a menu can persist or reuse any hotel-scoped state.
    if use_command_menu or reply:
        result = _route_command_menu(
            message=message,
            role=role,
            output_profile=output_profile,
            db_path=db_path,
            hotel_id=hotel_id,
            chat_id=chat_id,
            chat_type=chat_type,
            user_id=user_id,
            open_id=open_id,
            union_id=union_id,
            auth_config=auth_config,
            reply=reply,
        )
        if render:
            result["rendered"] = render_feishu_output(result, result.get("output_profile"))
            result["send_payload"] = build_feishu_send_payload(result, role=role)
        return result

    if intent == "runtime_status":
        result = _runtime_status(
            role=role,
            output_profile=output_profile,
            db_path=db_path,
            hotel_id=hotel_id,
            production_feishu=force_feishu_auth,
        )
    elif intent == "business_calendar":
        result = _business_calendar(role=role, output_profile=output_profile, db_path=db_path, hotel_id=hotel_id)
    elif intent == "operation_diagnosis":
        # The S14 runtime patch composes real versioned capability results after
        # trusted auth and tenant scoping complete.  Demo remains explicit only.
        for key in ("demo_dataset_id", "demo_business_date", "demo_run_id"):
            result.pop(key, None)
        result.update(
            {
                "status": "ok",
                "intent": "operation_diagnosis",
                "skill_id": "S14",
                "node_id": "N009",
                "agent_id": agent_id_for_node("N009"),
                "runtime_command": "s14-diagnosis --versioned-capability-results",
                "data_source_type": "pending_real_capability_results",
                "data_business_date": None,
                "freshness_status": "pending_real_capability_results",
                "business_status": "current",
                "hotel_name": None,
                "approval_data_allowed": False,
                "approval_preview_allowed": False,
                "formal_approval_allowed": False,
                "live_allowed": False,
                "business_result_generated": False,
                "formal_approval_created": False,
                "live_execution_count": 0,
            }
        )
    elif intent == "health_ping":
        result = _health_ping(role=role, output_profile=output_profile)
    elif intent == "maintenance_safety_refusal":
        result = _maintenance_refusal(role=role, output_profile=output_profile)
    elif intent == "model_config_request":
        result = _model_config_refusal(role=role, output_profile=output_profile)
    elif intent == "chat_role_change_request":
        payload = _chat_role_change_payload(message)
        if not payload or not auth_context or not chat_id:
            result = _config_change_refusal(role=role, output_profile=output_profile)
        else:
            request = create_chat_role_change_request(
                db_path or ":memory:",
                hotel_id=hotel_id,
                chat_id=chat_id,
                requester=_control_plane_actor(auth_context, chat_id),
                target_principal_id=payload["principal_id"],
                requested_role=payload["role"],
                operation=payload["operation"],
            )
            result.update(request)
            result.update(
                {
                    "intent": intent,
                    "runtime_command": "chat-role-change-request",
                    "summary": "角色变更申请已创建，尚未生效。请在同一酒店群回复确认命令。",
                    "config_change_applied": False,
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                }
            )
    elif intent == "chat_role_named_request":
        payload = _chat_role_named_payload(message)
        resolved = _resolve_named_role_target(db_path, hotel_id=hotel_id, target=(payload or {}).get("target", ""), member_info=member_info)
        if not payload or resolved.get("status") != "ok" or not auth_context or not chat_id:
            result.update(
                {
                    "status": "blocked",
                    "reason": resolved.get("reason") or "role_membership_target_not_found",
                    "summary": "未找到可验证的成员身份。请让对方先在本酒店已绑定群发送“申请加入酒店”或“申请成为前台”，再由 owner/admin 确认 ROLE 申请编号。",
                    "config_change_applied": False,
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                }
            )
        else:
            request = create_chat_role_change_request(
                db_path or ":memory:",
                hotel_id=hotel_id,
                chat_id=chat_id,
                requester=_control_plane_actor(auth_context, chat_id),
                target_principal_id=resolved["principal_id"],
                requested_role=payload["role"],
                operation=payload["operation"],
            )
            result.update(request)
            result.update(
                {
                    "intent": intent,
                    "runtime_command": "chat-role-change-named-request",
                    "summary": "角色变更申请已创建，尚未生效。请在同一酒店群回复确认命令。",
                    "config_change_applied": False,
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                }
            )
    elif intent == "chat_role_change_confirm":
        confirmation_payload = _chat_role_confirmation_payload(message)
        request_id = (confirmation_payload or {}).get("request_id")
        if not request_id or not auth_context or not chat_id:
            result = _config_change_refusal(role=role, output_profile=output_profile)
        else:
            confirmation = confirm_chat_role_change_request(
                db_path or ":memory:",
                request_id=request_id,
                actor=_control_plane_actor(auth_context, chat_id),
                chat_id=chat_id,
                requested_role=(confirmation_payload or {}).get("requested_role"),
            )
            result.update(confirmation)
            result.update(
                {
                    "intent": intent,
                    "runtime_command": "chat-role-change-confirm",
                    "summary": "角色申请已确认并写入 SQLite Active Auth。" if confirmation.get("status") == "confirmed" else "角色申请未确认，请检查状态、有效期和酒店范围。",
                    "config_change_applied": confirmation.get("status") == "confirmed",
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                }
            )
    elif intent == "chat_role_change_cancel":
        request_id = _chat_request_id(message, _CHAT_ROLE_CANCELLATION_RE)
        if not request_id or not auth_context or not chat_id:
            result = _config_change_refusal(role=role, output_profile=output_profile)
        else:
            cancellation = cancel_chat_role_change_request(
                db_path or ":memory:",
                request_id=request_id,
                actor=_control_plane_actor(auth_context, chat_id),
                chat_id=chat_id,
            )
            result.update(cancellation)
            result.update(
                {
                    "intent": intent,
                    "runtime_command": "chat-role-change-cancel",
                    "summary": "角色申请已取消。" if cancellation.get("status") == "cancelled" else "角色申请未取消，请检查状态和酒店范围。",
                    "config_change_applied": False,
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                }
            )
    elif intent == "chat_configuration_request":
        payload = _chat_price_guard_payload(message)
        if not payload or not auth_context or not chat_id:
            result = _config_change_refusal(role=role, output_profile=output_profile)
        else:
            request = create_chat_configuration_request(
                db_path or ":memory:",
                request_kind="price_guard_policy",
                hotel_id=hotel_id,
                requester=_control_plane_actor(auth_context, chat_id),
                chat_id=chat_id,
                payload=payload,
                expires_at=_chat_request_expiry(),
            )
            result.update(request)
            result.update(
                {
                    "intent": "chat_configuration_request",
                    "runtime_command": "chat-configuration-request",
                    "summary": "价格护栏变更申请已创建，尚未生效。请在同一酒店群回复确认命令。",
                    "payload": payload,
                    "room_type_id": payload.get("room_type_id"),
                    "config_change_applied": False,
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                }
            )
    elif intent == "chat_configuration_confirm":
        request_id = _chat_request_id(message, _CHAT_CONFIRMATION_RE)
        if not request_id or not auth_context or not chat_id:
            result = _config_change_refusal(role=role, output_profile=output_profile)
        else:
            confirmation = confirm_chat_configuration_request(
                db_path or ":memory:",
                request_id=request_id,
                actor=_control_plane_actor(auth_context, chat_id),
                chat_id=chat_id,
            )
            result.update(confirmation)
            result.update(
                {
                    "intent": "chat_configuration_confirm",
                    "runtime_command": "chat-configuration-confirm",
                    "summary": "配置申请已确认并写入当前酒店的 Active Policy。" if confirmation.get("status") == "confirmed" else "配置申请未确认，请检查申请状态、有效期和酒店权限。",
                    "config_change_applied": confirmation.get("status") == "confirmed",
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                }
            )
    elif intent == "chat_configuration_cancel":
        request_id = _chat_request_id(message, _CHAT_CANCELLATION_RE)
        if not request_id or not auth_context or not chat_id:
            result = _config_change_refusal(role=role, output_profile=output_profile)
        else:
            cancellation = cancel_chat_configuration_request(
                db_path or ":memory:",
                request_id=request_id,
                actor=_control_plane_actor(auth_context, chat_id),
                chat_id=chat_id,
            )
            result.update(cancellation)
            result.update(
                {
                    "intent": "chat_configuration_cancel",
                    "runtime_command": "chat-configuration-cancel",
                    "summary": "配置申请已取消。" if cancellation.get("status") == "cancelled" else "配置申请未取消，请检查申请状态和酒店权限。",
                    "config_change_applied": False,
                    "formal_approval_created": False,
                    "live_execution_count": 0,
                }
            )
    elif intent == "config_change_request":
        result = _config_change_refusal(role=role, output_profile=output_profile)
    elif intent == "priceable_product_list":
        source_platform = _priceable_product_platform(message)
        result.update(
            list_priceable_products(
                hotel_id=hotel_id,
                control_db_path=db_path or ":memory:",
                as_of_time=as_of_time,
                source_platform=source_platform,
            )
        )
        result.update(
            {
                "intent": intent,
                "runtime_command": "ota-priceable-product-list",
                "business_result_generated": result.get("status") == "ok",
                "approval_required": False,
                "live_allowed": False,
            }
        )
        if result.get("status") == "ok":
            result["blocked_reason"] = None
    elif intent in {name for name, _ in MANAGEMENT_READ_INTENTS}:
        result.update(
            build_tenant_management_read_model(
                db_path or ":memory:",
                hotel_id=hotel_id,
                role_map=load_auth_config(auth_config) if auth_config else None,
                chat_id=chat_id,
            )
        )
        result["intent"] = intent
        result["runtime_command"] = "tenant-management-read-model"
        result["auth_backend"] = result.get("auth_backend") or (auth_context or {}).get("auth_backend") or "sqlite_active"
        result["tenant_status"] = result.get("tenant_status") or (auth_context or {}).get("tenant_status")
        result["summary"] = "运行时事实源：SQLite Active Auth；JSON 用途：auth-bootstrap-sync bootstrap seed。角色变更必须走 ROLE 二次确认。"
    elif intent == "identity":
        principal_id = str((auth_context or {}).get("principal_id") or "")
        binding = _chat_binding_status(db_path, chat_id)
        tenant_status = (auth_context or {}).get("tenant_status")
        if tenant_status in {"ok", "chat_role_bound", "hotel_membership_fallback"} and (binding.get("chat_bound") or (auth_context or {}).get("resolved_hotel_id")):
            tenant_status = "hotel_bound"
        result.update(
            {
                "status": "ok",
                "runtime_command": "identity",
                "personal_role": (auth_context or {}).get("user_role") or role,
                "principal_id_hash": _safe_hash(principal_id) if principal_id else None,
                "auth_backend": (auth_context or {}).get("auth_backend") or "sqlite_active",
                "auth_status": (auth_context or {}).get("auth_status"),
                "tenant_status": tenant_status,
                "chat_bound": bool(binding.get("chat_bound") or (auth_context or {}).get("resolved_hotel_id")),
                "chat_type": (auth_context or {}).get("chat_type") or binding.get("chat_type") or chat_type,
                "resolved_hotel_id": (auth_context or {}).get("resolved_hotel_id") or binding.get("resolved_hotel_id"),
                "live_allowed": False,
                "formal_approval_allowed": False,
                "summary": "本指令只检查身份和群绑定，不读取 PMS/MySQL 经营数据。如需确认真实数据源，请发送“当前数据源”或“实时房态”。",
            }
        )
    elif intent == "auth_path_explanation":
        binding = _chat_binding_status(db_path, chat_id)
        tenant_status = (auth_context or {}).get("tenant_status")
        if tenant_status in {"ok", "chat_role_bound", "hotel_membership_fallback"} and (binding.get("chat_bound") or (auth_context or {}).get("resolved_hotel_id")):
            tenant_status = "hotel_bound"
        result.update(
            {
                "status": "ok",
                "intent": "auth_path_explanation",
                "runtime_command": "auth-path-explanation",
                "auth_backend": (auth_context or {}).get("auth_backend") or "sqlite_active",
                "auth_status": (auth_context or {}).get("auth_status"),
                "tenant_status": tenant_status,
                "chat_bound": bool(binding.get("chat_bound") or (auth_context or {}).get("resolved_hotel_id")),
                "renderer_template": "auth_path_explanation",
                "summary": "插件层负责 inbound_claim 和标准化飞书字段；runtime 层读取 SQLite Active Auth、auth_principals、chat_bindings/group_chat_bindings、hotel_memberships，再进入 permission_gate。JSON 只用于 auth-bootstrap-sync 初始化/同步。",
            }
        )
        result["summary"] = "当前主路径：Feishu channel → 路由绑定 → Agent → runtime feishu-route/auth-check → SQLite Active Auth → permission_gate。hotel-ota-feishu-auth 插件仅作为可选防护/诊断，不作为当前主鉴权入口。"
    elif intent == "menu":
        result.update({"status": "ok", "agent_id": "A0", "runtime_command": "menu"})
    elif intent == "enter_demo_mode":
        result.update(
            {
                "status": "ok",
                "agent_id": "A0",
                "runtime_command": "enter-demo-mode",
                "mode": "demo",
                "demo_policy": "preview_and_dry_run_only",
                "message": "Entered demo mode. All outputs are demo/synthetic data and formal approval/live execution stay blocked.",
            }
        )
    elif intent == "developer_detail":
        detail = build_all_demo_chains_result(db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        result.update(detail)
        result["intent"] = "developer_detail"
        result["runtime_command"] = "--demo demo-chain --all --debug"
        result["output_profile"] = "developer_debug"
    elif intent == "seed_demo":
        generated = generate_today_demo_result(
            argparse.Namespace(
                business_date=None,
                seed=None,
                profile="normal",
                hotel_id=hotel_id,
                write_db=True,
                write_fixtures=False,
                dry_run=False,
                output_dir=None,
                db=db_path or ":memory:",
            )
        )
        result.update(generated)
        result["runtime_command"] = "generate-today-demo --write-db"
        result["generated_today_demo_ready"] = generated.get("status") == "ok"
    elif intent == "historical_room_type_performance":
        days = _historical_room_type_performance_days(message) or 7
        result.update(
            build_historical_room_type_performance(
                hotel_id=hotel_id,
                days=days,
                as_of_time=demo_time_context.get("as_of_time") or now_local(),
            )
        )
        result.update(
            {
                "intent": intent,
                "node_id": "N005",
                "skill_id": "S2",
                "agent_id": agent_id_for_node("N005"),
                "runtime_command": "historical-room-type-performance",
            }
        )
    elif intent == "run_s02":
        result.update(
            _production_snapshot_result(
                hotel_id=hotel_id,
                role=role,
                output_profile=output_profile,
                target_business_date=demo_time_context.get("target_business_date") or now_local()[:10],
                as_of_time=demo_time_context.get("as_of_time"),
            )
        )
    elif intent == "run_s02_demo":
        node = build_demo_node_result("N005", db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        snapshot = node.get("node_result") or business_snapshot()
        result.update(
            {
                "status": "ok",
                "node_id": "N005",
                "skill_id": "S2",
                "agent_id": agent_id_for_node("N005"),
                "runtime_command": "--demo snapshot",
                "run_context": node.get("run_context"),
                "context_source": (node.get("run_context") or {}).get("context_source"),
                "data_source_type": snapshot.get("data_source_type", result.get("data_source_type")),
                "freshness_status": snapshot.get("freshness_status", result.get("freshness_status")),
                "core_metrics": {
                    "total_rooms": snapshot["total_rooms"],
                    "sold_rooms": snapshot["sold_rooms"],
                    "occupancy_rate": snapshot["occupancy_rate"],
                    "adr": snapshot["adr"],
                    "revpar": snapshot["revpar"],
                },
            }
        )
    elif intent == "demo_node_all":
        node_result = build_all_demo_nodes_result(db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        result.update(node_result)
        result["intent"] = "demo_node_all"
        result["runtime_command"] = "--demo demo-node --all"
    elif intent == "demo_chain_all":
        chain_result = build_all_demo_chains_result(db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        result.update(chain_result)
        result["intent"] = "demo_chain_all"
        result["runtime_command"] = "--demo demo-chain --all"
    elif intent == "full_chain_demo":
        chain_result = build_all_demo_chains_result(db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        result.update(chain_result)
        result["intent"] = "full_chain_demo"
        result["runtime_command"] = "--demo demo-chain --all"
        result["message_preview_allowed"] = True
        result["message_send_attempted"] = False
    elif intent == "owner_today_demo":
        node = build_demo_node_result("N005", db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        snapshot = node.get("node_result") or business_snapshot()
        result.update(node)
        result.update(
            {
                "intent": "owner_today_demo",
                "status": "ok",
                "runtime_command": "--demo demo-node --node N005",
                "core_metrics": {
                    "total_rooms": snapshot.get("total_rooms"),
                    "sold_rooms": snapshot.get("sold_rooms"),
                    "occupancy_rate": snapshot.get("occupancy_rate"),
                    "adr": snapshot.get("adr"),
                    "revpar": snapshot.get("revpar"),
                },
            }
        )
    elif intent == "operator_full_demo":
        chain_result = build_all_demo_chains_result(db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        result.update(chain_result)
        result["intent"] = "operator_full_demo"
        result["runtime_command"] = "--demo demo-chain --all"
    elif intent == "frontdesk_today_tasks":
        node = build_demo_node_result("N018", db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        result.update(node)
        result.update(
            {
                "intent": "frontdesk_today_tasks",
                "status": "preview_only",
                "runtime_command": "--demo demo-node --node N018",
                "frontdesk_tasks": ["room_status_follow_up", "guest_message_preview", "complaint_escalation_preview"],
            }
        )
    elif intent == "market_context_demo":
        result.update(_market_context_demo(role=role, output_profile=output_profile, db_path=db_path, hotel_id=hotel_id))
    elif intent == "competition_alert":
        competition = _capture_runtime_emit(competition_alert, argparse.Namespace(hotel_id=hotel_id))
        result.update(competition)
        result.update(
            {
                "intent": "competition_alert",
                "node_id": "N007",
                "skill_id": "S7",
                "agent_id": agent_id_for_node("N007"),
                "runtime_command": "competition-alert",
                "data_source_type": "real_database" if database_source_enabled() else "unavailable",
                "approval_data_allowed": False,
                "live_allowed": False,
            }
        )
    elif intent == "roi_decision":
        performance = query_s10_promotion_performance(hotel_id, as_of_time=demo_time_context.get("as_of_time"))
        result.update(build_s10_promotion_roi(performance_result=performance, as_of_time=demo_time_context.get("as_of_time")))
        payload = performance.get("payload") if isinstance(performance.get("payload"), dict) else {}
        result.update(
            {
                "intent": intent, "node_id": "N013", "skill_id": "S10", "agent_id": agent_id_for_node("N013"),
                "runtime_command": "s10-promotion-roi --read-only", "data_source_type": "mysql_db",
                "data_business_date": payload.get("data_business_date"), "data_snapshot_time": payload.get("data_snapshot_time"),
                "as_of_time": demo_time_context.get("as_of_time"), "business_result_generated": result.get("status") in {"ok", "partial"},
                "blocked_reason": "read_only_roi_no_promotion_execution",
            }
        )
    elif intent == "revenue_decision":
        if not database_source_enabled():
            result.update(
                {
                    "intent": intent,
                    "skill_id": "S5",
                    "status": "data_gap",
                    "blocked_reason": "database_source_disabled",
                    "candidate_count": 0,
                    "eligible_for_s6_count": 0,
                    "candidates": [],
                    "target_stay_date": demo_time_context.get("target_business_date") or now_local()[:10],
                    "as_of_time": demo_time_context.get("as_of_time"),
                    "as_of_time_source": demo_time_context.get("as_of_time_source"),
                    "data_source_type": "unavailable",
                    "live_allowed": False,
                    "approval_data_allowed": False,
                }
            )
        else:
            target_stay_date = demo_time_context.get("target_business_date") or now_local()[:10]
            s15_result = _query_s15_baseline(
                hotel_id=hotel_id,
                target_stay_date=target_stay_date,
                as_of_time=demo_time_context.get("as_of_time"),
                db_path=db_path,
            )
            result.update(
                build_s5_real_candidates(
                    query=database_template_result,
                    resolve_guard=resolve_price_guard_policy,
                    control_db_path=_s6_confirmation_db_path(db_path) or ":memory:",
                    hotel_id=hotel_id,
                    target_stay_date=target_stay_date,
                    as_of_time=demo_time_context.get("as_of_time"),
                    channel=_priceable_product_platform(message),
                    ota_product_id=_s5_ota_product_id(message),
                    s15_result=s15_result,
                    s16_result=_query_s16_after_s15(
                        s15_result=s15_result,
                        hotel_id=hotel_id,
                        target_stay_date=target_stay_date,
                        as_of_time=demo_time_context.get("as_of_time"),
                        db_path=db_path,
                    ),
                )
            )
            _create_s5_candidate_confirmations(
                result,
                hotel_id=hotel_id,
                db_path=db_path,
                chat_id=raw_chat_id,
                requester_id=(auth_context or {}).get("principal_id"),
            )
            for key in ("demo_dataset_id", "demo_business_date", "demo_run_id"):
                result.pop(key, None)
            result.update(
                {
                    "intent": intent,
                    "node_id": "N015",
                    "agent_id": agent_id_for_node("N015"),
                    "runtime_command": "s5-revenue-candidate --read-only",
                    "blocked_reason": result.get("blocked_reason") or "read_only_candidate_no_live",
                }
            )
    elif intent in NODE_DEMO_INTENTS:
        node_id = NODE_DEMO_INTENTS[intent]
        node = build_demo_node_result(node_id, db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        _apply_demo_node_result(
            result,
            node,
            intent=intent,
            runtime_command=NODE_DEMO_RUNTIME_COMMANDS[intent],
        )
        if intent == "progress_deviation_demo":
            chain = _build_skill_dependency_chain(
                target_skill="S16_PROGRESS_DEVIATION",
                hotel_id=hotel_id,
                db_path=db_path,
                use_generated_today=use_generated_today,
                demo_data_dir=demo_data_dir,
                time_context=demo_runtime_time_context,
            )
            _apply_skill_dependency_chain(result, chain)
        elif intent == "revenue_decision_demo":
            chain = _build_skill_dependency_chain(
                target_skill="S5_REVENUE_DECISION",
                hotel_id=hotel_id,
                db_path=db_path,
                use_generated_today=use_generated_today,
                demo_data_dir=demo_data_dir,
                time_context=demo_runtime_time_context,
            )
            _apply_skill_dependency_chain(result, chain)
    elif intent == "revenue_decision_demo":
        chain = _build_skill_dependency_chain(
            target_skill="S5_REVENUE_DECISION",
            hotel_id=hotel_id,
            db_path=db_path,
            use_generated_today=use_generated_today,
            demo_data_dir=demo_data_dir,
            time_context=demo_runtime_time_context,
        )
        s5 = build_demo_node_result("N015", db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        result.update(s5.get("node_result") or {})
        result["intent"] = "revenue_decision_demo"
        result["runtime_command"] = "--demo demo-node --node N015"
        _apply_skill_dependency_chain(result, chain)
    elif intent == "review_reply_draft":
        review = build_demo_node_result("N017", db_path=db_path, hotel_id=hotel_id, use_generated_today=use_generated_today, demo_data_dir=demo_data_dir, **demo_runtime_time_context)
        result.update(review)
        result.update(
            {
                "intent": "review_reply_draft",
                "status": "preview_only",
                "runtime_command": "--demo demo-node --node N017",
                "draft_preview_allowed": True,
                "publish_allowed": False,
                "publish_attempted": False,
            }
        )
    elif intent == "review_publish_request":
        result.update(
            {
                "status": "blocked",
                "intent": "review_publish_request",
                "node_id": "N017",
                "skill_id": "S13",
                "agent_id": agent_id_for_node("N017"),
                "runtime_command": "review-publish --live",
                "blocked_reason": "review_publish_requires_formal_approval_and_real_data",
                "blocked_reasons": ["demo_data_never_live", "approval_id_required", "review_publish_live_disabled"],
                "publish_allowed": False,
                "publish_attempted": False,
                "approval_id_required": True,
            }
        )
    elif intent == "promotion_suggestion":
        promotion = _capture_runtime_emit(promotion_execute, argparse.Namespace(hotel_id=hotel_id))
        result.update(promotion)
        for key in ("demo_dataset_id", "demo_business_date", "demo_run_id"):
            result.pop(key, None)
        result.update(
            {
                "intent": "promotion_suggestion",
                "node_id": "N021",
                "skill_id": "S11",
                "agent_id": agent_id_for_node("N021"),
                "runtime_command": "promotion-suggestion --read-only",
                "promotion_execute_allowed": False,
                "write_performed": False,
                "live_allowed": False,
                "handoff_to": None,
            }
        )
    elif intent == "live_execution_request":
        result.update(
            {
                "status": "blocked",
                "intent": "live_execution_request",
                "node_id": "N016",
                "skill_id": "S6",
                "agent_id": agent_id_for_node("N016"),
                "runtime_command": "execute-price --live",
                "blocked_reason": "demo_data_never_live",
                "blocked_reasons": ["demo_data_never_live", "approval_id_required", "live_switch_disabled"],
                "approval_id_required": True,
            }
        )
    elif intent == "price_execution_dry_run":
        if not database_source_enabled():
            result.update(
                {
                    "status": "data_gap",
                    "intent": "price_execution_dry_run",
                    "skill_id": "S6",
                    "node_id": "N016",
                    "blocked_reason": "database_source_disabled",
                    "live_allowed": False,
                }
            )
        else:
            builder = _build_s6_batch_dry_run if _s6_batch_room_price_change(message) else _build_s6_real_dry_run
            result.update(
                builder(
                    message=message,
                    hotel_id=hotel_id,
                    db_path=db_path,
                    as_of_time=demo_time_context.get("as_of_time"),
                    auth_config=auth_config,
                    chat_id=raw_chat_id,
                    chat_type=chat_type,
                    user_id=user_id,
                    open_id=open_id,
                    union_id=union_id,
                    role=role,
                    requester_id=(auth_context or {}).get("principal_id"),
                )
            )
            for key in ("demo_dataset_id", "demo_business_date", "demo_run_id"):
                result.pop(key, None)
    elif intent == "price_execution_confirm":
        if not auth_context:
            result.update({
                "status": "blocked", "intent": intent, "skill_id": "S6", "node_id": "N016",
                "blocked_reason": "verified_feishu_identity_required",
            })
        else:
            result.update(
                _write_s6_confirmation_fast(
                    message=message, hotel_id=hotel_id, db_path=db_path, auth_context=auth_context,
                    auth_config=auth_config, chat_id=raw_chat_id, chat_type=chat_type,
                    user_id=user_id, open_id=open_id, union_id=union_id,
                )
            )
    elif intent == "promotion_execute_dry_run":
        suggestion = _capture_runtime_emit(promotion_execute, argparse.Namespace(hotel_id=hotel_id))
        result.update(suggestion)
        result.update({
            "intent": "promotion_suggestion", "node_id": "N021", "skill_id": "S11",
            "agent_id": agent_id_for_node("N021"), "runtime_command": "promotion-suggestion --read-only",
            "promotion_execute_allowed": False, "write_performed": False, "live_allowed": False,
        })
    elif intent == "experience_candidates":
        result.update(
            {
                "status": "ok",
                "intent": "experience_candidates",
                "node_id": "N019",
                "skill_id": "EXP-LAYER",
                "agent_id": "A6",
                "runtime_command": "experience-candidates",
                "summary": "Experience candidates require manual review and cannot directly change production rules.",
            }
        )
    elif intent == "self_check":
        result.update(
            {
                "status": "ok",
                "intent": "self_check",
                "agent_id": "A0",
                "runtime_command": "self-check",
                "restart_attempted": False,
                "restart_success_claimed": False,
                "gateway_status": "unknown",
                "gateway_uptime_seconds": None,
                "process_introspection_available": False,
                "cron_diagnostics": {
                    "cron_status": "unknown",
                    "gateway_status": "unknown",
                    "source": "feishu_runtime_no_process_introspection",
                    "success_claimed": False,
                    "restart_attempted": False,
                    "restart_success_claimed": False,
                    "diagnostic_note": "Feishu runtime can report configured safety flags, but cron/gateway process state must be checked on the server.",
                },
                "environment_scope": "feishu_gateway_runtime_or_current_cli_env",
                **_live_flag_status(),
            }
        )

    if render:
        result["rendered"] = render_feishu_output(result, result.get("output_profile"))
        result["send_payload"] = build_feishu_send_payload(result, role=role)
    return result


def _expected_hotel_for_bot_account(account_id: str | None, auth_config: str | None) -> str | None:
    config = load_auth_config(auth_config)
    mapping = config.get("bot_account_hotel_map") or {}
    if not isinstance(mapping, dict):
        return None
    expected = mapping.get(str(account_id or "").strip())
    return str(expected).strip() if expected else None


def _active_chat_hotel_id(db_path: str | None, chat_id: str | None) -> str | None:
    if not db_path or not chat_id:
        return None
    try:
        with sqlite3.connect(db_path) as connection:
            for table in ("chat_bindings", "group_chat_bindings"):
                row = connection.execute(
                    f"SELECT hotel_id FROM {table} WHERE chat_id=? AND status='active'",
                    (chat_id,),
                ).fetchone()
                if row and row[0]:
                    return str(row[0])
    except sqlite3.Error:
        return None
    return None


def _bot_scope_blocked_result(
    *, intent: str, role: str, output_profile: str | None, reason: str, render: bool
) -> dict[str, Any]:
    result = _permission_blocked_result(
        intent=intent, role=role or "guest", output_profile=output_profile,
        blocked_reason=reason, required_permission=_permission_action_for_intent(intent),
        auth_status="invalid_context", self_claim_ignored=False,
    )
    result.update({"production_feishu": True, "business_result_generated": False})
    if render:
        result["rendered"] = render_feishu_output(result, result.get("output_profile"))
        result["send_payload"] = build_feishu_send_payload(result, role=role or "guest")
    return result


def safe_route_feishu_command(
    message: str,
    *,
    role: str = "guest",
    output_profile: str | None = None,
    db_path: str | None = None,
    render: bool = False,
    hotel_id: str | None = None,
    account_id: str | None = None,
    chat_id: str | None = None,
    chat_type: str | None = None,
    user_id: str | None = None,
    open_id: str | None = None,
    union_id: str | None = None,
    auth_config: str | None = None,
    s14_source_config: str | None = None,
    member_info: list[dict[str, Any]] | None = None,
    use_command_menu: bool = False,
    reply: str | None = None,
    use_generated_today: bool = False,
    demo_data_dir: str | None = None,
    trusted_runtime_role: bool = False,
    full_json_requested: bool = False,
    production_feishu: bool = False,
    compact: bool = False,
    as_of_time: str | None = None,
) -> dict[str, Any]:
    raw_chat_id = chat_id
    explicit_auth_db_path = db_path
    chat_id_resolution = resolve_feishu_business_chat_id(raw_chat_id)
    chat_id = chat_id_resolution.get("chat_id")
    started_at = time.perf_counter()
    correlation_id = _new_correlation_id()
    try:
        requested_intent = _detect_intent(message)
        if production_feishu and (trusted_runtime_role or role not in {None, "guest"}):
            result = _production_role_override_blocked_result(
                role=role,
                output_profile=output_profile,
                correlation_id=correlation_id,
                render=render,
            )
            _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
            return compact_feishu_route_result(result) if compact else result

        if production_feishu and (output_profile == "developer_debug" or requested_intent == "developer_detail"):
            result = _developer_debug_blocked_result(
                role=role,
                output_profile=output_profile,
                correlation_id=correlation_id,
                render=render,
            )
            _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
            return compact_feishu_route_result(result) if compact else result

        if production_feishu and _explicit_demo_requested(message) and not _requested_demo_hotel_id(message):
            result = _permission_blocked_result(
                intent=requested_intent,
                role=role or "guest",
                output_profile=output_profile,
                blocked_reason="demo_not_allowed_in_production_feishu",
                required_permission="production_real_data",
                auth_status="not_evaluated",
            )
            result.update(
                {
                    "production_feishu": True,
                    "allow_demo_fallback": False,
                    "allow_sample_evidence": False,
                    "data_source_type": "unavailable",
                    "freshness_status": "missing_real_data",
                    "safe_user_message": "生产飞书不能使用 demo/sample/synthetic/static fixture；请在本地 CLI 或测试环境运行演示。",
                }
            )
            if render:
                result["rendered"] = render_feishu_output(result, result.get("output_profile"))
                result["send_payload"] = build_feishu_send_payload(result, role=role or "guest")
            _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
            return compact_feishu_route_result(result) if compact else result

        if (output_profile == "developer_debug" or requested_intent == "developer_detail") and (
            not trusted_runtime_role or role != "admin"
        ):
            result = _developer_debug_blocked_result(
                role=role,
                output_profile=output_profile,
                correlation_id=correlation_id,
                render=render,
            )
            result["blocked_reason"] = "developer_debug_local_admin_only"
            result["safe_user_message"] = "调试详情仅允许本地受信维护模式下的 admin 使用。"
            _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
            return compact_feishu_route_result(result) if compact else result

        if full_json_requested and not trusted_runtime_role:
            result = _full_json_blocked_result(
                role=role,
                output_profile=output_profile,
                correlation_id=correlation_id,
                render=render,
            )
            _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
            return compact_feishu_route_result(result) if compact else result

        expected_hotel_id = None
        if production_feishu:
            expected_hotel_id = _expected_hotel_for_bot_account(account_id, auth_config)
            if not expected_hotel_id:
                result = _bot_scope_blocked_result(
                    intent=requested_intent, role=role, output_profile=output_profile,
                    reason="unrecognized_feishu_bot_account", render=render,
                )
                _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
                return compact_feishu_route_result(result) if compact else result
            if chat_type == "group":
                bound_hotel_id = _active_chat_hotel_id(explicit_auth_db_path, chat_id)
                if bound_hotel_id != expected_hotel_id:
                    result = _bot_scope_blocked_result(
                        intent=requested_intent, role=role, output_profile=output_profile,
                        reason="bot_account_hotel_mismatch", render=render,
                    )
                    _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
                    return compact_feishu_route_result(result) if compact else result

        tokens = _numeric_menu_tokens(message)
        if tokens and not use_command_menu and not reply:
            result = _route_multi_intent(
                tokens,
                role=role,
                output_profile=output_profile,
                db_path=db_path,
                render=render,
                hotel_id=hotel_id,
                chat_id=chat_id,
                chat_type=chat_type,
                user_id=user_id,
                open_id=open_id,
                union_id=union_id,
                auth_config=auth_config,
                use_generated_today=use_generated_today,
                demo_data_dir=demo_data_dir,
                trusted_runtime_role=trusted_runtime_role,
                production_feishu=production_feishu,
                correlation_id=correlation_id,
            )
        else:
            intent = _detect_intent(message)
            if (
                intent in PROTECTED_BUSINESS_INTENTS
                and not trusted_runtime_role
                and not _has_complete_feishu_identity_context(
                    chat_id=raw_chat_id,
                    chat_type=chat_type,
                    user_id=user_id,
                    open_id=open_id,
                    union_id=union_id,
                    auth_config=auth_config,
                )
            ):
                result = _safe_auth_context_blocked_result(
                    message=message,
                    intent=intent,
                    role=role,
                    output_profile=output_profile,
                    correlation_id=correlation_id,
                    render=render,
                )
                if production_feishu and chat_id_resolution.get("reason") in {"missing_required_chat_id", "missing_business_chat_id"}:
                    result["blocked_reason"] = "missing_trusted_business_chat_id"
                    result["auth_status"] = "invalid_context"
                    result["hotel_id"] = None
                    result["hotel_name"] = None
                    result["safe_user_message"] = "生产飞书消息缺少可信业务会话 ID，不能使用正文或发送目标作为酒店会话。"
                    if render:
                        result["rendered"] = render_feishu_output(result, result.get("output_profile"))
                        result["send_payload"] = build_feishu_send_payload(result, role=role)
                _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
                return compact_feishu_route_result(result) if compact else result

            result = route_feishu_command(
                message,
                role=role,
                output_profile=output_profile,
                db_path=db_path,
                render=render,
                hotel_id=hotel_id,
                account_id=account_id,
                chat_id=raw_chat_id,
                chat_type=chat_type,
                user_id=user_id,
                open_id=open_id,
                union_id=union_id,
                auth_config=auth_config,
                s14_source_config=s14_source_config,
                member_info=member_info,
                expected_hotel_id=expected_hotel_id,
                use_command_menu=use_command_menu,
                reply=reply,
                use_generated_today=use_generated_today,
                demo_data_dir=demo_data_dir,
                force_feishu_auth=production_feishu
                and (intent not in ISOLATED_EXTERNAL_REPORT_INTENTS or intent in TENANT_AUTH_REQUIRED_ISOLATED_INTENTS),
                as_of_time=as_of_time,
            )
            result.setdefault("correlation_id", correlation_id)
        _record_feishu_audit(
            db_path=db_path,
            message=message,
            result=result,
            chat_id=chat_id,
            chat_type=chat_type,
            open_id=open_id,
            user_id=user_id,
            union_id=union_id,
        )
        _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
        return compact_feishu_route_result(result) if compact else result
    except Exception as exc:
        result = _safe_error_result(
            exc=exc,
            role=role,
            output_profile=output_profile,
            correlation_id=correlation_id,
        )
        _record_feishu_audit(
            db_path=db_path,
            message=message,
            result=result,
            chat_id=chat_id,
            chat_type=chat_type,
            open_id=open_id,
            user_id=user_id,
            union_id=union_id,
        )
        _write_route_log(result, started_at=started_at, chat_id=chat_id, open_id=open_id, user_id=user_id)
        return compact_feishu_route_result(result) if compact else result

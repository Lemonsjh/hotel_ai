from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from runtime.algorithms.s2_operating_reply import render_s2_operating_reply
from runtime.algorithms.s5_real_reply import render_s5_real_reply
from runtime.algorithms.s7_competition_reply import render_s7_competition_reply
from runtime.common import PACKAGE_ROOT
from runtime.historical_room_type_performance import render_historical_room_type_performance_reply
from runtime.safety.feishu_output import feishu_output_gate as evaluate_feishu_output_gate

PRICEABLE_PRODUCT_STATE_LABELS = {
    "ota_product_id_missing": "OTA 商品标识缺失",
    "current_price_missing": "当前价格缺失",
    "platform_price_not_editable": "平台标记为不可调价",
    "room_type_mapping_pending": "房型映射待确认",
    "price_guard_not_configured": "未配置有效价格护栏",
    "price_guard_incomplete": "价格护栏不完整",
}


ROLE_TO_OUTPUT_PROFILE = {
    "admin": "owner_business",
    "owner": "owner_business",
    "operator": "operator_workbench",
    "frontdesk": "frontdesk_task",
    "guest": "guest_limited",
}

INTERNAL_FIELDS = {
    "run_id",
    "generated_by_runtime",
    "runtime_command",
    "node_id",
    "skill_id",
    "agent_id",
    "scenario_id",
    "fixture_path",
    "raw_json",
    "model",
    "provider",
    "open_id",
    "chat_id",
    "user_id",
    "union_id",
    "server_path",
    "server_root",
    "html_report_path",
    "report_local_path",
    "coverage_report",
    "field_coverage_report",
    "calculation_trace",
    "hourly_points",
    "actual_hourly_sales",
    "target_hourly_curve",
    "actual_vs_target_hourly",
    "contract_input_coverage",
    "runtime_feed_coverage",
    "algorithm_usage_coverage",
    "algorithm_used_inputs",
    "algorithm_unused_available_inputs",
    "member_role_counts",
    "price_guard_statuses",
    "pending_configuration_requests",
}

TEMPLATE_DIR = PACKAGE_ROOT / "runtime" / "feishu_templates"
DEFAULT_FEISHU_TEXT_LIMIT = 1200


def default_output_profile(role: str | None, explicit_profile: str | None = None) -> str:
    if explicit_profile:
        return explicit_profile
    return ROLE_TO_OUTPUT_PROFILE.get(role or "guest", "guest_limited")


def load_template(name: str) -> str:
    return (TEMPLATE_DIR / f"{name}.md").read_text(encoding="utf-8")


def _value(result: dict[str, Any], key: str, default: Any = "-") -> Any:
    value = result.get(key)
    if value in (None, ""):
        return default
    return value


def _business_date(result: dict[str, Any]) -> Any:
    return result.get("business_date") or result.get("data_business_date") or result.get("demo_business_date") or "-"


def _short_ota_product_name(value: Any, product_id: Any = None, room_type_name: Any = None) -> str:
    room_type = str(room_type_name or "").strip()
    if room_type:
        return room_type
    name = str(value or "").strip()
    primary = re.split(r"\s*(?:-|—|–|｜|\||（|【)", name, maxsplit=1)[0].strip()
    return primary or name or str(product_id or "-")


def _render_s6_batch_dry_run(result: dict[str, Any]) -> str:
    direction = "下调" if result.get("batch_direction") == "decrease" else "上调"
    try:
        amount = f"{float(result.get('batch_change_amount')):g}"
    except (TypeError, ValueError):
        amount = "-"
    lines = ["S6 批量调价 dry-run（真实数据，只预览）"]
    if result.get("status") in {"blocked", "data_gap"}:
        return "\n".join([*lines, f"结论：{'已阻断' if result.get('status') == 'blocked' else '数据不足'}，原因：{result.get('blocked_reason') or '-'}。"])
    items = result.get("batch_items") or []
    lines.append(f"结论：每个可执行房型挂牌价{direction} ¥{amount}；已通过预览 {len(items)} 个。")
    for item in items:
        product = item.get("selected_product") or {}
        product_name = _short_ota_product_name(
            product.get("ota_product_name"), product.get("ota_product_id"),
            product.get("ota_room_type_name") or product.get("room_type_name"),
        )
        product_id = product.get("ota_product_id") or item.get("ota_product_id")
        current = product.get("current_price")
        target = item.get("execution_price")
        if item.get("status") != "dry_run" or item.get("confirmation_blocked_reason"):
            lines.append(f"- {product_name}（OTA 商品 ID {product_id or '-'}）：未通过，{item.get('confirmation_blocked_reason') or item.get('blocked_reason') or '执行校验失败'}。")
            continue
        try:
            listing_change = (float(target) / float(current) - 1.0) * 100
            change_text = f"（{listing_change:+.1f}%）"
        except (TypeError, ValueError, ZeroDivisionError):
            change_text = ""
        line = f"- {product_name}（OTA 商品 ID {product_id or '-'}）：¥{current} → ¥{target}{change_text}"
        try:
            net_change = (float(item["net_revenue_target"]) / float(item["net_revenue_current"]) - 1.0) * 100
            line += f"；预计净收 ¥{float(item['net_revenue_current']):.2f} → ¥{float(item['net_revenue_target']):.2f}（{net_change:+.1f}%）"
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            pass
        lines.append(line + "。")
    excluded = result.get("excluded_room_types") or []
    if excluded:
        lines.append(f"未纳入：{len(excluded)} 个房型因存在多个标准商品，需指定 OTA 商品后单独预览。")
    lines.append("已排除钟点房、超级团购、不可编辑、无可售库存或映射不可信的商品；本次未创建审批、未写入调价任务。")
    if result.get("confirmation_command"):
        lines.append(f"确认写入：回复「{result['confirmation_command']}」；令牌有效至 {result.get('confirmation_expires_at') or '-'}。")
    elif result.get("confirmation_blocked_reason"):
        lines.append("未生成确认令牌：存在未通过执行校验的商品，请调整后重新预览。")
    return "\n".join(lines)


def _fmt_bool(value: Any) -> str:
    if value is True:
        return "是"
    if value is False:
        return "否"
    if value in (None, ""):
        return "-"
    return str(value)


def _bullet(items: list[Any] | tuple[Any, ...] | set[Any] | None, fallback: str = "-") -> str:
    if not items:
        return fallback
    return "\n".join(f"- {item}" for item in items)


def _inline_list(items: list[Any] | tuple[Any, ...] | set[Any] | None, fallback: str = "-") -> str:
    if not items:
        return fallback
    return ", ".join(str(item) for item in items)


def _progress_table(rows: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None, columns: list[tuple[str, str]]) -> str:
    if not rows:
        return "-"
    lines = [" | ".join(label for label, _ in columns)]
    for item in rows:
        lines.append(" | ".join(str(item.get(key, "-")) for _, key in columns))
    return "\n".join(lines)


def _metrics_for_business(result: dict[str, Any]) -> str:
    metrics = result.get("core_metrics") or {}
    if not metrics:
        metrics = {
            "total_rooms": result.get("total_rooms"),
            "sold_rooms": result.get("sold_rooms"),
            "sold_room_nights_today": result.get("sold_room_nights_today") or result.get("room_nights"),
            "sold_orders_today": result.get("sold_orders_today") or result.get("orders_today"),
            "occupancy_rate": result.get("occupancy_rate"),
            "adr": result.get("adr"),
            "revpar": result.get("revpar"),
        }
    else:
        metrics = dict(metrics)
        if result.get("actual_occupancy_rate") is not None:
            metrics["occupancy_rate"] = result.get("actual_occupancy_rate")
        elif result.get("formula_version") and result.get("blocked_reason") == "realtime_occupancy_formula_evidence_missing":
            metrics["occupancy_rate"] = None
    sold_room_nights = metrics.get("sold_room_nights_today")
    if sold_room_nights in (None, ""):
        sold_room_nights = metrics.get("room_nights") or metrics.get("sold_rooms")
    rows = [
        f"- 总房量：{metrics.get('total_rooms', '-')}",
        f"- 今日已售间夜：{sold_room_nights if sold_room_nights not in (None, '') else '-'}",
        f"- 今日订单数：{metrics.get('sold_orders_today') or metrics.get('orders_today') or '-'}",
        f"- 当前占用房：{metrics.get('sold_rooms', '-')}",
        f"- 出租率：{metrics.get('occupancy_rate', '-')}",
        f"- ADR：{metrics.get('adr', '-')}",
        f"- RevPAR：{metrics.get('revpar', '-')}",
    ]
    if result.get("formula_version") == "pms_room_type_forecast_committed_sales_v1":
        committed_sold = metrics.get("committed_sold_rooms")
        physical_occupied = metrics.get("physical_occupied_rooms")
        rows[1] = f"- 承诺已售间夜：{committed_sold if committed_sold is not None else '-'}"
        rows[2] = "- 今日订单数：PMS 房型快照不提供"
        rows[3] = f"- 物理在住房：{physical_occupied if physical_occupied is not None else '-'}"
        rows[4] = f"- 承诺出租率：{metrics.get('occupancy_rate', '-')}"
    return "\n".join(rows)


def _coverage_rate(result: dict[str, Any]) -> Any:
    coverage = result.get("field_coverage_report") or {}
    return coverage.get("field_coverage_rate") or coverage.get("coverage_rate") or "-"


def _payload_summary(result: dict[str, Any]) -> str:
    keys = [
        "status",
        "mode",
        "total_nodes",
        "passed_nodes",
        "failed_nodes",
        "total_scenarios",
        "passed_scenarios",
        "failed_scenarios",
        "formal_approval_created",
        "live_execution_count",
    ]
    return ", ".join(f"{key}={result.get(key)}" for key in keys if key in result)


def _management_membership_summary(result: dict[str, Any]) -> str:
    counts = result.get("member_role_counts") or {}
    return ", ".join(f"{role}={counts.get(role, 0)}" for role in ("owner", "operator", "frontdesk"))


def _management_guard_summary(result: dict[str, Any]) -> str:
    guards = result.get("price_guard_statuses") or []
    if not guards:
        return "no_active_policy"
    return ", ".join(
        "{room} {source} v{version} {floor}-{ceiling} +{min_up:.0%}~{max_up:.0%} -{min_down:.0%}~{max_down:.0%}".format(
            room=item.get("room_type_id") or "-",
            source=item.get("source") or "default_policy",
            version=item.get("version") or "-",
            floor=item.get("floor_price") if item.get("floor_price") is not None else "-",
            ceiling=item.get("ceiling_price") if item.get("ceiling_price") is not None else "-",
            min_up=float(item.get("min_increase_pct") or 0),
            max_up=float(item.get("max_increase_pct") or 0),
            min_down=float(item.get("min_decrease_pct") or 0),
            max_down=float(item.get("max_decrease_pct") or 0),
        )
        for item in guards
    )


def _management_pending_summary(result: dict[str, Any]) -> str:
    pending = result.get("pending_configuration_requests") or {}
    if not pending:
        return "none"
    return ", ".join(f"{kind}={count}" for kind, count in sorted(pending.items()))


def _is_real_business_data(result: dict[str, Any]) -> bool:
    source = str(result.get("data_source_type") or "").lower()
    return bool(result.get("business_result_generated") and source not in {"demo_data", "sample_data", "synthetic_today_demo", ""})


def _context(result: dict[str, Any]) -> dict[str, Any]:
    preview = result.get("dry_run_preview") or {}
    blocked_reasons = result.get("blocked_reasons") or [result.get("blocked_reason") or "demo_data_never_live"]
    covered_nodes = result.get("covered_nodes") or []
    real_business_data = _is_real_business_data(result)
    return {
        "data_source_type": _value(result, "data_source_type"),
        "business_date": _business_date(result),
        "real_business_data": _fmt_bool(real_business_data),
        "approval_data_allowed": _fmt_bool(result.get("approval_data_allowed")),
        "live_allowed": _fmt_bool(result.get("live_allowed")),
        "conclusion": result.get("summary") or ("真实经营数据已由 runtime 读取；当前仅允许只读分析，不允许审批或 live 执行。" if real_business_data else "演示结果已由 runtime 生成，仅用于流程预览。"),
        "metrics": _metrics_for_business(result),
        "risks": _bullet(result.get("risk_items") or (["真实数据只读返回，正式审批和 live 执行已阻断"] if real_business_data else ["演示数据不能作为真实经营结论", "正式审批和 live 执行已阻断"])),
        "actions": _bullet(result.get("suggested_actions") or (["继续查看经营、诊断或 dry-run 结果", "如需执行写入，必须走审批和写入开关"] if real_business_data else ["查看 dry-run 预览", "核对字段覆盖率", "真实上线时重新接入 fresh 数据"])),
        "boundaries": result.get("blocked_reason") or ("read_only_runtime_formal_live_blocked" if real_business_data else "demo_preview_allowed_formal_live_blocked"),
        "next_steps": result.get("next_steps") or "继续查看节点、场景或报告预览。",
        "passed_scenarios": _value(result, "passed_scenarios", 0),
        "total_scenarios": _value(result, "total_scenarios", 0),
        "covered_node_count": len(covered_nodes),
        "uncovered_nodes": result.get("uncovered_nodes") or [],
        "passed_nodes": _value(result, "passed_nodes", 0),
        "total_nodes": _value(result, "total_nodes", 0),
        "candidate_price": _value(result, "candidate_price", result.get("recommended_price", "-")),
        "current_price": _value(result, "current_price"),
        "conservative_price": _value(result, "conservative_price"),
        "decision_strength": _value(result, "decision_strength", "preview_only"),
        "contract_input_coverage": _value(result, "contract_input_coverage"),
        "runtime_feed_coverage": _value(result, "runtime_feed_coverage"),
        "algorithm_usage_coverage": _value(result, "algorithm_usage_coverage"),
        "algorithm_used_inputs": _inline_list(result.get("algorithm_used_inputs")),
        "algorithm_unused_available_inputs": _inline_list(result.get("algorithm_unused_available_inputs")),
        "conversion_problem": _value(result, "conversion_problem"),
        "exposure": _value(result, "exposure"),
        "exposure_unit": _value(result, "exposure_unit"),
        "exposure_metric_name": _value(result, "exposure_metric_name"),
        "payment_conversion_rate": _value(result, "payment_conversion_rate"),
        "payment_conversion_rate_basis": _value(result, "payment_conversion_rate_basis"),
        "our_price_index": _value(result, "our_price_index"),
        "current_window_type": _value(result, "current_window_type"),
        "approval_preview_allowed": _fmt_bool(result.get("approval_preview_allowed")),
        "formal_approval_allowed": _fmt_bool(result.get("formal_approval_allowed")),
        "risk_level": _value(result, "risk_level", result.get("risk", "-")),
        "floor_price": _value(result, "floor_price", preview.get("floor_price", "-")),
        "ceiling_price": _value(result, "ceiling_price", preview.get("ceiling_price", "-")),
        "execution_price": _value(result, "execution_price", preview.get("execution_price", "-")),
        "live_execution_count": _value(result, "live_execution_count", 0),
        "blocked_reasons": _bullet(blocked_reasons),
        "html_report_preview_status": _value(result, "html_report_preview_status"),
        "publisher_status": _value(result, "publisher_status"),
        "report_url": _value(result, "report_url", "未配置公开报告服务"),
        "report_id": _value(result, "report_id"),
        "field_coverage_rate": _coverage_rate(result),
        "ota_health_score": _value(result, "ota_health_score"),
        "hos_score": _value(result, "hos_score"),
        "content_score": _value(result, "content_score"),
        "ranking": _value(result, "ranking"),
        "run_id": _value(result, "run_id"),
        "intent": _value(result, "intent"),
        "node_id": _value(result, "node_id"),
        "skill_id": _value(result, "skill_id"),
        "agent_id": _value(result, "agent_id"),
        "scenario_id": _value(result, "scenario_id"),
        "generated_by_runtime": _value(result, "generated_by_runtime"),
        "freshness_status": _value(result, "freshness_status"),
        "runtime_command": _value(result, "runtime_command"),
        "blocked_reason": _value(result, "blocked_reason"),
        "personal_role": _value(result, "personal_role", result.get("auth_role") or "guest"),
        "auth_backend": _value(result, "auth_backend"),
        "tenant_status": _value(result, "tenant_status"),
        "identity_present": _fmt_bool(result.get("identity_present")),
        "chat_bound": _fmt_bool(result.get("chat_bound")),
        "payload_summary": _payload_summary(result),
        "member_role_summary": _management_membership_summary(result),
        "price_guard_summary": _management_guard_summary(result),
        "pending_configuration_summary": _management_pending_summary(result),
        "audit_event_count": _value(result, "audit_event_count", 0),
        "audit_chain_valid": _fmt_bool(result.get("audit_chain_valid")),
        "as_of_time": _value(result, "as_of_time"),
        "as_of_actual_sold_rooms": _value(result, "as_of_actual_sold_rooms"),
        "as_of_target_sold_rooms": _value(result, "as_of_target_sold_rooms"),
        "as_of_checkpoint_gap": _value(result, "as_of_checkpoint_gap"),
        "daily_remaining_gap": _value(result, "daily_remaining_gap"),
        "pickup_speed": _value(result, "pickup_speed"),
        "progress_status": _value(result, "progress_status"),
        "completion_rate": _value(result, "completion_rate"),
        "target_room_nights": _value(result, "target_room_nights"),
        "baseline_confidence": _value(result, "baseline_confidence"),
        "active_target_source": _value(result, "active_target_source"),
        "hourly_target_summary": "已加载" if result.get("hourly_target_curve") else "-",
        "actual_hourly_sales": _progress_table(
            result.get("actual_hourly_sales"),
            [("hour", "hour"), ("actual", "sold_rooms"), ("increment", "orders_increment"), ("occ", "occupancy_rate")],
        ),
        "target_hourly_curve": _progress_table(
            result.get("target_hourly_curve"),
            [("hour", "hour"), ("target", "target_sold_rooms")],
        ),
        "actual_vs_target_hourly": _progress_table(
            result.get("actual_vs_target_hourly"),
            [("hour", "hour"), ("actual", "actual_sold_rooms"), ("target", "target_sold_rooms"), ("gap", "gap")],
        ),
        "holiday_source": _value(result, "holiday_source"),
        "event_source": _value(result, "event_source"),
        "weather_source": _value(result, "weather_source"),
        "regional_heat_source": _value(result, "regional_heat_source"),
        "market_context_status": _value(result, "market_context_status"),
        "event_discovery_reason": _value(result, "event_discovery_reason"),
        "weather_reason": _value(result, "weather_reason"),
        "regional_heat_missing_fields": _inline_list(result.get("regional_heat_missing_fields")),
        "local_event_count": _value(result.get("event_context") or {}, "local_event_count", 0),
        "event_heat_level": _value(result.get("event_context") or {}, "event_heat_level"),
        "weather_risk_level": _value(result.get("weather_context") or {}, "weather_risk_level"),
        "weather_signal": _value(result.get("weather_context") or {}, "weather_signal"),
        "regional_heat_index": _value(result.get("regional_heat_context") or {}, "regional_heat_index"),
        "chat_bound": _fmt_bool(result.get("chat_bound")),
        "binding_status": _value(result, "binding_status"),
        "resolved_hotel_id": _value(result, "resolved_hotel_id", result.get("hotel_id", "-")),
        "chat_type": _value(result, "chat_type"),
        "channel_source": _value(result, "channel_source"),
        "execute_status": _value(result, "execute_status"),
        "inserted_task_count": _value(result, "inserted_task_count", 0),
        "expanded_product_count": _value(result, "expanded_product_count", 0),
        "skipped_product_count": _value(result, "skipped_product_count", 0),
        "task_db_kind": _value(result, "task_db_kind"),
        "active_campaign_count": _value((result.get("evidence") or {}).get("promotion_context") or {}, "active_campaign_count", 0),
        "campaign_room_type_count": _value((result.get("evidence") or {}).get("promotion_context") or {}, "campaign_room_type_count", 0),
        "campaign_platforms": _inline_list(((result.get("evidence") or {}).get("promotion_context") or {}).get("campaign_platforms")),
        "data_snapshot_time": _value(result, "data_snapshot_time"),
        "s10_promotion_observation": _bullet(
            ((result.get("evidence") or {}).get("s10_promotion_observation") or {}).get("observations"),
            "S10 推广表现未形成可用观测。",
        ),
        "s11_operating_observation": _bullet(
            ((result.get("evidence") or {}).get("s11_operating_observation") or {}).get("observations"),
            "经营进度暂未形成可用观测。",
        ),
        "s11_traffic_observation": _bullet(
            ((result.get("evidence") or {}).get("s11_traffic_observation") or {}).get("observations"),
            "当日流量仅作参考，当前未形成可用观测。",
        ),
        "s11_plan_recommendations": _bullet(
            ((result.get("evidence") or {}).get("s11_plan_recommendations") or {}).get("observations"),
            "暂无分计划建议。",
        ),
        "s11_promotion_window": _value(
            result.get("evidence") or {}, "s11_promotion_window", "统计窗口和抓取时间暂未提供"
        ),
    }


def _template_for_intent(result: dict[str, Any]) -> str:
    intent = result.get("intent")
    if intent in {"multi_intent_summary", "multi_intent_too_many", "feishu_route_error"}:
        return "system_health"
    if intent == "identity":
        return "identity"
    if intent == "chat_binding_status":
        return "chat_binding_status"
    if intent in {"health_ping", "runtime_status"}:
        return "system_health"
    if intent == "model_config_request":
        return "model_config_blocked"
    if intent == "config_change_request":
        return "config_change_blocked"
    if intent in {"member_role_status", "price_guard_status", "pending_configuration_requests", "configuration_audit_summary"}:
        return "management_control"
    if intent == "priceable_product_list":
        return "business_snapshot"
    if intent == "maintenance_safety_refusal":
        return "live_blocked"
    if intent == "menu" or intent == "enter_demo_mode":
        return "menu"
    if intent in {"demo_node_all"}:
        return "node_check_summary"
    if intent in {"demo_chain_all", "full_chain_demo", "developer_detail"}:
        return "full_chain_demo"
    if intent in {"run_s02", "run_s02_demo"}:
        return "business_snapshot"
    if intent == "historical_room_type_performance":
        return "business_snapshot"
    if intent == "sales_baseline_demo":
        return "sales_baseline"
    if intent == "progress_deviation_demo":
        return "progress_diagnosis"
    if intent == "business_calendar":
        return "business_calendar"
    if intent == "market_context_demo":
        return "market_context_demo"
    if intent == "price_task_outbox_write":
        return "price_task_outbox_write"
    if intent == "promotion_suggestion":
        return "promotion_suggestion"
    if intent in {"revenue_decision", "revenue_decision_demo"}:
        return "revenue_decision"
    if intent in {"price_execution_dry_run", "promotion_execute_dry_run"}:
        return "execution_dry_run"
    if intent == "live_execution_request":
        return "live_blocked"
    if intent == "third_party_report_preview":
        return "external_ota_report"
    return "business_snapshot"


def _render_template(name: str, context: dict[str, Any]) -> str:
    return load_template(name).format(**context)


def _frontdesk_text(result: dict[str, Any]) -> str:
    return (
        "【前台任务视图】\n\n"
        "数据标签：演示数据，不代表真实经营。\n\n"
        "一、结论\n"
        "当前仅展示前台可执行事项：房态提醒、客诉跟进、到离店沟通。\n\n"
        "二、边界\n"
        "调价、推广执行、审批请求体和算法细节不在前台视图展示。"
    )


def _operator_text(result: dict[str, Any]) -> str:
    base = _render_template(_template_for_intent(result), _context(result))
    return f"{base}\n\n操作清单：核对数据标签，查看 dry-run 预览，确认阻断原因：{result.get('blocked_reason') or 'demo_data_never_live'}。"


def render_feishu_output(result: dict[str, Any], output_profile: str | None = None) -> dict[str, Any]:
    profile = output_profile or result.get("output_profile") or default_output_profile(result.get("auth_role"))
    system_template = _template_for_intent(result)
    if result.get("status") == "blocked" and result.get("business_result_generated") is False:
        text = _render_template("guest_limited", _context(result))
        return {
            "status": "ok",
            "output_profile": "guest_limited",
            "text": text,
            "visible_fields": ["permission_denied", "blocked_reason", "correlation_id"],
            "hidden_fields": sorted(INTERNAL_FIELDS),
            "message_send_attempted": False,
            "template": "guest_limited",
        }
    if result.get("intent") in {"health_ping", "runtime_status", "model_config_request", "config_change_request", "maintenance_safety_refusal"}:
        text = _render_template(system_template, _context(result))
        return {
            "status": "ok",
            "output_profile": "system_status",
            "text": text,
            "visible_fields": ["status", "summary", "blocked_reason", "live_allowed"],
            "hidden_fields": sorted(INTERNAL_FIELDS),
            "message_send_attempted": False,
            "template": system_template,
        }
    if profile == "developer_debug":
        text = _render_template("developer_debug", _context(result))
        visible_fields = sorted(result.keys())
    elif profile == "owner_business":
        text = _render_template(_template_for_intent(result), _context(result))
        visible_fields = ["conclusion", "data_status", "core_metrics", "risk", "next_action"]
    elif profile == "operator_workbench":
        text = _operator_text(result)
        visible_fields = ["task", "priority", "dry_run", "blocked_reason", "next_action"]
    elif profile == "frontdesk_task":
        text = _frontdesk_text(result)
        visible_fields = ["frontdesk_tasks", "room_status", "complaint_tasks", "guest_notes"]
    else:
        profile = "guest_limited"
        text = _render_template("guest_limited", _context(result))
        visible_fields = ["permission_denied"]
    return {
        "status": "ok",
        "output_profile": profile,
        "text": text,
        "visible_fields": visible_fields,
        "hidden_fields": sorted(INTERNAL_FIELDS - set(visible_fields)),
        "message_send_attempted": False,
        "template": "developer_debug" if profile == "developer_debug" else _template_for_intent(result) if profile in {"owner_business", "operator_workbench"} else profile,
    }


def build_feishu_send_payload(result: dict[str, Any], role: str | None = None) -> dict[str, Any]:
    if result.get("blocked_reason") == "s14_ext_migrated_to_independent_service":
        return {
            "text": result.get("summary") or "第三方营销诊断已迁移到独立服务，本项目不再处理该入口。",
            "card": None,
            "send_allowed": False,
            "output_profile": result.get("output_profile") or default_output_profile(role or result.get("auth_role")),
            "warnings": ["s14_ext_migrated_to_independent_service"],
            "data_source_type": result.get("data_source_type"),
            "freshness_status": result.get("freshness_status"),
        }
    if result.get("external_isolated") and result.get("intent") in {"third_party_report_preview", "s14_source_request"}:
        profile = result.get("output_profile") or "owner_business"
    else:
        profile = default_output_profile(role or result.get("auth_role"))
    if result.get("production_feishu") and profile == "developer_debug":
        return {
            "text": "您好，调试详情不能通过飞书业务通道发送。",
            "card": None,
            "send_allowed": False,
            "output_profile": "guest_limited",
            "warnings": ["developer_debug_local_only"],
            "data_source_type": result.get("data_source_type"),
            "freshness_status": result.get("freshness_status"),
        }
    rendered = render_feishu_output(result, profile)
    text = rendered["text"]
    if result.get("intent") == "historical_room_type_performance":
        text = render_historical_room_type_performance_reply(result)
    elif result.get("intent") in {"run_s02", "run_s02_demo"} and result.get("s2_contract") == "pms_room_type_forecast_v1" and result.get("operating_views"):
        text = render_s2_operating_reply(result["operating_views"])
    elif result.get("intent") == "revenue_decision":
        text = render_s5_real_reply(result)
    elif result.get("intent") == "price_execution_dry_run" and result.get("batch_dry_run"):
        text = _render_s6_batch_dry_run(result)
    elif result.get("intent") == "price_execution_dry_run" and result.get("runtime_command") == "s6-price-dry-run --real-product":
        product = result.get("selected_product") or {}
        guard = result.get("guard") or {}
        policy = result.get("price_guard_policy") or {}
        max_increase = guard.get("max_increase_pct", policy.get("max_increase_pct"))
        max_decrease = guard.get("max_decrease_pct", policy.get("max_decrease_pct"))

        def _change_limit(value: Any) -> str:
            try:
                return f"{float(value) * 100:.0f}%"
            except (TypeError, ValueError):
                return "-"

        lines = ["S6 调价 dry-run（真实数据，只预览）"]
        if result.get("blocked_reason") == "target_listing_price_must_be_whole_yuan":
            result = {**result, "blocked_reason": "目标挂牌价必须为整数元"}
        if result.get("status") == "blocked":
            lines.append(f"结论：已阻断，原因：{result.get('blocked_reason') or '-'}。")
        elif result.get("status") == "data_gap":
            lines.append(f"结论：数据不足，原因：{result.get('blocked_reason') or '-'}。")
        else:
            product_name = _short_ota_product_name(
                product.get("ota_product_name"),
                product.get("ota_product_id") or result.get("ota_product_id"),
                product.get("ota_room_type_name") or product.get("room_type_name"),
            )
            product_id = product.get("ota_product_id") or result.get("ota_product_id")
            lines.extend(
                [
                    f"商品：{product_name}（{result.get('channel_source') or '-'}"
                    f"{f'，OTA 商品 ID {product_id}' if product_id else ''}）",
                    f"价格：¥{product.get('current_price') or '-'} → ¥{result.get('execution_price') or '-'}；生效日：{result.get('business_date') or '-'}。",
                    f"单次变动限制：上调、下调均不超过 {_change_limit(max_increase)}（与 S5 一致）。",
                    "本次仅完成校验和预览，未创建审批、未写入调价任务、未调用渠道接口。",
                ]
            )
            if result.get("input_price_mode") == "net_revenue_target":
                try:
                    current_net = float(result["net_revenue_current"])
                    target_net = float(result["net_revenue_target"])
                    current_listing = float(product["current_price"])
                    target_listing = float(result["execution_price"])
                    net_change = (target_net / current_net - 1.0) * 100
                    listing_change = (target_listing / current_listing - 1.0) * 100
                    lines.append(
                        f"净收：¥{current_net:.2f} → ¥{target_net:.2f}（{net_change:+.1f}%）；"
                        f"挂牌价同步：¥{current_listing:.2f} → ¥{target_listing:.2f}（{listing_change:+.1f}%）。"
                    )
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    lines.append(
                        f"净收目标：¥{result.get('net_revenue_target') or '-'}；"
                        f"对应挂牌价 ¥{result.get('execution_price') or '-'}，"
                        f"预计净收 ¥{result.get('net_revenue_after_conversion') or '-'}。"
                    )
            elif result.get("net_revenue_preview_status") == "ok":
                try:
                    current_net = float(result["net_revenue_current"])
                    target_net = float(result["net_revenue_target"])
                    change = (target_net / current_net - 1.0) * 100
                    lines.append(
                        f"预计净收：¥{current_net:.2f} → ¥{target_net:.2f}（{change:+.1f}%）；"
                        "按当前佣金、有效活动与会员预期折算，不含用户券。"
                    )
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    pass
            elif result.get("input_price_mode") == "listing_price_target":
                lines.append("预计净收：暂不可计算（佣金或活动依据不足；不影响本次价格校验）。")
            requested_net = result.get("requested_net_revenue_target")
            if requested_net is not None and requested_net != result.get("net_revenue_target"):
                lines.append(
                    f"净收目标 ¥{float(requested_net):.2f}；挂牌价按整数元取整后，预计净收 ¥{float(result.get('net_revenue_target')):.2f}。"
                )
            if result.get("confirmation_command"):
                lines.append(
                    f"确认写入：回复「{result['confirmation_command']}」；令牌有效至 {result.get('confirmation_expires_at') or '-'}。"
                )
            elif result.get("confirmation_blocked_reason"):
                details = result.get("confirmation_blocked_details") or {}
                try:
                    change_pct = float(details["actual_change_pct"]) * 100
                    limit_pct = float(
                        details["max_increase_pct"] if change_pct >= 0 else details["max_decrease_pct"]
                    ) * 100
                    direction = "上调" if change_pct >= 0 else "下调"
                    lines.append(
                        f"未生成确认令牌：本次{direction} {abs(change_pct):.1f}%，超过单次{direction} {limit_pct:.0f}%的上限；"
                        "不能确认或写入调价任务。请调整目标价后重新执行 dry-run。"
                    )
                except (KeyError, TypeError, ValueError):
                    lines.append("未生成确认令牌：本次预览未通过执行校验，不能确认或写入调价任务。请调整目标价后重新执行 dry-run。")
            elif result.get("confirmation_unavailable_reason"):
                lines.append("本次预览未生成确认令牌，请在已连接控制库的生产会话中重新执行 dry-run。")
            trust_labels = {
                "confirmed_mapping": "人工确认映射",
                "exact_match_rule:manual": "人工规则精确匹配",
                "exact_match_rule:room_id": "房型 ID 精确匹配",
                "exact_match_rule:product_id": "商品 ID 精确匹配",
                "exact_match_rule:goods_id": "商品组 ID 精确匹配",
            }
            trust_basis = product.get("s6_task_mapping_trust_basis")
            if product.get("s6_task_mapping_ready"):
                lines.append(f"任务写入映射：可用（{trust_labels.get(trust_basis, '可信精确映射')}）；实际写入时仍会重新校验。")
            else:
                lines.append("商品映射暂不足以写入任务；本次仍可作为预览参考，确认写入时会重新校验可信精确映射。")
        if result.get("blocked_reason") == "active_price_guard_policy_required_before_live":
            lines.append("默认护栏仅用于预览；配置并启用商品级价格护栏后，才可进入确认写入。")
        text = "\n".join(lines)
    elif result.get("intent") == "price_execution_confirm":
        reason = str(result.get("reason") or result.get("blocked_reason") or "")
        if reason in {"s6_confirmation_token_required", "s6_confirmation_not_pending"}:
            text = (
                "S6 调价确认未执行\n"
                "未找到唯一有效的调价预览，未创建审批、未写入调价任务。\n"
                "请从最新 S6 预览卡复制完整的「确认调价 PRC-xxxx」后重试；不要只回复“确认”。"
            )
        elif reason == "s6_latest_preview_not_confirmable":
            preview = result.get("preview") or {}
            try:
                change_pct = float(preview["actual_change_pct"]) * 100
                limit_pct = float(
                    preview["max_increase_pct"] if change_pct >= 0 else preview["max_decrease_pct"]
                ) * 100
                direction = "上调" if change_pct >= 0 else "下调"
                text = (
                    "S6 调价确认未执行\n"
                    f"上一条预览未通过单次调价幅度校验：本次{direction} {abs(change_pct):.1f}%，超过单次{direction} {limit_pct:.0f}%的上限。\n"
                    "该预览未生成 PRC 确认令牌，不能创建审批或写入调价任务；请调整目标价后重新执行 dry-run。"
                )
            except (KeyError, TypeError, ValueError):
                text = "S6 调价确认未执行\n上一条预览未通过执行校验，未生成 PRC 确认令牌，不能写入调价任务。请调整目标价后重新执行 dry-run。"
        elif reason == "s6_confirmation_store_unavailable":
            text = (
                "S6 调价确认不可用\n"
                "确认令牌未能保存，未创建审批、未写入调价任务。请在控制库恢复后重新执行 dry-run。"
            )
        else:
            text = (
                "S6 调价确认未完成\n"
                f"原因：{reason or '确认条件未满足'}。未写入调价任务。"
            )
    elif result.get("intent") == "price_task_outbox_write":
        if result.get("status") == "queued" and result.get("execute_status") == "PENDING":
            if result.get("batch_write"):
                text = (
                    f"S6 批量调价任务已写入\n已写入 {result.get('task_count') or 0} 个独立任务，状态均为 PENDING，已进入渠道插件队列。\n"
                    "本次写入完成即返回，不等待插件执行或平台回查。"
                )
            else:
                text = (
                    "S6 调价任务已写入\n"
                    "状态：PENDING，已进入渠道插件队列。\n"
                    "本次写入完成即返回，不等待插件执行或平台回查。"
                )
        else:
            prefix = "S6 批量调价任务未完整写入" if result.get("task_count") else "S6 调价任务未写入"
            progress = f"已写入 {result.get('queued_count')} / {result.get('task_count')} 个。\n" if result.get("task_count") else ""
            text = f"{prefix}\n{progress}原因：{result.get('blocked_reason') or result.get('reason') or '任务写入失败'}。"
    elif result.get("intent") == "roi_decision":
        labels = {"meituan": "美团", "ctrip": "携程"}
        lines = ["S10 推广效果（真实数据只读）", "结论：以下是平台来源归因观测值，不等同于增量收益或净利润。"]
        platforms = result.get("platforms") or {}
        if not platforms:
            lines.append(f"未形成可用结果：{'、'.join(map(str, result.get('data_gaps') or [])) or 'source_missing'}")
        for platform, detail in platforms.items():
            items = detail.get("items") or []
            if not items:
                lines.append(f"\n{labels.get(platform, platform)}：无该酒店的推广表现记录。")
                continue
            lines.append(f"\n{labels.get(platform, platform)}")
            for item in items:
                if platform == "meituan":
                    plan_name = f"（{item['plan_name']}）" if item.get("plan_name") else ""
                    launch_name = f"（{item['launch_name']}）" if item.get("launch_name") else ""
                    scope = f"计划 {item.get('plan_id') or '-'}{plan_name} / 投放 {item.get('launch_id') or '-'}{launch_name}"
                else:
                    scope = "酒店渠道滚动窗口"
                lines.extend([
                    f"- {scope}｜{item.get('period_start_date') or '-'} 至 {item.get('period_end_date') or '-'}｜抓取 {item.get('snapshot_time') or '-'}｜状态 {item.get('promotion_status') or '-'}",
                    f"  曝光 {item.get('exposure_count') if item.get('exposure_count') is not None else '-'}；点击 {item.get('click_count') if item.get('click_count') is not None else '-'}；订单 {item.get('booking_order_count') if item.get('booking_order_count') is not None else '-'}；间夜 {item.get('room_night_count') if item.get('room_night_count') is not None else '-'}",
                    f"  归因金额 ¥{item.get('booking_order_amount') if item.get('booking_order_amount') is not None else '-'}；总花费 ¥{item.get('spend_amount') if item.get('spend_amount') is not None else '-'}；现金花费 ¥{item.get('cash_spend_amount') if item.get('cash_spend_amount') is not None else '-'}",
                    f"  CTR {item.get('ctr') if item.get('ctr') is not None else '-'}；CPC {item.get('cpc') if item.get('cpc') is not None else '-'}；CPA {item.get('cpa') if item.get('cpa') is not None else '-'}；每间夜成本 {item.get('cost_per_room_night') if item.get('cost_per_room_night') is not None else '-'}；观测 ROAS {item.get('observed_roas') if item.get('observed_roas') is not None else '-'}",
                    f"  归因金额－总花费 ¥{item.get('observed_media_net_revenue') if item.get('observed_media_net_revenue') is not None else '-'}（仅观测差额，非净利润）",
                ])
                if item.get("quality_flags"):
                    lines.append("  质量：" + "、".join(map(str, item["quality_flags"])))
            for portfolio in detail.get("portfolios") or []:
                lines.append(f"  同窗口组合：观测 ROAS {portfolio.get('observed_roas') if portfolio.get('observed_roas') is not None else '-'}；CPC {portfolio.get('cpc') if portfolio.get('cpc') is not None else '-'}；CPA {portfolio.get('cpa') if portfolio.get('cpa') is not None else '-'}（按总量加权）")
        gaps = result.get("data_gaps") or []
        if gaps:
            lines.append("\n数据缺口：" + "、".join(map(str, gaps)))
        lines.append("贡献估算：不可用（未配置兼容成本政策，且佣金、退款/取消口径不能与计划归因精确对齐）。")
        lines.append("增量 ROI：不可用（缺少批准的对照或可比基线）；未创建推广任务，也不产生继续/暂停投放结论。")
        text = "\n".join(lines)
    elif result.get("intent") == "competition_alert":
        context = (result.get("evidence") or {}).get("competitor_context") or {}
        text = render_s7_competition_reply(context)
    elif result.get("intent") == "price_execution_dry_run" and (
        result.get("blocked_reason") == "active_price_guard_policy_required_before_live"
        or (result.get("price_guard_policy") or {}).get("source") == "default_policy"
    ):
        lines = [
            "S6 调价 dry-run（只读）",
            "当前命中默认护栏层：可用于预览、涨跌幅风险提示和数据缺口诊断，但不等同于有效价格护栏。",
            "结论：未配置有效价格护栏，不能创建调价任务；确认也不能把默认护栏升级为可执行护栏。",
            "下一步：先通过 CFG 为该酒店、房型、渠道/OTA 商品配置并激活价格护栏。",
            "护栏生效后，重新读取最新价格并生成 dry-run；创建审批时必须明确单日或起止日期区间。",
            "本次未创建审批、未写入 outbox、未执行渠道调价。",
        ]
        text = "\n".join(lines)
    elif result.get("intent") == "competition_alert":
        context = (result.get("evidence") or {}).get("competitor_context") or {}
        labels = {
            "exact_product": "精确商品",
            "peer_aggregate": "同行聚合",
            "loss_context": "月度流失背景",
            "own_only": "仅本店",
        }
        lines = [
            "S7 竞态监控（真实数据只读）",
            "结论：仅按标注的可比等级展示；没有精确竞品商品记录时，不输出房型竞品价差。",
        ]
        for platform, item in (context.get("platforms") or {}).items():
            lines.append(f"\n{ {'meituan': '美团', 'ctrip': '携程'}.get(platform, platform) }")
            for peer in (item.get("peer_aggregate") or [])[:5]:
                label = labels[peer["comparison_level"]]
                metric_name = peer.get("metric_name") or peer.get("metric_code") or "指标"
                metric_code = peer.get("metric_code")
                metric = metric_name if metric_name == metric_code else f"{metric_name}（{metric_code}）"
                value = peer.get("own_value")
                average = peer.get("peer_average")
                rank = peer.get("rank_position")
                peer_count = peer.get("peer_count")
                suffix = f"，排名 {rank}/{peer_count}" if rank is not None and peer_count is not None else ""
                lines.append(
                    f"- {label}｜{metric}：本店 {value}，同行均值 {average}{suffix}，单位 {peer.get('metric_unit') or '-'}，"
                    f"业务日 {peer.get('business_date') or peer.get('period_end_date') or '-'}，抓取 {peer.get('snapshot_time') or '-'}"
                )
            for product in (item.get("own_products") or [])[:5]:
                lines.append(f"- {labels['own_only']}｜{product.get('ota_product_name') or product.get('ota_product_id') or '未命名商品'}：{product.get('price') or '-'}，状态 {product.get('product_state') or '-'}，业务日 {product.get('price_business_date') or '-'}")
            loss = item.get("loss_context")
            if loss:
                lines.append(f"- {labels['loss_context']}｜窗口 {loss.get('period_start_date') or '-'} 至 {loss.get('period_end_date') or '-'}：流失订单 {loss.get('loss_order_count') or '-'}，竞店 {loss.get('competitor_count') or '-'} 家，最低价范围 {loss.get('competitor_lowest_price_range') or '-'}")
            circle_context = item.get("competition_circle_context") or {}
            circles = circle_context.get("circles") or []
            if circles:
                lines.append("- 月度竞争圈与订单流失（美团；月度流失背景，非实时竞品商品价）：")
                for circle in circles[:8]:
                    price_range = circle.get("competitor_lowest_price_range") or ["-", "-"]
                    lines.append(
                        f"  - {circle.get('competition_circle_name') or '-'}：竞店 {circle.get('competitor_count') or 0} 家，"
                        f"流失订单 {circle.get('loss_order_count') or 0}，流失金额 ¥{circle.get('loss_order_amount') or 0}，"
                        f"竞店最低价 {price_range[0]}–{price_range[-1]}，窗口 {circle.get('period_start_date') or '-'} 至 {circle.get('period_end_date') or '-'}"
                    )
            activity = item.get("activity_context") or {}
            if activity.get("activity_count") or activity.get("activity_product_count"):
                lines.append(f"- {labels['own_only']}｜活动 {activity.get('activity_count', 0)} 个，商品 {activity.get('activity_product_count', 0)} 个，缺 canonical 房型映射 {activity.get('mapping_missing_count', 0)} 行")
        flags = context.get("quality_flags") or []
        if flags:
            lines.append("\n数据质量：" + "；".join(str(flag) for flag in flags))
        lines.append(f"抓取时间：{context.get('data_snapshot_time') or '-'}；本次不创建调价或推广任务。")
        text = "\n".join(lines)
    elif result.get("intent") == "priceable_product_list":
        platform_label = {"meituan": "美团", "ctrip": "携程"}.get(result.get("source_platform"), "OTA")
        lines = [
            f"{platform_label} 可调价商品清单（只读）",
            "展示口径：仅普通全天房；钟点房和超级团购已排除。",
        ]
        products = result.get("products") or []
        if not products:
            lines.append(f"暂无可展示商品：{result.get('blocked_reason') or 'ota_price_mapping_no_rows'}")
        for item in products[:30]:
            price = item.get("current_price")
            price_text = "-" if price in (None, "") else str(price)
            name = item.get("ota_product_name") or "未命名 OTA 商品"
            reason = PRICEABLE_PRODUCT_STATE_LABELS.get(item.get("state_reason"), "暂不具备调价条件")
            state = "可申请调价" if item.get("price_request_eligible") else f"仅查看（{reason}）"
            lines.append(f"- {item.get('channel') or '-'}｜{name}｜当前价 {price_text}｜{state}")
        lines.append(f"商品数：{result.get('product_count', 0)}；可申请调价：{result.get('eligible_product_count', 0)}")
        if result.get("excluded_unsupported_product_count"):
            lines.append(
                f"已排除：钟点房 / 超级团购 {result['excluded_unsupported_product_count']} 个。"
            )
        if result.get("excluded_sold_out_product_count"):
            lines.append(
                f"已排除：售完或关房商品 {result['excluded_sold_out_product_count']} 个。"
            )
        text = "\n".join(lines)
    elif result.get("intent") in {"chat_configuration_request", "chat_role_join_request", "chat_role_change_request", "chat_role_named_request"}:
        label = "角色变更申请" if result.get("intent") in {"chat_role_join_request", "chat_role_change_request", "chat_role_named_request"} else "配置申请"
        if result.get("status") in {"pending_confirmation", "pending_owner_approval"} and result.get("request_id"):
            text = "{label}已创建，尚未生效。\n申请编号：{request_id}\n确认命令：{command}\n过期时间：{expires_at}\nconfig_change_applied=False\nformal_approval_created=False\nlive_execution_count=0".format(
                label=label,
                request_id=result.get("request_id"),
                command=result.get("confirmation_command", "-"),
                expires_at=result.get("expires_at", "-"),
            )
        else:
            reason = result.get("reason") or result.get("blocked_reason") or "request_blocked"
            failed_label = "角色变更" if label == "角色变更申请" else label
            text = (
                f"{failed_label}未创建。\n"
                f"原因：{reason}\n"
                "建议：确认目标是否在当前绑定群、是否有唯一成员信息、是否由 owner/admin 发起。\n"
                "config_change_applied=False\nformal_approval_created=False\nlive_execution_count=0"
            )
    elif result.get("intent") == "identity":
        bound = "已绑定酒店：" + str(result.get("resolved_hotel_id")) if result.get("chat_bound") else "未绑定酒店，业务操作 blocked"
        text = (
            "身份与会话状态\n"
            f"个人角色：{result.get('personal_role') or result.get('auth_role')}\n"
            f"鉴权来源：{result.get('auth_backend')}\n"
            f"鉴权状态：{result.get('auth_status')}\n"
            f"租户状态：{result.get('tenant_status')}\n"
            f"当前会话类型：{result.get('chat_type')}\n"
            f"当前会话：{bound}\n"
            "本指令只检查身份、角色、群绑定和当前可用权限。\n"
            "经营数据、调价和诊断能力会在对应业务指令中单独校验权限与数据条件。"
        )
    elif result.get("intent") == "auth_path_explanation":
        text = (
            "鉴权路径\n"
            "runtime 层：读取 SQLite Active Auth，包括 auth_principals、chat_bindings/group_chat_bindings、hotel_memberships，再进入 permission_gate。\n"
            "bootstrap 文件：只用于 auth-bootstrap-sync bootstrap seed，不是日常运行时事实源。\n"
            f"当前消息诊断：auth_backend={result.get('auth_backend')}，auth_status={result.get('auth_status')}，tenant_status={result.get('tenant_status')}，chat_bound={bool(result.get('chat_bound'))}。"
        )
        text = (
            "鉴权路径\n"
            "当前主路径：Feishu channel → 路由绑定 → Agent → runtime feishu-route/auth-check → SQLite Active Auth → permission_gate。\n"
            "hotel-ota-feishu-auth 插件仅作为可选防护/诊断，不作为当前主鉴权入口。\n"
            "bootstrap 文件：只用于 auth-bootstrap-sync bootstrap seed，不是日常运行时事实源。\n"
            f"当前消息诊断：auth_backend={result.get('auth_backend')}，auth_status={result.get('auth_status')}，tenant_status={result.get('tenant_status')}，chat_bound={bool(result.get('chat_bound'))}。"
        )
    elif result.get("intent") == "member_role_status":
        role_scope = "当前群" if result.get("role_scope") == "current_chat" else "酒店级汇总"
        text = (
            f"{role_scope}成员权限\n"
            "运行时事实源：SQLite Active Auth。\n"
            "bootstrap 用途：auth-bootstrap-sync bootstrap seed。\n"
            f"hotel_id：{result.get('hotel_id') or result.get('resolved_hotel_id')}\n"
            f"角色数量：{_management_membership_summary(result)}\n"
            "角色变更必须走 ROLE 二次确认。"
        )
    elif result.get("intent") == "market_context_demo":
        text = (
            "S4 环境行情感知\n"
            f"weather_source：{result.get('weather_source')}\n"
            f"event_source：{result.get('event_source')}\n"
            f"display_location：{result.get('display_location') or '-'}\n"
            f"event_heat_level：{result.get('event_heat_level') or '-'}\n"
            "direct_price_trigger_allowed=false"
        )
    elif result.get("intent") == "s14_source_request":
        report_url = result.get("report_url") or "未配置公开报告服务"
        text = (
            "S14-EXT 外部 OTA 诊断报告\n"
            f"状态：{result.get('status') or '-'}\n"
            f"HTML 预览：{result.get('html_report_preview_status') or '-'}\n"
            f"发布状态：{result.get('publisher_status') or '-'}\n"
            f"查看完整诊断报告：{report_url}\n"
            "来源：注册 source_key；飞书正文不接收服务器路径。\n"
            "飞书上传 transport：未启用。\n"
            "正式审批：false\n"
            "live 执行：false"
        )
    elif result.get("intent") in {"chat_configuration_confirm", "chat_role_change_confirm"}:
        text = "您好，{summary}\n申请编号：{request_id}".format(
            summary=result.get("summary", "配置申请处理完成。"),
            request_id=result.get("request_id", "-"),
        )
    elif result.get("intent") in {"chat_configuration_cancel", "chat_role_change_cancel"}:
        text = "您好，{summary}\n申请编号：{request_id}".format(
            summary=result.get("summary", "配置申请处理完成。"),
            request_id=result.get("request_id", "-"),
        )
    elif result.get("intent") == "config_change_request":
        text = "您好，配置变更请求已拒绝。演示链路不需要打开真实 DB source；请使用批准的服务器维护流程。"
    elif result.get("intent") == "maintenance_safety_refusal":
        text = "您好，维护类命令不能在飞书业务通道执行。"
    if result.get("blocked_reason") in {"missing_required_feishu_auth_context", "missing_trusted_business_chat_id"}:
        text = (
            "飞书业务鉴权未通过。\n"
            f"原因：{result.get('blocked_reason')}\n"
            "本次消息缺少可信的飞书会话或发送人身份上下文，runtime 不能判断当前群是否已绑定酒店，也不能运行经营、调价或诊断业务。\n"
            "请通过生产飞书事件入口重试，并确保同一条消息带有真实会话 ID 和发送人身份。"
        )
    warnings = list(result.get("context_warnings") or [])
    try:
        max_text_chars = int(os.environ.get("HOTEL_OTA_FEISHU_TEXT_LIMIT", str(DEFAULT_FEISHU_TEXT_LIMIT)))
    except ValueError:
        max_text_chars = DEFAULT_FEISHU_TEXT_LIMIT
    if max_text_chars > 0 and len(text) > max_text_chars:
        suffix = "\n\n内容已截断；详细诊断仅限本地受信维护通道。"
        keep = max(max_text_chars - len(suffix), 0)
        text = text[:keep].rstrip() + suffix
        warnings.append("feishu_text_truncated")
    delivery_gate = evaluate_feishu_output_gate(source="feishu", content_kind="text", message=text)
    if delivery_gate.get("status") != "ok":
        warnings.append(f"feishu_output_gate:{delivery_gate.get('blocked_reason')}")
        text = "您好，该内容不能通过飞书业务通道发送。"
    return {
        "text": text,
        "card": None,
        "send_allowed": rendered.get("status") == "ok" and delivery_gate.get("status") == "ok",
        "output_profile": rendered["output_profile"],
        "warnings": warnings,
        "data_source_type": result.get("data_source_type"),
        "freshness_status": result.get("freshness_status"),
    }

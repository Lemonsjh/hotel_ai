from __future__ import annotations

import argparse
import re
from typing import Any, Callable

_INSTALLED = False
VERSION = "p0-route-ownership.v4"


def _normalize(message: str) -> str:
    text = str(message or "").strip().lower()
    return re.sub(r"[\s，。！？、；：,.!?;:]+", "", text)


_S2_EXACT = frozenset(
    _normalize(item)
    for item in (
        "今天经营怎么样",
        "今天经营好不好",
        "今日经营怎么样",
        "今天经营情况",
        "今日经营情况",
        "经营情况",
        "经营快照",
        "当前房态",
        "当前出租率",
    )
)

_S4_EXACT = frozenset(
    _normalize(item)
    for item in (
        "大盘冷不冷",
        "大盘是否冷",
        "今天市场怎么样",
        "今日市场怎么样",
        "市场怎么样",
        "市场热度怎么样",
        "大盘热度怎么样",
    )
)

_S16_EXACT = frozenset(
    _normalize(item)
    for item in (
        "今天流量怎么样",
        "今日流量怎么样",
        "流量怎么样",
        "浏览怎么样",
        "今天浏览怎么样",
        "一转怎么样",
        "今天一转怎么样",
        "二转怎么样",
        "今天二转怎么样",
        "销售进度怎么样",
        "今天销售进度怎么样",
    )
)

_S5_PRIMARY_TERMS = tuple(
    _normalize(item)
    for item in (
        "要不要调价",
        "是否需要调价",
        "需不需要调价",
        "该不该调价",
        "调价建议",
        "需要涨价",
        "要不要涨价",
        "需要降价",
        "要不要降价",
        "涨还是降",
        "该涨还是该降",
        "哪些商品需要调价",
        "哪些房型需要调价",
    )
)

_EXECUTION_TERMS = tuple(
    _normalize(item)
    for item in (
        "dry-run",
        "dry run",
        "执行预览",
        "调价预览",
        "确认执行",
        "立即执行",
        "同步房价",
        "提交审批",
    )
)

_S8_DISPLAY_EXACT = frozenset(
    _normalize(item)
    for item in (
        "推广通",
        "推广通数据",
        "查看推广通数据",
        "推广通表现",
        "推广通近30天表现",
        "推广近30天表现",
        "当前推广通快照",
        "推广通快照",
        "查看当前推广通快照",
    )
)

_S8_DISPLAY_TERMS = tuple(
    _normalize(item)
    for item in (
        "推广通数据",
        "推广通表现",
        "推广通近30天",
        "推广近30天表现",
        "推广通快照",
    )
)

_S8_FACT_METRIC_TERMS = tuple(
    _normalize(item)
    for item in (
        "花了多少钱",
        "花费",
        "费用",
        "消耗",
        "曝光",
        "点击",
        "订单",
        "间夜",
        "订单额",
    )
)

_S8_DAY_SCOPE_TERMS = tuple(
    _normalize(item)
    for item in (
        "今天",
        "今日",
        "当天",
        "昨天",
        "昨日",
        "单日",
    )
)

_S8_PERIOD_SCOPE_TERMS = tuple(
    _normalize(item)
    for item in (
        "近30天",
        "最近30天",
        "近30日",
        "最近30日",
        "30天",
        "30日",
        "统计周期",
        "周期累计",
    )
)

_S8_NON_DISPLAY_TERMS = tuple(
    _normalize(item)
    for item in (
        "建议",
        "怎么做",
        "要不要",
        "值不值",
        "是否值得",
        "roi",
        "效果",
        "预算",
        "出价",
        "执行",
        "打开",
        "开启",
        "关闭",
        "暂停",
        "扩量",
        "投放策略",
    )
)


def _is_s8_display_request(message: str) -> bool:
    normalized = _normalize(message)
    if not normalized:
        return False
    if any(term in normalized for term in _S8_NON_DISPLAY_TERMS):
        return False
    if normalized in _S8_DISPLAY_EXACT:
        return True
    if "推广通" in normalized and any(term in normalized for term in _S8_DISPLAY_TERMS):
        return True
    return "推广" in normalized and any(
        term in normalized for term in _S8_FACT_METRIC_TERMS
    )


def _is_s8_daily_fact_request(message: str) -> bool:
    normalized = _normalize(message)
    if not _is_s8_display_request(message):
        return False
    if any(term in normalized for term in _S8_PERIOD_SCOPE_TERMS):
        return False
    return any(term in normalized for term in _S8_DAY_SCOPE_TERMS) and any(
        term in normalized for term in _S8_FACT_METRIC_TERMS
    )


def _display_number(value: Any, *, money: bool = False, percent: bool = False) -> str:
    if value in (None, ""):
        return "-"
    if value == "not_computable":
        return "不可计算"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if money:
        return f"¥{number:.2f}".rstrip("0").rstrip(".")
    if percent:
        return f"{number:.2f}%".rstrip("0").rstrip(".")
    return f"{number:.4f}".rstrip("0").rstrip(".")


def _render_s8_display_text(result: dict[str, Any]) -> str:
    if result.get("blocked_reason") == "s8_daily_granularity_unavailable":
        return str(result.get("summary") or "")

    display = ((result.get("evidence") or {}).get("promotion_display") or {})
    source_table = display.get("source_table") or "meituan_ota_promotion_performance_30d"
    lines = [
        "S8 推广通数据（真实数据只读）",
        f"来源：{source_table}",
    ]
    if display.get("data_snapshot_time"):
        lines.append(f"快照：{display.get('data_snapshot_time')}")
    if display.get("period_start_date") or display.get("period_end_date"):
        lines.append(
            f"统计周期：{display.get('period_start_date') or '-'} 至 {display.get('period_end_date') or '-'}"
        )

    items = display.get("items") if isinstance(display.get("items"), list) else []
    if not items:
        if display.get("source_status") == "no_rows":
            lines.append("当前最新快照没有可展示的推广通数据。")
        else:
            lines.append(
                f"未形成可用推广通数据：{display.get('reason') or result.get('summary') or 'source_unavailable'}"
            )
        lines.append("边界：仅展示推广通事实与确定性计算，不生成建议、审批、任务或执行动作。")
        return "\n".join(lines)

    lines.append(f"投放单元：{len(items)} 个")
    for item in items:
        lines.extend(
            [
                "",
                (
                    f"- 推广计划：{item.get('plan_name') or '-'}｜"
                    f"投放单元：{item.get('launch_name') or '-'}｜"
                    f"推广产品：{item.get('promotion_name') or '-'}"
                ),
                (
                    f"  花费 {_display_number(item.get('spend_amount'), money=True)}，"
                    f"现金花费 {_display_number(item.get('cash_spend_amount'), money=True)}；"
                    f"曝光 {_display_number(item.get('exposure_count'))}，"
                    f"点击 {_display_number(item.get('click_count'))}，"
                    f"订单 {_display_number(item.get('booking_order_count'))}，"
                    f"间夜 {_display_number(item.get('room_night_count'))}，"
                    f"推广订单额 {_display_number(item.get('booking_order_amount'), money=True)}。"
                ),
                (
                    f"  获客成本 {_display_number(item.get('cost_per_booking'), money=True)}，"
                    f"单间夜成本 {_display_number(item.get('cost_per_room_night'), money=True)}，"
                    f"平均推广订单金额 {_display_number(item.get('average_booking_order_amount'), money=True)}，"
                    f"推广 ADR {_display_number(item.get('promotion_adr'), money=True)}。"
                ),
                (
                    f"  ROAS {_display_number(item.get('roas'))}，"
                    f"现金 ROAS {_display_number(item.get('cash_roas'))}，"
                    f"预订转化 {_display_number(item.get('booking_conversion_rate_pct'), percent=True)}，"
                    f"推广花费后金额 {_display_number(item.get('promotion_amount_after_spend'), money=True)}，"
                    f"点击率（来源值）{_display_number(item.get('click_rate_pct'), percent=True)}。"
                ),
            ]
        )
    lines.append("")
    lines.append("边界：仅展示推广通事实与确定性计算，不生成建议、审批、任务或执行动作。")
    return "\n".join(lines)


def _wrap_s8_route(
    router: Any,
    previous: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    def route_feishu_command(message: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if router._detect_intent(message) != "s8_promotion_display":
            return previous(message, *args, **kwargs)

        role = kwargs.get("role") or "guest"
        output_profile = kwargs.get("output_profile")
        hotel_id = kwargs.get("hotel_id")
        render = bool(kwargs.get("render", False))
        as_of_time = kwargs.get("as_of_time")
        result = router._base_result(
            "s8_promotion_display",
            role=role,
            output_profile=output_profile,
        )
        if not hotel_id:
            result.update(
                {
                    "status": "data_gap",
                    "intent": "s8_promotion_display",
                    "node_id": "N012",
                    "skill_id": "S8",
                    "runtime_command": "promotion-plan --display-only",
                    "business_result_generated": False,
                    "data_source_type": "unavailable",
                    "blocked_reason": "hotel_id_required",
                    "approval_data_allowed": False,
                    "formal_approval_allowed": False,
                    "formal_approval_created": False,
                    "live_allowed": False,
                    "live_execution_count": 0,
                }
            )
        elif _is_s8_daily_fact_request(message):
            result.update(
                {
                    "status": "data_gap",
                    "intent": "s8_promotion_display",
                    "node_id": "N012",
                    "skill_id": "S8",
                    "agent_id": router.agent_id_for_node("N012"),
                    "runtime_command": None,
                    "hotel_id": hotel_id,
                    "summary": (
                        "当前 S8 固定数据源只有近30天周期快照，不能把周期累计值冒充今天/昨日单日值。"
                        "这是事实查询，可在20秒响应预算内尝试一次受控只读数据库补查；"
                        "如果20秒内仍不能形成可靠答案，就结束本轮并提示你回复“继续查询”再深入查。"
                    ),
                    "evidence": {
                        "promotion_display": {
                            "source_table": "meituan_ota_promotion_performance_30d",
                            "source_status": "unsupported_time_granularity",
                            "requested_time_granularity": "day",
                            "supported_time_granularity": "rolling_30d_snapshot",
                            "items": [],
                        }
                    },
                    "business_result_generated": False,
                    "data_source_type": "unavailable",
                    "data_business_date": None,
                    "data_snapshot_time": None,
                    "freshness_status": "not_applicable",
                    "blocked_reason": "s8_daily_granularity_unavailable",
                    "fallback_eligible": True,
                    "fallback_type": "read_only_fact_sql",
                    "fallback_reason": "native_time_granularity_missing",
                    "continuation_allowed": True,
                    "continuation_trigger": "继续查询",
                    "response_budget_seconds": 20,
                    "approval_data_allowed": False,
                    "formal_approval_allowed": False,
                    "formal_approval_created": False,
                    "live_allowed": False,
                    "live_execution_count": 0,
                    "write_performed": False,
                }
            )
        else:
            from runtime.decisions.promotion import promotion_plan

            promotion = router._capture_runtime_emit(
                promotion_plan,
                argparse.Namespace(hotel_id=hotel_id, as_of_time=as_of_time),
            )
            result.update(promotion)
            display = ((promotion.get("evidence") or {}).get("promotion_display") or {})
            source_status = display.get("source_status")
            result.update(
                {
                    "intent": "s8_promotion_display",
                    "node_id": "N012",
                    "skill_id": "S8",
                    "agent_id": router.agent_id_for_node("N012"),
                    "runtime_command": "promotion-plan --display-only",
                    "hotel_id": hotel_id,
                    "data_source_type": "mysql_db" if source_status in {"ok", "no_rows"} else "unavailable",
                    "data_business_date": display.get("data_business_date"),
                    "data_snapshot_time": display.get("data_snapshot_time"),
                    "business_result_generated": promotion.get("status") == "ok",
                    "approval_data_allowed": False,
                    "formal_approval_allowed": False,
                    "formal_approval_created": False,
                    "live_allowed": False,
                    "live_execution_count": 0,
                    "write_performed": False,
                    "blocked_reason": "s8_display_only",
                }
            )

        if render:
            result["rendered"] = router.render_feishu_output(
                result, result.get("output_profile")
            )
            result["send_payload"] = router.build_feishu_send_payload(
                result, role=role
            )
        return result

    route_feishu_command._S8_FEISHU_DISPLAY_ROUTE_V1 = True  # type: ignore[attr-defined]
    return route_feishu_command


def _wrap_s8_send_payload(
    previous: Callable[..., dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    def build_feishu_send_payload(
        result: dict[str, Any],
        role: str | None = None,
    ) -> dict[str, Any]:
        payload = dict(previous(result, role=role))
        if result.get("intent") == "s8_promotion_display" and result.get("skill_id") == "S8":
            payload["text"] = _render_s8_display_text(result)
            payload["send_allowed"] = True
            payload["warnings"] = []
            payload["data_source_type"] = result.get("data_source_type")
            payload["freshness_status"] = result.get("freshness_status")
        return payload

    build_feishu_send_payload._S8_FEISHU_DISPLAY_ROUTE_V1 = True  # type: ignore[attr-defined]
    return build_feishu_send_payload


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import feishu_command_router as router
    from runtime import feishu_output_renderer as renderer

    previous = router._detect_intent
    if not getattr(previous, "_P0_ROUTE_OWNERSHIP_V2", False):

        def detect_intent(message: str) -> str:
            normalized = _normalize(message)
            if not normalized:
                return previous(message)

            if _is_s8_display_request(message):
                return "s8_promotion_display"
            if normalized in _S2_EXACT:
                return "run_s02_demo"
            if normalized in _S4_EXACT:
                return "market_context_demo"
            if normalized in _S16_EXACT:
                return "progress_deviation_demo"

            if not any(term in normalized for term in _EXECUTION_TERMS):
                if any(term in normalized for term in _S5_PRIMARY_TERMS):
                    return "revenue_decision"

            return previous(message)

        detect_intent._P0_ROUTE_OWNERSHIP_V1 = True  # type: ignore[attr-defined]
        detect_intent._P0_ROUTE_OWNERSHIP_V2 = True  # type: ignore[attr-defined]
        detect_intent._P0_ROUTE_OWNERSHIP_VERSION = VERSION  # type: ignore[attr-defined]
        router._detect_intent = detect_intent

    router.PROTECTED_BUSINESS_INTENTS.add("s8_promotion_display")

    previous_route = router.route_feishu_command
    if not getattr(previous_route, "_S8_FEISHU_DISPLAY_ROUTE_V1", False):
        router.route_feishu_command = _wrap_s8_route(router, previous_route)

    previous_send = router.build_feishu_send_payload
    if not getattr(previous_send, "_S8_FEISHU_DISPLAY_ROUTE_V1", False):
        wrapped_send = _wrap_s8_send_payload(previous_send)
        router.build_feishu_send_payload = wrapped_send
        renderer.build_feishu_send_payload = wrapped_send
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


_INSTALLED = False
VERSION = "s4-s16-market-heat-contract.v1"
FORBIDDEN_INTERPRETATIONS = [
    "event_heat_score_as_market_heat",
    "regional_heat_partial_as_market_heat",
    "event_heat_score_as_demand_index",
]


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _capture_emit(func: Any, namespace: argparse.Namespace) -> dict[str, Any]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(namespace)
    output = buffer.getvalue().strip()
    if not output:
        return {
            "status": "error",
            "reason": "runtime_command_returned_empty_output",
        }
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        return {
            "status": "error",
            "reason": f"runtime_command_returned_invalid_json:{exc.msg}",
        }


def _regional_semantics(
    regional_heat_context: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], float | None]:
    regional = _mapping(regional_heat_context)
    scores = _mapping(regional.get("component_scores"))
    available = [
        key
        for key, value in scores.items()
        if _number(value) is not None
    ]
    event_score = _number(scores.get("event_heat"))
    event_only = available == ["event_heat"]

    if event_only:
        label = "周边事件单项分"
        semantics = "event_only_environment_signal"
    elif available:
        label = "区域环境综合信号"
        semantics = (
            "partial_environment_composite"
            if regional.get("status") == "partial"
            else "environment_composite"
        )
    else:
        label = "区域环境信号"
        semantics = "environment_signal_unavailable"

    regional.update(
        {
            "display_label": label,
            "score_semantics": semantics,
            "available_components": available,
            "event_only": event_only,
            "is_market_heat": False,
            "is_demand_index": False,
            "market_heat_eligible": False,
            "demand_index_eligible": False,
            "metric_contract_version": VERSION,
        }
    )
    return regional, event_score


def annotate_market_context_result(
    result: Mapping[str, Any] | None,
    s16_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    from runtime.s5_s16_market_heat_sync_patch import (
        s5_market_evidence_from_s16,
    )

    annotated = _mapping(result)
    regional, event_score = _regional_semantics(
        annotated.get("regional_heat_context")
    )
    annotated["regional_heat_context"] = regional
    annotated["event_heat_score"] = event_score
    annotated["event_heat_score_label"] = "周边事件单项分"
    annotated["event_heat_score_is_market_heat"] = False
    annotated["event_heat_score_is_demand_index"] = False

    evidence = s5_market_evidence_from_s16(s16_result)
    evidence = _mapping(evidence)
    calculation_ok = (
        evidence.get("market_heat_calculation_status") == "ok"
        and _number(evidence.get("market_heat_ratio")) is not None
    )
    ratio = _number(evidence.get("market_heat_ratio")) if calculation_ok else None
    reason = (
        None
        if calculation_ok
        else str(
            evidence.get("market_heat_calculation_reason")
            or "s16_market_heat_unavailable"
        )
    )
    evidence.update(
        {
            "source_capability": "S16",
            "fallback_used": False,
            "event_score_fallback_allowed": False,
            "contract_version": VERSION,
        }
    )

    demand_index = _number(annotated.get("demand_index"))
    demand_status = "ok" if demand_index is not None else "data_gap"
    demand_reason = (
        None
        if demand_index is not None
        else str(
            annotated.get("demand_index_reason")
            or "s4_demand_index_inputs_incomplete"
        )
    )

    annotated.update(
        {
            "market_heat_context": evidence,
            "market_heat_ratio": ratio,
            "market_status": (
                evidence.get("market_status")
                if calculation_ok
                else "unavailable"
            ),
            "market_heat_calculation_status": (
                "ok" if calculation_ok else "unavailable"
            ),
            "market_heat_calculation_reason": reason,
            "market_heat_source": "S16",
            "market_heat_fallback_used": False,
            "market_heat_event_score_fallback_allowed": False,
            "demand_index": demand_index,
            "demand_index_status": demand_status,
            "demand_index_reason": demand_reason,
            "metric_semantics_contract": {
                "contract_version": VERSION,
                "market_heat_source": "S16",
                "market_heat_definition": (
                    "S16 projected or completed full-day market orders "
                    "divided by historical full-day market-order baseline"
                ),
                "event_score_definition": (
                    "nearby-event environment signal only; never market heat"
                ),
                "regional_heat_definition": (
                    "environment composite or partial signal; never a "
                    "substitute for market heat or demand_index"
                ),
                "forbidden_interpretations": list(
                    FORBIDDEN_INTERPRETATIONS
                ),
            },
        }
    )

    if calculation_ok:
        annotated["summary"] = (
            "大盘热度来自 S16 统一口径；周边活动分仅为环境单项信号，"
            "不代表大盘热度或需求指数。"
        )
    else:
        annotated["summary"] = (
            f"大盘热度不可计算（{reason}）；不使用周边活动分回退。"
            "周边活动分仅作为环境单项信号。"
        )
    return annotated


def _format_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "-"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}".rstrip("0").rstrip(".")


def render_s4_market_text(result: Mapping[str, Any]) -> str:
    evidence = _mapping(result.get("market_heat_context"))
    regional = _mapping(result.get("regional_heat_context"))
    ratio = _number(result.get("market_heat_ratio"))
    calculation_ok = (
        result.get("market_heat_calculation_status") == "ok"
        and ratio is not None
    )
    lines = ["S4 环境行情感知"]

    if calculation_ok:
        basis = str(evidence.get("market_orders_basis") or "")
        market_orders = evidence.get("market_orders")
        baseline = evidence.get("baseline_market_orders")
        current = evidence.get("current_market_orders")
        if basis == "s16_linear_projected_full_day":
            lines.append(
                "大盘热度："
                f"{ratio:.2f}（当前累计大盘订单 {_format_number(current)}，"
                f"S16 预计全天 {_format_number(market_orders)} ÷ "
                f"历史完整日基线 {_format_number(baseline)}）"
            )
        else:
            lines.append(
                "大盘热度："
                f"{ratio:.2f}（S16 大盘订单 {_format_number(market_orders)} ÷ "
                f"历史完整日基线 {_format_number(baseline)}）"
            )
        status_label = {
            "cold": "低于历史基线",
            "normal": "接近历史基线",
            "hot": "高于历史基线",
        }.get(str(result.get("market_status") or ""), "状态未分类")
        lines.append(f"大盘状态：{status_label}；来源：S16")
    else:
        reason = (
            result.get("market_heat_calculation_reason")
            or "s16_market_heat_unavailable"
        )
        lines.append(
            f"大盘热度：不可计算（{reason}）；未使用周边事件分回退。"
        )

    event_score = _number(result.get("event_heat_score"))
    if event_score is not None:
        lines.append(
            "周边事件单项分："
            f"{_format_number(event_score)}"
            "（仅周边活动环境信号，不代表大盘热度或需求指数）"
        )
    elif _number(regional.get("regional_heat_index")) is not None:
        lines.append(
            f"{regional.get('display_label') or '区域环境信号'}："
            f"{_format_number(regional.get('regional_heat_index'))}"
            "（不代表大盘热度或需求指数）"
        )
    else:
        lines.append("周边事件单项分：不可用")

    demand_index = _number(result.get("demand_index"))
    if demand_index is None:
        lines.append(
            "环境需求指数：不可计算（"
            f"{result.get('demand_index_reason') or '输入维度不完整'}）"
        )
    else:
        lines.append(f"环境需求指数：{_format_number(demand_index)}")

    weather = _mapping(result.get("weather_context"))
    events = _mapping(result.get("event_context"))
    if weather:
        lines.append(
            "天气信号："
            f"{weather.get('weather_signal') or '-'}"
            f"（风险 {weather.get('weather_risk_level') or '-'}）"
        )
    if events:
        lines.append(
            "周边活动："
            f"{events.get('local_event_count') or 0} 个，"
            f"热度等级 {events.get('event_heat_level') or '-'}"
        )
    lines.append("S4 只提供只读行情信号，不直接触发调价。")
    return "\n".join(lines)


def _replace_prebound_market_context(
    previous: Any,
    replacement: Any,
) -> None:
    for name, module in list(sys.modules.items()):
        if not name.startswith("runtime.") or module is None:
            continue
        if getattr(module, "market_context", None) is previous:
            setattr(module, "market_context", replacement)


def _install_calendar_patch() -> None:
    from runtime import common
    from runtime.decisions import calendar as calendar_module
    from runtime.decisions import deviation as deviation_module

    previous = calendar_module.market_context

    def market_context_with_s16(args: argparse.Namespace) -> None:
        base_result = _capture_emit(previous, args)
        business_date = str(
            base_result.get("business_date")
            or getattr(args, "date", None)
            or common.today()
        )[:10]
        try:
            s16_result = _capture_emit(
                deviation_module.deviation,
                argparse.Namespace(
                    hotel_id=getattr(args, "hotel_id", None),
                    date=business_date,
                    as_of_time=getattr(args, "as_of_time", None),
                    db=getattr(args, "db", None),
                    use_generated_today=False,
                    strict_generated_today=False,
                ),
            )
        except Exception as exc:  # pragma: no cover - fail closed.
            s16_result = {
                "status": "data_gap",
                "reason": f"s16_market_heat_query_error:{exc.__class__.__name__}",
            }
        common.emit(
            annotate_market_context_result(base_result, s16_result)
        )

    market_context_with_s16.__name__ = previous.__name__
    market_context_with_s16.__doc__ = previous.__doc__
    calendar_module.market_context = market_context_with_s16
    _replace_prebound_market_context(previous, market_context_with_s16)


def _install_router_patch() -> None:
    from runtime import feishu_command_router as router

    router.MARKET_CONTEXT_PHRASES = tuple(
        dict.fromkeys(
            tuple(router.MARKET_CONTEXT_PHRASES)
            + (
                "市场热度",
                "大盘热度",
                "需求指数",
                "需求热度",
                "市场冷热",
                "大盘冷热",
                "商圈热度",
            )
        )
    )

    def market_context_demo(
        *,
        role: str,
        output_profile: str | None,
        db_path: str | None,
        hotel_id: str,
    ) -> dict[str, Any]:
        market_db_path = (
            db_path
            or os.environ.get("HOTEL_OTA_DB")
            or str(
                Path(tempfile.gettempdir())
                / "hotel-ota-market-context.sqlite"
            )
        )
        market = router._capture_runtime_emit(
            router.market_context,
            argparse.Namespace(
                db=market_db_path,
                hotel_id=hotel_id,
                date=None,
                as_of_time=None,
                weather_provider="market_source",
                weather_fixture=None,
                operating_fixture=None,
                progress_fixture=None,
                market_source_config=None,
            ),
        )
        event_context = _mapping(market.get("event_context"))
        weather_context = _mapping(market.get("weather_context"))
        regional_heat_context = _mapping(
            market.get("regional_heat_context")
        )
        result = router._base_result(
            "market_context_demo",
            role=role,
            output_profile=output_profile,
        )
        # `_base_result` carries local-demo metadata for legacy commands.
        # S4 must only expose dates returned by its own market query; otherwise
        # a missing market date is rendered as the demo manifest business date.
        result.pop("demo_business_date", None)
        result["data_business_date"] = (
            market.get("data_business_date")
            or market.get("business_date")
        )
        result.update(
            {
                "status": market.get("status", "data_gap"),
                "blocked_reason": (
                    market.get("downstream_blocked_reason")
                    or market.get("blocked_reason")
                    or market.get("reason")
                    or "tenant_context_not_found"
                ),
                "runtime_command": "market-context",
                "node_id": "N006",
                "skill_id": "S4",
                "hotel_id": hotel_id,
                "resolved_hotel_id": hotel_id,
                "business_date": market.get("business_date"),
                "data_source_type": (
                    market.get("data_source_type") or "market_runtime"
                ),
                "freshness_status": (
                    market.get("freshness_status") or "partial"
                ),
                "context_source": (
                    market.get("context_source")
                    or "runtime_market_context"
                ),
                "weather_context": weather_context,
                "event_context": event_context,
                "regional_heat_context": regional_heat_context,
                "market_heat_context": _mapping(
                    market.get("market_heat_context")
                ),
                "market_heat_ratio": market.get("market_heat_ratio"),
                "market_status": market.get("market_status"),
                "market_heat_calculation_status": market.get(
                    "market_heat_calculation_status"
                ),
                "market_heat_calculation_reason": market.get(
                    "market_heat_calculation_reason"
                ),
                "market_heat_source": market.get("market_heat_source"),
                "market_heat_fallback_used": False,
                "event_heat_score": market.get("event_heat_score"),
                "event_heat_score_label": market.get(
                    "event_heat_score_label"
                ),
                "demand_index": market.get("demand_index"),
                "demand_index_status": market.get(
                    "demand_index_status"
                ),
                "demand_index_reason": market.get(
                    "demand_index_reason"
                ),
                "metric_semantics_contract": market.get(
                    "metric_semantics_contract"
                ),
                "weather_source": (
                    market.get("weather_source")
                    or weather_context.get("source")
                ),
                "event_source": (
                    market.get("event_source")
                    or event_context.get("event_source")
                    or event_context.get("source")
                ),
                "regional_heat_source": (
                    market.get("regional_heat_source")
                    or regional_heat_context.get("source")
                ),
                "display_location": (
                    weather_context.get("display_location")
                    or market.get("display_location")
                ),
                "event_heat_level": event_context.get(
                    "event_heat_level"
                ),
                "direct_price_trigger_allowed": False,
                "summary": market.get("summary"),
            }
        )
        return result

    router._market_context_demo = market_context_demo


def _install_renderer_patch() -> None:
    from runtime import feishu_output_renderer as renderer

    previous = renderer.build_feishu_send_payload

    def build_feishu_send_payload(
        result: dict[str, Any],
        role: str | None = None,
    ) -> dict[str, Any]:
        payload = previous(result, role=role)
        if result.get("intent") != "market_context_demo":
            return payload

        text = render_s4_market_text(result)
        try:
            max_chars = int(
                os.environ.get(
                    "HOTEL_OTA_FEISHU_TEXT_LIMIT",
                    str(renderer.DEFAULT_FEISHU_TEXT_LIMIT),
                )
            )
        except ValueError:
            max_chars = renderer.DEFAULT_FEISHU_TEXT_LIMIT
        warnings = list(payload.get("warnings") or [])
        if max_chars > 0 and len(text) > max_chars:
            suffix = "\n\n内容已截断；详细诊断仅限本地受信维护通道。"
            keep = max(max_chars - len(suffix), 0)
            text = text[:keep].rstrip() + suffix
            warnings.append("feishu_text_truncated")

        gate = renderer.evaluate_feishu_output_gate(
            source="feishu",
            content_kind="text",
            message=text,
        )
        if gate.get("status") != "ok":
            warnings.append(
                f"feishu_output_gate:{gate.get('blocked_reason')}"
            )
            text = "您好，该内容不能通过飞书业务通道发送。"

        payload.update(
            {
                "text": text,
                "card": None,
                "send_allowed": (
                    bool(payload.get("send_allowed", True))
                    and gate.get("status") == "ok"
                ),
                "warnings": warnings,
            }
        )
        return payload

    renderer.build_feishu_send_payload = build_feishu_send_payload

    router = sys.modules.get("runtime.feishu_command_router")
    if router is not None:
        router.build_feishu_send_payload = build_feishu_send_payload


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _install_calendar_patch()
    _install_router_patch()
    _install_renderer_patch()

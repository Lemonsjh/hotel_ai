from __future__ import annotations

import sys
from typing import Any, Mapping

from runtime.s15_technical_analysis import (
    VERSION,
    build_s15_operating_analysis,
)
from runtime.s15_technical_decision import (
    _strict_s16_boundary,
    render_s15_analysis,
)

_INSTALLED = False
_S15_ANALYSIS_PHRASES = (
    "为什么销售落后",
    "为什么销售慢",
    "销售为什么慢",
    "为什么卖得慢",
    "为什么落后",
    "进度落后原因",
    "销售落后原因",
    "基准线分析",
    "基准经营分析",
    "经营判断",
    "七线分析",
    "七类基准",
    "大盘是否冷",
    "大盘冷吗",
    "市场份额是否下降",
    "份额下降吗",
    "浏览是否不足",
    "浏览不足吗",
    "一转是否弱",
    "一转弱吗",
    "二转是否弱",
    "二转弱吗",
    "价格是否偏高",
    "价格偏高吗",
    "是否应该降价",
    "要不要降价",
    "该不该降价",
    "是否应该开推广",
    "要不要开推广",
    "该不该开推广",
    "是否应该关推广",
    "要不要关推广",
)
_EXECUTION_PHRASES = (
    "dry-run",
    "执行预览",
    "调价预览",
    "推广执行",
    "立即执行",
    "直接执行",
    "确认执行",
    "同步房价",
    "创建任务",
    "提交审批",
    " live",
)


def _should_route_to_s15(message: str) -> bool:
    raw = str(message or "")
    text = raw.lower()
    if any(term in text or term in raw for term in _EXECUTION_PHRASES):
        return False
    if any(term in raw for term in _S15_ANALYSIS_PHRASES):
        return True
    reason_terms = ("为什么", "原因", "怎么回事", "问题在哪")
    sales_terms = ("销售", "进度", "卖房", "间夜", "落后", "偏慢")
    if any(term in raw for term in reason_terms) and any(
        term in raw for term in sales_terms
    ):
        return True
    action_terms = ("降价", "开推广", "关推广", "广告位")
    analysis_terms = ("是否", "要不要", "该不该", "应不应该")
    return any(term in raw for term in action_terms) and any(
        term in raw for term in analysis_terms
    )


def _patch_repository() -> None:
    from runtime.sales_progress.repository import (
        DirectSalesProgressRepository,
    )

    if getattr(
        DirectSalesProgressRepository,
        "_S15_TECHNICAL_METRICS_PATCHED",
        False,
    ):
        return
    original = DirectSalesProgressRepository.ota_business_metrics

    def ota_business_metrics(
        self: Any,
        platform: str,
        hotel_id: str,
        start_date: str,
        end_date: str,
        as_of_datetime: str,
    ) -> list[dict[str, Any]]:
        if str(platform).lower() != "meituan":
            return original(
                self,
                platform,
                hotel_id,
                start_date,
                end_date,
                as_of_datetime,
            )
        try:
            return self._query(
                """
                SELECT * FROM (
                  SELECT id, hotel_id, business_date, snapshot_time,
                         metric_code, metric_name, metric_value,
                         metric_unit, compare_label, compare_value,
                         competitor_rank, peer_average,
                         ROW_NUMBER() OVER (
                           PARTITION BY hotel_id, business_date, metric_code
                           ORDER BY snapshot_time DESC
                         ) AS rn
                  FROM meituan_ota_business_metrics
                  WHERE hotel_id=%s
                    AND business_date BETWEEN %s AND %s
                    AND snapshot_time<=%s
                ) ranked WHERE rn=1
                """,
                (
                    hotel_id,
                    start_date,
                    end_date,
                    as_of_datetime,
                ),
            )
        except Exception:
            return original(
                self,
                platform,
                hotel_id,
                start_date,
                end_date,
                as_of_datetime,
            )

    DirectSalesProgressRepository.ota_business_metrics = (
        ota_business_metrics
    )
    DirectSalesProgressRepository._S15_TECHNICAL_METRICS_PATCHED = True


def _patch_baseline_service() -> None:
    from runtime.sales_progress import (
        baseline_service,
        deviation_service,
        service,
    )
    from runtime.sales_progress.core import stable_hash

    if getattr(
        baseline_service,
        "_S15_TECHNICAL_ANALYSIS_PATCHED",
        False,
    ):
        return
    previous = baseline_service.build_baseline

    def build_baseline(
        repository: Any,
        *,
        hotel_id: str,
        target_date: str,
        as_of_datetime: str,
        date_contexts: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload = dict(
            previous(
                repository,
                hotel_id=hotel_id,
                target_date=target_date,
                as_of_datetime=as_of_datetime,
                date_contexts=date_contexts,
            )
        )
        analysis = build_s15_operating_analysis(
            repository,
            payload,
            hotel_id=hotel_id,
            target_date=str(target_date)[:10],
            as_of_datetime=str(as_of_datetime),
            date_contexts=date_contexts,
        )
        payload["operating_analysis"] = analysis
        platform_reference = analysis.get("platform_reference") or {}
        ota_baselines = dict(payload.get("ota_baselines") or {})
        meituan = dict(ota_baselines.get("meituan") or {})
        if platform_reference:
            meituan.update(
                {
                    "baselines": platform_reference.get("baselines") or {},
                    "selected_dates": platform_reference.get(
                        "selected_dates"
                    )
                    or [],
                    "selected_tier": platform_reference.get(
                        "selected_tier"
                    ),
                    "baseline_confidence_level": (
                        platform_reference.get(
                            "baseline_confidence_level"
                        )
                    ),
                    "auto_action_allowed": bool(
                        platform_reference.get("auto_action_allowed")
                    ),
                    "grain": "daily",
                    "hourly_baseline_available": False,
                    "date_tag_filter_applied": True,
                }
            )
            ota_baselines["meituan"] = meituan
            payload["ota_baselines"] = ota_baselines
        unavailable = dict(
            payload.get("unavailable_baseline_families") or {}
        )
        unavailable.pop("market_orders_baseline", None)
        unavailable.pop("hotel_market_share_baseline", None)
        payload["unavailable_baseline_families"] = unavailable
        payload["estimated_baseline_families"] = {
            "market_orders_baseline": {
                "status": "available_as_estimate",
                "method": "peer_average_times_peer_hotel_count",
            },
            "hotel_market_share_baseline": {
                "status": "available_as_estimate",
                "method": (
                    "own_orders_divided_by_estimated_market_orders"
                ),
            },
        }
        payload["technical_spec_authority"] = (
            "Digital-Employee-Algorithm-Technical-Spec-2026-07-08"
        )
        payload["technical_spec_analysis_version"] = VERSION
        revision_payload = dict(payload)
        revision_payload.pop("baseline_revision", None)
        payload["baseline_revision"] = stable_hash(revision_payload)
        return payload

    baseline_service.build_baseline = build_baseline
    service._build_baseline = build_baseline
    deviation_service.build_baseline = build_baseline
    baseline_service._S15_TECHNICAL_ANALYSIS_PATCHED = True


def _patch_cache_contract() -> None:
    from runtime.decisions import baseline as baseline_decision

    if getattr(
        baseline_decision,
        "_S15_TECHNICAL_CACHE_PATCHED",
        False,
    ):
        return
    previous_cached = baseline_decision._cached_baseline

    def cached(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
        payload = previous_cached(*args, **kwargs)
        if payload is None:
            return None
        if payload.get("technical_spec_analysis_version") != VERSION:
            return None
        if not payload.get("operating_analysis"):
            return None
        return payload

    baseline_decision._cached_baseline = cached
    baseline_decision._S15_TECHNICAL_CACHE_PATCHED = True


def _patch_presentation() -> None:
    from runtime.sales_progress import presentation

    if getattr(
        presentation,
        "_S15_S16_TECHNICAL_PRESENTATION_PATCHED",
        False,
    ):
        return
    previous_s15 = presentation.build_s15_user_message
    previous_s16 = presentation.build_s16_user_message

    def build_s15_user_message(payload: Mapping[str, Any]) -> str:
        analysis = render_s15_analysis(payload)
        base = previous_s15(payload)
        return f"{analysis}\n\n{base}" if analysis else base

    def build_s16_user_message(report: Mapping[str, Any]) -> str:
        return _strict_s16_boundary(previous_s16(report))

    def attach_s15_user_view(
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = dict(payload)
        message = build_s15_user_message(result)
        result.update(
            {
                "summary": message,
                "user_message": message,
                "business_view_version": (
                    "s15.zh-CN.technical-spec.v2"
                ),
                "target_business_term": (
                    "历史同类日参考最终已售房量"
                ),
                "order_count_available": False,
                "order_count_unavailable_reason": (
                    "订单数不能由已售房量或间夜按1比1换算"
                ),
                "ai_analysis_allowed": False,
                "delivery_mode": "authoritative_runtime_text",
            }
        )
        return result

    def attach_s16_user_view(
        report: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = dict(report)
        message = build_s16_user_message(result)
        result.update(
            {
                "summary": message,
                "user_message": message,
                "business_view_version": (
                    "s16.zh-CN.sales-structure-only.v1"
                ),
                "order_count_available": False,
                "order_count_unavailable_reason": (
                    "订单数不能由承诺已售房量按1比1换算"
                ),
                "analysis_scope": {
                    "included": [
                        "hotel_sales_progress",
                        "room_type_sales_progress",
                        "room_type_structure",
                    ],
                    "excluded": [
                        "market",
                        "market_share",
                        "browse",
                        "first_conversion",
                        "second_conversion",
                        "price",
                        "pricing_action",
                        "promotion_action",
                    ],
                },
                "ai_analysis_allowed": False,
                "delivery_mode": "authoritative_runtime_text",
            }
        )
        return result

    presentation.build_s15_user_message = build_s15_user_message
    presentation.build_s16_user_message = build_s16_user_message
    presentation.attach_s15_user_view = attach_s15_user_view
    presentation.attach_s16_user_view = attach_s16_user_view

    from runtime.decisions import baseline as baseline_decision
    from runtime.decisions import deviation as deviation_decision

    baseline_decision.attach_s15_user_view = attach_s15_user_view
    deviation_decision.attach_s16_user_view = attach_s16_user_view
    presentation._S15_S16_TECHNICAL_PRESENTATION_PATCHED = True


def _patch_direct_delivery() -> None:
    from runtime import s15_s16_runtime_patch

    if getattr(
        s15_s16_runtime_patch,
        "_S15_S16_TECHNICAL_DELIVERY_PATCHED",
        False,
    ):
        return

    def direct_delivery(
        result: dict[str, Any],
        role: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from runtime.safety.feishu_output import feishu_output_gate

        text = str(
            result.get("user_message")
            or result.get("summary")
            or "当前结果暂不可用。"
        )
        warnings: list[str] = []
        gate = feishu_output_gate(
            source="feishu",
            content_kind="text",
            message=text,
        )
        if gate.get("status") != "ok":
            text = "您好，当前业务摘要不能通过飞书业务通道发送。"
            warnings.append(
                f"feishu_output_gate:{gate.get('blocked_reason')}"
            )
        profile = result.get("output_profile") or (
            "owner_business"
            if role in {"admin", "owner"}
            else "operator_workbench"
        )
        rendered = {
            "status": (
                "ok" if gate.get("status") == "ok" else "blocked"
            ),
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
            "delivery_mode": "authoritative_runtime_text",
            "ai_rewrite_allowed": False,
        }
        send_payload = {
            "text": text,
            "card": None,
            "send_allowed": gate.get("status") == "ok",
            "output_profile": profile,
            "warnings": warnings,
            "data_source_type": result.get("data_source_type"),
            "freshness_status": result.get("freshness_status"),
            "delivery_mode": "authoritative_runtime_text",
            "ai_rewrite_allowed": False,
        }
        return rendered, send_payload

    s15_s16_runtime_patch._direct_delivery = direct_delivery
    s15_s16_runtime_patch._S15_S16_TECHNICAL_DELIVERY_PATCHED = True


def _patch_router_module(module: Any) -> None:
    if getattr(module, "_S15_S16_TECHNICAL_ROUTER_PATCHED", False):
        return
    original = module._detect_intent

    def detect_intent(message: str) -> str:
        if _should_route_to_s15(message):
            return "sales_baseline_demo"
        return original(message)

    module._detect_intent = detect_intent
    module._S15_S16_TECHNICAL_ROUTER_PATCHED = True


def _patch_router_import_contract() -> None:
    from runtime import live_contract_patch

    if getattr(
        live_contract_patch,
        "_S15_S16_TECHNICAL_ROUTER_HOOK_PATCHED",
        False,
    ):
        return
    previous_apply = live_contract_patch._apply_patch

    def apply_patch(module: Any) -> None:
        previous_apply(module)
        if module.__name__ == "runtime.feishu_command_router":
            _patch_router_module(module)

    live_contract_patch._apply_patch = apply_patch
    existing = sys.modules.get("runtime.feishu_command_router")
    if existing is not None:
        _patch_router_module(existing)
    live_contract_patch._S15_S16_TECHNICAL_ROUTER_HOOK_PATCHED = True


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    _patch_repository()
    _patch_baseline_service()
    _patch_cache_contract()
    _patch_presentation()
    _patch_direct_delivery()
    _patch_router_import_contract()

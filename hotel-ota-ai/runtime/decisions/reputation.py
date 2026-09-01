from __future__ import annotations

import argparse

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit
from runtime.contracts import standard_envelope
from runtime.derived_contexts import build_reputation_context


def reputation_diagnosis(args: argparse.Namespace) -> None:
    if database_source_enabled():
        context = build_reputation_context(
            database_template_result("ota_review_overview", args.hotel_id),
            ranking_result=database_template_result("ota_review_ranking", args.hotel_id),
        )
        if context.get("status") == "data_gap":
            emit(
                standard_envelope(
                    status="data_gap",
                    skill_id="S12/S13",
                    summary="当前没有可用于商业展示的口碑聚合数据，评论回复模块保持隐藏。",
                    evidence={"reputation_context": context},
                    recommendations=["先查看 OTA 运营诊断；待 review_overview 或 review_ranking 可用后再输出口碑摘要。"],
                    risk_level="medium",
                )
            )
            return
        emit(
            standard_envelope(
                status=context.get("status") or "partial",
                skill_id="S12/S13",
                summary="已基于 OTA 评分、差评数、未回复数和排名关键词生成口碑概览；当前无单条评论文本，不生成具体回复草稿。",
                evidence={"reputation_context": context},
                recommendations=["优先处理未回复差评和排名关键词暴露的服务/卫生/设施问题。"],
                actions=[{"type": "reply_strategy", "preview_only": True, "auto_publish": False}],
                risk_level="medium",
                approval_required=True,
            )
        )
        return
    review = {
        "sentiment": "negative",
        "issue_tags": ["noise", "service_response"],
        "severity": "medium",
        "needs_manager_escalation": True,
        "needs_private_message": True,
    }
    emit(
        standard_envelope(
            status="ok",
            skill_id="S12/S13",
            summary="该评论属于中等严重差评，建议升级店长并生成回复草稿，不自动发布。",
            evidence={"review": review},
            recommendations=["先内部跟进问题，再公开回复。", "涉及补偿必须人工确认。"],
            actions=[
                {"type": "manager_escalation", "owner": "店长"},
                {"type": "reply_draft", "content": "非常抱歉影响您的入住体验，我们已安排店长复盘并跟进整改。"},
            ],
            risk_level="medium",
            approval_required=True,
        )
    )

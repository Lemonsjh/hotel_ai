from __future__ import annotations

import argparse

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.algorithms.s7_competition_context import build_s7_competition_context
from runtime.common import emit
from runtime.contracts import standard_envelope


def competition_alert(args: argparse.Namespace) -> None:
    if not database_source_enabled():
        emit(
            standard_envelope(
                status="data_gap",
                skill_id="S7",
                summary="S7 only returns competition facts when the real read-only data source is enabled.",
                evidence={"reason": "database_source_disabled"},
                risk_level="medium",
            )
        )
        return
    context = build_s7_competition_context(
        price_result=database_template_result("ota_price_mapping", args.hotel_id),
        metrics_result=database_template_result("ota_business_metrics", args.hotel_id),
        competition_result=database_template_result("ctrip_competition_metrics_30d", args.hotel_id),
        loss_result=database_template_result("ota_order_loss_monthly", args.hotel_id),
        activity_result=database_template_result("ota_activity_summary", args.hotel_id),
        activity_detail_result=database_template_result("ota_activity_product_detail", args.hotel_id),
        rights_result=database_template_result("ota_joined_rights", args.hotel_id),
        psi_result=database_template_result("ctrip_psi_metrics", args.hotel_id),
        ranking_result=database_template_result("ota_review_ranking", args.hotel_id),
    )
    emit(
        standard_envelope(
            status=context["status"],
            skill_id="S7",
            summary="S7 separates own products, peer aggregates, monthly loss context and exact-product comparisons; no room-type price gap is inferred without exact competitor product records.",
            evidence={"competitor_context": context},
            recommendations=["Use S7 only as evidence for S5/S14; it never creates a price or promotion task."],
            actions=[{"type": "alert", "warning_level": "watch", "next_skill": "S5"}],
            risk_level="medium",
        )
    )

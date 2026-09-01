from __future__ import annotations

import argparse
import os

from runtime.adapters.database import database_source_enabled, database_template_result
from runtime.common import emit
from runtime.contracts import ota_health_level, standard_envelope
from runtime.decisions.demand import production_data_gap_snapshot, sample_snapshot
from runtime.decisions.realtime_occupancy import build_realtime_occupancy


def _realtime_occupancy_evidence(database_evidence: dict) -> dict:
    operating = database_evidence.get("operating_snapshot") or {}
    reservations = database_evidence.get("reservation_snapshot") or {}
    stayovers = database_evidence.get("stayover_snapshot") or {}
    if not all(block.get("status") == "ok" for block in (operating, reservations, stayovers)):
        return {}
    operating_payload = operating.get("payload") if isinstance(operating.get("payload"), dict) else {}
    reservation_payload = reservations.get("payload") if isinstance(reservations.get("payload"), dict) else {}
    stayover_payload = stayovers.get("payload") if isinstance(stayovers.get("payload"), dict) else {}
    business_date = operating_payload.get("data_business_date") or reservation_payload.get("data_business_date") or stayover_payload.get("data_business_date")
    if not business_date:
        return {}
    return build_realtime_occupancy(
        operating_payload=operating_payload,
        reservation_payload=reservation_payload,
        stayover_payload=stayover_payload,
        business_date=str(business_date),
        as_of_time=operating_payload.get("data_snapshot_time") or reservation_payload.get("data_snapshot_time") or stayover_payload.get("data_snapshot_time"),
    )


def ota_health(args: argparse.Namespace) -> None:
    db_enabled = database_source_enabled()
    snapshot = production_data_gap_snapshot("ota_health_score_unavailable") if db_enabled else sample_snapshot()
    database_evidence = {}
    realtime_occupancy: dict = {}
    if db_enabled:
        database_evidence = {
            "operation_diagnosis": database_template_result("operation_diagnosis", args.hotel_id),
            "operating_snapshot": database_template_result("operating_snapshot", args.hotel_id),
            "reservation_snapshot": database_template_result("reservation_snapshot", args.hotel_id),
            "stayover_snapshot": database_template_result("stayover_snapshot", args.hotel_id),
            "daily_metrics": database_template_result("daily_metrics", args.hotel_id),
        }
        realtime_occupancy = _realtime_occupancy_evidence(database_evidence)
        real_fields: dict[str, object] = {}
        for key in ("operation_diagnosis", "operating_snapshot"):
            evidence_block = database_evidence[key]
            if evidence_block.get("status") == "ok":
                real_fields.update(
                    {k: v for k, v in (evidence_block.get("payload") or {}).items() if v is not None}
                )
        # 生产口径：OTA 健康分/HOS 分必须来自真实数据库证据；任一缺失即 data_gap，绝不回退到样例的 5.74/4。
        if real_fields.get("hos_score") is None or real_fields.get("ota_health_score") is None:
            emit(
                standard_envelope(
                    status="data_gap",
                    skill_id="S14",
                    summary="OTA 健康分缺真实数据：数据库未提供 hos_score/ota_health_score，不输出任何样例分数。",
                    evidence={
                        "hos_score": None,
                        "ota_health_score": None,
                        "risk_flags": ["ota_health_score_unavailable"],
                        "data_source_type": real_fields.get("data_source_type"),
                        "freshness_status": real_fields.get("freshness_status"),
                        "business_status": real_fields.get("business_status"),
                        "today_label_allowed": False,
                        "realtime_occupancy": realtime_occupancy,
                        "database_evidence": database_evidence,
                    },
                    recommendations=[
                        "请接入真实 HOS/OTA 健康分来源（美团/携程经营指标或运营诊断）。",
                        "在补齐真实健康分前，相关结论保持空缺，不得用样例分替代。",
                    ],
                    actions=[
                        {"type": "diagnosis_task", "next_skill": "S14", "blocked_reason": "ota_health_score_unavailable"},
                    ],
                    risk_level="medium",
                )
            )
            return
        snapshot.update(real_fields)
        snapshot["risk_flags"] = list(real_fields.get("risk_flags") or [])
        snapshot["data_source_type"] = real_fields.get("data_source_type") or "database"
    score = snapshot.get("ota_health_score") or 0
    level = ota_health_level(score)
    business_status = snapshot.get("business_status")
    status = "ok" if business_status == "current" else "historical_only"
    emit(
        standard_envelope(
            status=status,
            skill_id="S14",
            summary=(
                f"OTA 健康为 {level}，当前优先处理确认率、评分、转化和推广余额。"
                if status == "ok"
                else f"当前为演示/历史口径，OTA 健康样例为 {level}，不能作为正式数据库诊断。"
            ),
            evidence={
                "hos_score": snapshot["hos_score"],
                "ota_health_score": score,
                "risk_flags": snapshot["risk_flags"],
                "data_source_type": snapshot.get("data_source_type"),
                "freshness_status": snapshot.get("freshness_status"),
                "data_business_date": snapshot.get("data_business_date"),
                "data_snapshot_time": snapshot.get("data_snapshot_time"),
                "data_age_hours": snapshot.get("data_age_hours"),
                "business_status": business_status,
                "today_label_allowed": snapshot.get("today_label_allowed"),
                "realtime_occupancy": realtime_occupancy,
                "database_evidence": database_evidence,
            },
            recommendations=["先修转化和口碑，再考虑降价。", "推广余额为 0 时应列入运营任务。"],
            actions=[
                {"type": "ab_task", "owner": "运营", "task": "检查美团 OTA 内容完整度、确认率和转化漏斗。"},
                {"type": "frontdesk_task", "owner": "前台", "task": "晚高峰前复核外网可售状态。"},
            ],
            risk_level="medium",
        )
    )


def conversion_diagnosis(args: argparse.Namespace) -> None:
    db_enabled = database_source_enabled()
    snapshot = production_data_gap_snapshot("conversion_metrics_unavailable") if db_enabled else sample_snapshot()
    database_evidence = {}
    if db_enabled:
        database_evidence = {
            "operation_diagnosis": database_template_result("operation_diagnosis", args.hotel_id),
            "daily_metrics": database_template_result("daily_metrics", args.hotel_id),
        }
        diagnosis = database_evidence["operation_diagnosis"]
        if diagnosis.get("status") == "ok":
            snapshot.update({key: value for key, value in (diagnosis.get("payload") or {}).items() if value is not None})
    required_fields = ("exposure", "views", "paid_orders", "payment_conversion_rate")
    if db_enabled and any(snapshot.get(field) is None for field in required_fields):
        evidence = {
            "exposure": snapshot.get("exposure"),
            "views": snapshot.get("views"),
            "clicks": snapshot.get("clicks"),
            "paid_orders": snapshot.get("paid_orders"),
            "payment_conversion_numerator": snapshot.get("payment_conversion_numerator"),
            "payment_conversion_denominator": snapshot.get("payment_conversion_denominator"),
            "payment_conversion_rate": snapshot.get("payment_conversion_rate"),
            "traffic_problem": None,
            "conversion_problem": None,
            "promotion_bid": snapshot.get("promotion_bid"),
            "promotion_cost": snapshot.get("promotion_cost"),
            "promotion_budget": snapshot.get("promotion_budget"),
            "promotion_orders": snapshot.get("promotion_orders"),
            "promotion_revenue": snapshot.get("promotion_revenue"),
            "data_source_type": snapshot.get("data_source_type"),
            "freshness_status": snapshot.get("freshness_status"),
            "data_business_date": snapshot.get("data_business_date"),
            "data_snapshot_time": snapshot.get("data_snapshot_time"),
            "data_age_hours": snapshot.get("data_age_hours"),
            "business_status": snapshot.get("business_status"),
            "today_label_allowed": False,
            "risk_flags": list(snapshot.get("risk_flags") or []) + ["conversion_metrics_unavailable"],
        }
        if bool(getattr(args, "debug", False) or os.environ.get("HOTEL_OTA_FEISHU_DEBUG") == "1"):
            evidence["database_evidence"] = database_evidence
        emit(
            standard_envelope(
                status="data_gap",
                skill_id="S14/S9",
                summary="真实曝光/浏览/支付转化数据不可用：不输出 demo/sample 转化指标。",
                evidence=evidence,
                recommendations=[
                    "请接入真实 OTA 曝光、浏览、点击、支付订单和支付转化率字段。",
                    "真实字段补齐前，只返回数据缺口，不用样例转化率替代。",
                ],
                actions=[{"type": "diagnosis_task", "next_skill": "S14", "blocked_reason": "conversion_metrics_unavailable"}],
                risk_level="medium",
            )
        )
        return
    exposure = snapshot["exposure"]
    views = snapshot["views"]
    clicks = snapshot.get("clicks")
    paid_orders = snapshot.get("paid_orders")
    pay_rate = snapshot["payment_conversion_rate"]
    traffic_problem = bool(exposure < 1000 or views < 100)
    conversion_problem = bool(pay_rate < 0.04)
    debug = bool(getattr(args, "debug", False) or os.environ.get("HOTEL_OTA_FEISHU_DEBUG") == "1")
    evidence = {
        "exposure": exposure,
        "views": views,
        "clicks": clicks,
        "paid_orders": paid_orders,
        "payment_conversion_numerator": snapshot.get("payment_conversion_numerator", paid_orders),
        "payment_conversion_denominator": snapshot.get("payment_conversion_denominator", views),
        "payment_conversion_rate": pay_rate,
        "traffic_problem": traffic_problem,
        "conversion_problem": conversion_problem,
        "promotion_bid": snapshot.get("promotion_bid"),
        "promotion_cost": snapshot.get("promotion_cost"),
        "promotion_budget": snapshot.get("promotion_budget"),
        "promotion_orders": snapshot.get("promotion_orders"),
        "promotion_revenue": snapshot.get("promotion_revenue"),
        "data_source_type": snapshot.get("data_source_type"),
        "freshness_status": snapshot.get("freshness_status"),
        "data_business_date": snapshot.get("data_business_date"),
        "data_snapshot_time": snapshot.get("data_snapshot_time"),
        "data_age_hours": snapshot.get("data_age_hours"),
        "business_status": snapshot.get("business_status"),
        "today_label_allowed": snapshot.get("today_label_allowed"),
        "risk_flags": snapshot.get("risk_flags"),
    }
    if debug:
        evidence["database_evidence"] = database_evidence
    emit(
        standard_envelope(
            status="historical_only" if snapshot.get("business_status") != "current" else "ok",
            skill_id="S14/S9",
            summary="转化诊断为聚合摘要：保留曝光、浏览、点击、支付订单和支付转化率，用于区分流量不足和转化不足。",
            evidence=evidence,
            recommendations=[
                "只有流量不足时，优先补曝光、活动入口和推广预算，不直接降价。",
                "只有转化不足时，才进入价格、活动叠加和内容修复候选。",
            ],
            actions=[{"type": "diagnosis_task", "next_skill": "S14", "priority": "P0/P1"}],
            risk_level="medium",
        )
    )

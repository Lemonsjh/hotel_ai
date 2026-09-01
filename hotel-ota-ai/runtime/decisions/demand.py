from __future__ import annotations

import argparse
from contextlib import closing
from typing import Any

from runtime.adapters.database import database_source_enabled, database_template_result, freshness_metadata
from runtime.common import emit, json_dumps, now_local, source_meta, today
from runtime.contracts import demand_level, standard_envelope
from runtime.demo_facts import business_snapshot
from runtime.demo_mode import is_demo_mode
from runtime.storage import connect, init_schema


def _business_summary(payload: dict[str, Any], summary: str, *, status: str) -> dict[str, Any]:
    approval_status = "不允许进入正式审批"
    if payload.get("freshness_status") == "fresh" and payload.get("business_status") == "current":
        approval_status = "仅可作为经营建议；真实调价仍需单独审批"
    risks = list(payload.get("risk_flags") or [])
    if payload.get("freshness_status") != "fresh":
        risks.append("数据不是今日实时口径，不能包装成今日经营快报")
    return {
        "template_id": "business-summary",
        "status": status,
        "sections": {
            "conclusion": summary,
            "evidence_date": {
                "data_business_date": payload.get("data_business_date"),
                "data_snapshot_time": payload.get("data_snapshot_time"),
                "freshness_status": payload.get("freshness_status"),
                "today_label_allowed": payload.get("today_label_allowed"),
            },
            "core_metrics": {
                "occupancy_rate": payload.get("occupancy_rate"),
                "adr": payload.get("adr"),
                "revpar": payload.get("revpar"),
                "available_rooms": payload.get("available_rooms"),
                "sold_rooms": payload.get("sold_rooms"),
                "remaining_rooms": payload.get("remaining_rooms"),
                "orders_today": payload.get("orders_today"),
            },
            "risks": risks,
            "recommended_actions": [
                "先确认数据日期和新鲜度，再解读经营结论。",
                "需要调价、推广或房量动作时，必须走 dry-run 和 admin/owner 审批。",
            ],
            "approval_status": approval_status,
        },
    }


def _demo_sample_snapshot() -> dict[str, Any]:
    return {
        "business_date": today(),
        **source_meta("manual", "manual", "sample_data", "read_only", "inferred"),
        "occupancy_rate": 0.7993,
        "adr": 135.83,
        "revpar": 108.26,
        "ota_share": 0.87,
        "hos_score": 5.74,
        "rank": 2,
        "orders_today": 8,
        "orders_last_week_same_time": 7,
        "market_orders_today": 170,
        "market_orders_last_week_same_time": 107,
        "exposure": 2100,
        "views": 328,
        "clicks": 116,
        "paid_orders": 11,
        "payment_conversion_numerator": 11,
        "payment_conversion_denominator": 328,
        "payment_conversion_rate": 0.034,
        "promotion_bid": None,
        "promotion_cost": 0,
        "promotion_budget": 0,
        "promotion_orders": 0,
        "promotion_revenue": 0,
        "demand_index": 58,
        "demand_level": "strong",
        "ota_health_score": 4,
        "action_strength": 2,
        "risk_flags": ["demo_data", "confirmation_rate_low", "promotion_balance_zero"],
        **freshness_metadata(None, demo_data=True),
        "business_status": "demo_or_historical",
    }


def sample_snapshot() -> dict[str, Any]:
    """Demo/local-only fixture. Production paths must use production_data_gap_snapshot()."""
    return _demo_sample_snapshot()


def production_data_gap_snapshot(reason: str, *, business_date: str | None = None) -> dict[str, Any]:
    return {
        "business_date": business_date or today(),
        "adapter_vendor": "database",
        "channel_source": "pms",
        "data_source_type": "unavailable",
        "source_capability": "unavailable",
        "field_quality": "missing",
        "business_status": "data_gap",
        "freshness_status": "missing_date",
        "data_age_hours": None,
        "data_business_date": None,
        "data_snapshot_time": None,
        "today_label_allowed": False,
        "risk_flags": [reason],
    }


def snapshot(args: argparse.Namespace) -> None:
    if is_demo_mode(args):
        payload = business_snapshot()
        summary = (
            f"演示业务日期 {payload['demo_business_date']} 的经营快照："
            f"总房量 {payload['total_rooms']}，已售 {payload['sold_rooms']}，"
            f"出租率 {payload['occupancy_rate']}%，ADR {payload['adr']}，RevPAR {payload['revpar']}。"
            "本结果来自 demo_data，不代表今日真实经营。"
        )
        payload["captured_at"] = now_local()
        with closing(connect(args.db)) as conn:
            with conn:
                init_schema(conn)
                conn.execute(
                    "INSERT INTO snapshots (hotel_id, captured_at, source, payload_json) VALUES (?, ?, ?, ?)",
                    (args.hotel_id, payload["captured_at"], "demo_data", json_dumps(payload)),
                )
        emit(
            {
                "status": "ok",
                "hotel_id": payload["hotel_id"],
                "summary": summary,
                "business_summary": _business_summary(payload, summary, status="ok"),
                "business_status": payload.get("business_status"),
                "freshness_status": payload.get("freshness_status"),
                "demo_business_date": payload.get("demo_business_date"),
                "data_business_date": payload.get("data_business_date"),
                "data_snapshot_time": payload.get("data_snapshot_time"),
                "today_label_allowed": payload.get("today_label_allowed"),
                "payload": payload,
            }
        )
        return
    db_result = database_template_result("operating_snapshot", args.hotel_id) if database_source_enabled() else {"status": "disabled"}
    if db_result.get("status") == "ok":
        db_payload = db_result.get("payload") or {}
        freshness_status = db_payload.get("freshness_status") or "missing_date"
        data_business_date = db_payload.get("data_business_date") or db_payload.get("snapshot_time")
        payload = {
            "business_date": data_business_date,
            "source": "database",
            **db_result,
            **db_payload,
        }
        if freshness_status == "fresh":
            payload["business_status"] = "current"
            summary = (
                f"数据库今日经营快照：出租率 {float(payload.get('occupancy_rate') or 0):.2%}, "
                f"ADR {payload.get('adr', 0)}, RevPAR {payload.get('revpar', 0)}"
            )
        else:
            payload["business_status"] = "demo_or_historical"
            summary = (
                f"数据库最新数据为 {payload.get('data_snapshot_time') or payload.get('data_business_date') or '未知日期'}，"
                "不是可直接用于今日快报的实时数据；只能按历史/演示口径使用。"
            )
    else:
        payload = {
            "business_date": today(),
            "source": args.source,
            "database_fallback": db_result,
            "business_status": "demo_or_historical",
            "freshness_status": "missing_date" if db_result.get("status") == "disabled" else "demo_data",
            "data_business_date": None,
            "data_snapshot_time": None,
            "data_age_hours": None,
            "today_label_allowed": False,
            "adapter_vendor": "database",
            "channel_source": "pms",
            "data_source_type": "unavailable",
            "source_capability": "unavailable",
            "field_quality": "missing",
            "risk_flags": ["database_source_disabled"],
        }
        summary = "数据库来源未启用，无法生成真实今日经营快照；请先加载 MySQL 数据源环境变量。"
        payload["captured_at"] = now_local()
        emit(
            {
                "status": "data_gap",
                "hotel_id": args.hotel_id,
                "summary": summary,
                "business_summary": _business_summary(payload, summary, status="data_gap"),
                "business_status": payload.get("business_status"),
                "freshness_status": payload.get("freshness_status"),
                "data_business_date": payload.get("data_business_date"),
                "data_snapshot_time": payload.get("data_snapshot_time"),
                "data_age_hours": payload.get("data_age_hours"),
                "today_label_allowed": payload.get("today_label_allowed"),
                "payload": payload,
            }
        )
        return
    payload["captured_at"] = now_local()
    with closing(connect(args.db)) as conn:
        with conn:
            conn.execute(
                "INSERT INTO snapshots (hotel_id, captured_at, source, payload_json) VALUES (?, ?, ?, ?)",
                (args.hotel_id, payload["captured_at"], payload["source"], json_dumps(payload)),
            )
    emit(
        {
            "status": "ok" if db_result.get("status") == "ok" else "data_gap",
            "hotel_id": args.hotel_id,
            "summary": summary,
            "business_summary": _business_summary(payload, summary, status="ok" if db_result.get("status") == "ok" else "data_gap"),
            "business_status": payload.get("business_status"),
            "freshness_status": payload.get("freshness_status"),
            "data_business_date": payload.get("data_business_date"),
            "data_snapshot_time": payload.get("data_snapshot_time"),
            "data_age_hours": payload.get("data_age_hours"),
            "today_label_allowed": payload.get("today_label_allowed"),
            "payload": payload,
        }
    )


def demand_index(args: argparse.Namespace) -> None:
    if database_source_enabled():
        context_result = database_template_result("demand_context", args.hotel_id)
        if context_result.get("status") == "ok":
            context_payload = context_result.get("payload") or {}
            score = context_payload.get("demand_index")
            level_text = context_payload.get("demand_level")
            if score is not None:
                try:
                    level_text = level_text or demand_level(float(score))
                except (TypeError, ValueError):
                    level_text = level_text or str(score)
                status = "ok" if context_payload.get("freshness_status") == "fresh" else "historical_only"
                emit(
                    standard_envelope(
                        status=status,
                        skill_id="S4/S9",
                        summary="Demand context is from business_dataset_v1; it is market context only and does not trigger price execution.",
                        evidence=context_payload,
                        recommendations=[
                            "Use calendar, weather, event, competitor, operating, and progress context together.",
                            "S4 only provides market context. S5/S6 approval and dry-run gates still apply.",
                        ],
                        actions=[
                            {
                                "type": "market_context",
                                "demand_level": level_text,
                                "next_skill": "S14/S5" if status == "ok" else "S14",
                                "downstream_allowed": status == "ok",
                            }
                        ],
                        risk_level="medium",
                        approval_required=False,
                    )
                )
                return
    if database_source_enabled():
        # 生产数据源已启用，但真实 demand_context 不可用：绝不编造需求指数/HOS/商圈数据。
        operating = database_template_result("operating_snapshot", args.hotel_id)
        operating_payload = operating.get("payload") if operating.get("status") == "ok" else None
        evidence = {
            "demand_index": None,
            "demand_level": None,
            "hos_score": None,
            "ota_health_score": None,
            "market_orders_today": None,
            "market_orders_last_week_same_time": None,
            "demand_index_source": "unavailable",
            "demand_index_field_quality": "missing",
            "freshness_status": "data_gap",
            "today_label_allowed": False,
            "business_status": "data_gap",
            "risk_flags": ["demand_context_unavailable"],
            "operating_evidence": operating_payload,
        }
        emit(
            standard_envelope(
                status="data_gap",
                skill_id="S4/S9",
                summary="真实行情/需求上下文不可用：缺少 demand_context 数据，无法给出需求指数；不提供任何样例数字。",
                evidence=evidence,
                recommendations=[
                    "请接入 demand_context 真实数据（天气、节假日、周边活动、OTA 小时级曝光/浏览/转化）。",
                    "在补齐真实行情前，需求指数、HOS、OTA健康分、商圈订单等指标保持空缺，不得用样例数字替代。",
                ],
                actions=[
                    {
                        "type": "market_context",
                        "demand_level": None,
                        "next_skill": "S14",
                        "downstream_allowed": False,
                        "blocked_reason": "demand_context_unavailable",
                    }
                ],
                risk_level="medium",
                approval_required=False,
            )
        )
        return
    # 无数据库来源（纯本地/测试）才允许带标记的样例口径。
    payload = _demo_sample_snapshot()
    payload["database_fallback"] = {"status": "disabled"}
    payload["demand_index_source"] = "sample_data"
    payload["demand_index_field_quality"] = "hardcoded_sample"
    payload["business_status"] = "demo_or_historical"
    payload["freshness_status"] = "demo_data"
    payload["today_label_allowed"] = False
    risk_flags = list(payload.get("risk_flags") or [])
    if "demand_index_sample_only" not in risk_flags:
        risk_flags.append("demand_index_sample_only")
    payload["risk_flags"] = risk_flags
    score = payload["demand_index"]
    level = demand_level(score)
    reasons = [
        "需求指数当前仍为样例/硬编码口径，不能作为正式调价或推广依据。",
        "如需正式行情，请接入天气、节假日、活动和 OTA 小时级曝光/浏览/转化数据。",
        "当前只能作为历史/演示分析，建议保守动作。",
    ]
    emit(
        standard_envelope(
            status="historical_only",
            skill_id="S4/S9",
            summary=f"需求指数 {score}，当前为 {level} 档；该指数为样例口径，不能作为正式提价窗口。",
            evidence=payload,
            recommendations=reasons,
            actions=[
                {
                    "type": "market_context",
                    "action_strength": payload["action_strength"],
                    "demand_level": level,
                    "next_skill": "S14",
                    "blocked_reason": "demand_index_sample_only",
                }
            ],
            risk_level="medium" if payload["risk_flags"] else "low",
            approval_required=False,
        )
    )

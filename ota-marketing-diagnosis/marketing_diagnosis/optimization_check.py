from __future__ import annotations

from typing import Any

from marketing_diagnosis.rule_catalog import OPTIMIZATION_RULES


def build_optimization_checks(result: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = result.get("metrics") or {}
    op = metrics.get("operating") or {}
    funnel = metrics.get("ota_funnel") or {}
    data_quality = result.get("data_quality") or {}
    missing = sum(len(v or []) for v in (data_quality.get("missing_fields") or {}).values())

    return [
        {
            "check_id": item["check_id"],
            "name": item["name"],
            "logic": item["logic"],
            "current_status": "待历史动作数据" if item["check_id"] != "O06" else ("需先补字段" if missing else "可复盘"),
            "required_fields": _required_fields(item["check_id"]),
            "current_evidence": {
                "final_score": result.get("final_score"),
                "revpar": op.get("revpar"),
                "room_revenue": op.get("room_revenue"),
                "paid_orders": funnel.get("paid_orders"),
                "payment_conversion_rate": funnel.get("payment_conversion_rate"),
                "missing_fields_count": missing,
            },
        }
        for item in OPTIMIZATION_RULES
    ]


def _required_fields(check_id: str) -> list[str]:
    if check_id == "O01":
        return ["before_score", "after_score", "before_revpar", "after_revpar", "before_orders", "after_orders"]
    if check_id == "O02":
        return ["before_score", "after_score", "before_revenue", "after_revenue"]
    if check_id == "O03":
        return ["before_exposure", "after_exposure", "before_orders", "after_orders"]
    if check_id == "O04":
        return ["before_orders", "after_orders", "before_revenue", "after_revenue", "before_adr", "after_adr"]
    if check_id == "O05":
        return ["rating", "review_count", "revpar", "occupancy_rate", "paid_orders"]
    return ["missing_fields", "source_diagnostics", "freshness"]

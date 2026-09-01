from __future__ import annotations

from typing import Any

from runtime.algorithm_rule_loader import load_algorithm_rule
from runtime.common import PACKAGE_ROOT

DATA_GAP_IMPACT_SOURCE = "contracts/v27/data_gap_impact_matrix.yaml"


FALLBACK_DATA_GAP_IMPACT_MATRIX: dict[str, dict[str, Any]] = {
    "S2": {
        "node_ids": ["N005"],
        "required_fields": ["total_rooms", "sold_rooms", "adr", "revpar", "data_business_date"],
        "if_missing": "business_snapshot_becomes_data_gap",
        "blocked_downstream": ["S14", "S5", "S16"],
    },
    "S4/S9": {
        "node_ids": ["N006", "N020"],
        "required_fields": [
            "date_environment_score",
            "regional_heat_index",
            "historical_same_period_score",
            "booking_progress",
            "current_traffic_score",
            "payment_conversion_rate",
            "room_type_inventory_pressure",
        ],
        "if_missing": "demand_or_funnel_confidence_downgraded",
        "blocked_downstream": ["S5"],
    },
    "S5": {
        "node_ids": ["N015"],
        "required_fields": ["current_price", "floor_price", "ceiling_price", "expected_occupancy_tonight", "baseline_price_by_room_type"],
        "if_missing": "pricing_decision_blocked",
        "blocked_downstream": ["S6"],
    },
    "S6": {
        "node_ids": ["N016"],
        "required_fields": ["approval_id", "floor_price", "ceiling_price", "execution_price", "live_switch"],
        "if_missing": "dry_run_only_or_blocked",
        "blocked_downstream": ["live_price_write"],
    },
    "S7": {
        "node_ids": ["N007"],
        "required_fields": ["competitor_price", "current_price", "competitor_rank"],
        "if_missing": "watch_only_no_price_trigger",
        "blocked_downstream": ["direct_price_update"],
    },
    "S8/S10/S11": {
        "node_ids": ["N012", "N013", "N021"],
        "required_fields": ["promotion_budget", "promotion_cost", "promotion_revenue", "expected_orders", "approval_id"],
        "if_missing": "promotion_execution_blocked",
        "blocked_downstream": ["promotion_live_write"],
    },
    "S12/S13": {
        "node_ids": ["N008", "N017"],
        "required_fields": ["review_text", "rating", "privacy_checked"],
        "if_missing": "reply_draft_or_publish_blocked",
        "blocked_downstream": ["review_publish"],
    },
    "S14/S14-EXT": {
        "node_ids": ["N009", "N022"],
        "required_fields": ["exposure", "views", "clicks", "paid_orders", "hos_score", "rating_total"],
        "if_missing": "health_score_partial_or_structure_only_report",
        "blocked_downstream": ["complete_html_report_claim"],
    },
}


def _load_contract_matrix() -> dict[str, dict[str, Any]]:
    try:
        payload = load_algorithm_rule(PACKAGE_ROOT / DATA_GAP_IMPACT_SOURCE)
    except Exception:
        return FALLBACK_DATA_GAP_IMPACT_MATRIX
    matrix = payload.get("matrix")
    if not isinstance(matrix, dict):
        return FALLBACK_DATA_GAP_IMPACT_MATRIX
    return {str(key): dict(value) for key, value in matrix.items() if isinstance(value, dict)}


DATA_GAP_IMPACT_MATRIX: dict[str, dict[str, Any]] = _load_contract_matrix()


def field_gap_report(skill_id: str, available_fields: set[str]) -> dict[str, Any]:
    rule = DATA_GAP_IMPACT_MATRIX.get(skill_id) or {}
    required = list(rule.get("required_fields") or [])
    missing = sorted(field for field in required if field not in available_fields)
    return {
        "skill_id": skill_id,
        "required_fields": required,
        "available_fields": sorted(available_fields),
        "missing_fields": missing,
        "impact": rule.get("if_missing") if missing else "none",
        "blocked_downstream": rule.get("blocked_downstream") if missing else [],
        "status": "ok" if not missing else "data_gap",
    }

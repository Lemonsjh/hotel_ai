from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from runtime.agent_mapping_loader import node_mapping
from runtime.algorithms.activity_decision import calculate_activity_decision
from runtime.algorithms.competitor_alert import calculate_competitor_alert
from runtime.algorithms.conversion_funnel import calculate_conversion_funnel
from runtime.algorithms.demand_index import calculate_demand_index
from runtime.algorithms.ota_health_score import calculate_ota_health_score
from runtime.algorithms.review_classifier import classify_review
from runtime.algorithms.roi_decision import calculate_roi_decision
from runtime.algorithms.s5_decision_context import build_s5_decision_context
from runtime.business_context_resolver import resolve_business_context
from runtime.common import PACKAGE_ROOT, emit
from runtime.decisions.progress_diagnosis import build_progress_diagnosis
from runtime.decisions.revenue_decision import run_revenue_decision_demo
from runtime.s14_ext_third_party_diagnosis import build_s14_ext_third_party_preview
from runtime.safety.payload_hash import price_execution_payload_hash
from runtime.demo_facts import (
    business_snapshot,
    demo_safety_flags,
    demo_run_id,
    execution_preview,
    external_ota_report_preview,
    revenue_decision_input,
)


DEMO_DATA_DIR = PACKAGE_ROOT / "examples" / "demo_data"
DEMO_METADATA = demo_safety_flags()

NODE_REGISTRY_PATH = PACKAGE_ROOT / "architecture" / "node_registry.json"
EDGE_REGISTRY_PATH = PACKAGE_ROOT / "architecture" / "edge_registry.json"
SCENARIO_REGISTRY_PATH = PACKAGE_ROOT / "architecture" / "scenario_chain_registry.json"


def is_demo_mode(args: Any | None = None) -> bool:
    return os.environ.get("HOTEL_OTA_DEMO_MODE") == "1" or bool(getattr(args, "demo", False))


def allow_demo_placeholder(args: Any | None = None) -> bool:
    return os.environ.get("HOTEL_OTA_ALLOW_DEMO_PLACEHOLDER") == "1" or bool(getattr(args, "allow_placeholder", False))


def demo_metadata() -> dict[str, Any]:
    return demo_safety_flags()


def is_demo_payload(payload: dict[str, Any] | None) -> bool:
    data = payload or {}
    return data.get("data_source_type") == "demo_data" or data.get("freshness_status") == "demo_data"


def mark_demo_payload(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = dict(payload or {})
    data.update(demo_metadata())
    risk_flags = set(data.get("risk_flags") or [])
    risk_flags.add("demo_data")
    data["risk_flags"] = sorted(risk_flags)
    return data


def formal_approval_allowed(payload: dict[str, Any] | None) -> bool:
    data = payload or {}
    return not is_demo_payload(data) and data.get("approval_data_allowed") is not False


def live_execution_allowed(payload: dict[str, Any] | None) -> bool:
    data = payload or {}
    return not is_demo_payload(data) and data.get("live_allowed") is True


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_json_or_empty(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json(path)


def _node_registry() -> dict[str, dict[str, Any]]:
    payload = _read_json_or_empty(NODE_REGISTRY_PATH)
    return {str(node.get("id") or node.get("node_id")): node for node in payload.get("nodes", [])}


def _edge_registry() -> dict[str, dict[str, Any]]:
    payload = _read_json_or_empty(EDGE_REGISTRY_PATH)
    return {str(edge.get("edge_id")): edge for edge in payload.get("edges", [])}


def _scenario_registry() -> dict[str, dict[str, Any]]:
    payload = _read_json_or_empty(SCENARIO_REGISTRY_PATH)
    return {str(scenario.get("id") or scenario.get("scenario_id")): scenario for scenario in payload.get("scenarios", [])}


def load_demo_fixture(fixture_id: str) -> dict[str, Any]:
    return _read_json(DEMO_DATA_DIR / "fixtures" / f"{fixture_id}.json")


def load_demo_scenario(scenario_id: str) -> dict[str, Any]:
    normalized = scenario_id.upper()
    return _read_json(DEMO_DATA_DIR / "scenarios" / f"{normalized}.json")


def load_demo_node(node_id: str) -> dict[str, Any]:
    normalized = node_id.upper()
    return _read_json(DEMO_DATA_DIR / "nodes" / f"{normalized}.json")


def _placeholder_node(node_id: str) -> dict[str, Any]:
    registry_node = _node_registry().get(node_id, {})
    mapping = node_mapping(node_id)
    return {
        "node_id": node_id,
        "node_name": mapping.get("node_name") or registry_node.get("name") or "placeholder demo node",
        "skill_id": mapping.get("skill_id") or registry_node.get("skill_id") or "-",
        "agent_id": mapping.get("agent_id"),
        "phase": registry_node.get("phase"),
        "demo_meta": demo_metadata(),
        "demo_input": {"hotel_id": "puyue-demo", "placeholder": True},
        "expected_output": {
            "status": "placeholder_demo",
            "node_id": node_id,
            **demo_metadata(),
        },
        "covered_by_scenarios": [],
        "placeholder": True,
    }


def _load_demo_node_or_placeholder(node_id: str, *, allow_placeholder: bool = False) -> dict[str, Any]:
    try:
        return load_demo_node(node_id)
    except FileNotFoundError:
        if not allow_placeholder:
            raise
        return _placeholder_node(node_id)


def _load_demo_scenario_or_placeholder(scenario_id: str, *, allow_placeholder: bool = False) -> dict[str, Any]:
    normalized = scenario_id.upper()
    try:
        return load_demo_scenario(normalized)
    except FileNotFoundError:
        if not allow_placeholder:
            raise
        registry = _scenario_registry().get(normalized, {})
        return {
            "scenario_id": normalized,
            "fixture_id": f"placeholder_{normalized.lower()}",
            "name": registry.get("name") or "placeholder demo scenario",
            "nodes": registry.get("nodes") or [],
            "required_edges": registry.get("required_edges") or [],
            "optional_edges": registry.get("optional_edges") or [],
            "demo_meta": demo_metadata(),
            "fixture_refs": [],
            "expected_outputs": [
                "data_source_type=demo_data",
                "freshness_status=demo_data",
                "approval_data_allowed=false",
                "live_allowed=false",
            ],
            "placeholder": True,
        }


def _safe_load_demo_fixture(fixture_id: str, *, allow_placeholder: bool = False) -> dict[str, Any]:
    try:
        return load_demo_fixture(fixture_id)
    except FileNotFoundError:
        if not allow_placeholder:
            raise
        return {
            "fixture_id": fixture_id,
            "status": "placeholder_demo",
            **DEMO_METADATA,
            "reason": "missing_demo_fixture_placeholder",
        }


def _node_demo_input(fixture: dict[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    data.update(fixture.get("demo_input") or {})
    data.update(fixture.get("demo_meta") or {})
    data.update(demo_metadata())
    return data


def _execution_preview(skill_id: str) -> dict[str, Any]:
    preview = execution_preview()
    action = "price_sync" if skill_id == "S6" else "promotion_execution"
    return {
        "blocked_reason": "demo_data_never_live",
        "dry_run_preview": {
            "action": action,
            "write_attempted": False,
            "formal_approval_created": False,
            "live_execution_count": 0,
            "execution_price": preview.get("execution_price") if skill_id == "S6" else None,
            "floor_price": preview.get("floor_price") if skill_id == "S6" else None,
            "ceiling_price": preview.get("ceiling_price") if skill_id == "S6" else None,
        },
        "verification_checklist": [
            "data_source_type=demo_data",
            "approval_data_allowed=false",
            "live_allowed=false",
            "live_switch=false",
            "readback_required_before_any_future_live",
        ],
        "readback_required": True,
    }


def _execution_preview_from_context(skill_id: str, context: dict[str, Any], *, db_path: str | None = None) -> dict[str, Any]:
    preview = dict((context.get("facts") or {}).get("execution_preview") or execution_preview())
    rooms = (((context.get("facts") or {}).get("room_types") or {}).get("room_types") or [])
    selected_room = next((room for room in rooms if room.get("room_type_id") == preview.get("room_type_id")), {})
    action = "price_sync" if skill_id == "S6" else "promotion_execution"
    upstream_decision_ref = None
    s5_output_hash = None
    execution_payload_hash = None
    approval_payload_match = None
    if skill_id == "S6":
        s5_result = run_revenue_decision_demo(
            {"demo_input": _revenue_input_from_context(context), "demo_meta": _context_safety(context)},
            db_path=db_path or context.get("_db_path"),
        )
        selected = s5_result.get("selected_recommendation") or {}
        upstream_decision_ref = s5_result.get("decision_ref")
        s5_output_hash = s5_result.get("s5_output_hash")
        preview.update(
            {
                "room_type_id": selected.get("room_type_id") or preview.get("room_type_id"),
                "room_type_name": selected.get("room_type_name") or preview.get("room_type_name"),
                "channel": selected.get("channel") or preview.get("channel"),
                "adapter": selected.get("adapter") or preview.get("adapter"),
                "method": selected.get("method") or preview.get("method"),
                "execution_price": selected.get("execution_price") or preview.get("execution_price"),
                "floor_price": selected.get("floor_price") or preview.get("floor_price"),
                "ceiling_price": selected.get("ceiling_price") or preview.get("ceiling_price"),
                "price_guard_source": selected.get("price_guard_source"),
                "price_guard_policy_id": selected.get("price_guard_policy_id"),
                "price_guard_policy_version": selected.get("price_guard_policy_version"),
            }
        )
        execution_payload = dict((upstream_decision_ref or {}).get("payload") or {})
        execution_payload_hash = price_execution_payload_hash(execution_payload) if execution_payload else None
        approval_payload_match = bool(execution_payload_hash and execution_payload_hash == s5_output_hash)
    return {
        "blocked_reason": "synthetic_today_demo_never_live" if context.get("data_source_type") == "synthetic_today_demo" else "demo_data_never_live",
        "dry_run_preview": {
            "action": action,
            "room_type_id": preview.get("room_type_id"),
            "room_type_name": preview.get("room_type_name") or selected_room.get("room_type_name"),
            "channel": preview.get("channel"),
            "adapter": preview.get("adapter"),
            "method": preview.get("method"),
            "write_attempted": False,
            "formal_approval_created": False,
            "live_execution_count": 0,
            "execution_price": preview.get("execution_price") if skill_id == "S6" else None,
            "floor_price": preview.get("floor_price") if skill_id == "S6" else None,
            "ceiling_price": preview.get("ceiling_price") if skill_id == "S6" else None,
            "price_guard_source": preview.get("price_guard_source") if skill_id == "S6" else None,
            "price_guard_policy_id": preview.get("price_guard_policy_id") if skill_id == "S6" else None,
            "price_guard_policy_version": preview.get("price_guard_policy_version") if skill_id == "S6" else None,
            "upstream_decision_ref": upstream_decision_ref,
            "s5_output_hash": s5_output_hash,
            "execution_payload_hash": execution_payload_hash,
            "approval_payload_match": approval_payload_match,
            "approval_preview_allowed": True,
            "demo_approval_preview_id": f"demo-approval-preview-{(upstream_decision_ref or {}).get('decision_id') or skill_id.lower()}",
            "formal_approval_allowed": False,
            "formal_approval_created": False,
            "live_allowed": False,
            "live_execution_count": 0,
        },
        "approval_preview_allowed": True,
        "demo_approval_preview_id": f"demo-approval-preview-{(upstream_decision_ref or {}).get('decision_id') or skill_id.lower()}",
        "formal_approval_allowed": False,
        "formal_approval_created": False,
        "live_allowed": False,
        "live_execution_count": 0,
        "verification_checklist": [
            "data_source_type_is_demo_or_synthetic_today_demo",
            "approval_data_allowed=false",
            "live_allowed=false",
            "live_switch=false",
            "readback_required_before_any_future_live",
        ],
        "readback_required": True,
    }


def _context_safety(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "data_source_type": context.get("data_source_type"),
        "freshness_status": context.get("freshness_status"),
        "business_status": "demo_or_historical",
        "today_label_allowed": False,
        "approval_data_allowed": False,
        "approval_preview_allowed": True,
        "formal_approval_allowed": False,
        "live_allowed": False,
        "formal_approval_created": False,
        "live_execution_count": 0,
        "demo_dataset_id": (context.get("manifest") or {}).get("demo_dataset_id"),
        "hotel_id": context.get("hotel_id"),
        "data_business_date": context.get("business_date"),
        "demo_business_date": context.get("business_date"),
    }


def _run_context_summary(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_source": context.get("context_source"),
        "use_generated_today": bool(context.get("use_generated_today")),
        "requested_generated_today": bool(context.get("requested_generated_today")),
        "fallback_used": bool(context.get("fallback_used")),
        "generated_demo_run_id": context.get("generated_demo_run_id"),
        "generated_at": context.get("generated_at"),
        "business_date": context.get("business_date"),
        "data_source_type": context.get("data_source_type"),
        "freshness_status": context.get("freshness_status"),
        "demo_dataset_id": (context.get("manifest") or {}).get("demo_dataset_id"),
        "context_warnings": context.get("context_warnings") or [],
        "as_of_time": context.get("as_of_time"),
        "as_of_time_source": context.get("as_of_time_source"),
        "time_context_required": bool(context.get("time_context_required")),
    }


def _revenue_input_from_context(context: dict[str, Any]) -> dict[str, Any]:
    facts = context.get("facts") or {}
    snapshot = facts.get("business_snapshot") or {}
    rooms = (facts.get("room_types") or {}).get("room_types") or []
    room = dict(rooms[0] if rooms else {})
    room_type_candidates = [dict(item) for item in rooms]
    demand = calculate_demand_index(context)
    progress = facts.get("progress_deviation") or {}
    orders = facts.get("orders_aggregate") or {}
    baseline = facts.get("sales_baseline") or {}
    baseline_price_by_room_type = baseline.get("baseline_price_by_room_type") or []
    decision_context = build_s5_decision_context(context, scenario_id="SC03")
    conversion_context = decision_context.get("conversion_health_context") or {}
    competitor_context = decision_context.get("competitor_context") or {}
    traffic_context = decision_context.get("traffic_timing_context") or {}
    return {
        **_context_safety(context),
        **snapshot,
        "room_type_id": room.get("room_type_id"),
        "room_type_name": room.get("room_type_name"),
        "current_price": room.get("current_price"),
        "floor_price": room.get("floor_price"),
        "ceiling_price": room.get("ceiling_price"),
        "candidate_price": room.get("candidate_price"),
        "conservative_price": room.get("conservative_price"),
        "max_single_change_pct": room.get("max_single_change_pct"),
        "max_increase_pct": room.get("max_increase_pct", room.get("max_single_change_pct")),
        "max_decrease_pct": room.get("max_decrease_pct", room.get("max_single_change_pct")),
        "min_increase_pct": room.get("min_increase_pct", 0.0),
        "min_decrease_pct": room.get("min_decrease_pct", 0.0),
        "channel": room.get("channel"),
        "adapter": room.get("adapter"),
        "method": room.get("method"),
        "room_type_candidates": room_type_candidates,
        "expected_occupancy_tonight": orders.get("expected_occupancy_tonight"),
        "expected_sold_rooms_tonight": orders.get("expected_sold_rooms_tonight"),
        "stayover_rooms": orders.get("stayover_rooms"),
        "departure_rooms": orders.get("departure_rooms"),
        "reservation_summary": orders.get("reservation_summary"),
        "reservation_details": orders.get("reservation_details"),
        "baseline_price": room.get("baseline_price"),
        "baseline_price_by_room_type": baseline_price_by_room_type,
        "sales_baseline": baseline.get("sales_baseline") or baseline.get("target_sold_rooms"),
        "target_room_nights": baseline.get("target_room_nights"),
        "hourly_target_curve": baseline.get("hourly_target_curve"),
        "baseline_confidence": baseline.get("baseline_confidence"),
        "demo_required_inputs_covered": bool(
            orders.get("expected_occupancy_tonight")
            and orders.get("reservation_details")
            and baseline_price_by_room_type
            and rooms
        ),
        "demand_index": demand.get("demand_index"),
        "demand_level": demand.get("demand_level"),
        "demand_formula_version": demand.get("formula_version"),
        "demand_sub_scores": demand.get("sub_scores") or {},
        "demand_calibration_applied": demand.get("calibration_applied") or [],
        "demand_pressure": float(demand.get("demand_index") or 0) / 100.0,
        "progress_status": progress.get("progress_status"),
        "as_of_checkpoint_gap": progress.get("as_of_checkpoint_gap"),
        "daily_remaining_gap": progress.get("daily_remaining_gap"),
        "as_of_actual_sold_rooms": progress.get("as_of_actual_sold_rooms"),
        "as_of_target_sold_rooms": progress.get("as_of_target_sold_rooms"),
        "time_grain": progress.get("time_grain"),
        "inventory_pressure": (demand.get("inventory_diagnosis") or {}).get("inventory_pressure"),
        "conversion_problem": conversion_context.get("conversion_problem"),
        "ota_health_score": conversion_context.get("ota_health_score"),
        "payment_conversion_rate": decision_context.get("payment_conversion_rate"),
        "our_price_index": competitor_context.get("our_price_index"),
        "current_window_type": traffic_context.get("current_window_type"),
        "pickup_speed": decision_context.get("pickup_speed"),
        "as_of_time": decision_context.get("as_of_time"),
        "as_of_time_source": decision_context.get("as_of_time_source"),
        "missing_time_context_fields": decision_context.get("missing_time_context_fields") or [],
        "source_capability": "read_only",
        **{
            key: decision_context.get(key)
            for key in [
                "contract_input_coverage",
                "runtime_feed_coverage",
                "algorithm_usage_coverage",
                "algorithm_used_inputs",
                "algorithm_unused_available_inputs",
                "field_usage_states",
                "decision_strength",
                "not_allowed_conclusions",
                "pricing_guard_context",
                "business_pressure_context",
                "market_context",
                "competitor_context",
                "traffic_timing_context",
                "conversion_health_context",
                "diagnosis_constraint_context",
                "data_gap_context",
                "direct_price_trigger_allowed",
            ]
        },
    }


def _node_algorithm_result(normalized: str, skill_id: str, context: dict[str, Any], *, db_path: str | None = None) -> dict[str, Any] | None:
    facts = context.get("facts") or {}
    if normalized == "N005":
        return {**dict(facts.get("business_snapshot") or business_snapshot()), **_context_safety(context), "algorithm_ref": "run_context_v27"}
    if skill_id == "S15" or normalized == "N010":
        baseline = dict(facts.get("sales_baseline") or {})
        baseline.update(_context_safety(context))
        baseline.update(
            {
                "node_id": "N010",
                "skill_id": "S15",
                "status": "preview_only",
                "algorithm_ref": "sales_baseline_from_run_context_v27",
                "target_room_nights": baseline.get("target_room_nights") or baseline.get("sales_baseline"),
                "hourly_target_curve": baseline.get("hourly_target_curve") or [],
                "baseline_confidence": baseline.get("baseline_confidence") or "synthetic_demo",
                "as_of_time": context.get("as_of_time"),
                "as_of_time_source": context.get("as_of_time_source"),
                "as_of_target_sold_rooms": (context.get("progress") or {}).get("as_of_target_sold_rooms"),
            }
        )
        return baseline
    if skill_id in {"S4"} or normalized == "N006":
        return calculate_demand_index(context)
    if skill_id == "S7":
        return calculate_competitor_alert(context)
    if skill_id == "S8":
        return calculate_activity_decision(context)
    if skill_id == "S10":
        return calculate_roi_decision(context)
    if skill_id == "S12":
        review = ((facts.get("reputation") or {}).get("reviews") or [{}])[0]
        return classify_review(review)
    if skill_id == "S13":
        review = ((facts.get("reputation") or {}).get("reviews") or [{}])[0]
        result = classify_review(review)
        result.update({"publish_allowed": False, "approval_required": True, "dry_run_only": True})
        return result
    if skill_id == "S14":
        return calculate_ota_health_score(context)
    if skill_id == "S17" or normalized == "N014":
        segments = dict(facts.get("customer_segments") or {})
        segments.update(_context_safety(context))
        segments.update(
            {
                "node_id": "N014",
                "skill_id": "S17",
                "status": "preview_only",
                "algorithm_ref": "customer_segments_from_run_context_v27",
                "database_source_required_for_demo": False,
                "row_level_orders_included": False,
                "privacy_policy": "aggregate_only_no_row_level_orders",
                "blocked_reason": "demo_preview_allowed_formal_live_blocked",
            }
        )
        return segments
    if skill_id == "S9" or normalized == "N020":
        s5_context = build_s5_decision_context(context, scenario_id="SC03")
        return {
            "demand_index": calculate_demand_index(context),
            "conversion_funnel": calculate_conversion_funnel(facts.get("external_ota_report_fields") or {}),
            **s5_context.get("traffic_timing_context", {}),
            **_context_safety(context),
        }
    if skill_id == "S16" or normalized == "N011":
        return build_progress_diagnosis(
            hotel_id=context.get("hotel_id") or "puyue-demo",
            business_date=context.get("business_date"),
            as_of_time=context.get("as_of_time"),
            context=context,
        )
    if skill_id == "S5":
        return run_revenue_decision_demo(
            {"demo_input": _revenue_input_from_context(context), "demo_meta": _context_safety(context)},
            db_path=db_path or context.get("_db_path"),
        )
    if skill_id == "S6":
        result = dict(facts.get("execution_preview") or execution_preview())
        result.update(_context_safety(context))
        result.update(_execution_preview_from_context(skill_id, context, db_path=db_path))
        return result
    if skill_id == "S11":
        result = dict(facts.get("promotion") or {})
        result.update(calculate_roi_decision(context))
        result.update(_execution_preview_from_context(skill_id, context))
        result.update(_context_safety(context))
        return result
    if skill_id == "S14-EXT":
        return {
            **_context_safety(context),
            "node_id": "N022",
            "skill_id": "S14-EXT",
            "status": "blocked",
            "blocked_reason": "s14_ext_migrated_to_independent_service",
            "summary": "第三方营销诊断已迁移到独立服务，本项目 demo chain 不再生成该报告。",
            "external_isolated": True,
            "live_allowed": False,
            "html_report_preview_status": "migrated",
        }
    return None


def _optional_nodes_from_edges(scenario: dict[str, Any]) -> list[str]:
    required = set(scenario.get("nodes") or [])
    edges = _edge_registry()
    optional: set[str] = set()
    for edge_id in scenario.get("optional_edges") or []:
        edge = edges.get(edge_id) or {}
        for field in ("source_node_id", "target_node_id"):
            node_id = edge.get(field)
            if node_id and node_id not in required:
                optional.add(str(node_id))
    return sorted(optional)


def build_demo_node_result(
    node_id: str,
    *,
    allow_placeholder: bool | None = None,
    db_path: str | None = None,
    hotel_id: str | None = None,
    use_generated_today: bool = False,
    demo_data_dir: str | None = None,
    strict_generated_today: bool = False,
    as_of_time: str | None = None,
    as_of_time_source: str | None = None,
) -> dict[str, Any]:
    normalized = node_id.upper()
    placeholder_allowed = allow_demo_placeholder() if allow_placeholder is None else allow_placeholder
    fixture = _load_demo_node_or_placeholder(normalized, allow_placeholder=placeholder_allowed)
    mapping = node_mapping(normalized)
    skill_id = mapping.get("skill_id") or fixture.get("skill_id") or "-"
    expected = fixture.get("expected_output") or {}
    status = "placeholder_demo" if fixture.get("placeholder") else expected.get("status", "preview_only")
    node_result: dict[str, Any] | None = None
    handoff_to = expected.get("handoff_to")
    context = resolve_business_context(
        db_path=db_path or os.environ.get("HOTEL_OTA_DB", ""),
        hotel_id=hotel_id,
        use_generated_today=use_generated_today,
        demo_data_dir=demo_data_dir,
        strict_generated_today=strict_generated_today,
        as_of_time=as_of_time,
        as_of_time_source=as_of_time_source,
    )
    if context.get("status") == "data_gap":
        return {
            "run_id": demo_run_id(f"demo-node-{normalized.lower()}"),
            "generated_by_runtime": True,
            "node_id": normalized,
            "node_name": mapping.get("node_name") or fixture.get("node_name"),
            "skill_id": skill_id,
            "agent_id": mapping.get("agent_id"),
            "status": "data_gap",
            "mode": "demo-node",
            **demo_metadata(),
            **_context_safety(context),
            "blocked_for_live": True,
            "handoff_to": handoff_to,
            "data_gaps": ["generated_today_demo_not_found"],
            "blocked_reason": context.get("reason") or "strict_generated_today_no_static_fallback",
            "run_context": _run_context_summary(context),
            "node_result": None,
            "node": fixture,
            "placeholder": bool(fixture.get("placeholder")),
        }

    algorithm_result = _node_algorithm_result(normalized, skill_id, context, db_path=db_path)
    if algorithm_result is not None:
        node_result = algorithm_result
        status = algorithm_result.get("status", status)
        handoff_to = algorithm_result.get("handoff_to", handoff_to)
    elif skill_id == "S5":
        node_result = run_revenue_decision_demo({"demo_input": revenue_decision_input(), "demo_meta": demo_metadata()})
        status = node_result["status"]
        handoff_to = node_result.get("handoff_to")
    elif skill_id == "S14-EXT":
        node_result = external_ota_report_preview()
        status = "preview_only"
    elif normalized == "N005":
        node_result = business_snapshot()
        status = "preview_only"

    result = {
        "run_id": demo_run_id(f"demo-node-{normalized.lower()}"),
        "generated_by_runtime": True,
        "node_id": normalized,
        "node_name": mapping.get("node_name") or fixture.get("node_name"),
        "skill_id": skill_id,
        "agent_id": mapping.get("agent_id"),
        "status": status,
        "mode": "demo-node",
        **demo_metadata(),
        **_context_safety(context),
        "blocked_for_live": True,
        "handoff_to": handoff_to,
        "data_gaps": expected.get("missing_fields") or [],
        "blocked_reason": "demo_data_never_live",
        "run_context": _run_context_summary(context),
        "as_of_time": context.get("as_of_time"),
        "as_of_time_source": context.get("as_of_time_source"),
        "node_result": node_result,
        "node": fixture,
        "placeholder": bool(fixture.get("placeholder")),
        "execution_policy": {
            "formal_approval": "blocked",
            "live_execution": "blocked",
            "allowed_outputs": ["dry_run", "preview_only", "simulation_only", "html_report_preview"],
        },
    }
    if skill_id in {"S6", "S11"}:
        result.update(_execution_preview_from_context(skill_id, context, db_path=db_path))
    if skill_id == "S3":
        result.update(
            {
                "message_preview_allowed": True,
                "message_send_attempted": False,
                "approval_card_preview_allowed": True,
                "formal_approval_created": False,
                "live_execution_count": 0,
            }
        )
    return result


def build_demo_chain_result(
    scenario_id: str,
    *,
    allow_placeholder: bool | None = None,
    db_path: str | None = None,
    hotel_id: str | None = None,
    use_generated_today: bool = False,
    demo_data_dir: str | None = None,
    strict_generated_today: bool = False,
    as_of_time: str | None = None,
    as_of_time_source: str | None = None,
) -> dict[str, Any]:
    normalized = scenario_id.upper()
    placeholder_allowed = allow_demo_placeholder() if allow_placeholder is None else allow_placeholder
    context = resolve_business_context(
        db_path=db_path or os.environ.get("HOTEL_OTA_DB", ""),
        hotel_id=hotel_id,
        use_generated_today=use_generated_today,
        demo_data_dir=demo_data_dir,
        strict_generated_today=strict_generated_today,
        as_of_time=as_of_time,
        as_of_time_source=as_of_time_source,
    )
    registry_scenario = _scenario_registry().get(normalized, {})
    scenario = _load_demo_scenario_or_placeholder(normalized, allow_placeholder=placeholder_allowed)
    required_nodes = list(registry_scenario.get("nodes") or scenario.get("nodes") or [])
    if context.get("status") == "data_gap":
        return {
            "run_id": demo_run_id(f"demo-chain-{normalized.lower()}"),
            "generated_by_runtime": True,
            "scenario_id": normalized,
            "scenario_name": registry_scenario.get("name") or scenario.get("name"),
            "required_nodes": required_nodes,
            "optional_nodes": [],
            "forbidden_nodes": [],
            "executed_nodes": [],
            "covered_nodes": [],
            "passed_nodes": [],
            "failed_nodes": required_nodes,
            "missing_nodes": required_nodes,
            "placeholder_nodes": [],
            "status": "data_gap",
            "mode": "demo-chain",
            **demo_metadata(),
            **_context_safety(context),
            "run_context": _run_context_summary(context),
            "context_source": context.get("context_source"),
            "use_generated_today": False,
            "requested_generated_today": True,
            "context_warnings": context.get("context_warnings") or [],
            "blocked_reason": context.get("reason") or "strict_generated_today_no_static_fallback",
            "scenario": scenario,
            "node_results": [],
            "fixtures": {},
        }
    optional_nodes = _optional_nodes_from_edges(registry_scenario or scenario)
    forbidden_nodes: list[str] = []
    node_results = [
                build_demo_node_result(
                    node_id,
                    allow_placeholder=placeholder_allowed,
                    db_path=db_path,
                    hotel_id=hotel_id,
            use_generated_today=use_generated_today,
            demo_data_dir=demo_data_dir,
            strict_generated_today=strict_generated_today,
            as_of_time=as_of_time,
            as_of_time_source=as_of_time_source,
        )
        for node_id in required_nodes
    ]
    executed_nodes = [item["node_id"] for item in node_results if item["node_id"] not in forbidden_nodes]
    missing_nodes = [item["node_id"] for item in node_results if item["status"] == "placeholder_demo"]
    failed_nodes = [item["node_id"] for item in node_results if item["status"] in {"failed", "blocked"}]
    fixtures = {fixture_id: _safe_load_demo_fixture(fixture_id, allow_placeholder=placeholder_allowed) for fixture_id in scenario.get("fixture_refs", [])}
    placeholder_nodes = [item["node_id"] for item in node_results if item.get("placeholder")]
    status = "ok" if not failed_nodes and not placeholder_nodes and not scenario.get("placeholder") else "failed"
    return {
        "run_id": demo_run_id(f"demo-chain-{normalized.lower()}"),
        "generated_by_runtime": True,
        "scenario_id": normalized,
        "scenario_name": registry_scenario.get("name") or scenario.get("name"),
        "required_nodes": required_nodes,
        "optional_nodes": optional_nodes,
        "forbidden_nodes": forbidden_nodes,
        "executed_nodes": executed_nodes,
        "covered_nodes": executed_nodes,
        "passed_nodes": [item["node_id"] for item in node_results if item["node_id"] not in failed_nodes and not item.get("placeholder")],
        "failed_nodes": failed_nodes,
        "missing_nodes": missing_nodes,
        "placeholder_nodes": placeholder_nodes,
        "status": status,
        "mode": "demo-chain",
        **demo_metadata(),
        **_context_safety(context),
        "run_context": _run_context_summary(context),
        "as_of_time": context.get("as_of_time"),
        "as_of_time_source": context.get("as_of_time_source"),
        "context_source": context.get("context_source"),
        "use_generated_today": bool(context.get("use_generated_today")),
        "requested_generated_today": bool(context.get("requested_generated_today")),
        "context_warnings": context.get("context_warnings") or [],
        "blocked_reason": "demo_preview_allowed_formal_live_blocked",
        "scenario": scenario,
        "node_results": node_results,
        "fixtures": fixtures,
        "stage_results": [
            {
                "stage": stage.get("stage"),
                "mode": stage.get("mode"),
                "edges": stage.get("edges") or [],
                "status": "preview_only",
                "blocked_reason": "demo_data_never_live",
            }
            for stage in registry_scenario.get("stages", [])
        ],
        "execution_policy": {
            "formal_approval": "blocked",
            "live_execution": "blocked",
            "allowed_outputs": ["dry_run", "preview_only", "simulation_only", "html_report_preview"],
        },
    }


def _failed_demo_chain_result(scenario_id: str, exc: Exception) -> dict[str, Any]:
    return {
        "run_id": demo_run_id(f"demo-chain-{scenario_id.lower()}"),
        "generated_by_runtime": True,
        "scenario_id": scenario_id,
        "status": "failed",
        "mode": "demo-chain",
        **demo_metadata(),
        "executed_nodes": [],
        "covered_nodes": [],
        "passed_nodes": [],
        "failed_nodes": [],
        "missing_nodes": [],
        "placeholder_nodes": [],
        "error": type(exc).__name__,
        "message": str(exc),
    }


def build_all_demo_chains_result(
    *,
    allow_placeholder: bool | None = None,
    db_path: str | None = None,
    hotel_id: str | None = None,
    use_generated_today: bool = False,
    demo_data_dir: str | None = None,
    strict_generated_today: bool = False,
    as_of_time: str | None = None,
    as_of_time_source: str | None = None,
) -> dict[str, Any]:
    scenario_ids = [f"SC{index:02d}" for index in range(1, 11)]
    placeholder_allowed = allow_demo_placeholder() if allow_placeholder is None else allow_placeholder
    context = resolve_business_context(
        db_path=db_path or os.environ.get("HOTEL_OTA_DB", ""),
        hotel_id=hotel_id,
        use_generated_today=use_generated_today,
        demo_data_dir=demo_data_dir,
        strict_generated_today=strict_generated_today,
        as_of_time=as_of_time,
        as_of_time_source=as_of_time_source,
    )
    if context.get("status") == "data_gap":
        return {
            "run_id": demo_run_id("demo-chain-all"),
            "generated_by_runtime": True,
            "status": "data_gap",
            "mode": "demo-chain",
            **demo_metadata(),
            **_context_safety(context),
            "run_context": _run_context_summary(context),
            "context_source": context.get("context_source"),
            "use_generated_today": False,
            "requested_generated_today": True,
            "context_warnings": context.get("context_warnings") or [],
            "total_scenarios": len(scenario_ids),
            "passed_scenarios": 0,
            "failed_scenarios": len(scenario_ids),
            "failed_scenario_ids": scenario_ids,
            "covered_nodes": [],
            "uncovered_nodes": [f"N{index:03d}" for index in range(1, 23)],
            "formal_approval_created": False,
            "live_execution_count": 0,
            "blocked_reason": context.get("reason") or "strict_generated_today_no_static_fallback",
            "chains": [],
        }
    chains = []
    for item in scenario_ids:
        try:
            chains.append(
                build_demo_chain_result(
                    item,
                    allow_placeholder=placeholder_allowed,
                    db_path=db_path,
                    hotel_id=hotel_id,
                    use_generated_today=use_generated_today,
                    demo_data_dir=demo_data_dir,
                    strict_generated_today=strict_generated_today,
                    as_of_time=as_of_time,
                    as_of_time_source=as_of_time_source,
                )
            )
        except FileNotFoundError as exc:
            chains.append(_failed_demo_chain_result(item, exc))
    covered_nodes = sorted({node_id for chain in chains for node_id in chain["executed_nodes"]})
    all_nodes = {f"N{index:03d}" for index in range(1, 23)}
    failed = [chain["scenario_id"] for chain in chains if chain["status"] != "ok"]
    return {
        "run_id": demo_run_id("demo-chain-all"),
        "generated_by_runtime": True,
        "status": "ok" if not failed else "failed",
        "mode": "demo-chain",
        **demo_metadata(),
        **_context_safety(context),
        "run_context": _run_context_summary(context),
        "as_of_time": context.get("as_of_time"),
        "as_of_time_source": context.get("as_of_time_source"),
        "context_source": context.get("context_source"),
        "use_generated_today": bool(context.get("use_generated_today")),
        "requested_generated_today": bool(context.get("requested_generated_today")),
        "context_warnings": context.get("context_warnings") or [],
        "total_scenarios": len(chains),
        "passed_scenarios": len(chains) - len(failed),
        "failed_scenarios": len(failed),
        "failed_scenario_ids": failed,
        "covered_nodes": covered_nodes,
        "uncovered_nodes": sorted(all_nodes - set(covered_nodes)),
        "formal_approval_created": False,
        "live_execution_count": 0,
        "blocked_reason": "demo_preview_allowed_formal_live_blocked",
        "chains": chains,
        "summary": {
            "total_scenarios": len(chains),
            "passed_scenarios": len(chains) - len(failed),
            "failed_scenarios": len(failed),
            "covered_nodes": covered_nodes,
            "uncovered_nodes": sorted(all_nodes - set(covered_nodes)),
            "formal_approval_created": False,
            "live_execution_count": 0,
            "context_source": context.get("context_source"),
            "use_generated_today": bool(context.get("use_generated_today")),
            "requested_generated_today": bool(context.get("requested_generated_today")),
            "context_warnings": context.get("context_warnings") or [],
        },
    }


def _failed_demo_node_result(node_id: str, exc: Exception) -> dict[str, Any]:
    mapping = node_mapping(node_id)
    return {
        "run_id": demo_run_id(f"demo-node-{node_id.lower()}"),
        "generated_by_runtime": True,
        "node_id": node_id,
        "node_name": mapping.get("node_name"),
        "skill_id": mapping.get("skill_id") or "-",
        "agent_id": mapping.get("agent_id"),
        "status": "failed",
        "mode": "demo-node",
        **demo_metadata(),
        "blocked_for_live": True,
        "placeholder": False,
        "error": type(exc).__name__,
        "message": str(exc),
    }


def build_all_demo_nodes_result(
    *,
    allow_placeholder: bool | None = None,
    db_path: str | None = None,
    hotel_id: str | None = None,
    use_generated_today: bool = False,
    demo_data_dir: str | None = None,
    strict_generated_today: bool = False,
    as_of_time: str | None = None,
    as_of_time_source: str | None = None,
) -> dict[str, Any]:
    node_ids = [f"N{index:03d}" for index in range(1, 23)]
    placeholder_allowed = allow_demo_placeholder() if allow_placeholder is None else allow_placeholder
    context = resolve_business_context(
        db_path=db_path or os.environ.get("HOTEL_OTA_DB", ""),
        hotel_id=hotel_id,
        use_generated_today=use_generated_today,
        demo_data_dir=demo_data_dir,
        strict_generated_today=strict_generated_today,
        as_of_time=as_of_time,
        as_of_time_source=as_of_time_source,
    )
    if context.get("status") == "data_gap":
        return {
            "run_id": demo_run_id("demo-node-all"),
            "generated_by_runtime": True,
            "status": "data_gap",
            "mode": "demo-node",
            **demo_metadata(),
            **_context_safety(context),
            "run_context": _run_context_summary(context),
            "context_source": context.get("context_source"),
            "use_generated_today": False,
            "requested_generated_today": True,
            "context_warnings": context.get("context_warnings") or [],
            "total_nodes": len(node_ids),
            "passed_nodes": 0,
            "failed_nodes": len(node_ids),
            "failed_node_ids": node_ids,
            "blocked_live_count": len(node_ids),
            "formal_approval_created": False,
            "live_execution_count": 0,
            "blocked_reason": context.get("reason") or "strict_generated_today_no_static_fallback",
            "nodes": [],
        }
    nodes = []
    for item in node_ids:
        try:
            nodes.append(
                build_demo_node_result(
                    item,
                    allow_placeholder=placeholder_allowed,
                    db_path=db_path,
                    hotel_id=hotel_id,
                    use_generated_today=use_generated_today,
                    demo_data_dir=demo_data_dir,
                    strict_generated_today=strict_generated_today,
                    as_of_time=as_of_time,
                    as_of_time_source=as_of_time_source,
                )
            )
        except FileNotFoundError as exc:
            nodes.append(_failed_demo_node_result(item, exc))
    failed = [node["node_id"] for node in nodes if node["status"] in {"failed", "blocked"} or node.get("placeholder")]
    return {
        "run_id": demo_run_id("demo-node-all"),
        "generated_by_runtime": True,
        "status": "ok" if not failed else "failed",
        "mode": "demo-node",
        **demo_metadata(),
        **_context_safety(context),
        "run_context": _run_context_summary(context),
        "as_of_time": context.get("as_of_time"),
        "as_of_time_source": context.get("as_of_time_source"),
        "context_source": context.get("context_source"),
        "use_generated_today": bool(context.get("use_generated_today")),
        "requested_generated_today": bool(context.get("requested_generated_today")),
        "context_warnings": context.get("context_warnings") or [],
        "total_nodes": len(nodes),
        "passed_nodes": len(nodes) - len(failed),
        "failed_nodes": len(failed),
        "failed_node_ids": failed,
        "blocked_live_count": sum(1 for node in nodes if node.get("blocked_for_live")),
        "formal_approval_created": False,
        "live_execution_count": 0,
        "blocked_reason": "demo_preview_allowed_formal_live_blocked",
        "nodes": nodes,
        "summary": {
            "total_nodes": len(nodes),
            "passed_nodes": len(nodes) - len(failed),
            "failed_nodes": len(failed),
            "blocked_live_count": sum(1 for node in nodes if node.get("blocked_for_live")),
            "formal_approval_created": False,
            "live_execution_count": 0,
            "context_source": context.get("context_source"),
            "use_generated_today": bool(context.get("use_generated_today")),
            "requested_generated_today": bool(context.get("requested_generated_today")),
            "context_warnings": context.get("context_warnings") or [],
        },
    }


def demo_chain(args: Any) -> None:
    if getattr(args, "all", False):
        emit(
            build_all_demo_chains_result(
                allow_placeholder=allow_demo_placeholder(args),
                db_path=getattr(args, "db", None),
                use_generated_today=bool(getattr(args, "use_generated_today", False)),
                demo_data_dir=getattr(args, "demo_data_dir", None),
                strict_generated_today=bool(getattr(args, "strict_generated_today", False)),
                as_of_time=getattr(args, "as_of_time", None),
                as_of_time_source="cli_explicit" if getattr(args, "as_of_time", None) else None,
            )
        )
        return
    emit(
        build_demo_chain_result(
            getattr(args, "scenario", "SC01"),
            allow_placeholder=allow_demo_placeholder(args),
            db_path=getattr(args, "db", None),
            use_generated_today=bool(getattr(args, "use_generated_today", False)),
            demo_data_dir=getattr(args, "demo_data_dir", None),
            strict_generated_today=bool(getattr(args, "strict_generated_today", False)),
            as_of_time=getattr(args, "as_of_time", None),
            as_of_time_source="cli_explicit" if getattr(args, "as_of_time", None) else None,
        )
    )


def demo_node(args: Any) -> None:
    if getattr(args, "all", False):
        emit(
            build_all_demo_nodes_result(
                allow_placeholder=allow_demo_placeholder(args),
                db_path=getattr(args, "db", None),
                use_generated_today=bool(getattr(args, "use_generated_today", False)),
                demo_data_dir=getattr(args, "demo_data_dir", None),
                strict_generated_today=bool(getattr(args, "strict_generated_today", False)),
                as_of_time=getattr(args, "as_of_time", None),
                as_of_time_source="cli_explicit" if getattr(args, "as_of_time", None) else None,
            )
        )
        return
    emit(
        build_demo_node_result(
            getattr(args, "node", "N001"),
            allow_placeholder=allow_demo_placeholder(args),
            db_path=getattr(args, "db", None),
            use_generated_today=bool(getattr(args, "use_generated_today", False)),
            demo_data_dir=getattr(args, "demo_data_dir", None),
            strict_generated_today=bool(getattr(args, "strict_generated_today", False)),
            as_of_time=getattr(args, "as_of_time", None),
            as_of_time_source="cli_explicit" if getattr(args, "as_of_time", None) else None,
        )
    )

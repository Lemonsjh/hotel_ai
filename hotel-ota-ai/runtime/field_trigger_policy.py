from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.algorithm_rule_loader import load_algorithm_rule
from runtime.common import PACKAGE_ROOT


CONTRACT_PATH = PACKAGE_ROOT / "contracts" / "v27" / "contract.json"
ROUTER_PATH = PACKAGE_ROOT / "router" / "scenario_router.yaml"


@lru_cache(maxsize=1)
def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _router() -> dict[str, Any]:
    return load_algorithm_rule(ROUTER_PATH)


def _scenario(scenario_id: str) -> dict[str, Any]:
    normalized = scenario_id.upper()
    for route in _router().get("routes") or []:
        if str(route.get("scenario_id")).upper() == normalized:
            return route
    raise KeyError(f"scenario not found: {scenario_id}")


def _skill(skill_id: str) -> dict[str, Any]:
    normalized = skill_id.upper()
    skills = _contract().get("skill_io_contract") or {}
    if normalized not in skills:
        raise KeyError(f"skill not found in V27 contract: {skill_id}")
    return skills[normalized]


def _edges(edge_ids: list[str] | set[str]) -> list[dict[str, Any]]:
    registry = _contract().get("edges") or {}
    return [dict(registry[edge_id], edge_id=edge_id) for edge_id in edge_ids if edge_id in registry]


def _edge_nodes(edge_ids: list[str] | set[str]) -> set[str]:
    nodes: set[str] = set()
    for edge in _edges(edge_ids):
        for key in ("source_node_id", "target_node_id"):
            if edge.get(key):
                nodes.add(str(edge[key]).upper())
    return nodes


def _edge_active_for_source(source_node: str | None, target_nodes: set[str], active_edges: set[str]) -> bool:
    if not source_node:
        return False
    normalized_source = source_node.upper()
    for edge in _edges(active_edges):
        if str(edge.get("source_node_id") or "").upper() == normalized_source and str(edge.get("target_node_id") or "").upper() in target_nodes:
            return True
    return False


def _canonical(field: dict[str, Any]) -> str:
    return str(field.get("canonical_key") or field.get("project_field_name") or field.get("field_id"))


def _available(field: dict[str, Any], available_fields: set[str]) -> bool:
    candidates = {
        str(field.get("field_id") or ""),
        str(field.get("canonical_key") or ""),
        str(field.get("project_field_name") or ""),
    }
    return bool(candidates & available_fields)


def _policy(required_level: str | None) -> str:
    text = required_level or ""
    if text == "必选":
        return "hard_required"
    if "按链路触发" in text:
        return "required_when_edge_active"
    if "增强" in text:
        return "enhancement_required"
    return "optional_context"


def evaluate_field_triggers(
    scenario_id: str,
    *,
    skill_id: str,
    available_fields: set[str] | list[str] | tuple[str, ...],
    active_optional_edges: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    scenario = _scenario(scenario_id)
    skill = _skill(skill_id)
    active_optional = {str(edge).upper() for edge in (active_optional_edges or set())}
    required_edges = {str(edge).upper() for edge in (scenario.get("required_edges") or [])}
    optional_edges = {str(edge).upper() for edge in (scenario.get("optional_edges") or [])}
    active_edges = required_edges | (optional_edges & active_optional)
    inactive_optional_edges = sorted(optional_edges - active_edges)

    active_nodes = _edge_nodes(active_edges)
    target_nodes = {str(node).upper() for node in (skill.get("node_ids") or [])}
    skill_triggered = bool(active_nodes & target_nodes)
    inputs = list(skill.get("inputs") or [])
    available = {str(item) for item in available_fields}

    if not skill_triggered:
        return {
            "scenario_id": scenario_id.upper(),
            "skill_id": skill_id.upper(),
            "status": "not_triggered",
            "active_edges": sorted(active_edges),
            "inactive_optional_edges": inactive_optional_edges,
            "active_nodes": sorted(active_nodes),
            "triggered_required_fields": [],
            "missing_triggered_fields": [],
            "untriggered_optional_fields": sorted({_canonical(field) for field in inputs}),
            "missing_by_policy": {},
            "field_policy": {},
        }

    triggered: set[str] = set()
    untriggered: set[str] = set()
    missing_by_policy: dict[str, list[str]] = {
        "hard_required": [],
        "required_when_edge_active": [],
        "enhancement_required": [],
        "formal_required": [],
        "optional_context": [],
    }
    field_policy: dict[str, str] = {}

    for field in inputs:
        canonical = _canonical(field)
        policy = _policy(field.get("required_level"))
        is_triggered = policy in {"hard_required", "enhancement_required"}
        if policy == "required_when_edge_active":
            is_triggered = _edge_active_for_source(field.get("source_node"), target_nodes, active_edges)
        if is_triggered:
            triggered.add(canonical)
            field_policy[canonical] = policy
            if not _available(field, available):
                missing_by_policy.setdefault(policy, []).append(canonical)
        else:
            untriggered.add(canonical)

    missing = sorted({field for fields in missing_by_policy.values() for field in fields})
    return {
        "scenario_id": scenario_id.upper(),
        "skill_id": skill_id.upper(),
        "status": "active",
        "active_edges": sorted(active_edges),
        "inactive_optional_edges": inactive_optional_edges,
        "active_nodes": sorted(active_nodes),
        "triggered_required_fields": sorted(triggered),
        "missing_triggered_fields": missing,
        "untriggered_optional_fields": sorted(untriggered),
        "missing_by_policy": {key: sorted(set(value)) for key, value in missing_by_policy.items()},
        "field_policy": field_policy,
    }

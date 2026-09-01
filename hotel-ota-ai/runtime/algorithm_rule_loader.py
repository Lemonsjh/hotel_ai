from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.common import PACKAGE_ROOT


RULE_DIR = PACKAGE_ROOT / "runtime" / "algorithm_rules"


def load_algorithm_rule(path: str | Path) -> dict[str, Any]:
    rule_path = Path(path)
    text = rule_path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as json_error:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ValueError(
                f"{rule_path} is not JSON-compatible YAML, and PyYAML is not installed for YAML parsing"
            ) from exc
        try:
            payload = yaml.safe_load(text)
        except Exception as exc:  # pragma: no cover - depends on optional PyYAML parser
            raise ValueError(f"{rule_path} could not be parsed as JSON or YAML: {exc}") from json_error
        if not isinstance(payload, dict):
            raise ValueError(f"{rule_path} must parse to an object")
        return payload


def load_all_algorithm_rules(base_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    root = Path(base_dir) if base_dir else RULE_DIR
    rules: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.yaml")):
        payload = load_algorithm_rule(path)
        owner = payload.get("owner_skill") or path.stem
        rules[str(owner)] = payload
    return rules


def list_algorithm_rules(base_dir: str | Path | None = None) -> list[dict[str, Any]]:
    return list(load_all_algorithm_rules(base_dir).values())


def validate_algorithm_rule(payload: dict[str, Any]) -> dict[str, Any]:
    missing: list[str] = []
    for field in ["owner_skill", "status", "demo_safety", "data_gate", "algorithm", "forbidden_actions", "demo_behavior_cases"]:
        if field not in payload:
            missing.append(field)

    algorithm = payload.get("algorithm") or {}
    for field in ["objective", "ordered_steps", "thresholds", "degradation", "output_contract"]:
        if field not in algorithm:
            missing.append(f"algorithm.{field}")

    if payload.get("status") != "implemented":
        missing.append("status=implemented")
    if not algorithm.get("ordered_steps"):
        missing.append("algorithm.ordered_steps.non_empty")
    if not payload.get("forbidden_actions"):
        missing.append("forbidden_actions.non_empty")
    if not payload.get("demo_behavior_cases"):
        missing.append("demo_behavior_cases.non_empty")

    demo_safety = payload.get("demo_safety") or {}
    if demo_safety.get("data_source_type") != "demo_data":
        missing.append("demo_safety.data_source_type=demo_data")
    if demo_safety.get("approval_data_allowed") is not False:
        missing.append("demo_safety.approval_data_allowed=false")
    if demo_safety.get("live_allowed") is not False:
        missing.append("demo_safety.live_allowed=false")

    return {"valid": not missing, "missing": missing, "owner_skill": payload.get("owner_skill")}

def find_algorithm_rule(skill_id: str | None = None, node_id: str | None = None, base_dir: str | Path | None = None) -> dict[str, Any]:
    rules = load_all_algorithm_rules(base_dir)
    if skill_id and skill_id in rules:
        return rules[skill_id]
    if node_id:
        for payload in rules.values():
            if payload.get("node_id") == node_id:
                return payload
    raise KeyError(f"algorithm rule not found for skill_id={skill_id!r}, node_id={node_id!r}")


def rule_execution_status(skill_id: str | None = None, node_id: str | None = None, base_dir: str | Path | None = None) -> dict[str, Any]:
    payload = find_algorithm_rule(skill_id=skill_id, node_id=node_id, base_dir=base_dir)
    executed_by = payload.get("executed_by_runtime") or []
    return {
        "owner_skill": payload.get("owner_skill"),
        "node_id": payload.get("node_id"),
        "rule_config_status": payload.get("status"),
        "runtime_execution_status": "executed" if executed_by else "rule_config_exists_but_not_executed",
        "executed_by_runtime": executed_by,
    }


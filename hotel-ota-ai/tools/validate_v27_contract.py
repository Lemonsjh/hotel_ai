from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "contracts" / "v27" / "contract.json"

REQUIRED_TOP_LEVEL_KEYS = {
    "metadata",
    "source_priority",
    "field_governance_policy",
    "agents",
    "skills",
    "nodes",
    "edges",
    "scenarios",
    "field_registry",
    "node_io_contract",
    "skill_io_contract",
    "edge_payload_contract",
    "source_alias_mapping",
    "source_field_inventory",
    "algorithm_field_requirements",
    "output_field_dictionary",
    "upstream_output_mapping",
    "field_gap_pending_confirmation",
    "demo_data_contract",
    "runtime_contract",
    "feishu_output_contract",
    "drawio_sync_policy",
    "validation_rules",
}

ALLOWED_STATUSES = {
    "confirmed_exact",
    "confirmed_alias",
    "candidate_inferred",
    "project_only",
    "config_only",
    "algorithm_output",
    "upstream_output",
    "manual_required",
    "not_available",
    "deprecated",
}

ALLOWED_DATA_TYPES = {
    "string",
    "number",
    "integer",
    "boolean",
    "datetime",
    "date",
    "object",
    "array",
    "enum",
    "money",
    "ratio",
}

EXPECTED_AGENT_MAPPING = {
    "A0": ["N001", "N002", "N003", "N004"],
    "A1": ["N005", "N006", "N007", "N008", "N014", "N020"],
    "A2": ["N009", "N010", "N011", "N022"],
    "A3": ["N012", "N013", "N015"],
    "A4": ["N016", "N017", "N021"],
    "A5": ["N018"],
    "A6": ["N019"],
}


def load_contract() -> dict[str, Any]:
    if not CONTRACT_PATH.exists():
        raise FileNotFoundError(f"missing V27 contract: {CONTRACT_PATH}")
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _values(section: Any) -> list[dict[str, Any]]:
    if isinstance(section, dict):
        return [item for item in section.values() if isinstance(item, dict)]
    if isinstance(section, list):
        return [item for item in section if isinstance(item, dict)]
    return []


def validate_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_TOP_LEVEL_KEYS - set(contract))
    if missing:
        errors.append(f"missing top-level keys: {', '.join(missing)}")

    metadata = contract.get("metadata") or {}
    if metadata.get("machine_readable") is not True:
        errors.append("metadata.machine_readable must be true")
    if "V27" not in str(metadata.get("contract_version") or ""):
        errors.append("metadata.contract_version must contain V27")

    expected_counts = {
        "agents": 7,
        "skills": 18,
        "nodes": 22,
        "edges": 67,
        "scenarios": 10,
    }
    for section, expected in expected_counts.items():
        actual = len(contract.get(section) or {})
        if actual != expected:
            errors.append(f"{section} count {actual} != {expected}")

    for section in ("field_registry", "node_io_contract", "skill_io_contract", "edge_payload_contract"):
        if not contract.get(section):
            errors.append(f"{section} must not be empty")

    field_ids: set[str] = set()
    for field in _values(contract.get("field_registry")):
        field_id = str(field.get("field_id") or "")
        key = str(field.get("canonical_key") or "")
        if not field_id or field_id in field_ids:
            errors.append(f"duplicate or missing field_id: {field_id}")
        field_ids.add(field_id)
        if not key:
            errors.append(f"{field_id}: canonical_key missing")
        if key and not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            errors.append(f"{field_id}: canonical_key is not snake_case: {key}")
        if field.get("source_match_status") not in ALLOWED_STATUSES:
            errors.append(f"{field_id}: unsupported status {field.get('source_match_status')}")
        if field.get("data_type") not in ALLOWED_DATA_TYPES:
            errors.append(f"{field_id}: unsupported data_type {field.get('data_type')}")

    node_ids = {str(node.get("node_id")) for node in _values(contract.get("nodes"))}
    edge_ids = {str(edge.get("edge_id")) for edge in _values(contract.get("edges"))}
    if node_ids != {f"N{index:03d}" for index in range(1, 23)}:
        errors.append("nodes must cover N001-N022")
    if edge_ids != {f"E{index:03d}" for index in range(1, 68)}:
        errors.append("edges must cover E001-E067")

    actual_agent_mapping: dict[str, list[str]] = {agent: [] for agent in EXPECTED_AGENT_MAPPING}
    for node in _values(contract.get("nodes")):
        actual_agent_mapping.setdefault(str(node.get("agent_id")), []).append(str(node.get("node_id")))
    for agent_id, expected_nodes in EXPECTED_AGENT_MAPPING.items():
        actual_nodes = sorted(actual_agent_mapping.get(agent_id, []))
        if actual_nodes != expected_nodes:
            errors.append(f"{agent_id} nodes {actual_nodes} != {expected_nodes}")

    for scenario in _values(contract.get("scenarios")):
        scenario_id = str(scenario.get("scenario_id") or "")
        if not scenario_id:
            errors.append("scenario_id missing")
        if not set(scenario.get("node_chain") or []).issubset(node_ids):
            errors.append(f"{scenario_id}: node_chain references missing node")
        if not set(scenario.get("required_edges") or []).issubset(edge_ids):
            errors.append(f"{scenario_id}: required_edges references missing edge")

    return errors


def main() -> int:
    try:
        contract = load_contract()
        errors = validate_contract(contract)
    except Exception as exc:  # pragma: no cover - command path
        errors = [f"{type(exc).__name__}: {exc}"]
    payload = {
        "status": "ok" if not errors else "failed",
        "contract": str(CONTRACT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "errors": errors,
        "error_count": len(errors),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

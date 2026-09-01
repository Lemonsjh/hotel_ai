from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.common import PACKAGE_ROOT


V27_CONTRACT_PATH = PACKAGE_ROOT / "contracts" / "v27" / "contract.json"


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_v27_contract() -> dict[str, Any]:
    return load_json(V27_CONTRACT_PATH)


def _section_item(section: str, item_id: str) -> dict[str, Any]:
    payload = load_v27_contract().get(section) or {}
    normalized = str(item_id)
    if isinstance(payload, dict):
        item = payload.get(normalized)
        if item:
            return dict(item)
        for candidate in payload.values():
            if not isinstance(candidate, dict):
                continue
            candidate_ids = {
                str(candidate.get("field_id")),
                str(candidate.get("canonical_key")),
                str(candidate.get("node_id")),
                str(candidate.get("skill_id")),
                str(candidate.get("edge_id")),
                str(candidate.get("scenario_id")),
                str(candidate.get("agent_id")),
            }
            if normalized in candidate_ids:
                return dict(candidate)
    raise KeyError(f"unknown V27 {section} item: {item_id}")


def get_field(field_id: str) -> dict[str, Any]:
    return _section_item("field_registry", field_id)


def get_field_by_key(canonical_key: str) -> dict[str, Any]:
    return _section_item("field_registry", canonical_key)


def get_node(node_id: str) -> dict[str, Any]:
    return _section_item("nodes", str(node_id).upper())


def get_node_io(node_id: str) -> dict[str, Any]:
    return _section_item("node_io_contract", str(node_id).upper())


def get_skill(skill_id: str) -> dict[str, Any]:
    return _section_item("skills", str(skill_id).upper())


def get_edge(edge_id: str) -> dict[str, Any]:
    return _section_item("edges", str(edge_id).upper())


def get_scenario(scenario_id: str) -> dict[str, Any]:
    return _section_item("scenarios", str(scenario_id).upper())


def get_agent_for_node(node_id: str) -> str:
    return str(get_node(node_id).get("agent_id") or "")


def validate_contract() -> dict[str, Any]:
    from runtime.v27_contract_validator import validate_v27_contract

    errors = validate_v27_contract(load_v27_contract())
    return {"status": "ok" if not errors else "failed", "errors": errors, "error_count": len(errors)}


def load_v27_field_registry() -> dict[str, Any]:
    return load_json(PACKAGE_ROOT / "contracts" / "v27" / "field_registry.yaml")


def load_v27_node_io_contract() -> dict[str, Any]:
    return load_json(PACKAGE_ROOT / "contracts" / "v27" / "node_io_contract.yaml")


def load_v27_skill_io_contract() -> dict[str, Any]:
    return load_json(PACKAGE_ROOT / "contracts" / "v27" / "skill_io_contract.yaml")


def load_v27_edge_payload_contract() -> dict[str, Any]:
    return load_json(PACKAGE_ROOT / "contracts" / "v27" / "edge_payload_contract.yaml")


def load_v27_scenario_chain_contract() -> dict[str, Any]:
    return load_json(PACKAGE_ROOT / "contracts" / "v27" / "scenario_chain_contract.yaml")

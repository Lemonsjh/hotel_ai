from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.common import PACKAGE_ROOT
from runtime.v27_contract_loader import load_v27_contract


NODE_AGENT_MAPPING_PATH = PACKAGE_ROOT / "architecture" / "node_agent_mapping.json"


@lru_cache(maxsize=1)
def load_node_agent_mapping(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    if path is None:
        contract = load_v27_contract()
        mappings = [
            {
                "node_id": node.get("node_id"),
                "node_name": node.get("node_name"),
                "agent_id": node.get("agent_id"),
                "skill_id": node.get("skill_id"),
                "source": "contracts/v27/contract.json",
            }
            for node in contract.get("nodes", {}).values()
        ]
    else:
        import json

        source = Path(path)
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        mappings = payload.get("mappings") or []
    result = {str(item["node_id"]): dict(item) for item in mappings if item.get("node_id")}
    if len(result) < 22:
        raise ValueError("node_agent_mapping must define N001-N022")
    return result


def node_mapping(node_id: str) -> dict[str, Any]:
    normalized = str(node_id).upper()
    mapping = load_node_agent_mapping().get(normalized)
    if not mapping:
        raise KeyError(f"missing node_agent_mapping for {normalized}")
    return dict(mapping)


def agent_id_for_node(node_id: str) -> str:
    return str(node_mapping(node_id)["agent_id"])


def skill_id_for_node(node_id: str) -> str:
    return str(node_mapping(node_id).get("skill_id") or "-")

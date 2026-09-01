from __future__ import annotations

from functools import lru_cache
from typing import Any

from runtime.v26_contract_loader import load_v26_node_io_contract


@lru_cache(maxsize=1)
def nodes_by_id() -> dict[str, dict[str, Any]]:
    contract = load_v26_node_io_contract()
    return {str(node["node_id"]): dict(node) for node in contract.get("nodes", [])}


def get_node(node_id: str) -> dict[str, Any]:
    normalized = str(node_id).upper()
    node = nodes_by_id().get(normalized)
    if not node:
        raise KeyError(f"unknown V26 node: {node_id}")
    return dict(node)


def node_field_keys(node_id: str, direction: str) -> list[str]:
    node = get_node(node_id)
    key = "input_fields" if direction == "input" else "output_fields"
    return [str(field.get("canonical_key")) for field in node.get(key, []) if field.get("canonical_key")]

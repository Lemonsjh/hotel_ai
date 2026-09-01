from __future__ import annotations

from functools import lru_cache
from typing import Any

from runtime.v27_contract_loader import load_v27_contract


@lru_cache(maxsize=1)
def nodes_by_id() -> dict[str, dict[str, Any]]:
    return {str(node["node_id"]): dict(node) for node in load_v27_contract()["nodes"].values()}


def get_node(node_id: str) -> dict[str, Any]:
    normalized = str(node_id).upper()
    node = nodes_by_id().get(normalized)
    if not node:
        raise KeyError(f"unknown V27 node: {node_id}")
    return dict(node)


def node_ids() -> set[str]:
    return set(nodes_by_id())

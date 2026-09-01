from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from runtime.common import PACKAGE_ROOT


CONTRACT_DIR = PACKAGE_ROOT / "contracts" / "v27"


def load_json_compatible(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_field_registry(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir) if base_dir else CONTRACT_DIR
    return load_json_compatible(root / "field_registry.yaml")


def load_node_io_contract(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir) if base_dir else CONTRACT_DIR
    return load_json_compatible(root / "node_io_contract.yaml")


def load_source_mapping(base_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(base_dir) if base_dir else CONTRACT_DIR
    path = root / "source_alias_mapping.yaml"
    if not path.exists() and base_dir is not None:
        path = root / "source_mapping.yaml"
    return load_json_compatible(path)


def find_node_contract(node_id: str, base_dir: str | Path | None = None) -> dict[str, Any]:
    contract = load_node_io_contract(base_dir)
    for node in contract.get("nodes", []):
        if node.get("node_id") == node_id:
            return node
    raise KeyError(f"unknown node contract: {node_id}")

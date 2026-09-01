from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from runtime.common import PACKAGE_ROOT


V26_REFERENCE_DIR = PACKAGE_ROOT / "docs" / "architecture_reference" / "v26"
V26_CONTRACT_DIR = PACKAGE_ROOT / "contracts" / "v26"


def load_json_compatible(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _first_matching(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"missing V26 reference file: {directory / pattern}")
    return matches[0]


@lru_cache(maxsize=1)
def v26_reference_json_path() -> Path:
    return _first_matching(V26_REFERENCE_DIR, "*V26*.json")


@lru_cache(maxsize=1)
def load_v26_reference_json() -> dict[str, Any]:
    return load_json_compatible(v26_reference_json_path())


def load_v26_contract(name: str) -> dict[str, Any]:
    filename = name if name.endswith(".yaml") else f"{name}.yaml"
    return load_json_compatible(V26_CONTRACT_DIR / filename)


def load_v26_field_registry() -> dict[str, Any]:
    return load_v26_contract("field_registry")


def load_v26_node_io_contract() -> dict[str, Any]:
    return load_v26_contract("node_io_contract")


def load_v26_skill_io_contract() -> dict[str, Any]:
    return load_v26_contract("skill_io_contract")


def load_v26_edge_payload_contract() -> dict[str, Any]:
    return load_v26_contract("edge_payload_contract")


def load_v26_scenario_chain_contract() -> dict[str, Any]:
    return load_v26_contract("scenario_chain_contract")


def load_v26_source_alias_mapping() -> dict[str, Any]:
    return load_v26_contract("source_alias_mapping")

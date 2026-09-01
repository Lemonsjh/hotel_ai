from __future__ import annotations

from functools import lru_cache
from typing import Any

from runtime.v27_contract_loader import load_v27_contract


@lru_cache(maxsize=1)
def fields_by_key() -> dict[str, dict[str, Any]]:
    return {str(field["canonical_key"]): dict(field) for field in load_v27_contract()["field_registry"].values()}


@lru_cache(maxsize=1)
def fields_by_id() -> dict[str, dict[str, Any]]:
    return {str(field["field_id"]): dict(field) for field in load_v27_contract()["field_registry"].values()}


def get_field(key_or_id: str) -> dict[str, Any]:
    value = str(key_or_id)
    field = fields_by_key().get(value) or fields_by_id().get(value)
    if not field:
        raise KeyError(f"unknown V27 field: {key_or_id}")
    return dict(field)


def canonical_keys() -> set[str]:
    return set(fields_by_key())

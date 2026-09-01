from __future__ import annotations

import re
from typing import Any


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


def _values(section: Any) -> list[dict[str, Any]]:
    if isinstance(section, dict):
        return [item for item in section.values() if isinstance(item, dict)]
    if isinstance(section, list):
        return [item for item in section if isinstance(item, dict)]
    return []


def validate_v27_contract(contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    metadata = contract.get("metadata") or {}
    if metadata.get("machine_readable") is not True:
        errors.append("metadata.machine_readable must be true")
    if "V27" not in str(metadata.get("contract_version") or ""):
        errors.append("metadata.contract_version must contain V27")
    for section, expected in {"agents": 7, "skills": 18, "nodes": 22, "edges": 67, "scenarios": 10}.items():
        actual = len(contract.get(section) or {})
        if actual != expected:
            errors.append(f"{section} count {actual} != {expected}")
    seen_ids: set[str] = set()
    for field in _values(contract.get("field_registry")):
        field_id = str(field.get("field_id") or "")
        key = str(field.get("canonical_key") or "")
        if not field_id or field_id in seen_ids:
            errors.append(f"duplicate or missing field_id: {field_id}")
        seen_ids.add(field_id)
        if not key:
            errors.append(f"{field_id}: canonical_key missing")
        if key and not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            errors.append(f"{field_id}: canonical_key not snake_case: {key}")
        if field.get("source_match_status") not in ALLOWED_STATUSES:
            errors.append(f"{field_id}: unsupported source_match_status {field.get('source_match_status')}")
        if field.get("data_type") not in ALLOWED_DATA_TYPES:
            errors.append(f"{field_id}: unsupported data_type {field.get('data_type')}")
    return errors

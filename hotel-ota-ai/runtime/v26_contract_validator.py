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


def validate_v26_field_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_keys: set[str] = set()
    for field in registry.get("fields", []):
        field_id = str(field.get("field_id") or "")
        key = str(field.get("canonical_key") or "")
        if not field_id:
            errors.append("field_id missing")
        elif field_id in seen_ids:
            errors.append(f"duplicate field_id: {field_id}")
        seen_ids.add(field_id)
        if not key:
            errors.append(f"{field_id}: canonical_key missing")
        elif not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            errors.append(f"{field_id}: canonical_key not snake_case: {key}")
        elif key in seen_keys:
            errors.append(f"duplicate canonical_key: {key}")
        seen_keys.add(key)
        if field.get("data_type") not in ALLOWED_DATA_TYPES:
            errors.append(f"{field_id}: unsupported data_type {field.get('data_type')}")
        if field.get("source_match_status") not in ALLOWED_STATUSES:
            errors.append(f"{field_id}: unsupported source_match_status {field.get('source_match_status')}")
        if "待命名字段" in str(field) or "字段覆盖率率" in str(field):
            errors.append(f"{field_id}: unresolved naming issue")
    return errors


def validate_v26_node_io(node_io: dict[str, Any], field_keys: set[str]) -> list[str]:
    errors: list[str] = []
    nodes = node_io.get("nodes", [])
    expected = {f"N{index:03d}" for index in range(1, 23)}
    actual = {str(node.get("node_id")) for node in nodes}
    for missing in sorted(expected - actual):
        errors.append(f"missing node: {missing}")
    for node in nodes:
        node_id = node.get("node_id")
        if not node.get("input_fields"):
            errors.append(f"{node_id}: input_fields missing")
        if not node.get("output_fields"):
            errors.append(f"{node_id}: output_fields missing")
        for direction in ("input_fields", "output_fields"):
            for field in node.get(direction, []):
                key = field.get("canonical_key")
                if key and key not in field_keys:
                    errors.append(f"{node_id}: {direction} unknown field {key}")
    return errors

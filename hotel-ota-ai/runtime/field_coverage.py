from __future__ import annotations

from typing import Any, Iterable


EMPTY_VALUES = (None, "", [], {})


def evaluate_field_coverage(required_fields: Iterable[str], payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload or {}
    required = list(dict.fromkeys(required_fields or []))
    present = [field for field in required if data.get(field) not in EMPTY_VALUES]
    missing = [field for field in required if field not in present]
    coverage_rate = 1.0 if not required else round(len(present) / len(required), 4)
    return {
        "required_count": len(required),
        "present_count": len(present),
        "missing_count": len(missing),
        "present_fields": present,
        "missing_fields": missing,
        "field_coverage_rate": coverage_rate,
    }


def calculate_field_coverage(
    *,
    required_fields: Iterable[str],
    available_fields: Iterable[str],
    partial_fields: Iterable[str] | None = None,
    missing_fields: Iterable[str] | None = None,
) -> dict[str, Any]:
    required = list(dict.fromkeys(required_fields or []))
    available = list(dict.fromkeys(available_fields or []))
    partial = list(dict.fromkeys(partial_fields or []))
    explicit_missing = set(missing_fields or [])
    required_set = set(required)
    available_set = set(available)
    partial_set = set(partial)
    calculated_missing = [field for field in required if field not in available_set and field not in partial_set]
    missing = list(dict.fromkeys([*calculated_missing, *[field for field in explicit_missing if field in required_set]]))
    weighted_present = len([field for field in required if field in available_set]) + 0.5 * len(
        [field for field in required if field in partial_set]
    )
    coverage_rate = 1.0 if not required else round(weighted_present / len(required), 4)
    return {
        "required_count": len(required),
        "available_count": len([field for field in required if field in available_set]),
        "partial_count": len([field for field in required if field in partial_set]),
        "missing_count": len(missing),
        "required_fields": required,
        "available_fields": [field for field in required if field in available_set],
        "partial_fields": [field for field in required if field in partial_set],
        "missing_fields": missing,
        "field_coverage_rate": coverage_rate,
        "coverage_formula": "(available_required_fields + 0.5 * partial_required_fields) / required_fields",
    }

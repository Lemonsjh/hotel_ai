from __future__ import annotations

from typing import Any, Iterable

from runtime.demo_mode import DEMO_METADATA, is_demo_payload
from runtime.field_coverage import evaluate_field_coverage


def evaluate_data_gate(
    payload: dict[str, Any] | None,
    *,
    hard_required: Iterable[str] | None = None,
    soft_required: Iterable[str] | None = None,
    allow_demo_preview: bool = True,
) -> dict[str, Any]:
    data = payload or {}
    hard_coverage = evaluate_field_coverage(hard_required or [], data)
    soft_coverage = evaluate_field_coverage(soft_required or [], data)

    if is_demo_payload(data):
        return {
            "status": "ok" if allow_demo_preview else "blocked",
            "allowed": allow_demo_preview,
            "reason": "demo_preview_only",
            "demo_mode": True,
            **DEMO_METADATA,
            "hard_required": hard_coverage,
            "soft_required": soft_coverage,
            "missing_fields": hard_coverage["missing_fields"],
        }

    if hard_coverage["missing_fields"]:
        return {
            "status": "blocked",
            "allowed": False,
            "reason": "missing_hard_required_fields",
            "demo_mode": False,
            "data_source_type": data.get("data_source_type"),
            "freshness_status": data.get("freshness_status"),
            "business_status": data.get("business_status"),
            "approval_data_allowed": False,
            "live_allowed": False,
            "hard_required": hard_coverage,
            "soft_required": soft_coverage,
            "missing_fields": hard_coverage["missing_fields"],
        }

    approval_allowed = data.get("freshness_status") == "fresh" and data.get("business_status") in (None, "current")
    return {
        "status": "ok",
        "allowed": True,
        "reason": "data_gate_passed",
        "demo_mode": False,
        "data_source_type": data.get("data_source_type"),
        "freshness_status": data.get("freshness_status"),
        "business_status": data.get("business_status"),
        "approval_data_allowed": approval_allowed,
        "live_allowed": bool(data.get("live_allowed") is True and approval_allowed),
        "hard_required": hard_coverage,
        "soft_required": soft_coverage,
        "missing_fields": [],
    }


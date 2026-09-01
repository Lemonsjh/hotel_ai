from __future__ import annotations

from typing import Any

from runtime.demo_mode import is_demo_payload
from runtime.safety.approvals import validate_approval_payload


def validate_demo_safe_approval_payload(payload: dict[str, Any], action_type: str) -> dict[str, Any]:
    if is_demo_payload(payload) or payload.get("approval_data_allowed") is False:
        return {
            "allowed": False,
            "reason": "approval_not_allowed_for_demo_data",
            "template_id": "demo-data",
        }
    return validate_approval_payload(payload, action_type)


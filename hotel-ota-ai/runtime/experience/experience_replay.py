from __future__ import annotations

from typing import Any


def replay_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    status_ok = candidate.get("status") in {"reviewed", "approved"}
    passed = (
        status_ok
        and
        candidate.get("privacy_checked") is True
        and candidate.get("contains_real_customer_data") is False
        and candidate.get("requires_human_review") is True
        and candidate.get("no_incremental_value") is not True
    )
    return {
        "status": "ok" if passed else "blocked",
        "candidate_id": candidate.get("candidate_id"),
        "replay_status": "passed" if passed else "failed",
        "replay_checks": {
            "privacy_checked": candidate.get("privacy_checked") is True,
            "contains_real_customer_data": candidate.get("contains_real_customer_data") is False,
            "requires_human_review": candidate.get("requires_human_review") is True,
            "status_reviewed_or_approved": status_ok,
            "has_incremental_value": candidate.get("no_incremental_value") is not True,
            "approval_data_allowed_unchanged": True,
            "live_allowed_unchanged": True,
        },
        "approval_data_allowed": False,
        "live_allowed": False,
        "production_rule_modified": False,
    }

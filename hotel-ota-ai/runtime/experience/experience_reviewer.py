from __future__ import annotations

from typing import Any

from runtime.experience.experience_candidate import validate_candidate


def review_candidate(candidate: dict[str, Any], *, approve: bool, reviewer: str = "manual_reviewer") -> dict[str, Any]:
    errors = validate_candidate(candidate)
    if approve and candidate.get("no_incremental_value") is True:
        errors.append("no_incremental_value_rejected")
    if errors:
        rejected = dict(candidate)
        rejected["status"] = "rejected"
        rejected["reviewed_by"] = reviewer
        return {
            "status": "blocked",
            "candidate_id": candidate.get("candidate_id"),
            "review_action": "approve" if approve else "reject",
            "candidate_status": "rejected",
            "candidate": rejected,
            "errors": errors,
            "approval_data_allowed": False,
            "live_allowed": False,
            "production_rule_modified": False,
        }
    reviewed = dict(candidate)
    reviewed["reviewed_by"] = reviewer
    reviewed["status"] = "approved" if approve else "rejected"
    return {
        "status": "ok",
        "candidate_id": reviewed["candidate_id"],
        "review_action": "approve" if approve else "reject",
        "candidate_status": reviewed["status"],
        "candidate": reviewed,
        "approval_data_allowed": False,
        "live_allowed": False,
        "production_rule_modified": False,
    }

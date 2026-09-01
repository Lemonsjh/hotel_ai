from __future__ import annotations

from typing import Any
import uuid


def promote_candidate(candidate: dict[str, Any], *, replay_result: dict[str, Any] | None = None, dry_run: bool = True) -> dict[str, Any]:
    source_type = candidate.get("source_data_source_type") or candidate.get("data_source_type")
    if source_type in {"demo_data", "synthetic_today_demo"}:
        return {
            "status": "blocked",
            "candidate_id": candidate.get("candidate_id"),
            "reason": "demo_or_synthetic_experience_cannot_promote_directly",
            "promote_mode": "manual_change_request",
            "requires_human_merge": True,
            "approval_data_allowed": False,
            "live_allowed": False,
            "production_rule_modified": False,
        }
    if candidate.get("status") != "approved":
        return {
            "status": "blocked",
            "candidate_id": candidate.get("candidate_id"),
            "reason": "candidate_not_approved",
            "promote_mode": "manual_change_request",
            "requires_human_merge": True,
            "approval_data_allowed": False,
            "live_allowed": False,
            "production_rule_modified": False,
        }
    if not replay_result or replay_result.get("replay_status") != "passed":
        return {
            "status": "blocked",
            "candidate_id": candidate.get("candidate_id"),
            "reason": "replay_not_passed",
            "promote_mode": "manual_change_request",
            "requires_human_merge": True,
            "approval_data_allowed": False,
            "live_allowed": False,
            "production_rule_modified": False,
        }
    return {
        "status": "manual_change_request" if dry_run else "ready_for_manual_merge",
        "candidate_id": candidate.get("candidate_id"),
        "change_request_id": f"manual-change-{uuid.uuid4().hex[:12]}",
        "promote_mode": "manual_change_request",
        "requires_human_merge": True,
        "rule_change_preview": candidate.get("proposed_rule"),
        "approval_data_allowed": False,
        "live_allowed": False,
        "production_rule_modified": False,
    }

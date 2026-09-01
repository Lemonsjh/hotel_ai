from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Any


EXPERIENCE_TYPES = {"pricing", "promotion", "diagnosis", "message_template", "fallback", "data_mapping"}
STATUSES = {"candidate", "reviewed", "approved", "rejected", "promoted", "deprecated"}
PRIVATE_FIELD_MARKERS = {"guest_name", "phone", "mobile", "room_no", "room_number", "order_id", "open_id", "chat_id"}
KNOWN_SAFETY_RULES = {
    "demo_data_never_live",
    "synthetic_today_demo_never_live",
    "approval_data_allowed=false",
    "live_allowed=false",
}
SENSITIVE_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("dsn", re.compile(r"\b(?:mysql|postgres(?:ql)?|sqlite)://[^\s]+", re.IGNORECASE)),
    ("secret", re.compile(r"\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;]+", re.IGNORECASE)),
    ("feishu_identity", re.compile(r"\b(?:ou|oc)_[A-Za-z0-9_-]+")),
)


def redact_sensitive_values(value: Any) -> tuple[str, list[str]]:
    text = str(value or "")
    redactions: list[str] = []
    for category, pattern in SENSITIVE_VALUE_PATTERNS:
        if pattern.search(text):
            text = pattern.sub("[redacted]", text)
            redactions.append(category)
    return text, redactions


def privacy_issues(candidate: dict[str, Any]) -> list[str]:
    serialized = str(candidate).lower()
    issues = [f"private_marker:{marker}" for marker in PRIVATE_FIELD_MARKERS if marker in serialized]
    for category, pattern in SENSITIVE_VALUE_PATTERNS:
        if pattern.search(str(candidate)):
            issues.append(f"sensitive_value:{category}")
    return sorted(issues)


def validate_candidate(candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = [
        "candidate_id",
        "created_at",
        "source_run_id",
        "source_scenario_id",
        "source_node_id",
        "source_skill_id",
        "experience_type",
        "observation",
        "proposed_rule",
        "evidence_items",
        "risk_level",
        "requires_human_review",
        "privacy_checked",
        "contains_real_customer_data",
        "status",
    ]
    for key in required:
        if key not in candidate:
            errors.append(f"missing:{key}")
    if candidate.get("experience_type") not in EXPERIENCE_TYPES:
        errors.append("unsupported_experience_type")
    if candidate.get("status") not in STATUSES:
        errors.append("unsupported_status")
    if candidate.get("requires_human_review") is not True:
        errors.append("human_review_required")
    if candidate.get("privacy_checked") is not True:
        errors.append("privacy_check_required")
    if candidate.get("contains_real_customer_data") is True:
        errors.append("real_customer_data_rejected")
    errors.extend(privacy_issues(candidate))
    return errors


def incremental_value_assessment(candidate: dict[str, Any]) -> dict[str, Any]:
    rule_text = " ".join(str(candidate.get(field) or "").lower() for field in ["observation", "proposed_rule"])
    evidence_text = str(candidate.get("evidence_items") or "").lower()
    repeats_existing_rule = any(rule.lower() in rule_text for rule in KNOWN_SAFETY_RULES)
    has_business_signal = any(
        token in f"{rule_text} {evidence_text}"
        for token in ["price", "promotion_cost", "promotion_budget", "campaign", "conversion", "inventory", "review_text", "reputation", "bad_review", "baseline", "mapping"]
    )
    incremental = bool(has_business_signal and not repeats_existing_rule)
    return {
        "incremental_value": incremental,
        "no_incremental_value": not incremental,
        "incremental_value_reason": "repeats_existing_safety_rule" if repeats_existing_rule else "business_signal_present" if has_business_signal else "no_business_signal",
        "recommended_review_action": "approve_for_manual_review" if incremental else "reject",
    }


def build_candidate_from_runtime_result(result: dict[str, Any], *, experience_type: str = "fallback") -> dict[str, Any]:
    observation, redactions = redact_sensitive_values(result.get("summary") or result.get("blocked_reason") or "Runtime generated a reviewable experience candidate.")
    candidate = {
        "candidate_id": f"exp-{uuid.uuid4().hex[:12]}",
        "created_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_run_id": result.get("run_id") or "unknown",
        "source_scenario_id": result.get("scenario_id") or "SC09",
        "source_node_id": result.get("node_id") or "N019",
        "source_skill_id": result.get("skill_id") or "EXP-LAYER",
        "experience_type": experience_type,
        "observation": observation,
        "proposed_rule": "Review candidate manually before any rule promotion.",
        "evidence_items": [
            f"data_source_type={result.get('data_source_type')}",
            f"approval_data_allowed={result.get('approval_data_allowed')}",
            f"live_allowed={result.get('live_allowed')}",
        ],
        "risk_level": "medium",
        "requires_human_review": True,
        "privacy_checked": True,
        "contains_real_customer_data": False,
        "status": "candidate",
        "source_data_source_type": result.get("data_source_type"),
        "approval_data_allowed": False,
        "live_allowed": False,
        "redaction_categories": redactions,
    }
    candidate.update(incremental_value_assessment(candidate))
    errors = validate_candidate(candidate)
    if errors:
        candidate["validation_errors"] = errors
    return candidate

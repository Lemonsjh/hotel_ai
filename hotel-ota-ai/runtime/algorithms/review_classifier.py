from __future__ import annotations

from typing import Any


NEGATIVE_MARKERS = {"dirty", "noise", "bad", "slow", "broken", "complaint", "refund"}
ESCALATION_MARKERS = {"refund", "compensation", "safety", "privacy", "police", "injury"}
CHINESE_ISSUE_MARKERS = {
    "hygiene": {"脏", "异味", "床品", "虫", "毛发"},
    "noise": {"隔音", "吵", "施工", "空调响"},
    "service": {"态度", "前台", "响应慢"},
    "facility": {"坏", "漏水", "空调", "热水"},
    "compensation": {"退款", "补偿", "投诉"},
    "safety_privacy": {"隐私", "报警", "受伤", "丢失"},
}


def classify_review(review: dict[str, Any]) -> dict[str, Any]:
    text = str(review.get("review_text") or review.get("desensitized_text") or "").lower()
    rating = review.get("rating")
    try:
        rating_value = float(rating)
    except (TypeError, ValueError):
        rating_value = None
    missing = [] if text else ["review_text"]
    issue_tags = {marker for marker in NEGATIVE_MARKERS if marker in text}
    for tag, markers in CHINESE_ISSUE_MARKERS.items():
        if any(marker in text for marker in markers):
            issue_tags.add(tag)
    escalation = any(marker in text for marker in ESCALATION_MARKERS) or bool(issue_tags & {"compensation", "safety_privacy"})
    if rating_value is not None and rating_value < 4.0:
        sentiment = "negative"
    elif issue_tags:
        sentiment = "negative"
    elif rating_value is not None and rating_value >= 4.6:
        sentiment = "positive"
    else:
        sentiment = "neutral"
    severity = "high" if escalation else "medium" if sentiment == "negative" else "low"
    reply_draft = None
    if text:
        reply_draft = "Thank you for the feedback. We have assigned the issue for manual follow-up before any public reply."
    return {
        "status": "ok" if not missing else "data_gap",
        "algorithm": "review_classifier_v1",
        "sentiment": sentiment,
        "issue_tags": sorted(issue_tags),
        "severity": severity,
        "needs_manager_escalation": escalation or severity == "high",
        "needs_private_message": sentiment == "negative",
        "compensation_requires_manual_approval": any(marker in text for marker in {"refund", "compensation", "退款", "补偿", "投诉"}) or "compensation" in issue_tags,
        "frontdesk_task_required": sentiment == "negative",
        "rectification_task_required": bool(issue_tags),
        "reputation_penalty_risk": severity in {"medium", "high"},
        "reply_draft": reply_draft,
        "missing_fields": missing,
        "approval_data_allowed": False,
        "live_allowed": False,
    }

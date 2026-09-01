from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from runtime.s13.contracts import ReviewRecord


URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
ID_RE = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
ORDER_RE = re.compile(r"(?i)(?:订单|order|booking)[号\s:#-]*[A-Za-z0-9_-]{5,}")
ROOM_RE = re.compile(r"(?:房间|房号|room)[号\s:#-]*[A-Za-z0-9_-]{1,12}", re.IGNORECASE)
NAME_RE = re.compile(r"[\u4e00-\u9fff]{2,4}(?:先生|女士|小姐|老师)")
WHITESPACE_RE = re.compile(r"\s+")


RISK_KEYWORDS: dict[str, tuple[str, ...]] = {
    "legal_dispute": ("起诉", "律师", "法院", "仲裁", "法律责任", "报警"),
    "claim": ("索赔", "赔偿", "退款", "退钱", "补偿"),
    "privacy": ("隐私", "身份证", "手机号泄露", "信息泄露", "偷拍视频"),
    "discrimination": ("歧视", "地域黑", "性别歧视"),
    "threat": ("威胁", "报复", "弄死", "打死", "恐吓"),
    "harm": ("受伤", "中毒", "触电", "火灾", "打人", "人身伤害"),
    "safety": ("消防", "安全事故", "燃气泄漏", "门锁失灵"),
    "major_public_opinion": ("媒体曝光", "记者", "热搜", "舆情", "全网曝光"),
}

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "cleanliness": ("卫生", "脏", "异味", "床单", "毛巾", "虫"),
    "service_response": ("服务", "前台", "态度", "响应", "处理慢"),
    "noise": ("噪音", "吵", "隔音"),
    "facilities": ("设施", "空调", "热水", "电视", "电脑", "设备"),
    "room_condition": ("房间", "房型", "面积", "采光"),
    "checkin": ("入住", "办理", "押金", "排队"),
}

COMPLAINT_MARKERS = (
    "差", "不好", "一般", "失望", "问题", "投诉", "不舒服", "不满意", "脏", "异味", "噪音",
    "太慢", "太吵", "故障", "坏", "不推荐", "不足", "遗憾",
)
TOPIC_LABELS = {
    "cleanliness": "卫生", "service_response": "服务响应", "noise": "噪音与隔音",
    "facilities": "设施设备", "room_condition": "房间体验", "checkin": "入住办理",
}

FORBIDDEN_COMMITMENTS = (
    "已退款",
    "已经退款",
    "已赔偿",
    "已经赔偿",
    "免费升级",
    "已处罚",
    "已经处罚",
    "删除评论",
    "删掉评论",
    "私下联系",
    "线下联系",
    "已经修复",
    "已修复",
    "已公开回复",
    "已经公开回复",
)


class ReplyValidationError(ValueError):
    pass


def redact_review_text(text: str | None) -> str:
    value = str(text or "")
    for pattern, replacement in (
        (URL_RE, "[链接已隐藏]"),
        (EMAIL_RE, "[邮箱已隐藏]"),
        (PHONE_RE, "[电话已隐藏]"),
        (ID_RE, "[证件号已隐藏]"),
        (ORDER_RE, "[订单号已隐藏]"),
        (ROOM_RE, "[房号已隐藏]"),
        (NAME_RE, "[姓名已隐藏]"),
    ):
        value = pattern.sub(replacement, value)
    return WHITESPACE_RE.sub(" ", value).strip()


def review_content_digest(record: ReviewRecord) -> str:
    payload = {
        "hotel_id": record.hotel_id,
        "platform": record.platform,
        "review_id": record.review_id,
        "review_content": record.review_content,
        "star_rating": record.star_rating,
        "is_replied": record.is_replied,
        "source_snapshot": record.source_snapshot,
        "review_time": record.review_time,
        "is_negative_review": record.is_negative_review,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def reply_content_hash(reply_content: str) -> str:
    return "sha256:" + hashlib.sha256(reply_content.encode("utf-8")).hexdigest()


def detect_risk_flags(text: str | None) -> list[str]:
    value = str(text or "")
    return sorted(
        flag
        for flag, keywords in RISK_KEYWORDS.items()
        if any(keyword in value for keyword in keywords)
    )


def detect_topics(text: str | None) -> list[str]:
    value = str(text or "")
    return sorted(
        topic
        for topic, keywords in TOPIC_KEYWORDS.items()
        if any(keyword in value for keyword in keywords)
    )


def _template_key(record: ReviewRecord, redacted_text: str) -> str:
    has_complaint = record.is_negative_review is True or any(marker in redacted_text for marker in COMPLAINT_MARKERS)
    if record.star_rating is not None and record.star_rating >= 4:
        return "high_rating_negative_feedback" if has_complaint else "positive_review"
    if record.is_negative_review is True or (record.star_rating is not None and record.star_rating <= 3):
        return "negative_review"
    return "neutral_feedback"


def tone_for_template(template_key: str, risk_flags: list[str]) -> str:
    if risk_flags:
        return "professional"
    if template_key in {"high_rating_negative_feedback", "negative_review"}:
        return "apologetic"
    if template_key == "positive_review":
        return "warm"
    return "professional"


def deterministic_template_draft(template_key: str, topics: list[str]) -> str:
    topic_text = "、".join(TOPIC_LABELS.get(topic, topic) for topic in topics)
    if template_key == "positive_review":
        detail = f"感谢您对{topic_text}的认可。" if topic_text else "感谢您的认可与支持。"
        return detail + "我们会继续用心做好每一项服务，期待再次为您服务。"
    if template_key == "high_rating_negative_feedback":
        opening = "感谢您给予肯定，也很抱歉仍有体验未达预期。"
    elif template_key == "negative_review":
        opening = "非常抱歉本次入住体验未达到您的预期。"
    else:
        opening = "感谢您的评价。"
    middle = (
        f"您反馈的{topic_text}问题我们已经记录，并会继续加强现场检查与服务流程。"
        if topic_text else "您反馈的体验问题我们已经记录，并会继续加强现场检查与服务流程。"
    )
    return opening + middle + "感谢您的反馈，也欢迎您再次向我们分享体验。"


def validate_reply_content(reply_content: str) -> str:
    text = str(reply_content or "").strip()
    if not text:
        raise ReplyValidationError("reply_content_required")
    if len(text) > 2000:
        raise ReplyValidationError("reply_content_too_long")
    if redact_review_text(text) != text:
        raise ReplyValidationError("reply_content_contains_pii")
    matched = [phrase for phrase in FORBIDDEN_COMMITMENTS if phrase in text]
    if matched:
        raise ReplyValidationError("reply_content_contains_unapproved_commitment")
    return text


def build_candidate(record: ReviewRecord, *, human_reply_content: str | None = None) -> dict[str, Any]:
    risk_flags = detect_risk_flags(record.review_content)
    if risk_flags:
        return {
            "blocked": True,
            "blocked_reason": "legal_or_claim_escalation",
            "risk_flags": risk_flags,
            "topics": detect_topics(record.review_content),
        }
    redacted = redact_review_text(record.review_content)
    topics = detect_topics(redacted)
    template_key = _template_key(record, redacted)
    tone = tone_for_template(template_key, risk_flags)
    if human_reply_content is not None:
        draft = validate_reply_content(human_reply_content)
        origin = "human_draft"
    elif record.review_content is None or not str(record.review_content).strip():
        draft = deterministic_template_draft(template_key, topics)
        origin = "deterministic_candidate"
    else:
        draft = deterministic_template_draft(template_key, topics)
        origin = "deterministic_candidate"
    draft = validate_reply_content(draft)
    return {
        "blocked": False,
        "draft": draft,
        "tone": tone,
        "template_key": template_key,
        "acknowledged_topics": topics,
        "risk_flags": risk_flags,
        "requires_human_escalation": False,
        "candidate_origin": origin,
        "redacted_excerpt": redacted[:500] if redacted else None,
    }

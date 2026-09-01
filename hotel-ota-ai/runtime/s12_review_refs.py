from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from runtime.s13.contracts import ReviewRecord
from runtime.s13.policy import review_content_digest
from runtime.s13.repository import S13ControlRepository, ref_hash


DEFAULT_REF_TTL_SECONDS = 1800


def issue_review_ref(
    repository: S13ControlRepository,
    record: ReviewRecord,
    *,
    now: datetime,
    ttl_seconds: int = DEFAULT_REF_TTL_SECONDS,
) -> str:
    """Issue a server-side opaque S12 review reference.

    The visible token contains no hotel, platform, review id, content, or
    snapshot. Those facts remain server-side and are revalidated by S13.
    """
    review_ref = "REV-" + secrets.token_urlsafe(32)
    repository.save_review_ref(
        review_ref=review_ref,
        hotel_id=record.hotel_id,
        platform=record.platform,
        review_id=record.review_id,
        source_snapshot=record.source_snapshot,
        content_digest=review_content_digest(record),
        issued_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    return review_ref


def resolve_review_ref(
    repository: S13ControlRepository,
    review_ref: str,
    *,
    hotel_id: str,
    now: datetime,
) -> dict:
    item = repository.get_review_ref(review_ref)
    if not item:
        raise ValueError("invalid_review_ref")
    if item.get("status") != "active":
        raise ValueError("inactive_review_ref")
    if str(item.get("hotel_id")) != str(hotel_id):
        raise ValueError("hotel_scope_mismatch")
    expires_at = datetime.fromisoformat(str(item["expires_at"]).replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=now.tzinfo)
    if now > expires_at:
        raise ValueError("expired_ref")
    item["ref_hash"] = ref_hash(review_ref)
    return item

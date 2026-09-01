from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any, Mapping

from runtime.s13.policy import detect_risk_flags


_INSTALLED = False
QUEUE_POLICY_VERSION = "s13-queue-priority.v1"


def _parse_time(value: Any) -> dt.datetime:
    text = str(value or "").strip()
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone(dt.timedelta(hours=8)))
        return parsed
    except ValueError:
        return dt.datetime.max.replace(tzinfo=dt.timezone.utc)


def _priority_band(content: str, score: Any, *, source_negative: bool = False) -> int:
    try:
        numeric_score = float(score) if score is not None else None
    except (TypeError, ValueError):
        numeric_score = None
    if detect_risk_flags(content):
        return 0
    if source_negative:
        return 1
    if numeric_score is not None and numeric_score <= 2:
        return 2
    if numeric_score is not None and numeric_score <= 3:
        return 3
    if not content:
        return 4
    return 5


def queue_priority(record: Any) -> tuple[int, dt.datetime, str]:
    content = str(getattr(record, "review_content", None) or "").strip()
    return (
        _priority_band(content, getattr(record, "star_rating", None)),
        _parse_time(getattr(record, "review_time", None) or getattr(record, "source_snapshot", None)),
        str(getattr(record, "review_id", "") or ""),
    )


def s12_detail_priority(row: Mapping[str, Any]) -> tuple[int, str, str]:
    content = str(row.get("review_content") or "").strip()
    raw_negative = row.get("is_negative_review")
    source_negative = raw_negative is True or str(raw_negative or "").strip().lower() in {"1", "true", "yes", "negative", "差评"}
    return (
        _priority_band(content, row.get("review_score"), source_negative=source_negative),
        str(row.get("review_time") or row.get("snapshot_time") or ""),
        str(row.get("review_id") or ""),
    )


def _patch_source(source: Any) -> None:
    for class_name in ("MemoryReviewSourceRepository", "MySQLReviewSourceRepository"):
        cls = getattr(source, class_name)
        original = cls.list_unreplied
        if getattr(original, "_s13_queue_priority", False):
            continue

        def list_unreplied(self, *, hotel_id, as_of, limit=50, _original=original):  # type: ignore[no-untyped-def]
            records = _original(
                self,
                hotel_id=hotel_id,
                as_of=as_of,
                limit=max(500, int(limit or 50)),
            )
            return sorted(records, key=queue_priority)[: max(1, int(limit or 50))]

        list_unreplied._s13_queue_priority = True  # type: ignore[attr-defined]
        cls.list_unreplied = list_unreplied


def _patch_service(service: Any) -> None:
    cls = service.S13Service
    original = cls.list_pending
    if getattr(original, "_s13_queue_metadata", False):
        return

    def list_pending(self, context, *, limit=50):  # type: ignore[no-untyped-def]
        result = original(self, context, limit=limit)
        if result.get("status") in {"ok", "partial"}:
            items = result.get("items") or []
            result["queue_policy_version"] = QUEUE_POLICY_VERSION
            result["pure_rating_count"] = sum(1 for item in items if not item.get("review_content_present"))
            result["platform_counts"] = dict(Counter(str(item.get("platform") or "unknown") for item in items))
            result["queue_order"] = [
                "risk_flags",
                "source_negative",
                "score_le_2",
                "score_le_3",
                "pure_rating",
                "other",
                "oldest_first_within_band",
            ]
        return result

    list_pending._s13_queue_metadata = True  # type: ignore[attr-defined]
    cls.list_pending = list_pending


def _patch_feishu(feishu: Any) -> None:
    original = feishu.is_s13_message
    if getattr(original, "_s13_exact_code", False):
        return

    def is_s13_message(message: str) -> bool:
        raw = str(message or "").strip().lower()
        if raw in {"s13", "s013"}:
            return True
        return original(message)

    is_s13_message._s13_exact_code = True  # type: ignore[attr-defined]
    feishu.is_s13_message = is_s13_message


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s12_reputation_real
    from runtime.s13 import feishu, service, source

    s12_reputation_real.detail_priority = s12_detail_priority
    _patch_source(source)
    _patch_service(service)
    _patch_feishu(feishu)

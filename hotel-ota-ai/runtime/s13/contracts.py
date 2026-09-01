from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


ALLOWED_ROLES = {"admin", "owner", "operator"}
BLOCKED_ROLES = {"frontdesk", "viewer"}
SUPPORTED_PLATFORMS = {"meituan", "dianping", "ctrip", "qunar", "tongcheng", "zhixing"}
WRITABLE_PLATFORMS = frozenset({"meituan", "dianping"})


def task_storage_platform(platform: str) -> str:
    """Return the physical task-table platform expected by the reply plugin."""
    if platform not in WRITABLE_PLATFORMS:
        raise ValueError("review_task_platform_not_approved")
    # Dianping review tasks are consumed by the Meituan-family plugin. The
    # channel_source field is what distinguishes Dianping from Meituan.
    return "meituan" if platform == "dianping" else platform


def task_channel_source(platform: str) -> str:
    """Return the physical channel_source expected by the reply plugin."""
    if platform not in WRITABLE_PLATFORMS:
        raise ValueError("review_task_platform_not_approved")
    # Keep the legacy plugin spelling. Changing this to ``dianping`` makes the
    # automatic reply worker ignore the row.
    return "dainping" if platform == "dianping" else platform


def logical_task_platform(platform: str, channel_source: str) -> str:
    """Map a physical task row back to the logical review platform."""
    if platform == "meituan" and channel_source == "dainping":
        return "dianping"
    return platform


TASK_STATUSES = {"pending", "processing", "success", "failed", "cancelled"}


@dataclass(frozen=True)
class RequestContext:
    hotel_id: str
    principal_role: str
    principal_ref: str
    as_of_datetime: datetime

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> "RequestContext":
        hotel_id = str(value.get("hotel_id") or "").strip()
        principal_role = str(value.get("principal_role") or "").strip().lower()
        principal_ref = str(value.get("principal_ref") or "").strip()
        raw_as_of = value.get("as_of_datetime")
        if not hotel_id:
            raise ValueError("missing_hotel_id")
        if not principal_role:
            raise ValueError("missing_principal_role")
        if not principal_ref:
            raise ValueError("missing_principal_ref")
        if isinstance(raw_as_of, datetime):
            as_of = raw_as_of
        else:
            text = str(raw_as_of or "").strip()
            if not text:
                raise ValueError("missing_as_of_datetime")
            as_of = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if as_of.tzinfo is None:
            raise ValueError("as_of_datetime_timezone_required")
        return cls(
            hotel_id=hotel_id,
            principal_role=principal_role,
            principal_ref=principal_ref,
            as_of_datetime=as_of,
        )


@dataclass(frozen=True)
class ReviewRecord:
    hotel_id: str
    platform: str
    review_id: str
    review_content: str | None
    star_rating: float | None
    is_replied: bool
    source_snapshot: str
    review_time: str | None = None
    is_negative_review: bool | None = None

    def __post_init__(self) -> None:
        if not self.hotel_id:
            raise ValueError("review_hotel_id_required")
        if self.platform not in SUPPORTED_PLATFORMS:
            raise ValueError("unsupported_review_platform")
        if not self.review_id:
            raise ValueError("review_id_required")
        if not self.source_snapshot:
            raise ValueError("source_snapshot_required")


@dataclass(frozen=True)
class TaskRecord:
    id: int
    hotel_id: str
    platform: str
    channel_source: str
    review_id: str
    review_content: str | None
    reply_content: str
    status: str
    error_message: str | None
    created_at: str
    replied_at: str | None


@dataclass(frozen=True)
class WriteResult:
    write_performed: bool
    affected_rows: int
    inserted_id: int | None
    pending_readback_verified: bool
    task: TaskRecord | None
    conflict_status: str | None = None
    error: str | None = None

from __future__ import annotations

from datetime import datetime, timezone

from runtime.s13.contracts import ALLOWED_ROLES, RequestContext
from runtime.s13.service import S13Service


def _context(role: str) -> RequestContext:
    return RequestContext(
        hotel_id="hotel-test",
        principal_role=role,
        principal_ref=f"principal-{role}",
        as_of_datetime=datetime(2026, 8, 6, tzinfo=timezone.utc),
    )


def test_admin_can_use_review_reply_service() -> None:
    assert "admin" in ALLOWED_ROLES
    assert S13Service._authorize(_context("admin"), "generate_draft") is None


def test_frontdesk_remains_blocked_from_review_reply() -> None:
    denied = S13Service._authorize(_context("frontdesk"), "generate_draft")

    assert denied is not None
    assert denied["status"] == "blocked"
    assert denied["blocked_reason"] == "review_reply_permission_denied"

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import closing
from datetime import datetime, timedelta
from typing import Any

from runtime.s12_review_refs import issue_review_ref, resolve_review_ref
from runtime.s13.contracts import ALLOWED_ROLES, RequestContext, ReviewRecord, TaskRecord, WRITABLE_PLATFORMS
from runtime.s13.policy import build_candidate, redact_review_text, reply_content_hash, review_content_digest
from runtime.s13.repository import S13ControlRepository
from runtime.s13.source import ReviewSourceRepository, SourceDataGap
from runtime.s13.task_outbox import ReviewTaskOutbox


CONFIRMATION_TTL_SECONDS = 1800


def _task_payload(task: TaskRecord | None, *, write_performed: bool, affected_rows: int, pending_verified: bool, retry_mode: str | None = None) -> dict[str, Any] | None:
    if not task:
        return None
    return {
        "task_ref": f"TASK-{task.id}",
        "platform": task.platform,
        "channel_source": task.channel_source,
        "status": task.status,
        "write_performed": write_performed,
        "affected_rows": affected_rows,
        "pending_readback_verified": pending_verified,
        "provider_status_observed": task.status in {"processing", "success", "failed", "cancelled"},
        "public_reply_verified": False,
        "retry_mode": retry_mode,
    }


def _base_output(action: str, *, status: str = "ok") -> dict[str, Any]:
    return {
        "status": status,
        "action": action,
        "review_ref": None,
        "platform": None,
        "star_rating": None,
        "review_content_present": None,
        "redacted_excerpt": None,
        "eligibility_status": None,
        "draft_candidate": None,
        "confirmation": None,
        "task": None,
        "copy_only": False,
        "blocked_reason": None,
        "risk_flags": [],
        "data_gaps": [],
    }


def _idempotency_key(request: dict[str, Any], *, operation: str, review_id: str) -> str:
    value = json.dumps(
        {
            "hotel_id": request["hotel_id"],
            "platform": request["platform"],
            "review_id": review_id,
            "draft_version": request["draft_version"],
            "content_hash": request["content_hash"],
            "operation": operation,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


class S13Service:
    def __init__(
        self,
        *,
        control_repository: S13ControlRepository,
        source_repository: ReviewSourceRepository,
        task_outbox: ReviewTaskOutbox,
        ref_ttl_seconds: int = 1800,
        confirmation_ttl_seconds: int = CONFIRMATION_TTL_SECONDS,
    ) -> None:
        self.control = control_repository
        self.source = source_repository
        self.outbox = task_outbox
        self.ref_ttl_seconds = ref_ttl_seconds
        self.confirmation_ttl_seconds = confirmation_ttl_seconds

    @staticmethod
    def _authorize(context: RequestContext, action: str) -> dict[str, Any] | None:
        if context.principal_role in ALLOWED_ROLES:
            return None
        result = _base_output(action, status="blocked")
        result.update({"eligibility_status": "permission_denied", "blocked_reason": "review_reply_permission_denied"})
        return result

    def list_pending(self, context: RequestContext, *, limit: int = 50) -> dict[str, Any]:
        denied = self._authorize(context, "list_pending")
        if denied:
            return denied
        try:
            records = self.source.list_unreplied(hotel_id=context.hotel_id, as_of=context.as_of_datetime, limit=limit)
        except SourceDataGap as exc:
            result = _base_output("list_pending", status="data_gap")
            result["blocked_reason"] = str(exc)
            result["data_gaps"] = [str(exc)]
            result["items"] = []
            return result
        items: list[dict[str, Any]] = []
        for record in records:
            review_ref = issue_review_ref(self.control, record, now=context.as_of_datetime, ttl_seconds=self.ref_ttl_seconds)
            content = str(record.review_content or "").strip()
            items.append(
                {
                    "review_ref": review_ref,
                    "platform": record.platform,
                    "star_rating": record.star_rating,
                    "review_content_present": bool(content),
                    "redacted_excerpt": None if not content else redact_review_text(content)[:500],
                    "source_snapshot": record.source_snapshot,
                    "review_time": record.review_time,
                }
            )
        result = _base_output("list_pending")
        result["items"] = items
        result["count"] = len(items)
        return result

    def latest_pending(self, context: RequestContext) -> dict[str, Any]:
        denied = self._authorize(context, "latest_pending")
        if denied:
            return denied
        try:
            record = self.source.latest_unreplied(
                hotel_id=context.hotel_id,
                as_of=context.as_of_datetime,
            )
        except SourceDataGap as exc:
            result = _base_output("latest_pending", status="data_gap")
            result.update({"blocked_reason": str(exc), "data_gaps": [str(exc)], "items": []})
            return result
        result = _base_output("latest_pending")
        if record is None:
            result.update({"items": [], "count": 0})
            return result
        review_ref = issue_review_ref(self.control, record, now=context.as_of_datetime, ttl_seconds=self.ref_ttl_seconds)
        content = str(record.review_content or "").strip()
        result.update(
            {
                "items": [
                    {
                        "review_ref": review_ref,
                        "platform": record.platform,
                        "star_rating": record.star_rating,
                        "review_content_present": bool(content),
                        "redacted_excerpt": None if not content else redact_review_text(content)[:500],
                        "source_snapshot": record.source_snapshot,
                        "review_time": record.review_time,
                    }
                ],
                "count": 1,
            }
        )
        return result

    def _resolve_exact(self, context: RequestContext, review_ref: str) -> tuple[dict[str, Any] | None, ReviewRecord | None, dict[str, Any] | None]:
        try:
            ref_item = resolve_review_ref(self.control, review_ref, hotel_id=context.hotel_id, now=context.as_of_datetime)
        except ValueError as exc:
            status = "expired_ref" if str(exc) == "expired_ref" else "source_changed"
            result = _base_output("generate_draft", status="blocked")
            result.update({"review_ref": review_ref, "eligibility_status": status, "blocked_reason": str(exc)})
            return None, None, result
        try:
            record = self.source.get_exact(
                hotel_id=context.hotel_id,
                platform=str(ref_item["platform"]),
                review_id=str(ref_item["review_id"]),
                as_of=context.as_of_datetime,
            )
        except SourceDataGap as exc:
            result = _base_output("generate_draft", status="data_gap")
            result.update({"review_ref": review_ref, "platform": ref_item.get("platform"), "blocked_reason": str(exc), "data_gaps": [str(exc)]})
            return ref_item, None, result
        if record is None:
            result = _base_output("generate_draft", status="blocked")
            result.update({"review_ref": review_ref, "platform": ref_item.get("platform"), "eligibility_status": "source_changed", "blocked_reason": "exact_review_not_found"})
            return ref_item, None, result
        if record.hotel_id != context.hotel_id or record.platform != ref_item["platform"] or record.review_id != ref_item["review_id"]:
            result = _base_output("generate_draft", status="blocked")
            result.update({"review_ref": review_ref, "platform": record.platform, "eligibility_status": "source_changed", "blocked_reason": "exact_review_scope_mismatch"})
            return ref_item, record, result
        if review_content_digest(record) != ref_item["content_digest"] or record.source_snapshot != ref_item["source_snapshot"]:
            result = _base_output("generate_draft", status="blocked")
            result.update({"review_ref": review_ref, "platform": record.platform, "eligibility_status": "source_changed", "blocked_reason": "review_source_snapshot_changed"})
            return ref_item, record, result
        if record.is_replied:
            result = _base_output("generate_draft", status="already_handled")
            result.update({"review_ref": review_ref, "platform": record.platform, "eligibility_status": "already_handled", "blocked_reason": "source_review_already_replied"})
            return ref_item, record, result
        return ref_item, record, None

    def generate_draft(self, context: RequestContext, *, review_ref: str, human_reply_content: str | None = None) -> dict[str, Any]:
        action = "submit_human_draft" if human_reply_content is not None else "generate_draft"
        denied = self._authorize(context, action)
        if denied:
            denied["review_ref"] = review_ref
            return denied
        ref_item, record, error = self._resolve_exact(context, review_ref)
        if error:
            error["action"] = action
            return error
        assert ref_item is not None and record is not None
        if record.platform in WRITABLE_PLATFORMS:
            existing = self.outbox.read_by_unique(hotel_id=context.hotel_id, platform=record.platform, review_id=record.review_id)
            if existing and existing.status in {"pending", "processing"}:
                result = _base_output(action, status="active_conflict")
                result.update({"review_ref": review_ref, "platform": record.platform, "eligibility_status": "active_conflict", "task": _task_payload(existing, write_performed=False, affected_rows=0, pending_verified=False), "blocked_reason": "active_review_reply_task_exists"})
                return result
            if existing and existing.status == "success":
                result = _base_output(action, status="already_handled")
                result.update({"review_ref": review_ref, "platform": record.platform, "eligibility_status": "already_handled", "task": _task_payload(existing, write_performed=False, affected_rows=0, pending_verified=False), "blocked_reason": "successful_review_reply_task_exists"})
                return result
        try:
            candidate = build_candidate(record, human_reply_content=human_reply_content)
        except ValueError as exc:
            result = _base_output(action, status="blocked")
            result.update({"review_ref": review_ref, "platform": record.platform, "eligibility_status": "blocked_escalation", "blocked_reason": str(exc), "risk_flags": [str(exc)]})
            return result
        if candidate["blocked"]:
            result = _base_output(action, status="blocked")
            result.update(
                {
                    "review_ref": review_ref,
                    "platform": record.platform,
                    "star_rating": record.star_rating,
                    "review_content_present": bool(str(record.review_content or "").strip()),
                    "eligibility_status": "blocked_escalation",
                    "blocked_reason": candidate["blocked_reason"],
                    "risk_flags": candidate["risk_flags"],
                }
            )
            return result
        ref_hash_value = str(ref_item["ref_hash"])
        self.control.invalidate_pending_requests(review_ref_hash=ref_hash_value, actor_ref=context.principal_ref, now=context.as_of_datetime)
        draft_version = self.control.latest_draft_version(ref_hash_value) + 1
        content_hash = reply_content_hash(candidate["draft"])
        copy_only = record.platform not in WRITABLE_PLATFORMS
        request_id = f"REQ-{uuid.uuid4().hex}"
        request_status = "copy_only" if copy_only else "confirmation_pending"
        expires_at = None if copy_only else context.as_of_datetime + timedelta(seconds=self.confirmation_ttl_seconds)
        self.control.create_request(
            request_id=request_id,
            review_ref_hash=ref_hash_value,
            hotel_id=context.hotel_id,
            platform=record.platform,
            principal_ref=context.principal_ref,
            principal_role=context.principal_role,
            draft_version=draft_version,
            content_hash=content_hash,
            reply_content=candidate["draft"],
            candidate_origin=candidate["candidate_origin"],
            tone=candidate["tone"],
            acknowledged_topics=candidate["acknowledged_topics"],
            risk_flags=candidate["risk_flags"],
            requires_human_escalation=candidate["requires_human_escalation"],
            status=request_status,
            expires_at=expires_at,
            created_at=context.as_of_datetime,
        )
        result = _base_output(action)
        result.update(
            {
                "review_ref": review_ref,
                "platform": record.platform,
                "star_rating": record.star_rating,
                "review_content_present": bool(str(record.review_content or "").strip()),
                "redacted_excerpt": candidate.get("redacted_excerpt"),
                "review_time": record.review_time,
                "source_snapshot": record.source_snapshot,
                "eligibility_status": "eligible",
                "draft_candidate": {
                    "draft": candidate["draft"],
                    "tone": candidate["tone"],
                    "template_key": candidate["template_key"],
                    "acknowledged_topics": candidate["acknowledged_topics"],
                    "risk_flags": candidate["risk_flags"],
                    "requires_human_escalation": candidate["requires_human_escalation"],
                    "candidate_origin": candidate["candidate_origin"],
                    "draft_version": draft_version,
                    "content_hash": content_hash,
                },
                "confirmation": None if copy_only else {
                    "request_id": request_id,
                    "status": "confirmation_pending",
                    "expires_at": expires_at.isoformat(timespec="seconds") if expires_at else None,
                    "draft_version": draft_version,
                    "content_hash": content_hash,
                },
                "copy_only": copy_only,
                "risk_flags": candidate["risk_flags"],
            }
        )
        return result

    def reject_or_cancel(self, context: RequestContext, *, request_id: str, action: str) -> dict[str, Any]:
        denied = self._authorize(context, action)
        if denied:
            return denied
        request = self.control.get_request(request_id)
        if not request:
            result = _base_output(action, status="data_gap")
            result.update({"blocked_reason": "request_not_found", "data_gaps": ["request_not_found"]})
            return result
        if request["hotel_id"] != context.hotel_id:
            result = _base_output(action, status="blocked")
            result["blocked_reason"] = "hotel_scope_mismatch"
            return result
        new_status = "rejected" if action == "reject" else "cancelled"
        changed = self.control.transition_request(
            request_id=request_id,
            expected_statuses=["confirmation_pending"],
            new_status=new_status,
            actor_ref=context.principal_ref,
            now=context.as_of_datetime,
        )
        result = _base_output(action, status="ok" if changed else "blocked")
        result.update(
            {
                "platform": request["platform"],
                "confirmation": {
                    "request_id": request_id,
                    "status": new_status if changed else request["status"],
                    "expires_at": request["expires_at"],
                    "draft_version": request["draft_version"],
                    "content_hash": request["content_hash"],
                },
                "blocked_reason": None if changed else "request_not_confirmation_pending",
                "copy_only": request["platform"] not in WRITABLE_PLATFORMS,
            }
        )
        return result

    def _request_and_record(self, context: RequestContext, request_id: str, *, action: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None, ReviewRecord | None, dict[str, Any] | None]:
        request = self.control.get_request(request_id)
        if not request:
            result = _base_output(action, status="data_gap")
            result.update({"blocked_reason": "request_not_found", "data_gaps": ["request_not_found"]})
            return None, None, None, result
        if request["hotel_id"] != context.hotel_id:
            result = _base_output(action, status="blocked")
            result["blocked_reason"] = "hotel_scope_mismatch"
            return request, None, None, result
        latest = self.control.latest_request_for_ref_hash(request["review_ref_hash"])
        if not latest or latest["request_id"] != request_id:
            result = _base_output(action, status="blocked")
            result.update({"platform": request["platform"], "blocked_reason": "request_invalidated_by_new_version", "confirmation": {"request_id": request_id, "status": "invalidated_by_new_version", "expires_at": request["expires_at"], "draft_version": request["draft_version"], "content_hash": request["content_hash"]}})
            return request, None, None, result
        if request["status"] != "confirmation_pending":
            result = _base_output(action, status="blocked")
            result.update({"platform": request["platform"], "blocked_reason": "request_not_confirmation_pending"})
            return request, None, None, result
        expires_at = datetime.fromisoformat(str(request["expires_at"]).replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=context.as_of_datetime.tzinfo)
        if context.as_of_datetime > expires_at:
            self.control.transition_request(request_id=request_id, expected_statuses=["confirmation_pending"], new_status="expired", actor_ref=context.principal_ref, now=context.as_of_datetime)
            result = _base_output(action, status="blocked")
            result.update({"platform": request["platform"], "blocked_reason": "request_expired"})
            return request, None, None, result
        with closing(self.control.connect()) as conn:
            row = conn.execute("SELECT * FROM s13_review_refs WHERE ref_hash=?", (request["review_ref_hash"],)).fetchone()
        if not row:
            result = _base_output(action, status="data_gap")
            result.update({"blocked_reason": "review_ref_state_missing", "data_gaps": ["review_ref_state_missing"]})
            return request, None, None, result
        ref_item = dict(row)
        try:
            record = self.source.get_exact(hotel_id=context.hotel_id, platform=request["platform"], review_id=ref_item["review_id"], as_of=context.as_of_datetime)
        except SourceDataGap as exc:
            result = _base_output(action, status="data_gap")
            result.update({"platform": request["platform"], "blocked_reason": str(exc), "data_gaps": [str(exc)]})
            return request, ref_item, None, result
        if not record or record.is_replied:
            result = _base_output(action, status="already_handled")
            result.update({"platform": request["platform"], "blocked_reason": "source_review_already_replied_or_missing"})
            return request, ref_item, record, result
        if record.source_snapshot != ref_item["source_snapshot"] or review_content_digest(record) != ref_item["content_digest"]:
            result = _base_output(action, status="blocked")
            result.update({"platform": request["platform"], "blocked_reason": "review_source_snapshot_changed"})
            return request, ref_item, record, result
        return request, ref_item, record, None

    def confirm(self, context: RequestContext, *, request_id: str) -> dict[str, Any]:
        denied = self._authorize(context, "confirm")
        if denied:
            return denied
        request, ref_item, record, error = self._request_and_record(context, request_id, action="confirm")
        if error:
            return error
        assert request is not None and ref_item is not None and record is not None
        if request["platform"] not in WRITABLE_PLATFORMS:
            result = _base_output("confirm", status="blocked")
            result.update({"platform": request["platform"], "copy_only": True, "blocked_reason": "review_task_platform_not_approved"})
            return result
        if context.principal_role == "operator" and str(os.environ.get("HOTEL_OTA_S13_REQUIRE_OWNER_CONFIRM", "false")).lower() in {"1", "true", "yes", "y"}:
            result = _base_output("confirm", status="blocked")
            result.update({"platform": request["platform"], "blocked_reason": "owner_confirmation_required_by_policy"})
            return result
        existing = self.outbox.read_by_unique(hotel_id=context.hotel_id, platform=record.platform, review_id=record.review_id)
        if existing:
            if existing.status in {"pending", "processing"}:
                result = _base_output("confirm", status="active_conflict")
                result.update({"platform": record.platform, "eligibility_status": "active_conflict", "task": _task_payload(existing, write_performed=False, affected_rows=0, pending_verified=False), "blocked_reason": "active_review_reply_task_exists"})
                return result
            if existing.status == "success":
                result = _base_output("confirm", status="already_handled")
                result.update({"platform": record.platform, "eligibility_status": "already_handled", "task": _task_payload(existing, write_performed=False, affected_rows=0, pending_verified=False), "blocked_reason": "successful_review_reply_task_exists"})
                return result
            if existing.status in {"failed", "cancelled"}:
                result = _base_output("confirm", status="blocked")
                result.update({"platform": record.platform, "task": _task_payload(existing, write_performed=False, affected_rows=0, pending_verified=False), "blocked_reason": "failed_or_cancelled_task_requires_retry_command"})
                return result
        key = _idempotency_key(request, operation="insert", review_id=record.review_id)
        attempt, created = self.control.begin_write_attempt(request_id=request_id, idempotency_key=key, operation="insert", now=context.as_of_datetime)
        if not created:
            reconciled = self.outbox.read_by_unique(hotel_id=context.hotel_id, platform=record.platform, review_id=record.review_id)
            if reconciled and reconciled.status == "pending" and reconciled.reply_content == request["reply_content"]:
                self.control.update_write_attempt(write_attempt_id=attempt["write_attempt_id"], status="verified", reconciliation_status="recovered", task_id=reconciled.id, error_message=None, now=context.as_of_datetime)
                self.control.transition_request(request_id=request_id, expected_statuses=["confirmation_pending"], new_status="confirmed", actor_ref=context.principal_ref, now=context.as_of_datetime, payload={"task_id": reconciled.id, "reconciliation_status": "recovered"})
                return self._confirmed_output(request, reconciled, retry_mode=None, reconciliation_status="recovered")
            if attempt["status"] == "verified" and attempt.get("task_id"):
                task = self.outbox.read_by_id(task_id=int(attempt["task_id"]), hotel_id=context.hotel_id, platform=record.platform, review_id=record.review_id)
                if task:
                    return self._confirmed_output(request, task, retry_mode=None, reconciliation_status=attempt["reconciliation_status"])
            result = _base_output("confirm", status="write_failed")
            result.update({"platform": record.platform, "blocked_reason": "write_reconciliation_unknown", "data_gaps": ["write_reconciliation_unknown"]})
            return result
        write = self.outbox.insert_pending(hotel_id=context.hotel_id, platform=record.platform, review_id=record.review_id, review_content=record.review_content, reply_content=request["reply_content"], created_at=context.as_of_datetime.isoformat(timespec="seconds"))
        if not write.pending_readback_verified or write.affected_rows != 1 or not write.task:
            self.control.update_write_attempt(write_attempt_id=attempt["write_attempt_id"], status="failed", reconciliation_status="conflict" if write.conflict_status else "unknown", task_id=write.inserted_id, error_message=write.error or write.conflict_status or "pending_readback_mismatch", now=context.as_of_datetime)
            status = "active_conflict" if write.conflict_status in {"pending", "processing"} else "write_failed"
            result = _base_output("confirm", status=status)
            result.update({"platform": record.platform, "task": _task_payload(write.task, write_performed=write.write_performed, affected_rows=write.affected_rows, pending_verified=False), "blocked_reason": write.error or write.conflict_status or "pending_readback_mismatch"})
            return result
        self.control.update_write_attempt(write_attempt_id=attempt["write_attempt_id"], status="verified", reconciliation_status="verified", task_id=write.task.id, error_message=None, now=context.as_of_datetime)
        self.control.transition_request(request_id=request_id, expected_statuses=["confirmation_pending"], new_status="confirmed", actor_ref=context.principal_ref, now=context.as_of_datetime, payload={"task_id": write.task.id, "pending_readback_verified": True})
        return self._confirmed_output(request, write.task, retry_mode=None, reconciliation_status="verified")

    def retry(self, context: RequestContext, *, request_id: str) -> dict[str, Any]:
        denied = self._authorize(context, "retry")
        if denied:
            return denied
        request, ref_item, record, error = self._request_and_record(context, request_id, action="retry")
        if error:
            return error
        assert request is not None and record is not None
        if request["platform"] not in WRITABLE_PLATFORMS:
            result = _base_output("retry", status="blocked")
            result.update({"platform": request["platform"], "copy_only": True, "blocked_reason": "review_task_platform_not_approved"})
            return result
        task = self.outbox.read_by_unique(hotel_id=context.hotel_id, platform=record.platform, review_id=record.review_id)
        if not task:
            result = _base_output("retry", status="data_gap")
            result.update({"platform": record.platform, "blocked_reason": "retry_task_not_found", "data_gaps": ["retry_task_not_found"]})
            return result
        if task.status in {"pending", "processing"}:
            result = _base_output("retry", status="active_conflict")
            result.update({"platform": record.platform, "task": _task_payload(task, write_performed=False, affected_rows=0, pending_verified=False), "blocked_reason": "active_review_reply_task_exists"})
            return result
        if task.status == "success":
            result = _base_output("retry", status="already_handled")
            result.update({"platform": record.platform, "task": _task_payload(task, write_performed=False, affected_rows=0, pending_verified=False), "blocked_reason": "successful_review_reply_task_exists"})
            return result
        if task.status not in {"failed", "cancelled"}:
            result = _base_output("retry", status="blocked")
            result.update({"platform": record.platform, "blocked_reason": "retry_old_status_not_allowed"})
            return result
        key = _idempotency_key(request, operation="cas_retry", review_id=record.review_id)
        attempt, created = self.control.begin_write_attempt(request_id=request_id, idempotency_key=key, operation="cas_retry", now=context.as_of_datetime)
        if not created:
            reconciled = self.outbox.read_by_unique(hotel_id=context.hotel_id, platform=record.platform, review_id=record.review_id)
            if reconciled and reconciled.status == "pending" and reconciled.reply_content == request["reply_content"]:
                return self._confirmed_output(request, reconciled, retry_mode="cas_update", reconciliation_status="recovered")
            result = _base_output("retry", status="write_failed")
            result.update({"platform": record.platform, "blocked_reason": "retry_reconciliation_unknown"})
            return result
        write = self.outbox.cas_retry(task=task, new_review_content=record.review_content, new_reply_content=request["reply_content"], new_created_at=context.as_of_datetime.isoformat(timespec="seconds"))
        if write.affected_rows != 1 or not write.pending_readback_verified or not write.task:
            self.control.update_write_attempt(write_attempt_id=attempt["write_attempt_id"], status="failed", reconciliation_status="conflict", task_id=task.id, error_message=write.error or "cas_compare_failed", now=context.as_of_datetime)
            result = _base_output("retry", status="write_failed")
            result.update({"platform": record.platform, "task": _task_payload(write.task or task, write_performed=write.write_performed, affected_rows=write.affected_rows, pending_verified=False, retry_mode="cas_update"), "blocked_reason": write.error or "cas_compare_failed"})
            return result
        self.control.update_write_attempt(write_attempt_id=attempt["write_attempt_id"], status="verified", reconciliation_status="verified", task_id=write.task.id, error_message=None, now=context.as_of_datetime)
        self.control.transition_request(request_id=request_id, expected_statuses=["confirmation_pending"], new_status="confirmed", actor_ref=context.principal_ref, now=context.as_of_datetime, payload={"task_id": write.task.id, "retry_mode": "cas_update"})
        return self._confirmed_output(request, write.task, retry_mode="cas_update", reconciliation_status="verified")

    @staticmethod
    def _confirmed_output(request: dict[str, Any], task: TaskRecord, *, retry_mode: str | None, reconciliation_status: str) -> dict[str, Any]:
        action = "retry" if retry_mode else "confirm"
        result = _base_output(action)
        result.update(
            {
                "platform": request["platform"],
                "eligibility_status": "eligible",
                "confirmation": {"request_id": request["request_id"], "status": "confirmed", "expires_at": None, "draft_version": request["draft_version"], "content_hash": request["content_hash"]},
                "task": {**(_task_payload(task, write_performed=True, affected_rows=1, pending_verified=True, retry_mode=retry_mode) or {}), "reconciliation_status": reconciliation_status, "idempotency_verified": True},
                "copy_only": False,
            }
        )
        return result

    def query_status(self, context: RequestContext, *, request_id: str | None = None, review_ref: str | None = None) -> dict[str, Any]:
        denied = self._authorize(context, "query_status")
        if denied:
            return denied
        request = self.control.get_request(request_id) if request_id else None
        ref_item: dict[str, Any] | None = None
        if request:
            if request["hotel_id"] != context.hotel_id:
                result = _base_output("query_status", status="blocked")
                result["blocked_reason"] = "hotel_scope_mismatch"
                return result
            with closing(self.control.connect()) as conn:
                row = conn.execute("SELECT * FROM s13_review_refs WHERE ref_hash=?", (request["review_ref_hash"],)).fetchone()
                ref_item = dict(row) if row else None
        elif review_ref:
            try:
                ref_item = resolve_review_ref(self.control, review_ref, hotel_id=context.hotel_id, now=context.as_of_datetime)
            except ValueError as exc:
                result = _base_output("query_status", status="blocked")
                result.update({"review_ref": review_ref, "blocked_reason": str(exc)})
                return result
            request = self.control.latest_request_for_ref_hash(ref_item["ref_hash"])
        else:
            result = _base_output("query_status", status="data_gap")
            result.update({"blocked_reason": "request_id_or_review_ref_required", "data_gaps": ["request_id_or_review_ref_required"]})
            return result
        if not ref_item:
            result = _base_output("query_status", status="data_gap")
            result.update({"blocked_reason": "review_ref_state_missing", "data_gaps": ["review_ref_state_missing"]})
            return result
        platform = str(ref_item["platform"])
        task = None
        if platform in WRITABLE_PLATFORMS:
            task = self.outbox.read_by_unique(hotel_id=context.hotel_id, platform=platform, review_id=str(ref_item["review_id"]))
        result = _base_output("query_status")
        result.update(
            {
                "review_ref": review_ref,
                "platform": platform,
                "confirmation": None if not request else {"request_id": request["request_id"], "status": request["status"], "expires_at": request["expires_at"], "draft_version": request["draft_version"], "content_hash": request["content_hash"]},
                "task": _task_payload(task, write_performed=False, affected_rows=0, pending_verified=bool(task and task.status == "pending")),
                "copy_only": platform not in WRITABLE_PLATFORMS,
            }
        )
        return result

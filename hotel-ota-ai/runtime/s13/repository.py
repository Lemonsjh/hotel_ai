from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS s13_review_refs (
  ref_hash TEXT PRIMARY KEY,
  hotel_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  review_id TEXT NOT NULL,
  source_snapshot TEXT NOT NULL,
  content_digest TEXT NOT NULL,
  issued_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active'
);
CREATE INDEX IF NOT EXISTS idx_s13_review_refs_scope
  ON s13_review_refs(hotel_id, platform, review_id, status, expires_at);

CREATE TABLE IF NOT EXISTS s13_reply_requests (
  request_id TEXT PRIMARY KEY,
  review_ref_hash TEXT NOT NULL,
  hotel_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  principal_ref TEXT NOT NULL,
  principal_role TEXT NOT NULL,
  draft_version INTEGER NOT NULL,
  content_hash TEXT NOT NULL,
  reply_content TEXT NOT NULL,
  candidate_origin TEXT NOT NULL,
  tone TEXT NOT NULL,
  acknowledged_topics_json TEXT NOT NULL,
  risk_flags_json TEXT NOT NULL,
  requires_human_escalation INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s13_reply_requests_ref
  ON s13_reply_requests(review_ref_hash, draft_version, created_at);
CREATE INDEX IF NOT EXISTS idx_s13_reply_requests_status
  ON s13_reply_requests(status, expires_at);

CREATE TABLE IF NOT EXISTS s13_reply_events (
  event_id TEXT PRIMARY KEY,
  request_id TEXT,
  review_ref_hash TEXT NOT NULL,
  actor_ref TEXT NOT NULL,
  action TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  previous_event_hash TEXT,
  event_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s13_reply_events_ref
  ON s13_reply_events(review_ref_hash, created_at, event_id);

CREATE TABLE IF NOT EXISTS s13_write_attempts (
  write_attempt_id TEXT PRIMARY KEY,
  request_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL UNIQUE,
  operation TEXT NOT NULL,
  status TEXT NOT NULL,
  task_id INTEGER,
  reconciliation_status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_s13_write_attempts_request
  ON s13_write_attempts(request_id, created_at);
"""


def _iso(value: datetime | str) -> str:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return str(value)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def ref_hash(review_ref: str) -> str:
    return _sha256(f"s13-review-ref:{review_ref}")


class S13ControlRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as conn:
            self.ensure_schema_conn(conn)
            conn.commit()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def ensure_schema_conn(conn: sqlite3.Connection) -> None:
        conn.executescript(SCHEMA_SQL)

    def save_review_ref(
        self,
        *,
        review_ref: str,
        hotel_id: str,
        platform: str,
        review_id: str,
        source_snapshot: str,
        content_digest: str,
        issued_at: datetime | str,
        expires_at: datetime | str,
    ) -> None:
        with closing(self.connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO s13_review_refs (
                  ref_hash, hotel_id, platform, review_id, source_snapshot,
                  content_digest, issued_at, expires_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
                ON CONFLICT(ref_hash) DO NOTHING
                """,
                (
                    ref_hash(review_ref),
                    hotel_id,
                    platform,
                    review_id,
                    source_snapshot,
                    content_digest,
                    _iso(issued_at),
                    _iso(expires_at),
                ),
            )

    def get_review_ref(self, review_ref: str) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM s13_review_refs WHERE ref_hash=?",
                (ref_hash(review_ref),),
            ).fetchone()
            return dict(row) if row else None

    def latest_draft_version(self, review_ref_hash: str) -> int:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT MAX(draft_version) AS version FROM s13_reply_requests WHERE review_ref_hash=?",
                (review_ref_hash,),
            ).fetchone()
            return int(row["version"] or 0)

    def invalidate_pending_requests(
        self,
        *,
        review_ref_hash: str,
        actor_ref: str,
        now: datetime | str,
    ) -> int:
        timestamp = _iso(now)
        with closing(self.connect()) as conn, conn:
            rows = conn.execute(
                "SELECT request_id FROM s13_reply_requests WHERE review_ref_hash=? AND status='confirmation_pending'",
                (review_ref_hash,),
            ).fetchall()
            conn.execute(
                """
                UPDATE s13_reply_requests
                SET status='invalidated_by_new_version', updated_at=?
                WHERE review_ref_hash=? AND status='confirmation_pending'
                """,
                (timestamp, review_ref_hash),
            )
            for row in rows:
                self._append_event_conn(
                    conn,
                    request_id=row["request_id"],
                    review_ref_hash=review_ref_hash,
                    actor_ref=actor_ref,
                    action="invalidated_by_new_version",
                    payload={"reason": "new_draft_version"},
                    created_at=timestamp,
                )
            return len(rows)

    def create_request(
        self,
        *,
        request_id: str,
        review_ref_hash: str,
        hotel_id: str,
        platform: str,
        principal_ref: str,
        principal_role: str,
        draft_version: int,
        content_hash: str,
        reply_content: str,
        candidate_origin: str,
        tone: str,
        acknowledged_topics: Iterable[str],
        risk_flags: Iterable[str],
        requires_human_escalation: bool,
        status: str,
        expires_at: datetime | str | None,
        created_at: datetime | str,
    ) -> None:
        timestamp = _iso(created_at)
        with closing(self.connect()) as conn, conn:
            conn.execute(
                """
                INSERT INTO s13_reply_requests (
                  request_id, review_ref_hash, hotel_id, platform,
                  principal_ref, principal_role, draft_version, content_hash,
                  reply_content, candidate_origin, tone,
                  acknowledged_topics_json, risk_flags_json,
                  requires_human_escalation, status, expires_at,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    review_ref_hash,
                    hotel_id,
                    platform,
                    principal_ref,
                    principal_role,
                    draft_version,
                    content_hash,
                    reply_content,
                    candidate_origin,
                    tone,
                    _json(list(acknowledged_topics)),
                    _json(list(risk_flags)),
                    int(requires_human_escalation),
                    status,
                    _iso(expires_at) if expires_at else None,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_event_conn(
                conn,
                request_id=request_id,
                review_ref_hash=review_ref_hash,
                actor_ref=principal_ref,
                action="draft_created",
                payload={
                    "draft_version": draft_version,
                    "content_hash": content_hash,
                    "candidate_origin": candidate_origin,
                    "status": status,
                },
                created_at=timestamp,
            )

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                "SELECT * FROM s13_reply_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            return self._decode_request(row)

    def latest_request_for_ref_hash(self, review_ref_hash: str) -> dict[str, Any] | None:
        with closing(self.connect()) as conn:
            row = conn.execute(
                """
                SELECT * FROM s13_reply_requests
                WHERE review_ref_hash=?
                ORDER BY draft_version DESC, created_at DESC
                LIMIT 1
                """,
                (review_ref_hash,),
            ).fetchone()
            return self._decode_request(row)

    @staticmethod
    def _decode_request(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if not row:
            return None
        item = dict(row)
        item["acknowledged_topics"] = json.loads(item.pop("acknowledged_topics_json") or "[]")
        item["risk_flags"] = json.loads(item.pop("risk_flags_json") or "[]")
        item["requires_human_escalation"] = bool(item["requires_human_escalation"])
        return item

    def transition_request(
        self,
        *,
        request_id: str,
        expected_statuses: Iterable[str],
        new_status: str,
        actor_ref: str,
        now: datetime | str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        expected = list(expected_statuses)
        if not expected:
            raise ValueError("expected_statuses_required")
        placeholders = ",".join("?" for _ in expected)
        timestamp = _iso(now)
        with closing(self.connect()) as conn, conn:
            row = conn.execute(
                "SELECT review_ref_hash FROM s13_reply_requests WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if not row:
                return False
            cursor = conn.execute(
                f"""
                UPDATE s13_reply_requests
                SET status=?, updated_at=?
                WHERE request_id=? AND status IN ({placeholders})
                """,
                (new_status, timestamp, request_id, *expected),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event_conn(
                conn,
                request_id=request_id,
                review_ref_hash=row["review_ref_hash"],
                actor_ref=actor_ref,
                action=new_status,
                payload=payload or {},
                created_at=timestamp,
            )
            return True

    def begin_write_attempt(
        self,
        *,
        request_id: str,
        idempotency_key: str,
        operation: str,
        now: datetime | str,
    ) -> tuple[dict[str, Any], bool]:
        timestamp = _iso(now)
        with closing(self.connect()) as conn, conn:
            existing = conn.execute(
                "SELECT * FROM s13_write_attempts WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                return dict(existing), False
            write_attempt_id = f"WRITE-{uuid.uuid4().hex}"
            conn.execute(
                """
                INSERT INTO s13_write_attempts (
                  write_attempt_id, request_id, idempotency_key, operation,
                  status, task_id, reconciliation_status, error_message,
                  created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'started', NULL, 'pending', NULL, ?, ?)
                """,
                (write_attempt_id, request_id, idempotency_key, operation, timestamp, timestamp),
            )
            row = conn.execute(
                "SELECT * FROM s13_write_attempts WHERE write_attempt_id=?",
                (write_attempt_id,),
            ).fetchone()
            return dict(row), True

    def update_write_attempt(
        self,
        *,
        write_attempt_id: str,
        status: str,
        reconciliation_status: str,
        task_id: int | None,
        error_message: str | None,
        now: datetime | str,
    ) -> None:
        with closing(self.connect()) as conn, conn:
            conn.execute(
                """
                UPDATE s13_write_attempts
                SET status=?, reconciliation_status=?, task_id=?,
                    error_message=?, updated_at=?
                WHERE write_attempt_id=?
                """,
                (
                    status,
                    reconciliation_status,
                    task_id,
                    error_message,
                    _iso(now),
                    write_attempt_id,
                ),
            )

    def append_event(
        self,
        *,
        request_id: str | None,
        review_ref_hash: str,
        actor_ref: str,
        action: str,
        payload: dict[str, Any],
        created_at: datetime | str,
    ) -> None:
        with closing(self.connect()) as conn, conn:
            self._append_event_conn(
                conn,
                request_id=request_id,
                review_ref_hash=review_ref_hash,
                actor_ref=actor_ref,
                action=action,
                payload=payload,
                created_at=_iso(created_at),
            )

    @staticmethod
    def _append_event_conn(
        conn: sqlite3.Connection,
        *,
        request_id: str | None,
        review_ref_hash: str,
        actor_ref: str,
        action: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> None:
        previous = conn.execute(
            """
            SELECT event_hash FROM s13_reply_events
            WHERE review_ref_hash=?
            ORDER BY created_at DESC, event_id DESC
            LIMIT 1
            """,
            (review_ref_hash,),
        ).fetchone()
        previous_hash = previous["event_hash"] if previous else None
        payload_hash = _sha256(_json(payload))
        event_id = f"EVT-{uuid.uuid4().hex}"
        event_hash = _sha256(
            _json(
                {
                    "event_id": event_id,
                    "request_id": request_id,
                    "review_ref_hash": review_ref_hash,
                    "actor_ref_hash": _sha256(actor_ref),
                    "action": action,
                    "payload_hash": payload_hash,
                    "previous_event_hash": previous_hash,
                    "created_at": created_at,
                }
            )
        )
        conn.execute(
            """
            INSERT INTO s13_reply_events (
              event_id, request_id, review_ref_hash, actor_ref, action,
              payload_hash, previous_event_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                request_id,
                review_ref_hash,
                _sha256(actor_ref),
                action,
                payload_hash,
                previous_hash,
                event_hash,
                created_at,
            ),
        )

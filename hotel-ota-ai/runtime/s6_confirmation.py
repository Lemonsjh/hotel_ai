from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from runtime.common import now_local
from runtime.storage import connect, init_schema


_TABLE = "s6_price_confirmations"


def _expiry(minutes: int = 10) -> str:
    return (datetime.fromisoformat(now_local()) + timedelta(minutes=minutes)).isoformat(timespec="seconds")


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS {_TABLE} (
          confirmation_id TEXT PRIMARY KEY,
          hotel_id TEXT NOT NULL,
          chat_id TEXT NOT NULL,
          requester_id TEXT NOT NULL,
          status TEXT NOT NULL,
          expires_at TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        )"""
    )


def create_confirmation(
    db_path: str | None, *, hotel_id: str, chat_id: str | None, requester_id: str | None, payload: dict[str, Any]
) -> dict[str, Any]:
    """Persist the exact S6 preview so a later Feishu confirmation is unambiguous."""
    if not db_path or db_path == ":memory:" or not chat_id or not requester_id:
        return {"status": "unavailable", "reason": "s6_confirmation_store_unavailable"}
    confirmation_id = f"PRC-{uuid.uuid4().hex[:10].upper()}"
    created_at = now_local()
    expires_at = _expiry()
    with connect(db_path) as conn:
        init_schema(conn)
        _ensure_table(conn)
        conn.execute(
            f"INSERT INTO {_TABLE} (confirmation_id, hotel_id, chat_id, requester_id, status, expires_at, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
            (
                confirmation_id,
                hotel_id,
                chat_id,
                requester_id,
                expires_at,
                json.dumps(payload, ensure_ascii=False, default=_json_default),
                created_at,
                created_at,
            ),
        )
    return {"status": "pending", "confirmation_id": confirmation_id, "expires_at": expires_at}


def record_rejected_preview(
    db_path: str | None, *, hotel_id: str, chat_id: str | None, requester_id: str | None, payload: dict[str, Any]
) -> dict[str, Any]:
    """Keep a short-lived rejected preview so a following plain confirmation is explainable."""
    if not db_path or db_path == ":memory:" or not chat_id or not requester_id:
        return {"status": "unavailable", "reason": "s6_confirmation_store_unavailable"}
    preview_id = f"PRR-{uuid.uuid4().hex[:10].upper()}"
    created_at = now_local()
    expires_at = _expiry()
    with connect(db_path) as conn:
        init_schema(conn)
        _ensure_table(conn)
        conn.execute(
            f"INSERT INTO {_TABLE} (confirmation_id, hotel_id, chat_id, requester_id, status, expires_at, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'rejected', ?, ?, ?, ?)",
            (
                preview_id,
                hotel_id,
                chat_id,
                requester_id,
                expires_at,
                json.dumps(payload, ensure_ascii=False, default=_json_default),
                created_at,
                created_at,
            ),
        )
    return {"status": "rejected", "preview_id": preview_id, "expires_at": expires_at}


def claim_confirmation(
    db_path: str | None, *, confirmation_id: str | None, hotel_id: str, chat_id: str | None, actor_id: str | None
) -> dict[str, Any]:
    """Atomically reserve a pending preview; plain '确认' only works for its requester."""
    if not db_path or db_path == ":memory:" or not chat_id or not actor_id:
        return {"status": "blocked", "reason": "s6_confirmation_store_unavailable"}
    with connect(db_path) as conn:
        init_schema(conn)
        _ensure_table(conn)
        conn.execute("BEGIN IMMEDIATE")
        if confirmation_id:
            row = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE confirmation_id=? AND hotel_id=? AND chat_id=?",
                (confirmation_id, hotel_id, chat_id),
            ).fetchone()
        else:
            rows = conn.execute(
                f"SELECT * FROM {_TABLE} WHERE hotel_id=? AND chat_id=? AND requester_id=? AND status='pending' AND expires_at>? ORDER BY created_at DESC LIMIT 2",
                (hotel_id, chat_id, actor_id, now_local()),
            ).fetchall()
            if len(rows) != 1:
                rejected = conn.execute(
                    f"SELECT payload_json FROM {_TABLE} WHERE hotel_id=? AND chat_id=? AND requester_id=? AND status='rejected' AND expires_at>? ORDER BY created_at DESC LIMIT 1",
                    (hotel_id, chat_id, actor_id, now_local()),
                ).fetchone()
                conn.rollback()
                if rejected:
                    return {
                        "status": "blocked",
                        "reason": "s6_latest_preview_not_confirmable",
                        "preview": json.loads(rejected["payload_json"]),
                    }
                return {"status": "blocked", "reason": "s6_confirmation_token_required"}
            row = rows[0]
        if not row or row["status"] != "pending" or row["expires_at"] <= now_local():
            conn.rollback()
            return {"status": "blocked", "reason": "s6_confirmation_not_pending"}
        cur = conn.execute(
            f"UPDATE {_TABLE} SET status='processing', updated_at=? WHERE confirmation_id=? AND status='pending'",
            (now_local(), row["confirmation_id"]),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return {"status": "blocked", "reason": "s6_confirmation_already_processing"}
        conn.commit()
    return {"status": "claimed", "confirmation_id": row["confirmation_id"], "payload": json.loads(row["payload_json"])}


def finish_confirmation(db_path: str | None, confirmation_id: str, *, completed: bool) -> None:
    if not db_path or db_path == ":memory:":
        return
    with connect(db_path) as conn:
        _ensure_table(conn)
        conn.execute(
            f"UPDATE {_TABLE} SET status=?, updated_at=? WHERE confirmation_id=?",
            ("completed" if completed else "pending", now_local(), confirmation_id),
        )

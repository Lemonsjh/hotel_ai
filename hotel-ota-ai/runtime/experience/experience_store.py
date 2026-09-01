from __future__ import annotations

import json
import os
from pathlib import Path
from contextlib import closing
from typing import Any

from runtime.common import PACKAGE_ROOT
from runtime.storage import connect, init_schema


EXPERIENCE_DIR = PACKAGE_ROOT / "examples" / "demo_data" / "experience"
DEFAULT_CANDIDATE_STORE = EXPERIENCE_DIR / "experience_candidates.json"


def runtime_experience_dir() -> Path:
    configured = os.environ.get("HOTEL_OTA_EXPERIENCE_DIR")
    if configured:
        return Path(configured)
    if os.name == "nt":
        return PACKAGE_ROOT / "data" / "experience"
    return Path("/var/lib/hotel-ota-ai/experience")


def default_runtime_candidate_store() -> Path:
    return runtime_experience_dir() / "experience_candidates.json"


def load_candidate_store(path: str | Path | None = None) -> dict[str, Any]:
    if path:
        store_path = Path(path)
        payload = json.loads(store_path.read_text(encoding="utf-8"))
        payload.setdefault("storage_mode", "explicit_store")
        return payload
    runtime_store = default_runtime_candidate_store()
    if runtime_store.exists():
        payload = json.loads(runtime_store.read_text(encoding="utf-8"))
        payload.setdefault("storage_mode", "runtime_store")
        return payload
    payload = json.loads(DEFAULT_CANDIDATE_STORE.read_text(encoding="utf-8"))
    payload["storage_mode"] = "demo_sample_readonly"
    payload["runtime_store_path"] = str(runtime_store)
    return payload


def _row_to_candidate(row: Any) -> dict[str, Any]:
    evidence = json.loads(row["evidence_json"] or "[]")
    candidate = {
        "candidate_id": row["candidate_id"],
        "hotel_id": row["hotel_id"],
        "created_at": row["created_at"],
        "source_scenario_id": row["source_scenario"],
        "source_node_id": row["source_node"],
        "source_skill_id": row["source_skill"],
        "experience_type": row["experience_type"],
        "observation": row["observation"],
        "proposed_rule": row["proposed_rule"],
        "evidence_items": evidence,
        "risk_level": row["risk_level"],
        "requires_human_review": bool(row["requires_human"]),
        "privacy_checked": bool(row["privacy_ok"]),
        "contains_real_customer_data": False,
        "status": row["status"],
        "reviewed_at": row["reviewed_at"],
        "reviewed_by": row["reviewed_by"],
        "promoted_to": row["promoted_to"],
        "approval_data_allowed": bool(row["approval_data"]),
        "live_allowed": bool(row["live_data"]),
        "storage_mode": "sqlite_runtime",
    }
    return candidate


def _candidate_to_db_values(candidate: dict[str, Any], *, hotel_id: str | None = None) -> dict[str, Any]:
    candidate_hotel = candidate.get("hotel_id") or hotel_id or "default"
    evidence = candidate.get("evidence_items")
    if evidence is None:
        evidence = candidate.get("evidence_json") or []
    return {
        "candidate_id": candidate["candidate_id"],
        "hotel_id": candidate_hotel,
        "source_scenario": candidate.get("source_scenario") or candidate.get("source_scenario_id"),
        "source_node": candidate.get("source_node") or candidate.get("source_node_id"),
        "source_skill": candidate.get("source_skill") or candidate.get("source_skill_id"),
        "experience_type": candidate.get("experience_type"),
        "observation": candidate.get("observation") or "",
        "proposed_rule": candidate.get("proposed_rule"),
        "evidence_json": json.dumps(evidence, ensure_ascii=False),
        "risk_level": candidate.get("risk_level") or "low",
        "status": candidate.get("status") or "candidate",
        "requires_human": 1 if candidate.get("requires_human_review", True) else 0,
        "privacy_ok": 1 if candidate.get("privacy_checked") is True else 0,
        "created_at": candidate.get("created_at"),
        "reviewed_at": candidate.get("reviewed_at"),
        "reviewed_by": candidate.get("reviewed_by"),
        "promoted_to": candidate.get("promoted_to"),
        "approval_data": 1 if candidate.get("approval_data_allowed") is True or candidate.get("approval_data") else 0,
        "live_data": 1 if candidate.get("live_allowed") is True or candidate.get("live_data") else 0,
    }


def upsert_candidate(candidate: dict[str, Any], *, db_path: str | Path | None = None, hotel_id: str | None = None) -> dict[str, Any]:
    values = _candidate_to_db_values(candidate, hotel_id=hotel_id)
    with closing(connect(str(db_path)) if db_path else connect()) as conn:
        with conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO experience_candidates (
                  candidate_id, hotel_id, source_scenario, source_node, source_skill,
                  experience_type, observation, proposed_rule, evidence_json, risk_level,
                  status, requires_human, privacy_ok, created_at, reviewed_at, reviewed_by,
                  promoted_to, approval_data, live_data
                )
                VALUES (
                  :candidate_id, :hotel_id, :source_scenario, :source_node, :source_skill,
                  :experience_type, :observation, :proposed_rule, :evidence_json, :risk_level,
                  :status, :requires_human, :privacy_ok, :created_at, :reviewed_at, :reviewed_by,
                  :promoted_to, :approval_data, :live_data
                )
                ON CONFLICT(candidate_id) DO UPDATE SET
                  hotel_id=excluded.hotel_id,
                  source_scenario=excluded.source_scenario,
                  source_node=excluded.source_node,
                  source_skill=excluded.source_skill,
                  experience_type=excluded.experience_type,
                  observation=excluded.observation,
                  proposed_rule=excluded.proposed_rule,
                  evidence_json=excluded.evidence_json,
                  risk_level=excluded.risk_level,
                  status=excluded.status,
                  requires_human=excluded.requires_human,
                  privacy_ok=excluded.privacy_ok,
                  reviewed_at=excluded.reviewed_at,
                  reviewed_by=excluded.reviewed_by,
                  promoted_to=excluded.promoted_to,
                  approval_data=excluded.approval_data,
                  live_data=excluded.live_data
                """,
                values,
            )
    stored = dict(candidate)
    stored["hotel_id"] = values["hotel_id"]
    stored["storage_mode"] = "sqlite_runtime"
    return stored


def list_sqlite_candidates(*, db_path: str | Path | None = None, hotel_id: str | None = None) -> list[dict[str, Any]]:
    with closing(connect(str(db_path)) if db_path else connect()) as conn:
        init_schema(conn)
        if hotel_id:
            rows = conn.execute(
                "SELECT * FROM experience_candidates WHERE hotel_id = ? ORDER BY created_at DESC, candidate_id DESC",
                (hotel_id,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM experience_candidates ORDER BY created_at DESC, candidate_id DESC").fetchall()
    return [_row_to_candidate(row) for row in rows]


def _filter_hotel(candidates: list[dict[str, Any]], hotel_id: str | None) -> list[dict[str, Any]]:
    if not hotel_id:
        return candidates
    return [candidate for candidate in candidates if candidate.get("hotel_id") == hotel_id]


def list_candidates(
    path: str | Path | None = None,
    *,
    hotel_id: str | None = None,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    if path:
        return _filter_hotel(list(load_candidate_store(path).get("candidates") or []), hotel_id)
    sqlite_candidates = list_sqlite_candidates(db_path=db_path, hotel_id=hotel_id)
    if sqlite_candidates:
        return sqlite_candidates
    fallback = list(load_candidate_store(None).get("candidates") or [])
    return _filter_hotel(fallback, hotel_id)


def find_candidate(
    candidate_id: str,
    path: str | Path | None = None,
    *,
    hotel_id: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    for candidate in list_candidates(path, hotel_id=hotel_id, db_path=db_path):
        if candidate.get("candidate_id") == candidate_id:
            return dict(candidate)
    raise KeyError(f"unknown experience candidate: {candidate_id}")


def write_candidate_store(payload: dict[str, Any], path: str | Path | None = None) -> None:
    store_path = Path(path) if path else default_runtime_candidate_store()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

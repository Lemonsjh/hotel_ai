from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SHANGHAI_TZ = timezone(timedelta(hours=8))
DEFAULT_CONTRACT_REVISION = "diagnosis-contract.v1"
DEFAULT_POLICY_REVISION = "diagnosis-default.v1"
ALLOWED_STATUSES = {
    "ok",
    "partial",
    "data_gap",
    "conflict",
    "stale",
    "blocked",
    "not_applicable",
}
_STATUS_ALIASES = {
    "success": "ok",
    "ready": "ok",
    "preview_only": "partial",
    "dry_run": "partial",
    "schema_drift": "conflict",
    "error": "data_gap",
    "failed": "data_gap",
    "deprecated": "not_applicable",
    "no_rows": "data_gap",
}
_SENSITIVE_KEYS = {
    "dsn",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "cookies",
    "open_id",
    "user_id",
    "union_id",
    "phone",
    "mobile",
    "email",
    "raw_sql",
    "sql",
    "payload_hash",
    "artifact_path",
    "html_report_path",
    "report_local_path",
    "private_path",
}
_CAPABILITY_WINDOWS = {
    "S2": "current_snapshot",
    "S4": "target_date_context",
    "S7": "rolling_30d_competition",
    "S8": "current_promotion_plan",
    "S9": "rolling_30d_traffic_conversion",
    "S10": "rolling_30d_promotion_effect",
    "S12": "review_window",
    "S15": "baseline_materialization",
    "S16": "as_of_progress",
    "S17": "rolling_30d_orders",
}
_CAPABILITY_GRAINS = {
    "S2": ["hotel", "room_type"],
    "S4": ["hotel", "market_date"],
    "S7": ["hotel", "channel", "room_type", "product"],
    "S8": ["hotel", "channel", "activity", "product"],
    "S9": ["hotel", "channel", "period"],
    "S10": ["hotel", "channel", "campaign", "period"],
    "S12": ["hotel", "channel", "review_window"],
    "S15": ["hotel", "room_type", "hour"],
    "S16": ["hotel", "room_type", "hour"],
    "S17": ["hotel", "channel", "order_cohort"],
}


def _now_iso() -> str:
    return datetime.now(SHANGHAI_TZ).isoformat(timespec="seconds")


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _safe_identifier(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in {"_", "-", "."})


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _safe_value(value: Any, *, depth: int = 0, max_depth: int = 5) -> Any:
    if depth > max_depth:
        return "[truncated]"
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in _SENSITIVE_KEYS or any(
                token in lowered
                for token in ("password", "secret", "token", "cookie", "private_path")
            ):
                continue
            if lowered in {"rows", "raw_rows", "order_rows", "review_rows", "customer_rows"}:
                if isinstance(item, list):
                    output[f"{key_text}_count"] = len(item)
                continue
            output[key_text] = _safe_value(item, depth=depth + 1, max_depth=max_depth)
        return output
    if isinstance(value, list):
        return [
            _safe_value(item, depth=depth + 1, max_depth=max_depth)
            for item in value[:100]
        ]
    if isinstance(value, tuple):
        return _safe_value(list(value), depth=depth, max_depth=max_depth)
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > 2000:
            return value[:2000]
        return value
    return str(value)


def _find_first(data: Any, names: Iterable[str]) -> Any:
    wanted = {str(name) for name in names}
    if isinstance(data, dict):
        for name in wanted:
            value = data.get(name)
            if value not in (None, ""):
                return value
        for value in data.values():
            found = _find_first(value, wanted)
            if found not in (None, ""):
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_first(item, wanted)
            if found not in (None, ""):
                return found
    return None


def _normalize_status(raw_result: dict[str, Any]) -> str:
    raw = str(
        raw_result.get("status")
        or raw_result.get("source_status")
        or raw_result.get("business_status")
        or "ok"
    ).strip().lower()
    normalized = _STATUS_ALIASES.get(raw, raw)
    return normalized if normalized in ALLOWED_STATUSES else "partial"


def _quality_flags(raw_result: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for key in (
        "quality_flags",
        "risk_flags",
        "context_warnings",
        "missing_fields",
        "missing_inputs",
        "not_allowed_conclusions",
    ):
        value = raw_result.get(key)
        if isinstance(value, list):
            values.extend(value)
        elif value not in (None, ""):
            values.append(value)
    for key in ("reason", "blocked_reason", "error_code"):
        if raw_result.get(key) not in (None, ""):
            values.append(f"{key}:{raw_result[key]}")
    return _dedupe_strings(values)


def _evidence_refs(raw_result: dict[str, Any], capability_id: str) -> list[str]:
    existing = raw_result.get("evidence_refs")
    if isinstance(existing, list) and existing:
        return _dedupe_strings(existing)
    evidence = raw_result.get("evidence")
    if evidence in (None, {}, []):
        evidence = {
            "capability_id": capability_id,
            "status": raw_result.get("status"),
            "summary": raw_result.get("summary"),
            "data_business_date": raw_result.get("data_business_date"),
            "data_snapshot_time": raw_result.get("data_snapshot_time"),
        }
    digest = hashlib.sha256(_json(_safe_value(evidence)).encode("utf-8")).hexdigest()
    return [f"sha256:{digest}"]


def _axis_entry(
    raw_result: dict[str, Any],
    *,
    actual_keys: Iterable[str] = (),
    baseline_keys: Iterable[str] = (),
    delta_keys: Iterable[str] = (),
    maturity_keys: Iterable[str] = (),
    gap_keys: Iterable[str] = (),
    unit: str | None = None,
) -> dict[str, Any] | None:
    actual = _find_first(raw_result, actual_keys)
    baseline = _find_first(raw_result, baseline_keys)
    delta = _find_first(raw_result, delta_keys)
    maturity = _find_first(raw_result, maturity_keys)
    gap = _find_first(raw_result, gap_keys)
    if all(value in (None, "") for value in (actual, baseline, delta, maturity, gap)):
        return None
    return {
        "actual": actual,
        "baseline": baseline,
        "delta": delta,
        "maturity": maturity,
        "gap": gap,
        "unit": unit,
    }


def _decision_axes(capability_id: str, raw_result: dict[str, Any]) -> dict[str, Any]:
    existing = raw_result.get("decision_axes")
    if isinstance(existing, dict):
        return _safe_value(existing)
    evidence = raw_result.get("evidence")
    if isinstance(evidence, dict) and isinstance(evidence.get("decision_axes"), dict):
        return _safe_value(evidence["decision_axes"])

    axes: dict[str, Any] = {}
    if capability_id in {"S2", "S15", "S16"}:
        entry = _axis_entry(
            raw_result,
            actual_keys=(
                "committed_sold_rooms",
                "actual_sold_rooms",
                "actual_room_nights",
                "sold_rooms",
                "sold_room_nights",
                "actual",
            ),
            baseline_keys=(
                "target_rooms",
                "target_orders",
                "target_room_nights",
                "expected_sold_rooms",
                "baseline",
            ),
            delta_keys=("progress_delta", "deviation", "delta"),
            maturity_keys=("maturity", "baseline_maturity"),
            gap_keys=("gap", "remaining_gap", "target_gap"),
            unit="room",
        )
        if entry:
            axes["sales_progress"] = entry

    if capability_id in {"S4", "S7", "S9", "S15"}:
        entry = _axis_entry(
            raw_result,
            actual_keys=("market_orders", "market_order_count", "peer_order_count"),
            baseline_keys=("market_orders_baseline", "peer_average_orders"),
            delta_keys=("market_orders_delta",),
            maturity_keys=("market_maturity", "maturity"),
            gap_keys=("market_orders_gap",),
            unit="order",
        )
        if entry:
            axes["market_orders"] = entry

        entry = _axis_entry(
            raw_result,
            actual_keys=("market_share", "market_share_pct"),
            baseline_keys=("market_share_baseline", "peer_market_share"),
            delta_keys=("market_share_delta", "market_share_delta_pp"),
            maturity_keys=("market_share_maturity", "maturity"),
            gap_keys=("market_share_gap",),
            unit="pct",
        )
        if entry:
            axes["market_share"] = entry

    if capability_id in {"S9", "S15"}:
        entry = _axis_entry(
            raw_result,
            actual_keys=("views", "browse_uv", "browse_users", "page_views"),
            baseline_keys=("peer_browse_uv", "browse_users_baseline"),
            delta_keys=("browse_delta",),
            maturity_keys=("traffic_maturity", "maturity"),
            gap_keys=("browse_gap",),
            unit="user",
        )
        if entry:
            axes["browse_users"] = entry

        entry = _axis_entry(
            raw_result,
            actual_keys=("first_conversion_rate", "exposure_to_browse_rate_pct"),
            baseline_keys=("peer_exposure_to_browse_rate_pct", "first_conversion_baseline"),
            delta_keys=("first_conversion_delta", "first_conversion_delta_pp"),
            maturity_keys=("conversion_maturity", "maturity"),
            gap_keys=("first_conversion_gap",),
            unit="pct",
        )
        if entry:
            axes["first_conversion"] = entry

        entry = _axis_entry(
            raw_result,
            actual_keys=(
                "second_conversion_rate",
                "payment_conversion_rate",
                "browse_to_pay_rate_pct",
            ),
            baseline_keys=(
                "peer_browse_to_pay_rate_pct",
                "second_conversion_baseline",
            ),
            delta_keys=("second_conversion_delta", "second_conversion_delta_pp"),
            maturity_keys=("conversion_maturity", "maturity"),
            gap_keys=("second_conversion_gap",),
            unit="pct",
        )
        if entry:
            axes["second_conversion"] = entry

    if capability_id in {"S2", "S7", "S15"}:
        entry = _axis_entry(
            raw_result,
            actual_keys=("current_price", "listed_price", "hotel_price"),
            baseline_keys=("competitor_price", "price_baseline", "peer_price"),
            delta_keys=("price_delta", "price_gap"),
            maturity_keys=("price_maturity", "mapping_maturity", "maturity"),
            gap_keys=("price_position_gap",),
            unit="currency",
        )
        if entry:
            axes["price"] = entry

    effective_window = raw_result.get("effective_window")
    for entry in axes.values():
        if isinstance(entry, dict) and "effective_window" not in entry:
            entry["effective_window"] = effective_window
    return axes


def _diagnostic_items(capability_id: str, raw_result: dict[str, Any]) -> list[dict[str, Any]]:
    existing = raw_result.get("diagnostic_items")
    if isinstance(existing, list):
        return _safe_value(existing)
    evidence = raw_result.get("evidence")
    if isinstance(evidence, dict) and isinstance(evidence.get("diagnostic_items"), list):
        return _safe_value(evidence["diagnostic_items"])
    items: list[dict[str, Any]] = []
    for flag in _quality_flags(raw_result)[:20]:
        items.append(
            {
                "module_id": "execution_data_quality",
                "issue_code": f"{capability_id.lower()}_quality:{_safe_identifier(flag)[:80]}",
                "issue_type": "observe",
                "severity": "low",
                "status": "needs_check",
                "confidence": 1.0,
                "impact": {
                    "metric": "unquantified",
                    "value": None,
                    "unit": "unknown",
                },
                "next_checks": [f"review_{capability_id}_source_quality"],
                "forbidden_conclusions": [
                    f"do_not_convert_{capability_id}_quality_flag_into_business_fact"
                ],
                "root_code": f"{capability_id.lower()}_quality",
            }
        )
    return items


def _deterministic_payload(
    capability_id: str, raw_result: dict[str, Any]
) -> dict[str, Any]:
    existing = raw_result.get("deterministic_payload")
    if isinstance(existing, dict):
        payload = _safe_value(existing)
    else:
        payload = {
            "summary": raw_result.get("summary"),
            "evidence": _safe_value(raw_result.get("evidence") or {}),
            "recommendations": _safe_value(raw_result.get("recommendations") or []),
            "actions": _safe_value(raw_result.get("actions") or []),
        }
        for key in (
            "room_type_items",
            "product_facts",
            "handoffs",
            "maturity",
            "field_coverage_rate",
            "freshness_status",
            "data_business_date",
            "data_snapshot_time",
        ):
            if raw_result.get(key) not in (None, ""):
                payload[key] = _safe_value(raw_result[key])
    payload.setdefault("decision_axes", _decision_axes(capability_id, raw_result))
    payload.setdefault("diagnostic_items", _diagnostic_items(capability_id, raw_result))
    return payload


def ensure_capability_result_schema_conn(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS capability_results (
          result_id TEXT PRIMARY KEY,
          result_version INTEGER NOT NULL,
          request_key TEXT NOT NULL,
          organization_id TEXT NOT NULL,
          hotel_id TEXT NOT NULL,
          capability_id TEXT NOT NULL,
          target_business_date TEXT NOT NULL,
          as_of_datetime TEXT NOT NULL,
          effective_window_json TEXT NOT NULL,
          captured_at TEXT NOT NULL,
          status TEXT NOT NULL,
          source_grain_json TEXT NOT NULL,
          source_units_json TEXT NOT NULL,
          deterministic_payload_json TEXT NOT NULL,
          evidence_refs_json TEXT NOT NULL,
          quality_flags_json TEXT NOT NULL,
          contract_revision TEXT NOT NULL,
          policy_revision TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE (
            organization_id,
            hotel_id,
            capability_id,
            target_business_date,
            result_version
          )
        );
        CREATE INDEX IF NOT EXISTS idx_capability_results_lookup
          ON capability_results (
            organization_id,
            hotel_id,
            capability_id,
            target_business_date,
            captured_at,
            result_version
          );
        CREATE INDEX IF NOT EXISTS idx_capability_results_request
          ON capability_results (request_key, capability_id, captured_at);

        CREATE TABLE IF NOT EXISTS s14_diagnosis_runs (
          diagnosis_run_id TEXT PRIMARY KEY,
          request_key TEXT NOT NULL,
          organization_id TEXT NOT NULL,
          hotel_id TEXT NOT NULL,
          target_business_date TEXT NOT NULL,
          as_of_datetime TEXT NOT NULL,
          status TEXT NOT NULL,
          coverage_score REAL,
          observed_health_score_json TEXT,
          result_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_s14_diagnosis_runs_lookup
          ON s14_diagnosis_runs (
            organization_id,
            hotel_id,
            target_business_date,
            as_of_datetime,
            created_at
          );
        """
    )


def _connect(db_path: str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    ensure_capability_result_schema_conn(conn)
    return conn


def ensure_capability_result_schema(db_path: str) -> None:
    with _connect(db_path) as conn:
        conn.commit()


def capability_request_key(
    *,
    organization_id: str,
    hotel_id: str,
    target_business_date: str,
    as_of_datetime: str,
    contract_revision: str,
    policy_revision: str,
) -> str:
    payload = {
        "organization_id": organization_id,
        "hotel_id": hotel_id,
        "target_business_date": str(target_business_date)[:10],
        "as_of_datetime": as_of_datetime,
        "contract_revision": contract_revision,
        "policy_revision": policy_revision,
    }
    return f"s14-request-sha256:{hashlib.sha256(_json(payload).encode('utf-8')).hexdigest()}"


def resolve_organization_id(db_path: str, hotel_id: str) -> str | None:
    try:
        with _connect(db_path) as conn:
            row = conn.execute(
                "SELECT org_id FROM hotels WHERE hotel_id=? LIMIT 1",
                (str(hotel_id),),
            ).fetchone()
        if row and row["org_id"] not in (None, ""):
            return str(row["org_id"])
    except sqlite3.Error:
        return None
    return None


def _next_result_version(
    conn: sqlite3.Connection,
    *,
    organization_id: str,
    hotel_id: str,
    capability_id: str,
    target_business_date: str,
) -> int:
    row = conn.execute(
        """
        SELECT MAX(result_version) AS latest_version
        FROM capability_results
        WHERE organization_id=? AND hotel_id=? AND capability_id=?
          AND target_business_date=?
        """,
        (
            organization_id,
            hotel_id,
            capability_id,
            str(target_business_date)[:10],
        ),
    ).fetchone()
    return int(row["latest_version"] or 0) + 1


def build_versioned_capability_result(
    *,
    capability_id: str,
    raw_result: dict[str, Any] | None,
    organization_id: str,
    hotel_id: str,
    target_business_date: str,
    as_of_datetime: str,
    contract_revision: str = DEFAULT_CONTRACT_REVISION,
    policy_revision: str = DEFAULT_POLICY_REVISION,
    effective_window: dict[str, Any] | None = None,
    result_version: int | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    raw = dict(raw_result or {})
    source_captured_at = (
        captured_at
        or raw.get("captured_at")
        or raw.get("data_snapshot_time")
        or raw.get("generated_at")
    )
    inferred_quality_flags: list[str] = []
    captured = source_captured_at or as_of_datetime or _now_iso()
    if source_captured_at in (None, ""):
        inferred_quality_flags.append("captured_at_inferred_from_request_as_of")
    if _parse_datetime(captured) is None:
        captured = as_of_datetime or _now_iso()
        inferred_quality_flags.append("captured_at_invalid_fell_back_to_request_as_of")
    result_id = str(raw.get("result_id") or "").strip()
    version = int(result_version or raw.get("result_version") or 0)
    if not result_id:
        result_id = f"cap-result-pending:{uuid.uuid4()}"
    source_units = raw.get("source_units")
    if not isinstance(source_units, dict):
        source_units = {}
        inferred_quality_flags.append("source_units_missing_or_inferred")
    source_grain = raw.get("source_grain")
    if not isinstance(source_grain, list):
        source_grain = list(_CAPABILITY_GRAINS.get(capability_id, ["hotel"]))
        inferred_quality_flags.append("source_grain_inferred_from_capability_contract")
    window = effective_window or raw.get("effective_window")
    if not isinstance(window, dict):
        window = {
            "type": _CAPABILITY_WINDOWS.get(capability_id, "capability_natural_window"),
            "target_business_date": str(target_business_date)[:10],
        }
    return {
        "capability_id": capability_id,
        "result_id": result_id,
        "result_version": version,
        "status": _normalize_status(raw),
        "organization_id": str(organization_id),
        "hotel_id": str(hotel_id),
        "target_business_date": str(target_business_date)[:10],
        "as_of_datetime": str(as_of_datetime),
        "effective_window": _safe_value(window),
        "captured_at": str(captured),
        "source_grain": _safe_value(source_grain),
        "source_units": _safe_value(source_units),
        "deterministic_payload": _deterministic_payload(capability_id, raw),
        "evidence_refs": _evidence_refs(raw, capability_id),
        "quality_flags": _dedupe_strings(
            [*_quality_flags(raw), *inferred_quality_flags]
        ),
        "contract_revision": str(contract_revision),
        "policy_revision": str(policy_revision),
    }


def save_capability_result(
    result: dict[str, Any], *, db_path: str
) -> dict[str, Any]:
    normalized = dict(result)
    with _connect(db_path) as conn:
        version = int(normalized.get("result_version") or 0)
        if version <= 0:
            version = _next_result_version(
                conn,
                organization_id=str(normalized["organization_id"]),
                hotel_id=str(normalized["hotel_id"]),
                capability_id=str(normalized["capability_id"]),
                target_business_date=str(normalized["target_business_date"]),
            )
        normalized["result_version"] = version
        if str(normalized.get("result_id") or "").startswith("cap-result-pending:"):
            digest = hashlib.sha256(
                _json(
                    {
                        "organization_id": normalized["organization_id"],
                        "hotel_id": normalized["hotel_id"],
                        "capability_id": normalized["capability_id"],
                        "target_business_date": normalized["target_business_date"],
                        "captured_at": normalized["captured_at"],
                        "result_version": version,
                        "evidence_refs": normalized["evidence_refs"],
                    }
                ).encode("utf-8")
            ).hexdigest()
            normalized["result_id"] = f"cap-result-sha256:{digest}"
        request_key = capability_request_key(
            organization_id=str(normalized["organization_id"]),
            hotel_id=str(normalized["hotel_id"]),
            target_business_date=str(normalized["target_business_date"]),
            as_of_datetime=str(normalized["as_of_datetime"]),
            contract_revision=str(normalized["contract_revision"]),
            policy_revision=str(normalized["policy_revision"]),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO capability_results (
              result_id, result_version, request_key,
              organization_id, hotel_id, capability_id,
              target_business_date, as_of_datetime,
              effective_window_json, captured_at, status,
              source_grain_json, source_units_json,
              deterministic_payload_json, evidence_refs_json,
              quality_flags_json, contract_revision, policy_revision,
              created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                normalized["result_id"],
                version,
                request_key,
                normalized["organization_id"],
                normalized["hotel_id"],
                normalized["capability_id"],
                normalized["target_business_date"],
                normalized["as_of_datetime"],
                _json(normalized["effective_window"]),
                normalized["captured_at"],
                normalized["status"],
                _json(normalized["source_grain"]),
                _json(normalized["source_units"]),
                _json(normalized["deterministic_payload"]),
                _json(normalized["evidence_refs"]),
                _json(normalized["quality_flags"]),
                normalized["contract_revision"],
                normalized["policy_revision"],
                _now_iso(),
            ),
        )
        conn.commit()
    return normalized


def _row_to_result(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "result_id": row["result_id"],
        "result_version": row["result_version"],
        "organization_id": row["organization_id"],
        "hotel_id": row["hotel_id"],
        "capability_id": row["capability_id"],
        "target_business_date": row["target_business_date"],
        "as_of_datetime": row["as_of_datetime"],
        "effective_window": _loads(row["effective_window_json"], {}),
        "captured_at": row["captured_at"],
        "status": row["status"],
        "source_grain": _loads(row["source_grain_json"], []),
        "source_units": _loads(row["source_units_json"], {}),
        "deterministic_payload": _loads(row["deterministic_payload_json"], {}),
        "evidence_refs": _loads(row["evidence_refs_json"], []),
        "quality_flags": _loads(row["quality_flags_json"], []),
        "contract_revision": row["contract_revision"],
        "policy_revision": row["policy_revision"],
    }


def find_latest_capability_result(
    *,
    db_path: str,
    organization_id: str,
    hotel_id: str,
    capability_id: str,
    target_business_date: str,
    as_of_datetime: str,
    contract_revision: str,
    policy_revision: str,
    compatible_contract_revisions: Iterable[str] = (),
    compatible_policy_revisions: Iterable[str] = (),
) -> dict[str, Any] | None:
    as_of = _parse_datetime(as_of_datetime)
    if as_of is None:
        return None
    allowed_contracts = {
        str(contract_revision),
        *[str(item) for item in compatible_contract_revisions],
    }
    allowed_policies = {
        str(policy_revision),
        *[str(item) for item in compatible_policy_revisions],
    }
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM capability_results
            WHERE organization_id=? AND hotel_id=? AND capability_id=?
              AND target_business_date=?
            ORDER BY result_version DESC, captured_at DESC
            """,
            (
                str(organization_id),
                str(hotel_id),
                str(capability_id),
                str(target_business_date)[:10],
            ),
        ).fetchall()
    candidates: list[dict[str, Any]] = []
    for row in rows:
        result = _row_to_result(row)
        captured = _parse_datetime(result["captured_at"])
        if captured is None or captured > as_of:
            continue
        if result["contract_revision"] not in allowed_contracts:
            continue
        if result["policy_revision"] not in allowed_policies:
            continue
        candidates.append(result)
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            _parse_datetime(item["captured_at"]) or datetime.min.replace(tzinfo=SHANGHAI_TZ),
            int(item["result_version"]),
        ),
        reverse=True,
    )
    return candidates[0]


def list_capability_results_for_request(
    *,
    db_path: str,
    organization_id: str,
    hotel_id: str,
    target_business_date: str,
    as_of_datetime: str,
    contract_revision: str,
    policy_revision: str,
    capability_ids: Iterable[str],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for capability_id in capability_ids:
        result = find_latest_capability_result(
            db_path=db_path,
            organization_id=organization_id,
            hotel_id=hotel_id,
            capability_id=str(capability_id),
            target_business_date=target_business_date,
            as_of_datetime=as_of_datetime,
            contract_revision=contract_revision,
            policy_revision=policy_revision,
        )
        if result is not None:
            output.append(result)
    return output


def save_s14_diagnosis_run(
    result: dict[str, Any],
    *,
    db_path: str,
    organization_id: str,
    hotel_id: str,
    target_business_date: str,
    as_of_datetime: str,
    contract_revision: str,
    policy_revision: str,
) -> str:
    request_key = capability_request_key(
        organization_id=organization_id,
        hotel_id=hotel_id,
        target_business_date=target_business_date,
        as_of_datetime=as_of_datetime,
        contract_revision=contract_revision,
        policy_revision=policy_revision,
    )
    digest = hashlib.sha256(
        _json(
            {
                "request_key": request_key,
                "status": result.get("status"),
                "items": [
                    item.get("item_id")
                    for item in result.get("items", [])
                    if isinstance(item, dict)
                ],
            }
        ).encode("utf-8")
    ).hexdigest()
    run_id = f"s14-run-sha256:{digest}"
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO s14_diagnosis_runs (
              diagnosis_run_id, request_key, organization_id, hotel_id,
              target_business_date, as_of_datetime, status,
              coverage_score, observed_health_score_json, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                request_key,
                organization_id,
                hotel_id,
                str(target_business_date)[:10],
                as_of_datetime,
                str(result.get("status") or "data_gap"),
                result.get("coverage_score"),
                _json(result.get("observed_health_score")),
                _json(_safe_value(result, max_depth=8)),
                _now_iso(),
            ),
        )
        conn.commit()
    return run_id


def latest_s14_diagnosis_run(
    *,
    db_path: str,
    organization_id: str,
    hotel_id: str,
    target_business_date: str,
) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT *
            FROM s14_diagnosis_runs
            WHERE organization_id=? AND hotel_id=? AND target_business_date=?
            ORDER BY created_at DESC LIMIT 1
            """,
            (organization_id, hotel_id, str(target_business_date)[:10]),
        ).fetchone()
    if not row:
        return None
    return {
        "diagnosis_run_id": row["diagnosis_run_id"],
        "request_key": row["request_key"],
        "organization_id": row["organization_id"],
        "hotel_id": row["hotel_id"],
        "target_business_date": row["target_business_date"],
        "as_of_datetime": row["as_of_datetime"],
        "status": row["status"],
        "coverage_score": row["coverage_score"],
        "observed_health_score": _loads(
            row["observed_health_score_json"], "not_computable"
        ),
        "result": _loads(row["result_json"], {}),
        "created_at": row["created_at"],
    }


__all__ = [
    "DEFAULT_CONTRACT_REVISION",
    "DEFAULT_POLICY_REVISION",
    "build_versioned_capability_result",
    "capability_request_key",
    "ensure_capability_result_schema",
    "ensure_capability_result_schema_conn",
    "find_latest_capability_result",
    "latest_s14_diagnosis_run",
    "list_capability_results_for_request",
    "resolve_organization_id",
    "save_capability_result",
    "save_s14_diagnosis_run",
]

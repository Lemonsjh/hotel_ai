from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


SHANGHAI_TZ = timezone(timedelta(hours=8))
DEFAULT_MIN_SCORE_COVERAGE = 0.80

REQUIRED_CAPABILITY_IDS = (
    "S2",
    "S4",
    "S7",
    "S8",
    "S9",
    "S10",
    "S12",
    "S15",
    "S16",
    "S17",
)

MODULE_DEFINITIONS = (
    ("operating_revenue", 20),
    ("traffic_competition", 15),
    ("conversion_orders", 15),
    ("price_inventory", 15),
    ("promotion_roi", 10),
    ("content_entry", 10),
    ("reputation_service", 8),
    ("execution_data_quality", 7),
)
MODULE_WEIGHTS = dict(MODULE_DEFINITIONS)
MODULE_ORDER = {module_id: index for index, (module_id, _) in enumerate(MODULE_DEFINITIONS)}

CAPABILITY_MODULES = {
    "S2": ("operating_revenue", "price_inventory"),
    "S4": ("traffic_competition",),
    "S7": ("traffic_competition", "price_inventory", "content_entry"),
    "S8": ("promotion_roi", "content_entry"),
    "S9": ("traffic_competition", "conversion_orders"),
    "S10": ("promotion_roi",),
    "S12": ("reputation_service",),
    "S15": ("operating_revenue",),
    "S16": ("operating_revenue",),
    "S17": ("conversion_orders",),
}
CAPABILITY_DEPENDENCIES = {"S16": ("S15",)}

RESULT_STATUSES = {"ok", "partial", "data_gap", "conflict", "stale", "blocked", "not_applicable"}
ISSUE_TYPES = {"anomaly", "conflict", "data_gap", "stale", "observe", "normal"}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
ITEM_STATUSES = {"open", "needs_check", "observing", "resolved", "not_applicable"}
SEVERITY_POINTS = {"critical": 100, "high": 75, "medium": 50, "low": 25, "info": 0}
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

AXIS_NAMES = (
    "sales_progress",
    "market_orders",
    "market_share",
    "browse_users",
    "first_conversion",
    "second_conversion",
    "price",
)
AXIS_SOURCE_PRIORITY = {
    "sales_progress": ("S16", "S2", "S15"),
    "market_orders": ("S9", "S7", "S4", "S15"),
    "market_share": ("S7", "S9", "S4", "S15"),
    "browse_users": ("S9", "S15"),
    "first_conversion": ("S9", "S15"),
    "second_conversion": ("S9", "S15"),
    "price": ("S7", "S2", "S15"),
}
AXIS_FIELDS = ("actual", "baseline", "delta", "maturity", "effective_window", "gap", "unit")
ALLOWED_HANDOFF_CAPABILITIES = {"S5", "S6", "S8", "S13"}
SERVICE_TO_CAPABILITY = {
    "S2_OPERATING_SNAPSHOT": "S2",
    "S4_MARKET_CONTEXT": "S4",
    "S7_COMPETITIVE_MONITORING": "S7",
    "S8_PROMOTION_PLANNING": "S8",
    "S9_TRAFFIC_PEAK_VALLEY": "S9",
    "S10_ROI_DECISION": "S10",
    "S12_REPUTATION_MANAGEMENT": "S12",
    "S15_SALES_BASELINE": "S15",
    "S16_PROGRESS_DEVIATION": "S16",
    "S17_CUSTOMER_ORDER_ANALYSIS": "S17",
}


class S14RequestError(ValueError):
    """Raised when the S14 request bundle is not structurally usable."""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _clamp(value: Any, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    return max(minimum, min(maximum, number))


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            raise S14RequestError(f"{field_name}_required")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise S14RequestError(f"{field_name}_invalid") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed.astimezone(SHANGHAI_TZ)


def _stable_id(prefix: str, payload: Any) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return f"{prefix}{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


def _compatible_revision(result_revision: Any, request_revision: str, compatible: set[str]) -> bool:
    revision = str(result_revision or "").strip()
    return bool(revision) and (revision == request_revision or revision in compatible)


def _legacy_source_removed(source_mode: str) -> dict[str, Any]:
    return {
        "status": "data_gap",
        "skill_id": "S14",
        "source_mode": source_mode,
        "blocked_reason": "s14_direct_source_removed_use_versioned_capability_results",
        "missing_inputs": ["capability_results"],
        "source_policy": "versioned_capability_results_only",
        "direct_business_table_read_allowed": False,
        "excel_source_allowed": False,
        "write_performed": False,
        "direct_execution_allowed": False,
        "live_allowed": False,
        "business_result_generated": False,
    }


def normalize_s14_facts(raw: dict[str, Any], *, source_mode: str) -> dict[str, Any]:
    """Deprecated compatibility shell for the retired raw-fact path."""
    del raw
    return _legacy_source_removed(source_mode)


def diagnose_s14_canonical_facts(facts: dict[str, Any], *, hotel_id: str, source_mode: str) -> dict[str, Any]:
    del facts, hotel_id
    return _legacy_source_removed(source_mode)


def diagnose_s14_excel_file(path: str, *, hotel_id: str, report_dir: str | None = None) -> dict[str, Any]:
    del path, hotel_id, report_dir
    return _legacy_source_removed("excel")


def diagnose_s14_mysql_template_result(
    template_result: dict[str, Any], *, hotel_id: str, report_dir: str | None = None
) -> dict[str, Any]:
    del template_result, hotel_id, report_dir
    return _legacy_source_removed("mysql")


def load_s14_request(*, request_json: str | None = None, request_file: str | None = None) -> dict[str, Any]:
    if bool(request_json) == bool(request_file):
        raise S14RequestError("exactly_one_of_request_json_or_request_file_required")
    try:
        if request_json is not None:
            payload = json.loads(request_json)
        else:
            payload = json.loads(Path(str(request_file)).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise S14RequestError("s14_request_bundle_unreadable") from exc
    if not isinstance(payload, dict):
        raise S14RequestError("s14_request_bundle_must_be_object")
    return payload


def build_s14_request_from_dependency_results(
    *,
    organization_id: str,
    hotel_id: str,
    target_business_date: str,
    as_of_datetime: str,
    contract_revision: str,
    policy_revision: str,
    dependency_results: dict[str, dict[str, Any]],
    handoffs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project already-versioned dependency results into the S14 envelope."""
    capability_results: list[dict[str, Any]] = []
    for key, result in dependency_results.items():
        capability_id = SERVICE_TO_CAPABILITY.get(str(key), str(key))
        if capability_id not in REQUIRED_CAPABILITY_IDS or not isinstance(result, dict):
            continue
        projected = dict(result)
        projected.setdefault("capability_id", capability_id)
        capability_results.append(projected)
    return {
        "organization_id": organization_id,
        "hotel_id": hotel_id,
        "target_business_date": target_business_date,
        "as_of_datetime": as_of_datetime,
        "contract_revision": contract_revision,
        "policy_revision": policy_revision,
        "capability_results": capability_results,
        "handoffs": list(handoffs or []),
    }


def _request_data_gap(reason: str, *, missing_fields: list[str] | None = None) -> dict[str, Any]:
    return {
        "status": "data_gap",
        "skill_id": "S14",
        "reason": reason,
        "missing_fields": list(missing_fields or []),
        "source_policy": "versioned_capability_results_only",
        "direct_business_table_read_allowed": False,
        "excel_source_allowed": False,
        "coverage_score": 0.0,
        "observed_risk_score": None,
        "observed_health_score": "not_computable",
        "items": [],
        "modules": [],
        "decision_axes": [],
        "room_type_exceptions": [],
        "product_layer": [],
        "handoffs": [],
        "data_limitations": [reason],
        "write_performed": False,
        "direct_execution_allowed": False,
        "live_allowed": False,
        "business_result_generated": False,
    }


def _make_item(
    *,
    hotel_id: str,
    target_business_date: str,
    module_id: str,
    issue_code: str,
    issue_type: str,
    severity: str,
    status: str,
    confidence: Any = 0.0,
    impact: dict[str, Any] | None = None,
    evidence_refs: Iterable[Any] = (),
    conflicts: Iterable[Any] = (),
    missing_inputs: Iterable[Any] = (),
    next_checks: Iterable[Any] = (),
    eligible_handoff: str | None = None,
    forbidden_conclusions: Iterable[Any] = (),
    scope: Any = None,
    root_code: str | None = None,
    blocked_by: str | None = None,
) -> dict[str, Any]:
    if module_id not in MODULE_WEIGHTS:
        module_id = "execution_data_quality"
    if issue_type not in ISSUE_TYPES:
        issue_type = "observe"
    if severity not in SEVERITIES:
        severity = "info"
    if status not in ITEM_STATUSES:
        status = "observing"
    evidence = sorted(_dedupe_strings(evidence_refs))
    scope_value = scope if scope not in (None, "") else "hotel"
    item_id = _stable_id(
        "diag-sha256:",
        {
            "hotel_id": hotel_id,
            "target_business_date": target_business_date,
            "module_id": module_id,
            "issue_code": issue_code,
            "scope": scope_value,
            "evidence_refs": evidence,
        },
    )
    item = {
        "item_id": item_id,
        "module_id": module_id,
        "issue_code": str(issue_code),
        "issue_type": issue_type,
        "severity": severity,
        "status": status,
        "confidence": round(_clamp(confidence), 6),
        "impact": impact if isinstance(impact, dict) else {"metric": "unquantified", "value": None, "unit": "unknown"},
        "evidence_refs": evidence,
        "conflicts": list(conflicts or []),
        "missing_inputs": _dedupe_strings(missing_inputs),
        "next_checks": _dedupe_strings(next_checks),
        "eligible_handoff": eligible_handoff,
        "forbidden_conclusions": _dedupe_strings(forbidden_conclusions),
        "direct_execution_allowed": False,
        "scope": scope_value,
        "blocked_by": blocked_by,
        "_root_code": root_code or str(issue_code),
    }
    if item["impact"].get("value") is None:
        item["impact"].setdefault("metric", "unquantified")
        item["impact"].setdefault("unit", "unknown")
    return item


def _alignment_problem_item(
    *, request: dict[str, Any], capability_id: str, reason: str, evidence_refs: Iterable[Any] = ()
) -> dict[str, Any]:
    return _make_item(
        hotel_id=str(request["hotel_id"]),
        target_business_date=str(request["target_business_date"]),
        module_id="execution_data_quality",
        issue_code=f"capability_alignment:{capability_id}:{reason}",
        issue_type="conflict",
        severity="high",
        status="needs_check",
        confidence=1.0,
        evidence_refs=evidence_refs,
        conflicts=[reason],
        missing_inputs=[capability_id],
        next_checks=[f"regenerate_{capability_id}_for_exact_request_context"],
        forbidden_conclusions=[f"do_not_use_{capability_id}_business_conclusions"],
        scope={"capability_id": capability_id},
        root_code=f"capability_alignment:{capability_id}",
    )


def _missing_capability_items(request: dict[str, Any], capability_id: str) -> list[dict[str, Any]]:
    return [
        _make_item(
            hotel_id=str(request["hotel_id"]),
            target_business_date=str(request["target_business_date"]),
            module_id=module_id,
            issue_code=f"missing_input:{capability_id}",
            issue_type="data_gap",
            severity="medium",
            status="needs_check",
            confidence=1.0,
            missing_inputs=[capability_id],
            next_checks=[f"run_{capability_id}_capability_service"],
            forbidden_conclusions=[f"do_not_infer_{module_id}_from_other_sources"],
            scope={"capability_id": capability_id},
            root_code=f"missing_capability:{capability_id}",
        )
        for module_id in CAPABILITY_MODULES[capability_id]
    ]


def _validate_request_identity(request: dict[str, Any]) -> tuple[datetime, set[str], set[str]]:
    required = (
        "organization_id",
        "hotel_id",
        "target_business_date",
        "as_of_datetime",
        "contract_revision",
        "policy_revision",
        "capability_results",
    )
    missing = [field for field in required if request.get(field) in (None, "")]
    if missing:
        raise S14RequestError(f"missing_request_fields:{','.join(missing)}")
    if not isinstance(request.get("capability_results"), list):
        raise S14RequestError("capability_results_must_be_array")
    as_of = _parse_datetime(request["as_of_datetime"], "as_of_datetime")
    target_date = str(request["target_business_date"])[:10]
    try:
        datetime.fromisoformat(target_date)
    except ValueError as exc:
        raise S14RequestError("target_business_date_invalid") from exc
    request["target_business_date"] = target_date
    compatible_contracts = set(_dedupe_strings(request.get("compatible_contract_revisions") or []))
    compatible_policies = set(_dedupe_strings(request.get("compatible_policy_revisions") or []))
    return as_of, compatible_contracts, compatible_policies


def _validate_capability_result(
    result: dict[str, Any],
    *,
    request: dict[str, Any],
    request_as_of: datetime,
    compatible_contracts: set[str],
    compatible_policies: set[str],
) -> list[str]:
    required = (
        "capability_id",
        "result_id",
        "result_version",
        "status",
        "organization_id",
        "hotel_id",
        "target_business_date",
        "as_of_datetime",
        "effective_window",
        "captured_at",
        "source_grain",
        "source_units",
        "deterministic_payload",
        "evidence_refs",
        "quality_flags",
        "contract_revision",
        "policy_revision",
    )
    errors = [f"missing_{field}" for field in required if result.get(field) in (None, "")]
    capability_id = str(result.get("capability_id") or "")
    if capability_id not in REQUIRED_CAPABILITY_IDS:
        errors.append("capability_id_not_allowed")
    if result.get("status") not in RESULT_STATUSES:
        errors.append("status_invalid")
    if str(result.get("organization_id")) != str(request["organization_id"]):
        errors.append("organization_mismatch")
    if str(result.get("hotel_id")) != str(request["hotel_id"]):
        errors.append("hotel_mismatch")
    if str(result.get("target_business_date"))[:10] != str(request["target_business_date"]):
        errors.append("target_business_date_mismatch")
    if not isinstance(result.get("deterministic_payload"), dict):
        errors.append("deterministic_payload_must_be_object")
    if not isinstance(result.get("evidence_refs"), list):
        errors.append("evidence_refs_must_be_array")
    if not isinstance(result.get("quality_flags"), list):
        errors.append("quality_flags_must_be_array")
    if not _compatible_revision(result.get("contract_revision"), str(request["contract_revision"]), compatible_contracts):
        errors.append("contract_revision_incompatible")
    if not _compatible_revision(result.get("policy_revision"), str(request["policy_revision"]), compatible_policies):
        errors.append("policy_revision_incompatible")
    try:
        if _parse_datetime(result.get("captured_at"), "captured_at") > request_as_of:
            errors.append("future_capture")
    except S14RequestError:
        errors.append("captured_at_invalid")
    try:
        if _parse_datetime(result.get("as_of_datetime"), "result_as_of_datetime") > request_as_of:
            errors.append("future_result_as_of")
    except S14RequestError:
        errors.append("result_as_of_datetime_invalid")
    return _dedupe_strings(errors)


def _status_item(request: dict[str, Any], capability_id: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    result_status = str(result.get("status"))
    if result_status == "ok":
        return []
    if result_status == "not_applicable":
        issue_type, severity, item_status = "normal", "info", "not_applicable"
    elif result_status == "partial":
        issue_type, severity, item_status = "data_gap", "low", "needs_check"
    elif result_status == "conflict":
        issue_type, severity, item_status = "conflict", "high", "needs_check"
    elif result_status == "stale":
        issue_type, severity, item_status = "stale", "medium", "needs_check"
    elif result_status == "blocked":
        issue_type, severity, item_status = "data_gap", "high", "needs_check"
    else:
        issue_type, severity, item_status = "data_gap", "medium", "needs_check"
    evidence = result.get("evidence_refs") or []
    quality_flags = result.get("quality_flags") or []
    return [
        _make_item(
            hotel_id=str(request["hotel_id"]),
            target_business_date=str(request["target_business_date"]),
            module_id=module_id,
            issue_code=f"capability_status:{capability_id}:{result_status}",
            issue_type=issue_type,
            severity=severity,
            status=item_status,
            confidence=1.0,
            evidence_refs=evidence,
            conflicts=quality_flags if result_status == "conflict" else [],
            missing_inputs=[capability_id] if result_status in {"partial", "data_gap", "blocked"} else [],
            next_checks=[f"review_{capability_id}_quality_flags"],
            forbidden_conclusions=[f"do_not_upgrade_{capability_id}_{result_status}_to_ok"],
            scope={"capability_id": capability_id},
            root_code=f"capability_status:{capability_id}:{result_status}",
        )
        for module_id in CAPABILITY_MODULES[capability_id]
    ]


def _normalize_upstream_item(
    *,
    request: dict[str, Any],
    capability_id: str,
    result: dict[str, Any],
    raw_item: dict[str, Any],
    handoff_refs: set[str],
    blocked_by: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    module_id = str(raw_item.get("module_id") or CAPABILITY_MODULES[capability_id][0])
    allowed_modules = {*CAPABILITY_MODULES[capability_id], "execution_data_quality"}
    if module_id not in allowed_modules:
        return None, _alignment_problem_item(
            request=request,
            capability_id=capability_id,
            reason=f"unapproved_module:{module_id}",
            evidence_refs=[*(result.get("evidence_refs") or []), *(raw_item.get("evidence_refs") or [])],
        )
    eligible_handoff = raw_item.get("eligible_handoff")
    forbidden = list(raw_item.get("forbidden_conclusions") or [])
    if eligible_handoff and str(eligible_handoff) not in handoff_refs:
        forbidden.append("handoff_ref_not_present_in_request")
        eligible_handoff = None
    return (
        _make_item(
            hotel_id=str(request["hotel_id"]),
            target_business_date=str(request["target_business_date"]),
            module_id=module_id,
            issue_code=str(raw_item.get("issue_code") or f"upstream_item:{capability_id}"),
            issue_type=str(raw_item.get("issue_type") or "observe"),
            severity=str(raw_item.get("severity") or "info"),
            status=str(raw_item.get("status") or "observing"),
            confidence=raw_item.get("confidence", 0.0),
            impact=raw_item.get("impact") if isinstance(raw_item.get("impact"), dict) else None,
            evidence_refs=[*(result.get("evidence_refs") or []), *(raw_item.get("evidence_refs") or [])],
            conflicts=raw_item.get("conflicts") or [],
            missing_inputs=raw_item.get("missing_inputs") or [],
            next_checks=raw_item.get("next_checks") or [],
            eligible_handoff=str(eligible_handoff) if eligible_handoff else None,
            forbidden_conclusions=forbidden,
            scope=raw_item.get("scope") or {"capability_id": capability_id},
            root_code=str(raw_item.get("root_code") or raw_item.get("issue_code") or f"upstream_item:{capability_id}"),
            blocked_by=blocked_by,
        ),
        None,
    )


def _collect_handoffs(request: dict[str, Any], items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], set[str]]:
    handoffs: list[dict[str, Any]] = []
    refs: set[str] = set()
    seen_keys: set[str] = set()
    for raw in request.get("handoffs") or []:
        if not isinstance(raw, dict):
            continue
        capability_id = str(raw.get("capability_id") or "")
        handoff_ref = str(raw.get("handoff_ref") or "")
        candidate_hash = str(raw.get("candidate_hash") or "")
        hotel_id = str(raw.get("hotel_id") or "")
        target_date = str(raw.get("target_business_date") or "")[:10]
        scope = raw.get("scope")
        reasons: list[str] = []
        if capability_id not in ALLOWED_HANDOFF_CAPABILITIES:
            reasons.append("handoff_capability_not_allowed")
        if not handoff_ref:
            reasons.append("handoff_ref_required")
        if not candidate_hash:
            reasons.append("candidate_hash_required")
        if hotel_id != str(request["hotel_id"]):
            reasons.append("handoff_hotel_mismatch")
        if target_date != str(request["target_business_date"]):
            reasons.append("handoff_target_date_mismatch")
        if reasons:
            items.append(
                _make_item(
                    hotel_id=str(request["hotel_id"]),
                    target_business_date=str(request["target_business_date"]),
                    module_id="execution_data_quality",
                    issue_code=f"invalid_handoff:{capability_id or 'unknown'}",
                    issue_type="conflict",
                    severity="medium",
                    status="needs_check",
                    confidence=1.0,
                    conflicts=reasons,
                    next_checks=["regenerate_exact_handoff_reference"],
                    forbidden_conclusions=["do_not_expose_invalid_handoff"],
                    scope=scope or "hotel",
                    root_code=f"invalid_handoff:{capability_id or 'unknown'}",
                )
            )
            continue
        dedupe_key = json.dumps([capability_id, hotel_id, scope, target_date, candidate_hash], sort_keys=True, ensure_ascii=False, default=str)
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        normalized = {
            "capability_id": capability_id,
            "handoff_ref": handoff_ref,
            "hotel_id": hotel_id,
            "scope": scope,
            "target_business_date": target_date,
            "candidate_hash": candidate_hash,
            "display_text": raw.get("display_text"),
            "direct_execution_allowed": False,
        }
        handoffs.append(normalized)
        refs.add(handoff_ref)
    return handoffs, refs


def _axis_payload_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("decision_axes")
    if isinstance(raw, dict):
        return [{"axis_id": axis_name, **value} for axis_name, value in raw.items() if isinstance(value, dict)]
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def _axis_priority(axis_id: str, capability_id: str) -> int:
    priority = AXIS_SOURCE_PRIORITY.get(axis_id, ())
    try:
        return priority.index(capability_id)
    except ValueError:
        return len(priority) + 100


def _collect_decision_axes(
    *, request: dict[str, Any], valid_results: dict[str, dict[str, Any]], items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = {axis_id: [] for axis_id in AXIS_NAMES}
    for capability_id, result in valid_results.items():
        if result.get("status") not in {"ok", "partial"}:
            continue
        payload = result.get("deterministic_payload") or {}
        for entry in _axis_payload_entries(payload):
            axis_id = str(entry.get("axis_id") or "")
            if axis_id not in candidates:
                continue
            candidate = {key: entry.get(key) for key in AXIS_FIELDS if key in entry}
            candidate.update(
                {
                    "axis_id": axis_id,
                    "source_capability_id": capability_id,
                    "result_id": result.get("result_id"),
                    "result_version": result.get("result_version"),
                    "evidence_refs": _dedupe_strings([*(result.get("evidence_refs") or []), *(entry.get("evidence_refs") or [])]),
                }
            )
            candidates[axis_id].append(candidate)
    output: list[dict[str, Any]] = []
    for axis_id in AXIS_NAMES:
        axis_candidates = sorted(
            candidates[axis_id],
            key=lambda item: (_axis_priority(axis_id, str(item["source_capability_id"])), str(item.get("result_id") or "")),
        )
        summary: dict[str, Any] = {
            "axis_id": axis_id,
            "status": "data_gap",
            "actual": None,
            "baseline": None,
            "delta": None,
            "maturity": None,
            "effective_window": None,
            "gap": None,
            "unit": None,
            "source_capabilities": [],
            "evidence_refs": [],
            "candidates": axis_candidates,
        }
        if axis_candidates:
            summary["status"] = "ok"
            summary["source_capabilities"] = _dedupe_strings(item.get("source_capability_id") for item in axis_candidates)
            summary["evidence_refs"] = _dedupe_strings(
                ref for candidate in axis_candidates for ref in candidate.get("evidence_refs") or []
            )
            for field in AXIS_FIELDS:
                for candidate in axis_candidates:
                    if candidate.get(field) not in (None, ""):
                        summary[field] = candidate[field]
                        break
            for field in ("actual", "baseline", "delta", "gap"):
                distinct = {
                    json.dumps(candidate.get(field), sort_keys=True, ensure_ascii=False, default=str)
                    for candidate in axis_candidates
                    if candidate.get(field) not in (None, "")
                }
                if len(distinct) > 1:
                    items.append(
                        _make_item(
                            hotel_id=str(request["hotel_id"]),
                            target_business_date=str(request["target_business_date"]),
                            module_id="execution_data_quality",
                            issue_code=f"axis_source_conflict:{axis_id}:{field}",
                            issue_type="conflict",
                            severity="medium",
                            status="needs_check",
                            confidence=1.0,
                            evidence_refs=summary["evidence_refs"],
                            conflicts=[{"axis_id": axis_id, "field": field, "values": sorted(distinct)}],
                            next_checks=[f"confirm_authoritative_source_for_{axis_id}_{field}"],
                            forbidden_conclusions=[f"do_not_recalculate_{axis_id}_{field}_inside_s14"],
                            scope={"axis_id": axis_id},
                            root_code=f"axis_source_conflict:{axis_id}",
                        )
                    )
        else:
            summary["missing_inputs"] = list(AXIS_SOURCE_PRIORITY.get(axis_id, ()))
        output.append(summary)
    return output


def _collect_room_type_exceptions(
    *, request: dict[str, Any], valid_results: dict[str, dict[str, Any]], items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for capability_id, result in valid_results.items():
        payload = result.get("deterministic_payload") or {}
        for raw in payload.get("room_type_items") or []:
            if not isinstance(raw, dict):
                continue
            issue_type = str(raw.get("issue_type") or "observe")
            is_exception = bool(raw.get("is_exception")) or issue_type in {"anomaly", "conflict", "data_gap", "stale"}
            if not is_exception:
                continue
            room_type_id = str(raw.get("room_type_id") or "").strip()
            if not room_type_id:
                items.append(
                    _make_item(
                        hotel_id=str(request["hotel_id"]),
                        target_business_date=str(request["target_business_date"]),
                        module_id="execution_data_quality",
                        issue_code=f"canonical_room_type_missing:{capability_id}",
                        issue_type="data_gap",
                        severity="medium",
                        status="needs_check",
                        confidence=1.0,
                        evidence_refs=[*(result.get("evidence_refs") or []), *(raw.get("evidence_refs") or [])],
                        missing_inputs=["canonical_room_type_id"],
                        next_checks=["complete_exact_hotel_room_type_mapping"],
                        forbidden_conclusions=["do_not_assign_hotel_average_to_unmapped_room_type"],
                        scope={"capability_id": capability_id},
                        root_code="canonical_room_type_missing",
                    )
                )
                continue
            output.append(
                {
                    **raw,
                    "room_type_id": room_type_id,
                    "source_capability_id": capability_id,
                    "result_id": result.get("result_id"),
                    "evidence_refs": _dedupe_strings([*(result.get("evidence_refs") or []), *(raw.get("evidence_refs") or [])]),
                    "direct_execution_allowed": False,
                }
            )
    output.sort(key=lambda item: (str(item.get("room_type_id") or ""), str(item.get("issue_code") or ""), str(item.get("source_capability_id") or "")))
    return output


def _collect_product_layer(
    *, request: dict[str, Any], valid_results: dict[str, dict[str, Any]], items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for capability_id, result in valid_results.items():
        payload = result.get("deterministic_payload") or {}
        for raw in payload.get("product_facts") or []:
            if not isinstance(raw, dict):
                continue
            if raw.get("hotel_id") not in (None, "", request["hotel_id"]):
                items.append(
                    _alignment_problem_item(
                        request=request,
                        capability_id=capability_id,
                        reason="product_fact_hotel_mismatch",
                        evidence_refs=[*(result.get("evidence_refs") or []), *(raw.get("evidence_refs") or [])],
                    )
                )
                continue
            output.append({**raw, "source_capability_id": capability_id, "result_id": result.get("result_id"), "direct_execution_allowed": False})
    return output


def _status_rank(item: dict[str, Any]) -> int:
    if item.get("issue_type") == "conflict" or item.get("status") == "needs_check":
        return 0
    return {"data_gap": 1, "stale": 2, "anomaly": 3, "observe": 4, "normal": 5}.get(str(item.get("issue_type")), 6)


def _assign_root_clusters(items: list[dict[str, Any]], request: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get("_root_code") or item.get("issue_code") or "unknown"), []).append(item)
    clusters: list[dict[str, Any]] = []
    for root_code, group in sorted(grouped.items()):
        evidence = _dedupe_strings(ref for item in group for ref in item.get("evidence_refs") or [])
        cluster_id = _stable_id(
            "diag-cluster-sha256:",
            {
                "hotel_id": request["hotel_id"],
                "target_business_date": request["target_business_date"],
                "root_code": root_code,
                "evidence_refs": sorted(evidence),
            },
        )
        for item in group:
            item["root_cause_cluster_id"] = cluster_id
            item.pop("_root_code", None)
        clusters.append({"cluster_id": cluster_id, "root_code": root_code, "item_ids": sorted(item["item_id"] for item in group), "evidence_refs": evidence})
    return clusters


def _top_root_cause_items(items: list[dict[str, Any]], *, limit: int = 5) -> list[dict[str, Any]]:
    """Return one deterministic representative per root cause for user-facing summaries."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item.get("root_cause_cluster_id") or item.get("item_id")), []).append(item)
    representatives: list[dict[str, Any]] = []
    for group in grouped.values():
        representative = dict(group[0])  # Items are already sorted by severity and status.
        if len(group) > 1:
            representative["occurrence_count"] = len(group)
            representative["related_issue_codes"] = _dedupe_strings(
                item.get("issue_code") for item in group
            )
        representatives.append(representative)
    return representatives[:limit]


def _module_projection(
    *, observed_modules: set[str], items: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], float, float | None, float | str]:
    modules: list[dict[str, Any]] = []
    observed_weight = sum(MODULE_WEIGHTS[module_id] for module_id in observed_modules)
    weighted_risk = 0.0
    for module_id, weight in MODULE_DEFINITIONS:
        unblocked = [item for item in items if item.get("module_id") == module_id and not item.get("blocked_by")]
        module_risk = max(
            (SEVERITY_POINTS[str(item["severity"])] * _clamp(item.get("confidence")) for item in unblocked),
            default=0.0,
        )
        if module_id in observed_modules:
            weighted_risk += weight * module_risk
        modules.append(
            {
                "module_id": module_id,
                "weight": weight,
                "observed": module_id in observed_modules,
                "module_risk": round(module_risk, 4) if module_id in observed_modules else None,
                "item_count": sum(1 for item in items if item.get("module_id") == module_id),
            }
        )
    coverage_score = round(observed_weight / 100.0, 6)
    if observed_weight <= 0:
        return modules, coverage_score, None, "not_computable"
    observed_risk = round(weighted_risk / observed_weight, 4)
    if coverage_score < DEFAULT_MIN_SCORE_COVERAGE:
        return modules, coverage_score, observed_risk, "not_computable"
    return modules, coverage_score, observed_risk, round(100.0 - observed_risk, 4)


def diagnose_s14_request(request: dict[str, Any]) -> dict[str, Any]:
    """Compose S14 only from aligned, versioned deterministic capability results."""
    if not isinstance(request, dict):
        return _request_data_gap("s14_request_bundle_must_be_object")
    request = dict(request)
    try:
        request_as_of, compatible_contracts, compatible_policies = _validate_request_identity(request)
    except S14RequestError as exc:
        reason = str(exc)
        missing = reason.partition(":")[2].split(",") if reason.startswith("missing_request_fields:") else []
        return _request_data_gap(reason, missing_fields=missing)

    items: list[dict[str, Any]] = []
    handoffs, handoff_refs = _collect_handoffs(request, items)
    raw_results = request.get("capability_results") or []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in raw_results:
        if not isinstance(raw, dict):
            items.append(_alignment_problem_item(request=request, capability_id="unknown", reason="capability_result_must_be_object"))
            continue
        grouped.setdefault(str(raw.get("capability_id") or "unknown"), []).append(raw)

    valid_results: dict[str, dict[str, Any]] = {}
    capability_problem_item_id: dict[str, str] = {}
    for capability_id in REQUIRED_CAPABILITY_IDS:
        candidates = grouped.get(capability_id, [])
        if not candidates:
            missing_items = _missing_capability_items(request, capability_id)
            items.extend(missing_items)
            capability_problem_item_id[capability_id] = missing_items[0]["item_id"]
            continue
        if len(candidates) != 1:
            duplicate_item = _alignment_problem_item(
                request=request,
                capability_id=capability_id,
                reason="duplicate_capability_results",
                evidence_refs=[ref for candidate in candidates for ref in candidate.get("evidence_refs") or []],
            )
            items.append(duplicate_item)
            capability_problem_item_id[capability_id] = duplicate_item["item_id"]
            continue
        result = candidates[0]
        errors = _validate_capability_result(
            result,
            request=request,
            request_as_of=request_as_of,
            compatible_contracts=compatible_contracts,
            compatible_policies=compatible_policies,
        )
        if errors:
            problem = _alignment_problem_item(
                request=request,
                capability_id=capability_id,
                reason="|".join(errors),
                evidence_refs=result.get("evidence_refs") or [],
            )
            items.append(problem)
            capability_problem_item_id[capability_id] = problem["item_id"]
            continue
        valid_results[capability_id] = result
        status_items = _status_item(request, capability_id, result)
        items.extend(status_items)
        if result.get("status") in {"data_gap", "conflict", "stale", "blocked"} and status_items:
            capability_problem_item_id[capability_id] = status_items[0]["item_id"]

    for unknown_id, candidates in grouped.items():
        if unknown_id not in REQUIRED_CAPABILITY_IDS:
            items.append(
                _alignment_problem_item(
                    request=request,
                    capability_id=unknown_id,
                    reason="capability_id_not_allowed",
                    evidence_refs=[ref for candidate in candidates for ref in candidate.get("evidence_refs") or []],
                )
            )

    for capability_id, result in valid_results.items():
        dependency_ids = _dedupe_strings([*CAPABILITY_DEPENDENCIES.get(capability_id, ()), *_as_list(result.get("depends_on_capabilities"))])
        blocked_by = next((capability_problem_item_id[dependency] for dependency in dependency_ids if dependency in capability_problem_item_id), None)
        raw_items = (result.get("deterministic_payload") or {}).get("diagnostic_items") or []
        if isinstance(raw_items, list):
            for raw_item in raw_items:
                if not isinstance(raw_item, dict):
                    continue
                normalized, quality_item = _normalize_upstream_item(
                    request=request,
                    capability_id=capability_id,
                    result=result,
                    raw_item=raw_item,
                    handoff_refs=handoff_refs,
                    blocked_by=blocked_by,
                )
                if normalized is not None:
                    items.append(normalized)
                if quality_item is not None:
                    items.append(quality_item)

    decision_axes = _collect_decision_axes(request=request, valid_results=valid_results, items=items)
    room_type_exceptions = _collect_room_type_exceptions(request=request, valid_results=valid_results, items=items)
    product_layer = _collect_product_layer(request=request, valid_results=valid_results, items=items)

    observed_modules: set[str] = {"execution_data_quality"} if raw_results else set()
    for capability_id, result in valid_results.items():
        if result.get("status") in {"ok", "partial"}:
            observed_modules.update(CAPABILITY_MODULES[capability_id])

    root_cause_clusters = _assign_root_clusters(items, request)
    items.sort(
        key=lambda item: (
            SEVERITY_ORDER.get(str(item.get("severity")), 99),
            _status_rank(item),
            MODULE_ORDER.get(str(item.get("module_id")), 99),
            str(item.get("issue_code") or ""),
            str(item.get("item_id") or ""),
        )
    )
    modules, coverage_score, observed_risk_score, observed_health_score = _module_projection(observed_modules=observed_modules, items=items)
    severity_counts = {severity: sum(1 for item in items if item.get("severity") == severity) for severity in ("critical", "high", "medium", "low", "info")}
    data_limitations = _dedupe_strings(
        item.get("issue_code")
        for item in items
        if item.get("issue_type") in {"data_gap", "conflict", "stale"} or item.get("missing_inputs")
    )
    if any(item.get("issue_type") == "conflict" for item in items):
        overall_status = "conflict"
    elif len(valid_results) < len(REQUIRED_CAPABILITY_IDS) or any(result.get("status") != "ok" for result in valid_results.values()):
        overall_status = "partial"
    else:
        overall_status = "ok"

    return {
        "status": overall_status,
        "skill_id": "S14",
        "schema_version": "s14-capability-results.v1",
        "organization_id": request["organization_id"],
        "hotel_id": request["hotel_id"],
        "target_business_date": request["target_business_date"],
        "as_of_datetime": request_as_of.isoformat(),
        "time_zone": "Asia/Shanghai",
        "contract_revision": request["contract_revision"],
        "policy_revision": request["policy_revision"],
        "source_policy": "versioned_capability_results_only",
        "direct_business_table_read_allowed": False,
        "excel_source_allowed": False,
        "capability_result_count": len(valid_results),
        "required_capability_count": len(REQUIRED_CAPABILITY_IDS),
        "modules": modules,
        "coverage_score": coverage_score,
        "min_score_coverage": DEFAULT_MIN_SCORE_COVERAGE,
        "observed_risk_score": observed_risk_score,
        "observed_health_score": observed_health_score,
        "severity_counts": severity_counts,
        "items": items,
        "top_items": _top_root_cause_items(items),
        "root_cause_clusters": root_cause_clusters,
        "decision_axes": decision_axes,
        "room_type_exceptions": room_type_exceptions,
        "product_layer": product_layer,
        "handoffs": handoffs,
        "data_limitations": data_limitations,
        "ai_analysis_status": "not_requested",
        "write_performed": False,
        "direct_execution_allowed": False,
        "approval_requested": False,
        "live_allowed": False,
        "business_result_generated": bool(observed_modules),
    }


__all__ = [
    "REQUIRED_CAPABILITY_IDS",
    "build_s14_request_from_dependency_results",
    "diagnose_s14_request",
    "load_s14_request",
    "diagnose_s14_excel_file",
    "diagnose_s14_mysql_template_result",
    "diagnose_s14_canonical_facts",
    "normalize_s14_facts",
]

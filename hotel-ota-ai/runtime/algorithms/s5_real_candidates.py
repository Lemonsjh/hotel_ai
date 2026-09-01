from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from runtime.algorithm_rule_loader import find_algorithm_rule
from runtime.adapters.normalized_query import is_price_task_mapping_ready, is_trusted_price_mapping
from runtime.algorithms.revenue_decision_engine import build_s5_decision_ref, calculate_revenue_recommendation
from runtime.algorithms.s7_competition_context import build_s7_competition_context


S5_QUERY_PLAN = {
    "operating": "operating_snapshot",
    "prices": "ota_price_mapping",
    "metrics": "ota_business_metrics",
    "competition": "ctrip_competition_metrics_30d",
    "loss": "ota_order_loss_monthly",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _payload(result: dict[str, Any]) -> dict[str, Any]:
    return result.get("payload") if isinstance(result.get("payload"), dict) else {}


def _query_ok(result: dict[str, Any]) -> bool:
    return result.get("status") == "ok" and _payload(result).get("source_status") in {None, "ok"}


def _query_all(
    query: Callable[..., dict[str, Any]], *, hotel_id: str, target_stay_date: str, as_of_time: str | None
) -> dict[str, dict[str, Any]]:
    def run(name: str, template: str) -> tuple[str, dict[str, Any]]:
        kwargs: dict[str, Any] = {"as_of_time": as_of_time}
        if name in {"operating", "prices", "metrics"}:
            kwargs["date"] = target_stay_date
        return name, query(template, hotel_id, **kwargs)

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(S5_QUERY_PLAN)) as executor:
        futures = {executor.submit(run, name, template): name for name, template in S5_QUERY_PLAN.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                name, results[name] = future.result()
            except Exception as exc:
                results[name] = {"status": "data_gap", "reason": f"s5_optional_query_failed:{exc.__class__.__name__}"}
    return results


def _price_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    payload = _payload(result)
    rows = payload.get("price_snapshots") or payload.get("rows") or []
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _is_editable(row: dict[str, Any]) -> bool:
    value = row.get("price_editable_flag")
    return not (value is False or str(value or "").strip().lower() in {"0", "false", "no", "n"})


def _is_active_mapping(row: dict[str, Any]) -> bool:
    value = row.get("mapping_active")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return float(value) == 1.0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "active"}


def _product_block_reason(row: dict[str, Any]) -> str | None:
    if not _text(row.get("ota_product_id")):
        return "ota_product_id_missing"
    if _number(row.get("current_price")) is None:
        return "current_price_missing"
    if not _is_editable(row):
        return "platform_price_not_editable"
    return None


def _mapping_quality_flags(row: dict[str, Any]) -> list[str]:
    """Keep mapping evidence visible in S5 without turning a read-only candidate into a hard block."""
    flags: list[str] = []
    mapping_signals_present = any(
        row.get(name) not in (None, "")
        for name in ("mapping_status", "match_rule", "mapping_active", "mapping_resolution_status")
    )
    if mapping_signals_present and not is_trusted_price_mapping(row):
        flags.append("room_type_mapping_not_trusted")
    elif mapping_signals_present and not _is_active_mapping(row):
        flags.append("room_type_mapping_inactive")

    mapping_risks = {
        str(item)
        for item in [
            *(row.get("row_risk_flags") or []),
            *(row.get("risk_flags") or []),
        ]
        if str(item)
    }
    if not _text(row.get("room_type_id")) or mapping_risks & {
        "ota_room_type_mapping_incomplete", "mapping_candidate_name_match", "inferred_by_name", "mapping_conflict"
    }:
        flags.append("room_type_mapping_pending")
    return list(dict.fromkeys(flags))


def _guard_band(policy: dict[str, Any], current_price: float) -> tuple[float, float, bool]:
    active = policy.get("source") == "active_price_guard_policy" and policy.get("floor_price") is not None and policy.get("ceiling_price") is not None
    if active:
        return float(policy["floor_price"]), float(policy["ceiling_price"]), True
    decrease = _number(policy.get("max_decrease_pct"), 0.15) or 0.15
    increase = _number(policy.get("max_increase_pct"), 0.15) or 0.15
    return round(current_price * (1 - decrease), 2), round(current_price * (1 + increase), 2), False


def _room_pressure(operating: dict[str, Any], room_type_id: str) -> tuple[float, list[str]]:
    rows = operating.get("room_type_forecasts") or []
    room = next((row for row in rows if str(row.get("room_type_id") or "") == room_type_id), None)
    if not isinstance(room, dict):
        return 0.5, ["room_type_forecast_missing"]
    total = _number(room.get("total_rooms"), 0.0) or 0.0
    sold = _number(room.get("committed_sold_rooms"), 0.0) or 0.0
    return (round(sold / total, 4) if total else 0.5), []


def _market_context(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return build_s7_competition_context(
        price_result=results.get("prices", {}), metrics_result=results.get("metrics", {}),
        competition_result=results.get("competition", {}), loss_result=results.get("loss", {}),
        activity_result={}, activity_detail_result={}, rights_result={}, psi_result={}, ranking_result={},
    )


def _s16_progress(progress_result: dict[str, Any] | None, *, target_stay_date: str) -> dict[str, Any]:
    if not isinstance(progress_result, dict) or progress_result.get("status") not in {"ok", "partial"}:
        return {"available": False, "complete": False, "reason": "s16_unavailable"}

    dynamic_value = progress_result.get("dynamic_diagnosis")
    dynamic = dynamic_value if isinstance(dynamic_value, dict) else {}
    sales_value = dynamic.get("sales") if dynamic else progress_result.get("sales")
    sales = sales_value if isinstance(sales_value, dict) else {}

    result_date = _text(
        dynamic.get("target_date")
        or progress_result.get("target_date")
        or progress_result.get("actual_basis_date")
    )[:10]
    if result_date != target_stay_date:
        return {"available": False, "complete": False, "reason": "s16_target_date_mismatch"}

    checkpoint_gap = _number(
        sales.get("checkpoint_room_gap"),
        _number(
            progress_result.get("as_of_checkpoint_gap"),
            _number(progress_result.get("room_night_gap")),
        ),
    )
    remaining_gap = _number(
        sales.get("remaining_target_gap"),
        _number(
            progress_result.get("daily_remaining_gap"),
            _number(progress_result.get("daily_remaining_room_nights")),
        ),
    )
    has_dynamic_result = bool(dynamic) or isinstance(progress_result.get("sales"), dict)
    has_legacy_progress = any(
        progress_result.get(name) not in (None, "")
        for name in (
            "as_of_checkpoint_gap",
            "room_night_gap",
            "daily_remaining_gap",
            "daily_remaining_room_nights",
        )
    )
    if not has_dynamic_result and not has_legacy_progress:
        return {"available": False, "complete": False, "reason": "s16_progress_payload_missing"}

    missing_fields: list[str] = []
    if checkpoint_gap is None:
        missing_fields.append("checkpoint_room_gap")
    if remaining_gap is None:
        missing_fields.append("remaining_target_gap")
    source = (
        "s16_dynamic_diagnosis.sales"
        if dynamic
        else "s16_sales"
        if isinstance(progress_result.get("sales"), dict)
        else "s16_progress_deviation"
    )
    return {
        "available": True,
        "complete": not missing_fields,
        "as_of_checkpoint_gap": round(checkpoint_gap, 2) if checkpoint_gap is not None else None,
        "daily_remaining_gap": round(max(remaining_gap, 0), 2) if remaining_gap is not None else None,
        "source": source,
        "status": dynamic.get("status") or progress_result.get("status"),
        "missing_fields": missing_fields,
    }


def _s15_baseline(
    baseline_result: dict[str, Any] | None, *, target_stay_date: str
) -> tuple[dict[str, Any], bool, str | None]:
    if not isinstance(baseline_result, dict) or baseline_result.get("status") != "ok":
        return {}, False, str((baseline_result or {}).get("reason") or "s15_unavailable")

    payload = baseline_result.get("baseline")
    payload = payload if isinstance(payload, dict) else baseline_result
    package = payload.get("baseline_package")
    package = package if isinstance(package, dict) else None

    if package is not None:
        baseline_date = _text(
            package.get("target_date")
            or payload.get("target_date")
            or payload.get("business_date")
            or payload.get("data_business_date")
        )[:10]
        target = _number(package.get("hotel_final_sales_target"))
        if baseline_date != target_stay_date or target is None:
            return package, False, "s15_baseline_contract_incomplete"

        data_gaps = [
            str(item)
            for item in (package.get("data_gaps") or payload.get("data_gaps") or [])
        ]
        if any(item.startswith("room_daily:") for item in data_gaps):
            return package, False, "s15_room_type_daily_data_unavailable"

        maturity = str(package.get("sample_maturity") or "")
        if maturity in {"trend_only", "weak"}:
            return package, False, f"s15_baseline_maturity_{maturity}"
        return package, True, None

    baseline_date = _text(
        payload.get("business_date")
        or payload.get("data_business_date")
        or payload.get("target_date")
    )[:10]
    target = _number(
        payload.get("target_room_nights"),
        _number(payload.get("daily_target_room_nights")),
    )
    policy = payload.get("hourly_curve_policy") or {}
    s16_allowed = policy.get("s16_deviation_allowed")
    if baseline_date != target_stay_date or target is None or s16_allowed is False:
        return payload, False, "s15_baseline_contract_incomplete"
    hotel = payload.get("hotel") or {}
    data_gaps = [str(item) for item in (payload.get("data_gaps") or [])]
    if any(item.startswith("room_daily:") for item in data_gaps):
        return payload, False, "s15_room_type_daily_data_unavailable"
    health = hotel.get("baseline_health") or {}
    maturity = str(health.get("object_maturity") or "")
    if maturity in {"trend_only", "weak"}:
        return payload, False, f"s15_baseline_maturity_{maturity}"
    confidences = [
        _number(hotel.get("capacity_series_confidence")),
        _number(hotel.get("target_series_confidence")),
    ]
    known_confidences = [value for value in confidences if value is not None]
    if known_confidences and min(known_confidences) < 0.60:
        return payload, False, "s15_baseline_confidence_low"
    return payload, True, None


def build_s5_real_candidates(
    *,
    query: Callable[..., dict[str, Any]],
    resolve_guard: Callable[..., dict[str, Any]],
    control_db_path: str,
    hotel_id: str,
    target_stay_date: str,
    as_of_time: str | None,
    channel: str | None = None,
    ota_product_id: str | None = None,
    s15_result: dict[str, Any] | None = None,
    s16_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic, read-only S5 product candidates; never creates a task."""
    results = _query_all(query, hotel_id=hotel_id, target_stay_date=target_stay_date, as_of_time=as_of_time)
    operating = _payload(results.get("operating", {}))
    market = _market_context(results)
    metrics_ok = _query_ok(results.get("metrics", {}))
    baseline_payload, baseline_ok, baseline_reason = _s15_baseline(s15_result, target_stay_date=target_stay_date)
    operating_ok = _query_ok(results.get("operating", {}))
    progress = _s16_progress(s16_result, target_stay_date=target_stay_date)
    rules = (find_algorithm_rule(skill_id="S5").get("algorithm") or {}).get("thresholds") or {}
    requested_channel = _text(channel).lower()
    requested_product = _text(ota_product_id)
    rows = _price_rows(results.get("prices", {}))
    candidates: list[dict[str, Any]] = []
    quality_flags: list[str] = []
    for name, result in results.items():
        if not _query_ok(result):
            quality_flags.append(f"source_missing:{name}:{_payload(result).get('source_status') or result.get('reason') or 'unavailable'}")
    if not baseline_ok:
        quality_flags.append(f"source_missing:s15:{baseline_reason or 'unavailable'}")
    if not progress.get("available"):
        quality_flags.append(
            f"source_missing:s16:{progress.get('reason') or (s16_result or {}).get('reason') or (s16_result or {}).get('status') or 'unavailable'}"
        )
    elif not progress.get("complete"):
        quality_flags.append(
            "source_partial:s16:" + ",".join(progress.get("missing_fields") or ["progress_fields_incomplete"])
        )
    for row in rows:
        product_channel = _text(row.get("channel") or row.get("source_platform") or row.get("channel_source")).lower()
        product_id = _text(row.get("ota_product_id"))
        if requested_channel and product_channel != requested_channel:
            continue
        if requested_product and product_id != requested_product:
            continue
        block_reason = _product_block_reason(row)
        mapping_flags = _mapping_quality_flags(row)
        current_price = _number(row.get("current_price"), 0.0) or 0.0
        policy = resolve_guard(
            control_db_path, hotel_id=hotel_id, room_type_id=_text(row.get("room_type_id")),
            channel_source=product_channel, ota_product_id=product_id, at_time=as_of_time or target_stay_date,
        )
        floor, ceiling, active_guard = _guard_band(policy, current_price)
        inventory_pressure, room_flags = _room_pressure(operating, _text(row.get("room_type_id"))) if operating_ok else (0.5, ["operating_snapshot_missing"])
        platform_market = (market.get("platforms") or {}).get(product_channel) or {}
        lead = next((item for item in (platform_market.get("peer_aggregate") or []) if item.get("metric_code") == "DAY_ROOM_LOWEST_PRICE_AVG"), {})
        recommendation = calculate_revenue_recommendation(
            {
                "room_type_id": row.get("room_type_id"), "room_type_name": row.get("room_type_name"),
                "channel": product_channel, "ota_product_id": product_id, "current_price": current_price,
                "floor_price": floor, "ceiling_price": ceiling, "max_increase_pct": policy.get("max_increase_pct"),
                "max_decrease_pct": policy.get("max_decrease_pct"), "min_increase_pct": policy.get("min_increase_pct"),
                "min_decrease_pct": policy.get("min_decrease_pct"),
                "demand_pressure": operating.get("committed_occupancy_rate"), "inventory_pressure": inventory_pressure,
                "as_of_checkpoint_gap": progress.get("as_of_checkpoint_gap"),
                "daily_remaining_gap": progress.get("daily_remaining_gap"),
                "competitor_context": {"our_price_index": lead.get("lead_price_index")},
                "diagnosis_constraint_context": {"diagnosis_status": "ok" if metrics_ok else "partial"},
            },
            rules,
        )
        recommendation["ota_product_id"] = product_id
        recommendation["ota_product_name"] = row.get("ota_product_name")
        recommendation["ota_room_type_name"] = row.get("ota_room_type_name")
        recommendation["hotel_name"] = row.get("hotel_name") or row.get("hotel_display_name")
        recommendation["target_stay_date"] = target_stay_date
        recommendation["price_observation_business_date"] = row.get("business_date")
        recommendation["price_observation_snapshot_time"] = row.get("snapshot_time")
        recommendation["price_guard_source"] = policy.get("source")
        recommendation["price_guard_policy_id"] = policy.get("policy_id")
        recommendation["price_guard_policy_version"] = policy.get("version")
        recommendation["price_guard_policy_state"] = policy.get("policy_state")
        recommendation["configured_floor_price"] = policy.get("floor_price")
        recommendation["configured_ceiling_price"] = policy.get("ceiling_price")
        recommendation["comparison_level"] = "peer_aggregate" if lead else "own_only"
        recommendation["peer_price_evidence"] = lead or None
        candidate_flags = [*room_flags, *mapping_flags]
        if not baseline_ok:
            candidate_flags.append("missing_s15_sales_baseline")
        if not progress.get("available"):
            candidate_flags.append("missing_s16_progress_deviation")
        elif not progress.get("complete"):
            candidate_flags.append("incomplete_s16_progress_deviation")
        if not metrics_ok:
            candidate_flags.append("missing_same_date_flow_metrics")
        if not lead:
            candidate_flags.append("exact_product_competitor_price_unavailable")
        if not active_guard:
            candidate_flags.append("default_guard_preview_only")
        if block_reason:
            recommendation["eligibility"] = "blocked"
            recommendation["blocked_reason"] = block_reason
        elif active_guard:
            recommendation["eligibility"] = "eligible_for_s6_dry_run"
        else:
            recommendation["eligibility"] = "preview_only_default_guard"
            recommendation["blocked_reason"] = "active_price_guard_policy_required_before_s6"
        # Missing or partial upstream evidence lowers confidence but never blocks
        # an otherwise safe S6 dry-run. S6 re-reads price and validates the
        # active guard, mapping and approval boundary before any task write.
        recommendation["reference_only"] = not (baseline_ok and progress.get("complete"))
        mapping_gate = is_price_task_mapping_ready({**row, "source_platform": product_channel})
        recommendation["s6_task_mapping_ready"] = bool(mapping_gate.get("ready_for_price_task"))
        recommendation["s6_task_mapping_blocked_reason"] = mapping_gate.get("blocked_reason")
        recommendation["s6_task_mapping_trust_basis"] = mapping_gate.get("mapping_trust_basis")
        recommendation["candidate_strength"] = "full" if operating_ok and baseline_ok and progress.get("complete") and metrics_ok and active_guard else "partial"
        recommendation["quality_flags"] = candidate_flags
        reference = build_s5_decision_ref(
            recommendation, freshness_status=operating.get("freshness_status"), business_date=target_stay_date,
            hotel_id=hotel_id, guard_version=str(policy.get("version") or "default_preview_guard_v1"),
            price_guard_policy_id=policy.get("policy_id"),
        )
        recommendation["decision_ref"] = reference
        candidates.append(recommendation)
    if requested_product and not candidates:
        quality_flags.append("requested_ota_product_not_observed")
    candidates.sort(key=lambda item: (item.get("eligibility") != "eligible_for_s6_dry_run", item.get("risk_level") != "low", _text(item.get("ota_product_name"))))
    eligible_count = sum(item.get("eligibility") == "eligible_for_s6_dry_run" for item in candidates)
    price_payload = _payload(results.get("prices", {}))
    data_business_date = (
        operating.get("data_business_date")
        or operating.get("business_date")
        or price_payload.get("data_business_date")
        or price_payload.get("business_date")
        or target_stay_date
    )
    data_snapshot_time = (
        operating.get("data_snapshot_time")
        or operating.get("snapshot_time")
        or price_payload.get("data_snapshot_time")
        or price_payload.get("snapshot_time")
    )
    freshness_status = operating.get("freshness_status") or price_payload.get("freshness_status") or "not_available"
    return {
        "skill_id": "S5", "status": "ok" if candidates else "data_gap", "hotel_id": hotel_id,
        "target_stay_date": target_stay_date, "as_of_time": as_of_time, "data_source_type": "mysql_db",
        "business_date": data_business_date, "data_business_date": data_business_date,
        "data_snapshot_time": data_snapshot_time, "freshness_status": freshness_status,
        "business_status": "current" if freshness_status == "fresh" and data_business_date == target_stay_date else "partial",
        "candidate_count": len(candidates), "eligible_for_s6_count": eligible_count, "candidates": candidates[:20],
        "s16_status": (s16_result or {}).get("status") or "unavailable",
        "s16_progress_source": progress.get("source"),
        "s16_progress_complete": bool(progress.get("complete")),
        "s16_missing_fields": progress.get("missing_fields") or [],
        "s15_status": (s15_result or {}).get("status") or "unavailable",
        "s15_baseline_source": "s15_capability_result",
        "s15_blocked_reason": baseline_reason,
        "quality_flags": quality_flags, "market_comparison_contract": market.get("comparison_contract_version"),
        "exact_product_competitor_price_available": False, "direct_price_trigger_allowed": False,
        "approval_data_allowed": False, "live_allowed": False, "handoff_to": "S6",
        "blocked_reason": None if candidates else "ota_price_mapping_unavailable_or_no_matching_product",
        "formal_approval_created": False, "live_execution_count": 0,
    }

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Callable

from runtime.algorithms.s7_competition_context import build_s7_competition_context
from runtime.s2_business_metric_snapshot_patch import s2_business_metric_snapshot_scope


S2_OPTIONAL_QUERIES = {
    "flow_conversion": (
        "ota_business_metrics",
        {"date_offset_days": 0, "source_platform": "meituan"},
    ),
    "market_metrics": ("ota_business_metrics", {"date_offset_days": 0}),
    "price_and_lead": ("ota_price_mapping", {"date_offset_days": 0}),
    "market_competition": ("ctrip_competition_metrics_30d", {"date_bound": False}),
    "monthly_loss": ("ota_order_loss_monthly", {"date_bound": False}),
    "promotion_activity": ("ota_activity_summary", {"date_bound": False}),
    "promotion_products": ("ota_activity_product_detail", {"date_bound": False}),
}


# The Meituan source also includes legacy aliases such as INTENTION_UV and
# PAY_ORDER_CNT. They describe the same facts as the FLOW_* codes and must
# never be added to, or displayed alongside, the canonical funnel.
FLOW_METRIC_CODES = (
    "FLOW_EXPOSURE_UV",
    "FLOW_INTENTION_UV",
    "FLOW_PAY_ORDER_CNT",
    "FLOW_INTENTION_PER_EXPOSURE",
    "FLOW_PAY_ORDER_PER_INTENTION",
)

FLOW_SOURCE_TABLE = "meituan_ota_business_metrics"


def _payload(result: dict[str, Any] | None) -> dict[str, Any]:
    return result.get("payload") if isinstance(result, dict) and isinstance(result.get("payload"), dict) else (result or {})


def _rows(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    payload = _payload(result)
    rows = payload.get("rows") or payload.get("price_snapshots") or []
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _platform(row: dict[str, Any]) -> str:
    source = str(
        row.get("channel")
        or row.get("channel_source")
        or row.get("table_key")
        or row.get("source_table_key")
        or row.get("source_platform")
        or row.get("platform")
        or ""
    ).lower()
    if "meituan" in source or "美团" in source:
        return "meituan"
    if "ctrip" in source or "携程" in source:
        return "ctrip"
    return "unknown"


def _view_meta(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = [row.get("business_date") for row in rows if row.get("business_date")]
    snapshots = [row.get("snapshot_time") or row.get("data_snapshot_time") for row in rows if row.get("snapshot_time") or row.get("data_snapshot_time")]
    return {
        "business_date": str(max(dates))[:10] if dates else None,
        "snapshot_time": str(max(snapshots)) if snapshots else None,
    }


def _query_state(result: dict[str, Any] | None) -> tuple[str, str | None]:
    payload = _payload(result)
    if not isinstance(result, dict) or result.get("status") != "ok":
        return "data_gap", str((result or {}).get("reason") or "optional_query_unavailable")
    source_status = str(payload.get("source_status") or "ok")
    if source_status in {"no_rows", "empty"}:
        return "no_records", None
    if source_status != "ok":
        return "data_gap", str(payload.get("reason") or source_status)
    return "ok", None


def _truncated(result: dict[str, Any] | None) -> bool:
    return bool((_payload(result).get("truncated_table_keys") or []))


def _metric_source_flags(result: dict[str, Any] | None, *, platform: str, metric_code: str | None = None) -> list[str]:
    """Describe the missing layer without calling a healthy query a gap."""
    state, reason = _query_state(result)
    if state == "no_records":
        return ["ota_business_metrics:no_records"]
    if state != "ok":
        return [f"source_missing:ota_business_metrics:{reason or 'optional_query_unavailable'}"]
    platform_rows = [row for row in _rows(result) if _platform(row) == platform]
    if not platform_rows:
        return [f"platform_missing:{platform}:ota_business_metrics"]
    if metric_code and not any(str(row.get("metric_code") or "").upper() == metric_code for row in platform_rows):
        return [f"metric_code_missing:{platform}:{metric_code}"]
    return []


def load_s2_optional_results(
    query: Callable[..., dict[str, Any]], *, hotel_id: str, business_date: str, as_of_time: str | None
) -> dict[str, dict[str, Any]]:
    """Fan out independent read-only views; no skill or action is invoked."""
    def load(name: str, template: str, options: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        kwargs: dict[str, Any] = {}
        source_date: date | None = None
        if "date_offset_days" in options:
            source_date = date.fromisoformat(str(business_date)[:10]) + timedelta(days=int(options["date_offset_days"]))
            kwargs = {"date": source_date.isoformat(), "as_of_time": as_of_time}
        if options.get("source_platform"):
            kwargs["source_platform"] = str(options["source_platform"])
        if template == "ota_business_metrics":
            with s2_business_metric_snapshot_scope():
                result = query(template, hotel_id, **kwargs)
        else:
            result = query(template, hotel_id, **kwargs)
        if name == "flow_conversion":
            # S2's current-day funnel is an exact-date Meituan fact view. Keep
            # the requested date beside the result so downstream composition
            # can reject any adapter/source fallback to an older business day.
            result = dict(result or {})
            result["_s2_requested_business_date"] = (
                source_date.isoformat() if source_date is not None else str(business_date)[:10]
            )
            result["_s2_source_table"] = FLOW_SOURCE_TABLE
        return name, result

    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=len(S2_OPTIONAL_QUERIES)) as executor:
        futures = {executor.submit(load, name, template, options): name for name, (template, options) in S2_OPTIONAL_QUERIES.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                name, result = future.result()
            except Exception as exc:  # Individual panels must not block the PMS core.
                result = {"status": "data_gap", "reason": f"optional_view_query_failed:{exc.__class__.__name__}"}
            results[name] = result
    return results


def _flow_view(result: dict[str, Any]) -> dict[str, Any]:
    requested_date = str(result.get("_s2_requested_business_date") or "")[:10] or None
    source_table = str(result.get("_s2_source_table") or FLOW_SOURCE_TABLE)
    raw_rows = _rows(result)
    rows = [
        row
        for row in raw_rows
        if _platform(row) == "meituan"
        and (
            requested_date is None
            or str(row.get("business_date") or "")[:10] == requested_date
        )
    ]
    query_state, query_reason = _query_state(result)

    if not rows:
        if query_state == "ok":
            return {
                "status": "no_records",
                "platforms": {},
                "business_date": requested_date,
                "source_table": source_table,
                "quality_flags": [
                    f"{source_table}:no_records:{requested_date or 'requested_business_date'}"
                ],
            }
        return {
            "status": query_state,
            "platforms": {},
            "business_date": requested_date,
            "source_table": source_table,
            "quality_flags": [
                f"{source_table}:no_records:{requested_date or 'requested_business_date'}"
                if query_state == "no_records"
                else f"source_missing:{source_table}:{query_reason}"
            ],
        }

    by_code = {str(row.get("metric_code") or "").upper(): row for row in rows}
    metrics = [
        {
            "metric_code": code,
            "metric_name": by_code[code].get("metric_name"),
            "metric_value": by_code[code].get("metric_value"),
            "metric_unit": by_code[code].get("metric_unit"),
            "peer_average": by_code[code].get("peer_average"),
            "competitor_rank": by_code[code].get("competitor_rank"),
            "business_date": by_code[code].get("business_date"),
            "snapshot_time": by_code[code].get("snapshot_time"),
        }
        for code in FLOW_METRIC_CODES
        if code in by_code
    ]
    missing = [code for code in FLOW_METRIC_CODES if code not in by_code]
    item = {
        "status": "ok" if metrics else "data_gap",
        "metric_count": len(metrics),
        "metrics": metrics,
        "quality_flags": [f"metric_code_missing:meituan:{code}" for code in missing],
        "source_table": source_table,
        **_view_meta(rows),
    }
    return {
        "status": item["status"],
        "platforms": {"meituan": item},
        "business_date": requested_date or item.get("business_date"),
        "source_table": source_table,
        "quality_flags": [f"{source_table}:truncated"] if _truncated(result) else [],
    }


def _promotion_view(summary: dict[str, Any], details: dict[str, Any]) -> dict[str, Any]:
    summary_rows, detail_rows = _rows(summary), _rows(details)
    summary_state, summary_reason = _query_state(summary)
    details_state, details_reason = _query_state(details)
    platforms: dict[str, dict[str, Any]] = {}
    for platform in ("meituan", "ctrip"):
        activities = [row for row in summary_rows if _platform(row) == platform]
        products = [row for row in detail_rows if _platform(row) == platform]
        if not activities and not products:
            continue
        identifiers = {str(row.get("activity_id") or row.get("activity_name")) for row in activities if row.get("activity_id") or row.get("activity_name")}
        mapped = {str(row.get("room_type_id")) for row in products if row.get("room_type_id")}
        statuses = sorted({str(row.get("activity_status")) for row in activities if row.get("activity_status") not in (None, "")})
        platforms[platform] = {
            "status": "ok", "activity_count": len(identifiers), "activity_product_count": len(products),
            "canonical_room_type_count": len(mapped), "mapping_missing_count": len(products) - len([row for row in products if row.get("room_type_id")]),
            "activity_product_count_is_lower_bound": _truncated(details),
            "activity_statuses": statuses, **_view_meta(activities + products),
        }
    if platforms:
        flags = []
        if _truncated(summary):
            flags.append("promotion_activity_summary:truncated")
        if _truncated(details):
            flags.append("promotion_activity_products:truncated")
        return {"status": "ok", "platforms": platforms, "quality_flags": flags}
    states = {summary_state, details_state}
    if states == {"no_records"}:
        return {"status": "no_records", "platforms": {}, "quality_flags": ["promotion_activity:no_records"]}
    reasons = [reason for reason in (summary_reason, details_reason) if reason]
    return {
        "status": "data_gap", "platforms": {},
        "quality_flags": [f"source_missing:promotion_activity:{','.join(reasons) or 'optional_query_unavailable'}"],
    }


def build_s2_operating_views(*, operating_payload: dict[str, Any], optional_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Compose the six S2 read-only views from shared capability queries."""
    competition = build_s7_competition_context(
        price_result=optional_results.get("price_and_lead", {}),
        metrics_result=optional_results.get("market_metrics", {}),
        competition_result=optional_results.get("market_competition", {}),
        loss_result=optional_results.get("monthly_loss", {}),
        activity_result=optional_results.get("promotion_activity", {}),
        activity_detail_result=optional_results.get("promotion_products", {}),
        rights_result={}, psi_result={}, ranking_result={},
    )
    price_platforms: dict[str, Any] = {}
    market_platforms: dict[str, Any] = {}
    for platform, item in (competition.get("platforms") or {}).items():
        peer = item.get("peer_aggregate") or []
        lead = next((row for row in peer if str(row.get("metric_code") or "").upper() == "DAY_ROOM_LOWEST_PRICE_AVG"), None)
        metric_flags = _metric_source_flags(
            optional_results.get("market_metrics"), platform=platform, metric_code="DAY_ROOM_LOWEST_PRICE_AVG"
        )
        price_platforms[platform] = {
            "status": "ok" if item.get("own_products") else "data_gap",
            "products": item.get("own_products") or [], "lead_price": lead,
            "quality_flags": [] if lead else metric_flags,
        }
        market_flags = list(item.get("quality_flags") or [])
        if not peer and not item.get("loss_context"):
            market_flags.extend(_metric_source_flags(optional_results.get("market_metrics"), platform=platform))
            market_flags.append("source_missing:peer_aggregate_and_loss_context")
        market_platforms[platform] = {
            "status": "ok" if peer or item.get("loss_context") else "data_gap",
            "peer_aggregate": peer, "loss_context": item.get("loss_context"),
            "competition_circles": (item.get("competition_circle_context") or {}).get("circles") or [],
            "quality_flags": [] if peer or item.get("loss_context") else list(dict.fromkeys(market_flags)),
        }

    core = {
        "status": "ok" if operating_payload.get("source_status") in {None, "ok"} else "data_gap",
        "total_rooms": operating_payload.get("total_rooms"), "available_rooms": operating_payload.get("available_rooms"),
        "base_committed_sold_rooms": operating_payload.get("base_committed_sold_rooms"), "overbooking_rooms": operating_payload.get("overbooking_rooms"),
        "committed_sold_rooms": operating_payload.get("committed_sold_rooms"), "committed_occupancy_rate": operating_payload.get("committed_occupancy_rate"),
        "physical_occupied_rooms": operating_payload.get("physical_occupied_rooms"), "physical_occupancy_rate": operating_payload.get("physical_occupancy_rate"),
        "room_revenue": operating_payload.get("room_revenue"), "adr": operating_payload.get("adr"), "revpar": operating_payload.get("revpar"),
        "business_date": operating_payload.get("data_business_date"), "snapshot_time": operating_payload.get("data_snapshot_time"),
    }
    quality_flags = list(operating_payload.get("risk_flags") or [])
    for name, view in (("flow_conversion", _flow_view(optional_results.get("flow_conversion", {}))), ("promotion_activity", _promotion_view(optional_results.get("promotion_activity", {}), optional_results.get("promotion_products", {})))):
        if view["status"] != "ok":
            quality_flags.append(f"{name}:{view['status']}")
    return {
        "schema_version": "s2_operating_snapshot_v2", "core_operating": core,
        "room_type_status": {"status": core["status"], "items": operating_payload.get("room_type_forecasts") or [], "business_date": core["business_date"], "snapshot_time": core["snapshot_time"]},
        "flow_conversion": _flow_view(optional_results.get("flow_conversion", {})),
        "market_competition": {"status": "ok" if any(item["status"] == "ok" for item in market_platforms.values()) else "data_gap", "platforms": market_platforms, "comparison_contract_version": competition.get("comparison_contract_version"), "quality_flags": competition.get("quality_flags") or []},
        "price_and_lead": {"status": "ok" if any(item["status"] == "ok" for item in price_platforms.values()) else "data_gap", "platforms": price_platforms},
        "promotion_activity": _promotion_view(optional_results.get("promotion_activity", {}), optional_results.get("promotion_products", {})),
        "quality_flags": quality_flags,
        "direct_price_trigger_allowed": False, "live_allowed": False,
    }

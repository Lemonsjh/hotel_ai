from __future__ import annotations

from collections import Counter
from typing import Any

from runtime.common import now_local


Context = dict[str, Any]

_OCCUPIED_ROOM_STATUS = {
    "occupied",
    "inhouse",
    "checked_in",
    "stayover",
    "住客房",
    "已住",
    "入住",
    "在住",
}
_AVAILABLE_ROOM_STATUS = {
    "vacant",
    "available",
    "clean",
    "空房",
    "可售",
    "干净房",
}


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_num(values: Context, *keys: str) -> float | None:
    for key in keys:
        number = _num(values.get(key))
        if number is not None:
            return number
    return None


def _first_num_in_contexts(contexts: list[Context], *keys: str) -> float | None:
    for values in contexts:
        number = _first_num(values, *keys)
        if number is not None:
            return number
    return None


def _first_ratio(*values: Any) -> float | None:
    for value in values:
        ratio = _ratio(value)
        if ratio is not None:
            return ratio
    return None


def _ratio(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return round(number / 100, 4) if number > 1 else round(number, 4)


def _payload(result: Context | None) -> Context:
    if not isinstance(result, dict):
        return {}
    payload = result.get("payload")
    return payload if isinstance(payload, dict) else result


def _rows(result: Context | None) -> list[Context]:
    payload = _payload(result)
    rows = payload.get("rows") or payload.get("items") or []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _status_is_active(value: Any) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"active", "enabled", "running", "online", "valid", "生效", "进行中", "启用", "可用"}


def _avg(values: list[float]) -> float | None:
    clean = [value for value in values if value is not None]
    return round(sum(clean) / len(clean), 4) if clean else None


def _base_context(name: str, *, status: str = "data_gap", capability_level: str = "unavailable") -> Context:
    return {
        "context_name": name,
        "status": status,
        "capability_level": capability_level,
        "source_mode": "mysql_runtime",
        "used_fields": [],
        "used_tables": [],
        "derived_fields": [],
        "estimated_fields": [],
        "internal_missing_fields": [],
        "commercial_visible": status in {"ok", "partial"},
        "commercial_sections": [],
        "risk_flags": [],
        "data_business_date": None,
        "data_snapshot_time": None,
        "freshness_status": None,
        "business_status": None,
        "approval_allowed": False,
        "live_allowed": False,
        "generated_at": now_local(),
    }


def _mark_used(context: Context, table: str, fields: list[str]) -> None:
    if table and table not in context["used_tables"]:
        context["used_tables"].append(table)
    for field in fields:
        if field and field not in context["used_fields"]:
            context["used_fields"].append(field)


def _room_status_distribution(room_status_result: Context | None) -> dict[str, int]:
    payload = _payload(room_status_result)
    rows = payload.get("rooms") or payload.get("rows") or payload.get("items") or []
    counter: Counter[str] = Counter()
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                status = str(row.get("room_status") or "unknown").strip() or "unknown"
                counter[status] += 1
    return dict(counter)


def _realtime_room_status_counts(room_status_result: Context | None) -> dict[str, int]:
    payload = _payload(room_status_result)
    rows = payload.get("rooms") or payload.get("rows") or payload.get("items") or []
    if not isinstance(rows, list):
        return {}
    unique_rooms: dict[Any, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        room_key = row.get("room_no") or row.get("room_id") or row.get("room_name") or index
        unique_rooms[room_key] = row
    if not unique_rooms:
        return {}
    occupied = 0
    available = 0
    for row in unique_rooms.values():
        status = str(row.get("room_status") or row.get("status") or "").strip().lower()
        if status in _OCCUPIED_ROOM_STATUS:
            occupied += 1
        elif status in _AVAILABLE_ROOM_STATUS:
            available += 1
    return {
        "total_rooms": len(unique_rooms),
        "sold_rooms": occupied,
        "remaining_rooms": available,
        "physical_total_rooms": len(unique_rooms),
        "physical_occupied_rooms": occupied,
        "physical_available_rooms": available,
    }


def build_operating_snapshot_context(
    daily_result: Context | None,
    *,
    room_status_result: Context | None = None,
    revenue_result: Context | None = None,
) -> Context:
    daily = _payload(daily_result)
    revenue = _payload(revenue_result)
    context = _base_context("operating_snapshot_context", status="partial", capability_level="derived")
    context["data_business_date"] = daily.get("data_business_date") or daily.get("business_date")
    context["data_snapshot_time"] = daily.get("data_snapshot_time") or daily.get("snapshot_time")
    context["freshness_status"] = daily.get("freshness_status")
    context["business_status"] = daily.get("business_status")

    room_count = _first_num(daily, "total_rooms", "room_count")
    remaining_rooms = _first_num(daily, "available_rooms", "remaining_rooms")
    overbooking_rooms = max(_first_num(daily, "overbooking_rooms", "overbooked_rooms") or 0, 0)
    explicit_committed_sold = _first_num(daily, "committed_sold_rooms")
    legacy_sold_rooms = _first_num(daily, "sold_rooms")
    physical_occupied_rooms = _first_num(daily, "physical_occupied_rooms", "occupied_rooms")
    physical_total_rooms = _first_num(daily, "physical_total_rooms")
    room_revenue = _first_num(daily, "room_revenue")
    if room_revenue is None:
        room_revenue = _first_num(revenue, "room_revenue", "room_fee")
    room_nights = _first_num(daily, "room_nights")
    if room_nights is None:
        room_nights = _first_num(revenue, "room_nights")

    base_committed_sold = None
    if room_count is not None and remaining_rooms is not None:
        base_committed_sold = max(room_count - remaining_rooms, 0)
    committed_sold_rooms = explicit_committed_sold
    committed_sold_source = "daily.committed_sold_rooms" if committed_sold_rooms is not None else None
    if committed_sold_rooms is None and base_committed_sold is not None:
        committed_sold_rooms = base_committed_sold + overbooking_rooms
        committed_sold_source = "forecast_inventory_formula"
        context["derived_fields"].extend(["base_committed_sold_rooms", "committed_sold_rooms"])
    if committed_sold_rooms is None and legacy_sold_rooms is not None:
        committed_sold_rooms = legacy_sold_rooms
        committed_sold_source = "legacy.sold_rooms"
        context["risk_flags"].append("legacy_sold_rooms_used_without_forecast_inventory")

    if room_count is None and committed_sold_rooms is not None and remaining_rooms is not None:
        base_committed_sold = max(committed_sold_rooms - overbooking_rooms, 0)
        room_count = base_committed_sold + remaining_rooms
        context["derived_fields"].append("total_rooms")
    if remaining_rooms is None and room_count is not None and committed_sold_rooms is not None:
        base_committed_sold = max(committed_sold_rooms - overbooking_rooms, 0)
        remaining_rooms = max(room_count - base_committed_sold, 0)
        context["derived_fields"].append("remaining_rooms")
    if base_committed_sold is None and room_count is not None and remaining_rooms is not None:
        base_committed_sold = max(room_count - remaining_rooms, 0)
    if explicit_committed_sold is not None and base_committed_sold is not None and explicit_committed_sold != base_committed_sold + overbooking_rooms:
        context["risk_flags"].append("committed_sold_conflicts_with_forecast_inventory")
    if legacy_sold_rooms is not None and base_committed_sold is not None and legacy_sold_rooms != base_committed_sold + overbooking_rooms:
        context["risk_flags"].append("legacy_sold_rooms_conflicts_with_forecast_inventory")

    occupancy = _ratio(daily.get("committed_occupancy_rate"))
    if occupancy is None and room_count and committed_sold_rooms is not None:
        occupancy = round(committed_sold_rooms / room_count, 4)
        context["derived_fields"].append("committed_occupancy_rate")
    physical_occupancy = _ratio(daily.get("physical_occupancy_rate"))
    if physical_occupancy is None and physical_total_rooms and physical_occupied_rooms is not None:
        physical_occupancy = round(physical_occupied_rooms / physical_total_rooms, 4)
        context["derived_fields"].append("physical_occupancy_rate")
    adr = _num(daily.get("adr"))
    if adr is None and room_revenue is not None and committed_sold_rooms:
        adr = round(room_revenue / committed_sold_rooms, 2)
        context["derived_fields"].append("adr")
    revpar = _num(daily.get("revpar"))
    if revpar is None and room_revenue is not None and room_count:
        revpar = round(room_revenue / room_count, 2)
        context["derived_fields"].append("revpar")

    distribution = _room_status_distribution(room_status_result)
    if distribution:
        context["derived_fields"].append("room_status_distribution")
        _mark_used(context, "kf11_room_status_snapshot", ["room_status", "room_type_name"])
    realtime_counts = _realtime_room_status_counts(room_status_result)
    if realtime_counts:
        physical_total_rooms = realtime_counts["physical_total_rooms"]
        physical_occupied_rooms = realtime_counts["physical_occupied_rooms"]
        physical_occupancy = round(physical_occupied_rooms / physical_total_rooms, 4) if physical_total_rooms else None
        context["derived_fields"].append("physical_room_status_snapshot")

    _mark_used(
        context,
        "jy01_hotel_statistics_daily",
        [
            field
            for field in ("room_count", "total_rooms", "available_rooms", "remaining_rooms", "overbooking_rooms", "committed_sold_rooms", "sold_rooms", "occupied_rooms", "room_revenue", "room_nights", "adr", "revpar")
            if daily.get(field) not in (None, "")
        ],
    )
    if revenue:
        _mark_used(context, "rs01_room_revenue_daily", ["room_fee", "room_nights"])

    core = {
        "total_rooms": int(room_count) if room_count is not None else None,
        "available_rooms": int(remaining_rooms) if remaining_rooms is not None else None,
        "remaining_rooms": int(remaining_rooms) if remaining_rooms is not None else None,
        "base_committed_sold_rooms": int(base_committed_sold) if base_committed_sold is not None else None,
        "overbooking_rooms": int(overbooking_rooms),
        "committed_sold_rooms": int(committed_sold_rooms) if committed_sold_rooms is not None else None,
        "committed_sold_source": committed_sold_source,
        "committed_occupancy_rate": occupancy,
        "physical_total_rooms": int(physical_total_rooms) if physical_total_rooms is not None else None,
        "physical_occupied_rooms": int(physical_occupied_rooms) if physical_occupied_rooms is not None else None,
        "physical_occupancy_rate": physical_occupancy,
        "sold_rooms": int(committed_sold_rooms) if committed_sold_rooms is not None else None,
        "occupancy_rate": occupancy,
        "adr": adr,
        "revpar": revpar,
        "room_revenue": room_revenue,
        "room_nights": room_nights,
        "room_status_distribution": distribution,
    }
    missing = [field for field in ("total_rooms", "committed_sold_rooms") if core.get(field) is None]
    context["core_metrics"] = core
    context["internal_missing_fields"] = missing
    context["commercial_sections"] = ["经营快照"] if not missing else []
    context["status"] = "ok" if not missing else "partial"
    if not context["derived_fields"]:
        context["capability_level"] = "full"
    return context


def build_progress_context(
    operating_result: Context | None,
    *,
    baseline_context: Context | None = None,
    order_result: Context | None = None,
) -> Context:
    operating = _payload(operating_result)
    metrics = operating.get("normalized_metrics") if isinstance(operating.get("normalized_metrics"), dict) else {}
    orders = _payload(order_result)
    context = _base_context("progress_context", status="partial", capability_level="derived")
    context["data_business_date"] = operating.get("data_business_date") or operating.get("business_date")
    context["data_snapshot_time"] = operating.get("data_snapshot_time") or operating.get("snapshot_time")
    context["freshness_status"] = operating.get("freshness_status")
    context["business_status"] = operating.get("business_status")

    core = operating.get("core_metrics") if isinstance(operating.get("core_metrics"), dict) else {}
    fact_contexts = [operating, core, metrics]
    actual_orders = _first_num_in_contexts([operating, metrics, orders], "orders_today", "actual_orders")
    actual_sold_rooms = _first_num_in_contexts(fact_contexts, "committed_sold_rooms")
    if actual_sold_rooms is None:
        actual_sold_rooms = _first_num_in_contexts(fact_contexts, "sold_rooms")
    actual_physical_occupied_rooms = _first_num_in_contexts(fact_contexts, "physical_occupied_rooms", "occupied_rooms")
    actual_room_nights = _first_num_in_contexts(fact_contexts, "room_nights")
    occupancy = _first_ratio(
        operating.get("committed_occupancy_rate"), core.get("committed_occupancy_rate"), metrics.get("committed_occupancy_rate"),
        operating.get("occupancy_rate"), core.get("occupancy_rate"), metrics.get("occupancy_rate"),
    )

    _mark_used(context, "jy01_hotel_statistics_daily", ["orders_today", "committed_sold_rooms", "sold_rooms", "room_nights", "committed_occupancy_rate"])
    if order_result:
        _mark_used(context, "jd01_booking_detail", ["room_count", "booking_status"])

    target = None
    if baseline_context:
        target = _num(baseline_context.get("target_room_nights") or baseline_context.get("daily_target_room_nights"))
    current_facts = {
        "actual_orders": int(actual_orders) if actual_orders is not None else None,
        "actual_sold_rooms": int(actual_sold_rooms) if actual_sold_rooms is not None else None,
        "actual_committed_sold_rooms": int(actual_sold_rooms) if actual_sold_rooms is not None else None,
        "actual_physical_occupied_rooms": int(actual_physical_occupied_rooms) if actual_physical_occupied_rooms is not None else None,
        "actual_room_nights": int(actual_room_nights) if actual_room_nights is not None else None,
        "current_occupancy_rate": occupancy,
    }
    context["current_facts"] = current_facts
    context["progress_granularity"] = "daily"
    context["commercial_sections"] = ["当前进度事实"] if any(value is not None for value in current_facts.values()) else []

    if target:
        context["target_room_nights"] = int(target)
        progress_actual = actual_sold_rooms if actual_sold_rooms is not None else actual_room_nights
        context["progress_actual_unit"] = "committed_sold_rooms" if actual_sold_rooms is not None else "room_nights"
        context["progress_gap"] = int((progress_actual or 0) - target)
        context["commercial_sections"].append("进度偏差")
        context["status"] = "ok"
    else:
        context["internal_missing_fields"].append("baseline_target_missing")
        context["risk_flags"].append("progress_deviation_hidden_without_target")
    return context


def build_promotion_roi_context(
    *,
    revenue_context: Context | None,
    activity_context: Context | None,
    cost_context: Context | None,
) -> Context:
    revenue_context = revenue_context or {}
    activity_context = activity_context or {}
    cost_context = cost_context or {}
    context = _base_context("promotion_roi_context", status="partial", capability_level="estimated")
    revenue = _num(revenue_context.get("room_revenue"))
    cost = _num(cost_context.get("ad_cost") or cost_context.get("promotion_cost"))
    active_campaigns = _num(activity_context.get("active_campaign_count"))
    if revenue is not None:
        _mark_used(context, "rs01_room_revenue_daily", ["room_fee", "room_nights"])
    if active_campaigns is not None:
        _mark_used(context, "ctrip_ota_promotion_activity/meituan_ota_promotion_activity", ["activity_status", "activity_name"])
    if cost is None:
        context["estimated_fields"].append("estimated_roi")
        context["internal_missing_fields"].append("roi_cost_missing")
        context["commercial_sections"] = ["ROI 保守测算参考"]
        context["estimated_roi"] = None if revenue is None else "cost_missing"
    else:
        context["capability_level"] = "derived"
        context["commercial_sections"] = ["ROI 测算"]
        context["estimated_roi"] = round((revenue or 0) / max(cost, 1), 4)
    return context


def build_promotion_context(
    activity_result: Context | None,
    *,
    product_detail_result: Context | None = None,
    price_mapping_result: Context | None = None,
    business_metrics_result: Context | None = None,
) -> Context:
    activity = _payload(activity_result)
    rows = _rows(activity_result)
    product_rows = _rows(product_detail_result)
    context = _base_context("promotion_context", status="data_gap", capability_level="unavailable")
    context["data_business_date"] = activity.get("data_business_date") or activity.get("business_date")
    context["data_snapshot_time"] = activity.get("data_snapshot_time") or activity.get("snapshot_time")
    context["freshness_status"] = activity.get("freshness_status")
    context["business_status"] = activity.get("business_status")
    source_result = activity_result if isinstance(activity_result, dict) else {}
    context["data_source_type"] = (
        source_result.get("data_source_type") or activity.get("data_source_type")
    )
    context["captured_at"] = source_result.get("captured_at") or activity.get("captured_at")
    if not rows and not product_rows:
        context["internal_missing_fields"].append("promotion_activity_rows_missing")
        context["commercial_visible"] = False
        return context

    active_count = 0
    status_summary: Counter[str] = Counter()
    room_types: set[str] = set()
    platforms: set[str] = set()
    for row in rows:
        status = str(row.get("activity_status") or row.get("status") or "unknown")
        status_summary[status] += 1
        if _status_is_active(status):
            active_count += 1
        room_type = row.get("room_type_name") or row.get("room_type_id")
        if room_type:
            room_types.add(str(room_type))
        platform = row.get("source_platform") or row.get("channel_source")
        if platform:
            platforms.add(str(platform))
    for row in product_rows:
        room_type = row.get("room_type_name") or row.get("room_type_id")
        if room_type:
            room_types.add(str(room_type))

    _mark_used(context, "ctrip_ota_promotion_activity/meituan_ota_promotion_activity", ["activity_status", "activity_name", "source_platform"])
    if product_rows:
        _mark_used(context, "ctrip_ota_activity_product_detail/meituan_ota_activity_product_detail", ["room_type_name", "activity_id"])
    if price_mapping_result:
        _mark_used(context, "ctrip_ota_goods_price_mapping/meituan_ota_goods_price_mapping", ["ota_sale_price", "commission_rate"])
    if business_metrics_result:
        _mark_used(context, "ctrip_ota_business_metrics/meituan_ota_business_metrics", ["exposure", "payment_conversion_rate"])

    context.update(
        {
            "status": "ok" if rows else "partial",
            "capability_level": "derived",
            "active_campaign_count": active_count,
            "campaign_status_summary": dict(status_summary),
            "campaign_room_type_count": len(room_types),
            "campaign_platforms": sorted(platforms),
            "commercial_sections": ["promotion_activity_summary"] if rows else [],
            "commercial_visible": True,
            "approval_allowed": False,
            "live_allowed": False,
        }
    )
    return context


def build_reputation_context(
    overview_result: Context | None,
    *,
    ranking_result: Context | None = None,
) -> Context:
    overview = _payload(overview_result)
    rows = _rows(overview_result)
    ranking_rows = _rows(ranking_result)
    context = _base_context("reputation_context", status="data_gap", capability_level="unavailable")
    context["data_business_date"] = overview.get("data_business_date") or overview.get("business_date")
    context["data_snapshot_time"] = overview.get("data_snapshot_time") or overview.get("snapshot_time")
    context["freshness_status"] = overview.get("freshness_status")
    context["business_status"] = overview.get("business_status")
    if not rows and not ranking_rows:
        context["internal_missing_fields"].append("review_overview_rows_missing")
        context["commercial_visible"] = False
        return context

    scores: list[float] = []
    bad_reviews = 0
    unreplied = 0
    keywords: list[str] = []
    for row in rows:
        score = _num(row.get("rating_score") or row.get("review_score") or row.get("score"))
        if score is not None:
            scores.append(score)
        bad_reviews += int(_num(row.get("bad_review_count") or row.get("negative_review_count")) or 0)
        unreplied += int(_num(row.get("unreplied_review_count") or row.get("unreplied_count")) or 0)
    for row in ranking_rows[:5]:
        keyword = row.get("keyword") or row.get("dimension_name") or row.get("ranking_keyword")
        if keyword:
            keywords.append(str(keyword))

    _mark_used(context, "ctrip_ota_review_overview/meituan_ota_review_overview", ["rating_score", "bad_review_count", "unreplied_review_count"])
    if ranking_rows:
        _mark_used(context, "ctrip_ota_review_ranking/meituan_ota_review_ranking", ["keyword", "rank"])

    sections = ["reputation_overview"]
    context.update(
        {
            "status": "ok",
            "capability_level": "derived",
            "review_score": _avg(scores),
            "negative_review_count": bad_reviews,
            "unreplied_review_count": unreplied,
            "ranking_keywords": keywords,
            "commercial_sections": sections,
            "commercial_visible": True,
            "approval_allowed": False,
            "live_allowed": False,
        }
    )
    context["risk_flags"].append("reply_strategy_only_without_review_text")
    return context


def build_competitor_context(metrics_result: Context | None, *, ranking_result: Context | None = None) -> Context:
    metrics = _payload(metrics_result)
    rows = _rows(metrics_result)
    ranking_rows = _rows(ranking_result)
    context = _base_context("competitor_context", status="data_gap", capability_level="unavailable")
    context["data_business_date"] = metrics.get("data_business_date") or metrics.get("business_date")
    context["data_snapshot_time"] = metrics.get("data_snapshot_time") or metrics.get("snapshot_time")
    context["freshness_status"] = metrics.get("freshness_status")
    context["business_status"] = metrics.get("business_status")
    if not rows and not ranking_rows:
        context["internal_missing_fields"].append("competitor_rank_signal_missing")
        context["commercial_visible"] = False
        return context

    ranks: list[float] = []
    peers: list[float] = []
    for row in rows + ranking_rows:
        rank = _num(row.get("peer_rank") or row.get("competitor_rank") or row.get("rank"))
        if rank is not None:
            ranks.append(rank)
        peer = _num(row.get("peer_average") or row.get("peer_avg") or row.get("same_level_average"))
        if peer is not None:
            peers.append(peer)
    best_rank = min(ranks) if ranks else None
    if best_rank is None:
        pressure = "unknown"
    elif best_rank <= 5:
        pressure = "medium"
    elif best_rank <= 20:
        pressure = "low"
    else:
        pressure = "high"

    _mark_used(context, "ctrip_ota_business_metrics/meituan_ota_business_metrics", ["peer_rank", "peer_average"])
    if ranking_rows:
        _mark_used(context, "ctrip_ota_review_ranking/meituan_ota_review_ranking", ["rank", "keyword"])
    context.update(
        {
            "status": "partial",
            "capability_level": "derived",
            "weak_competitor_signal": bool(ranks or peers),
            "peer_position_signal": "available" if peers else "unknown",
            "rank_pressure_signal": pressure,
            "best_peer_rank": best_rank,
            "peer_average": _avg(peers),
            "commercial_sections": ["platform_rank_pressure"] if ranks or peers else [],
            "commercial_visible": True,
            "approval_allowed": False,
            "live_allowed": False,
        }
    )
    context["risk_flags"].append("competitor_price_not_available")
    return context


def build_price_context(price_mapping_result: Context | None, *, revenue_result: Context | None = None) -> Context:
    payload = _payload(price_mapping_result)
    rows = _rows(price_mapping_result)
    if not rows and isinstance(payload.get("price_snapshots"), list):
        rows = [row for row in payload.get("price_snapshots") or [] if isinstance(row, dict)]
    context = _base_context("price_context", status="data_gap", capability_level="unavailable")
    context["data_business_date"] = payload.get("data_business_date") or payload.get("business_date")
    context["data_snapshot_time"] = payload.get("data_snapshot_time") or payload.get("snapshot_time")
    context["freshness_status"] = payload.get("freshness_status")
    context["business_status"] = payload.get("business_status")
    if not rows:
        context["internal_missing_fields"].append("ota_price_mapping_rows_missing")
        context["commercial_visible"] = False
        return context

    price_items: list[Context] = []
    incomplete_mapping = False
    for row in rows:
        room_type = str(row.get("room_type_name") or row.get("pms_room_type_name") or row.get("ota_room_type_id") or "").strip()
        product_id = str(row.get("ota_product_id") or "").strip()
        price = _num(row.get("ota_sale_price") or row.get("current_price") or row.get("room_daily_price"))
        if not room_type or not product_id:
            incomplete_mapping = True
        price_items.append(
            {
                "source_platform": row.get("source_platform") or row.get("channel_source"),
                "room_type_name": room_type or None,
                "ota_product_id_status": "present" if product_id else "missing",
                "ota_current_price": price,
                "commission_rate": _ratio(row.get("commission_rate")),
                "rate_plan_name": row.get("rate_plan_name"),
                "price_editable_flag": row.get("price_editable_flag"),
                "product_cipher_status": "present_hidden" if row.get("product_cipher") else "not_available",
            }
        )

    _mark_used(
        context,
        "ctrip_ota_goods_price_mapping/meituan_ota_goods_price_mapping",
        ["ota_product_id", "room_type_name", "ota_sale_price", "commission_rate", "price_editable_flag", "rate_plan_name"],
    )
    if revenue_result:
        _mark_used(context, "rs01_room_revenue_daily", ["room_daily_price", "room_fee", "room_nights"])
    context.update(
        {
            "status": "partial" if incomplete_mapping else "ok",
            "capability_level": "derived",
            "price_items": price_items,
            "price_item_count": len(price_items),
            "commercial_sections": ["price_mapping_summary"] if price_items else [],
            "commercial_visible": bool(price_items),
            "approval_allowed": False,
            "live_allowed": False,
        }
    )
    if incomplete_mapping:
        context["risk_flags"].append("ota_room_type_mapping_incomplete")
        context["internal_missing_fields"].append("ota_product_or_room_type_mapping_incomplete")
    return context


def build_ota_health_context(
    business_metrics_result: Context | None,
    *,
    review_overview_result: Context | None = None,
    review_ranking_result: Context | None = None,
    promotion_context: Context | None = None,
) -> Context:
    metrics_payload = _payload(business_metrics_result)
    metric_rows = _rows(business_metrics_result)
    review_rows = _rows(review_overview_result)
    ranking_rows = _rows(review_ranking_result)
    context = _base_context("ota_health_context", status="data_gap", capability_level="unavailable")
    context["data_business_date"] = metrics_payload.get("data_business_date") or metrics_payload.get("business_date")
    context["data_snapshot_time"] = metrics_payload.get("data_snapshot_time") or metrics_payload.get("snapshot_time")
    context["freshness_status"] = metrics_payload.get("freshness_status")
    context["business_status"] = metrics_payload.get("business_status")

    metrics: Context = {}
    peer_ranks: list[float] = []
    peer_averages: list[float] = []
    for row in metric_rows:
        name = str(row.get("metric_name") or row.get("metric_display_name") or "").strip().lower()
        value = _num(row.get("metric_value"))
        if name and value is not None:
            normalized = {
                "exposure": "exposure",
                "impression": "exposure",
                "曝光": "exposure",
                "views": "views",
                "view": "views",
                "浏览": "views",
                "payment_conversion_rate": "payment_conversion_rate",
                "conversion": "payment_conversion_rate",
                "转化": "payment_conversion_rate",
            }.get(name, name)
            metrics[normalized] = value
        rank = _num(row.get("competitor_rank"))
        if rank is not None:
            peer_ranks.append(rank)
        peer = _num(row.get("peer_average"))
        if peer is not None:
            peer_averages.append(peer)

    review_scores: list[float] = []
    negative_count = 0
    unreplied_count = 0
    for row in review_rows:
        score = _num(row.get("review_score") or row.get("rating_score"))
        if score is not None:
            review_scores.append(score)
        negative_count += int(_num(row.get("negative_review_count") or row.get("bad_review_count")) or 0)
        unreplied_count += int(_num(row.get("unreplied_review_count") or row.get("pending_reply_count")) or 0)

    used_any = bool(metrics or review_rows or ranking_rows or promotion_context)
    if not used_any:
        context["internal_missing_fields"].append("ota_health_inputs_missing")
        context["commercial_visible"] = False
        return context

    _mark_used(context, "ctrip_ota_business_metrics/meituan_ota_business_metrics", ["metric_name", "metric_value", "competitor_rank", "peer_average"])
    if review_rows:
        _mark_used(context, "ctrip_ota_review_overview/meituan_ota_review_overview", ["review_score", "negative_review_count", "unreplied_review_count"])
    if ranking_rows:
        _mark_used(context, "ctrip_ota_review_ranking/meituan_ota_review_ranking", ["ranking_type", "ranking_position", "rank_item_name"])
    context.update(
        {
            "status": "ok" if metrics and review_rows else "partial",
            "capability_level": "derived",
            "metrics": metrics,
            "review_score": _avg(review_scores),
            "negative_review_count": negative_count,
            "unreplied_review_count": unreplied_count,
            "best_peer_rank": min(peer_ranks) if peer_ranks else None,
            "peer_average": _avg(peer_averages),
            "active_campaign_count": (promotion_context or {}).get("active_campaign_count"),
            "commercial_sections": ["ota_health_summary"],
            "commercial_visible": True,
            "approval_allowed": False,
            "live_allowed": False,
        }
    )
    return context


def build_customer_order_context(
    order_result: Context | None,
    *,
    stayover_result: Context | None = None,
    revenue_result: Context | None = None,
) -> Context:
    payload = _payload(order_result)
    orders = payload.get("orders") or payload.get("rows") or []
    if not isinstance(orders, list):
        orders = []
    context = _base_context("customer_order_context", status="data_gap", capability_level="unavailable")
    context["data_business_date"] = payload.get("data_business_date") or payload.get("business_date")
    context["data_snapshot_time"] = payload.get("data_snapshot_time") or payload.get("snapshot_time")
    context["freshness_status"] = payload.get("freshness_status")
    context["business_status"] = payload.get("business_status")
    if not orders:
        context["internal_missing_fields"].append("order_rows_missing")
        context["commercial_visible"] = False
        return context

    seen: set[tuple[Any, ...]] = set()
    channel_counter: Counter[str] = Counter()
    room_type_counter: Counter[str] = Counter()
    price_type_counter: Counter[str] = Counter()
    total_fee = 0.0
    total_nights = 0.0
    for index, order in enumerate([row for row in orders if isinstance(row, dict)]):
        price_detail = order.get("price_detail") if isinstance(order.get("price_detail"), dict) else {}
        key = (
            order.get("order_id") or f"row-{index}",
            order.get("room_type_name"),
            order.get("checkin_time"),
            price_detail.get("room_fee") or order.get("room_fee"),
        )
        if key in seen:
            continue
        seen.add(key)
        channel_counter[str(order.get("customer_source") or order.get("guest_source") or order.get("channel_source") or "unknown")] += 1
        room_type_counter[str(order.get("room_type_name") or order.get("room_type_id") or "unknown")] += 1
        price_type_counter[str(order.get("price_type") or "unknown")] += 1
        nights = _num(order.get("room_nights")) or 1
        fee = _num(price_detail.get("room_fee") or order.get("room_fee")) or 0
        total_nights += nights
        total_fee += fee

    _mark_used(context, "jd01_booking_detail", ["guest_source", "room_type_name", "price_type", "room_count"])
    if stayover_result:
        _mark_used(context, "jd04_inhouse_extension", ["channel_source", "guest_source", "checkin_type", "room_type_name"])
    if revenue_result:
        _mark_used(context, "rs01_room_revenue_daily", ["customer_source", "room_type_name", "price_type", "stay_type", "room_fee", "room_nights"])
    context.update(
        {
            "status": "ok" if seen else "data_gap",
            "capability_level": "derived",
            "unique_order_count": len(seen),
            "overall_adr": round(total_fee / (total_nights or len(seen) or 1), 2) if total_fee else 0,
            "channel_source_distribution": dict(channel_counter),
            "room_type_distribution": dict(room_type_counter),
            "price_type_distribution": dict(price_type_counter),
            "privacy_policy": "aggregate_only_no_row_level_orders",
            "row_level_orders_included": False,
            "commercial_sections": ["customer_order_aggregate"] if seen else [],
            "commercial_visible": bool(seen),
            "approval_allowed": False,
            "live_allowed": False,
        }
    )
    return context


def build_sales_baseline_context(
    daily_result: Context | None,
    *,
    monthly_result: Context | None = None,
    revenue_result: Context | None = None,
    calendar_context: Context | None = None,
) -> Context:
    daily = _payload(daily_result)
    monthly = _payload(monthly_result)
    context = _base_context("sales_baseline_context", status="partial", capability_level="derived")
    context["data_business_date"] = daily.get("data_business_date") or daily.get("business_date")
    context["data_snapshot_time"] = daily.get("data_snapshot_time") or daily.get("snapshot_time")
    context["freshness_status"] = daily.get("freshness_status")
    context["business_status"] = daily.get("business_status")

    sold_rooms = _num(daily.get("sold_rooms"))
    orders_today = _num(daily.get("orders_today"))
    monthly_room_nights = _num(monthly.get("room_nights"))
    monthly_average = round(monthly_room_nights / 30, 2) if monthly_room_nights is not None else None
    target = _num(daily.get("daily_target_room_nights") or daily.get("target_room_nights"))
    if target is None:
        target = monthly_average
        if target is not None:
            context["derived_fields"].append("monthly_average_room_nights")

    _mark_used(context, "jy01_hotel_statistics_daily", ["sold_rooms", "orders_today", "occupancy_rate"])
    if monthly_result:
        _mark_used(context, "jy03_hotel_statistics_month", ["room_nights", "room_count", "occupancy_rate"])
    if revenue_result:
        _mark_used(context, "rs01_room_revenue_daily", ["room_nights", "room_fee"])
    if calendar_context:
        _mark_used(context, "calendar_days", ["date_type", "holiday_name", "source_quality"])

    context.update(
        {
            "current_sold_rooms": int(sold_rooms) if sold_rooms is not None else None,
            "current_orders": int(orders_today) if orders_today is not None else None,
            "daily_target_room_nights": int(target) if target is not None else None,
            "target_room_nights": int(target) if target is not None else None,
            "monthly_average_room_nights": monthly_average,
            "progress_granularity": "daily",
            "hourly_target_curve": [],
            "progress_checkpoints": [],
            "commercial_sections": ["sales_baseline_daily_reference"] if target is not None or sold_rooms is not None else [],
            "commercial_visible": target is not None or sold_rooms is not None,
            "approval_allowed": False,
            "live_allowed": False,
        }
    )
    if target is None:
        context["internal_missing_fields"].append("baseline_target_missing")
        context["risk_flags"].append("hourly_curve_hidden_without_hourly_data")
    else:
        context["status"] = "ok" if daily.get("freshness_status") == "fresh" else "partial"
    return context

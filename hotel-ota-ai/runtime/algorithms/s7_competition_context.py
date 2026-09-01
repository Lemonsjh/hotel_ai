from __future__ import annotations

from collections import defaultdict
from typing import Any


def _payload(result: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {}
    payload = result.get("payload")
    return payload if isinstance(payload, dict) else result


def _rows(result: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = _payload(result).get("rows") or _payload(result).get("price_snapshots") or []
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _platform(row: dict[str, Any]) -> str:
    raw = str(row.get("channel") or row.get("channel_source") or row.get("table_key") or row.get("source_table_key") or row.get("source_platform") or "").lower()
    if "meituan" in raw or "美团" in raw:
        return "meituan"
    if "ctrip" in raw or "携程" in raw:
        return "ctrip"
    return "unknown"


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _rank(value: Any) -> tuple[int | None, int | None]:
    raw = str(value or "").strip()
    if not raw:
        return None, None
    tokens = raw.replace("/", " ").split()
    try:
        position = int(float(tokens[0]))
        count = int(float(tokens[1])) if len(tokens) > 1 else None
        return position, count
    except (TypeError, ValueError):
        return None, None


def _latest_meta(results: list[dict[str, Any]]) -> dict[str, Any]:
    payloads = [_payload(result) for result in results]
    def latest(key: str) -> Any:
        values = [item.get(key) for item in payloads if item.get(key) not in (None, "")]
        return max(values, key=lambda value: str(value)) if values else None

    return {
        "data_business_date": latest("data_business_date"),
        "data_snapshot_time": latest("data_snapshot_time"),
        "freshness_status": next((item.get("freshness_status") for item in payloads if item.get("freshness_status")), "not_available"),
        "business_status": next((item.get("business_status") for item in payloads if item.get("business_status")), "unknown"),
    }


def _product_state(row: dict[str, Any]) -> str:
    if not row.get("ota_product_id"):
        return "not_observed"
    if str(row.get("room_type_id") or "").strip().lower() in {"", "unknown"}:
        return "mapping_missing"
    if _number(row.get("current_price") or row.get("ota_sale_price")) is None:
        return "not_observed"
    editable = row.get("price_editable_flag")
    if str(editable).strip().lower() in {"0", "false", "no", "n"}:
        return "not_sellable"
    return "sellable"


def _own_products(rows: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        if _platform(row) != platform:
            continue
        price = _number(row.get("current_price") or row.get("ota_sale_price"))
        items.append(
            {
                "comparison_level": "own_only",
                "room_type_id": row.get("room_type_id"),
                "ota_product_id": row.get("ota_product_id"),
                "ota_product_name": row.get("ota_product_name"),
                "price": price,
                "price_business_date": row.get("business_date"),
                "snapshot_time": row.get("snapshot_time") or row.get("data_snapshot_time"),
                "product_state": _product_state(row),
                "quality_flags": list(row.get("row_risk_flags") or row.get("risk_flags") or []),
            }
        )
    return items


def _peer_items(rows: list[dict[str, Any]], platform: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple[str, Any, Any, Any, Any, Any]] = set()
    for row in rows:
        if _platform(row) != platform:
            continue
        metric_code = row.get("metric_code") or row.get("metric_name")
        unit = row.get("metric_unit")
        own = _number(row.get("hotel_value") if row.get("hotel_value") is not None else row.get("metric_value"))
        peer = _number(row.get("competitor_avg") if row.get("competitor_avg") is not None else row.get("peer_average"))
        # Current-day values can precede platform peer aggregation. Never join
        # them to a previous business date or reporting window.
        if own is None or peer is None:
            continue
        scope_key = (
            str(metric_code or "").upper(), unit, row.get("business_date"),
            row.get("period_start_date"), row.get("period_end_date"), row.get("snapshot_time"),
        )
        if scope_key in seen:
            continue
        seen.add(scope_key)
        position, peer_count = _rank(row.get("competitor_rank"))
        item = {
            "comparison_level": "peer_aggregate",
            "metric_code": metric_code,
            "metric_name": row.get("metric_name") or metric_code,
            "metric_unit": unit,
            "own_value": own,
            "peer_average": peer,
            "peer_index": round(own / peer, 4) if own is not None and peer not in (None, 0) else None,
            "rank_position": position,
            "peer_count": peer_count or _number(row.get("competition_circle_hotel_count")),
            "business_date": row.get("business_date"),
            "period_start_date": row.get("period_start_date"),
            "period_end_date": row.get("period_end_date"),
            "snapshot_time": row.get("snapshot_time"),
            "quality_flags": [],
        }
        if platform == "meituan" and str(metric_code or "").upper() == "DAY_ROOM_LOWEST_PRICE_AVG":
            item["lead_price_index"] = item["peer_index"]
            item["lead_price_gap_pct"] = round((own - peer) / peer, 4) if own is not None and peer not in (None, 0) else None
        items.append(item)
    return items


def _loss_context(rows: list[dict[str, Any]], platform: str) -> dict[str, Any] | None:
    selected = [row for row in rows if _platform(row) == platform]
    if not selected:
        return None
    values = lambda key: [value for value in (_number(row.get(key)) for row in selected) if value is not None]
    low_prices = values("competitor_lowest_price")
    names = {str(row.get("competitor_hotel_name")) for row in selected if row.get("competitor_hotel_name")}
    def total_or_row_sum(total_key: str, row_key: str) -> float:
        row_values = values(row_key)
        if row_values:
            return sum(row_values)
        # Platform exports commonly repeat window totals on every competitor row.
        # The total is a window fact, not a per-competitor value, so never sum it.
        return max(values(total_key), default=0)

    return {
        "comparison_level": "loss_context",
        "period_start_date": next((row.get("period_start_date") for row in selected if row.get("period_start_date")), None),
        "period_end_date": next((row.get("period_end_date") for row in selected if row.get("period_end_date")), None),
        "loss_order_count": total_or_row_sum("total_loss_order_count", "competitor_loss_order_count"),
        "loss_room_night_count": max(values("total_loss_room_night_count"), default=0),
        "loss_order_amount": round(max(values("total_loss_order_amount"), default=0), 2),
        "competitor_count": len(names),
        "competitor_lowest_price_range": [min(low_prices), max(low_prices)] if low_prices else None,
        "snapshot_time": next((row.get("snapshot_time") for row in selected if row.get("snapshot_time")), None),
        "quality_flags": ["loss_context_not_real_time_product_price", "loss_orders_not_proven_price_causality"],
    }


def _meituan_competition_circles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate Meituan's monthly loss background by source competition circle.

    Window totals are repeated on each competitor row by the source, so this
    view deliberately uses only competitor-level counts and amounts.
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if _platform(row) != "meituan":
            continue
        source_name = str(row.get("competitor_circle_name") or "").strip()
        groups[source_name].append(row)

    circles: list[dict[str, Any]] = []
    for source_name, items in groups.items():
        values = lambda key: [value for value in (_number(row.get(key)) for row in items) if value is not None]
        loss_orders = sum(values("competitor_loss_order_count"))
        loss_amount = sum(values("competitor_loss_amount"))
        low_prices = values("competitor_lowest_price")
        scores = values("competitor_score")
        distances = values("competitor_distance_m")
        poi_ids = {str(row.get("competitor_poi_id")) for row in items if row.get("competitor_poi_id") not in (None, "")}
        names = {str(row.get("competitor_hotel_name")) for row in items if row.get("competitor_hotel_name")}
        unclassified = not source_name or source_name == "无合适商圈"
        circles.append(
            {
                "comparison_level": "loss_context",
                "source_table": "meituan_ota_order_loss_monthly",
                "source_circle_name": source_name or None,
                "competition_circle_name": "来源未归类" if unclassified else source_name,
                "circle_classification": "source_unclassified" if unclassified else "source_circle",
                "competitor_count": len(poi_ids) if poi_ids else len(names),
                "loss_order_count": loss_orders,
                "loss_order_amount": round(loss_amount, 2),
                "competitor_lowest_price_range": [min(low_prices), max(low_prices)] if low_prices else None,
                "competitor_score_average": round(sum(scores) / len(scores), 2) if scores else None,
                "competitor_distance_average_m": round(sum(distances) / len(distances), 1) if distances else None,
                "period_start_date": next((row.get("period_start_date") for row in items if row.get("period_start_date")), None),
                "period_end_date": next((row.get("period_end_date") for row in items if row.get("period_end_date")), None),
                "snapshot_time": next((row.get("snapshot_time") for row in items if row.get("snapshot_time")), None),
                "quality_flags": ["loss_context_not_real_time_product_price", "loss_orders_not_proven_price_causality"],
            }
        )
    return sorted(circles, key=lambda item: (item["loss_order_count"], item["loss_order_amount"]), reverse=True)


def _activity_context(rows: list[dict[str, Any]], detail_rows: list[dict[str, Any]], platform: str) -> dict[str, Any]:
    activities = [row for row in rows if _platform(row) == platform]
    details = [row for row in detail_rows if _platform(row) == platform]
    mapped = [row for row in details if row.get("room_type_id")]
    return {
        "comparison_level": "own_only",
        "activity_count": len({str(row.get("activity_id") or row.get("activity_name")) for row in activities if row.get("activity_id") or row.get("activity_name")}),
        "activity_product_count": len(details),
        "canonical_room_type_count": len({str(row["room_type_id"]) for row in mapped}),
        "mapping_missing_count": len(details) - len(mapped),
        "remaining_inventory_source_values": [row.get("remaining_inventory") for row in details if row.get("remaining_inventory") is not None][:10],
        "quality_flags": ["remaining_inventory_source_semantics_unconfirmed"] if any(row.get("remaining_inventory") is not None for row in details) else [],
    }


def build_s7_competition_context(*, price_result: dict[str, Any], metrics_result: dict[str, Any], competition_result: dict[str, Any], loss_result: dict[str, Any], activity_result: dict[str, Any], activity_detail_result: dict[str, Any], rights_result: dict[str, Any], psi_result: dict[str, Any], ranking_result: dict[str, Any]) -> dict[str, Any]:
    all_results = [price_result, metrics_result, competition_result, loss_result, activity_result, activity_detail_result, rights_result, psi_result, ranking_result]
    prices = _rows(price_result)
    metrics = _rows(metrics_result) + _rows(competition_result)
    losses = _rows(loss_result)
    activities = _rows(activity_result)
    details = _rows(activity_detail_result)
    rights = _rows(rights_result)
    psi = _rows(psi_result)
    rankings = _rows(ranking_result)
    platforms = [platform for platform in ("meituan", "ctrip") if any(_platform(row) == platform for row in prices + metrics + losses + activities + details + rights + psi + rankings)]
    by_platform: dict[str, Any] = {}
    for platform in platforms:
        own = _own_products(prices, platform)
        peer = _peer_items(metrics, platform)
        ranking_items = [row for row in rankings if _platform(row) == platform]
        by_platform[platform] = {
            "own_products": own,
            "peer_aggregate": peer,
            "loss_context": _loss_context(losses, platform),
            "competition_circle_context": {
                "comparison_level": "loss_context",
                "source_table": "meituan_ota_order_loss_monthly",
                "circles": _meituan_competition_circles(losses),
            } if platform == "meituan" else None,
            "activity_context": _activity_context(activities, details, platform),
            "joined_rights": [{"comparison_level": "own_only", "right_name": row.get("right_name") or row.get("joined_right_name"), "snapshot_time": row.get("snapshot_time")} for row in rights if _platform(row) == platform],
            "psi_metrics": [{"comparison_level": "own_only", "metric_code": row.get("metric_code") or ("PSI_TOTAL_SCORE" if row.get("psi_total_score") is not None else None), "metric_value": row.get("metric_value") or row.get("psi_score") or row.get("psi_total_score"), "metric_unit": row.get("metric_unit") or "score", "snapshot_time": row.get("snapshot_time")} for row in psi if _platform(row) == platform],
            "review_rankings": [
                {
                    "comparison_level": "own_only",
                    "ranking_type": row.get("ranking_type"),
                    "rank_position": _rank(row.get("ranking_position"))[0],
                    "peer_count": _rank(row.get("ranking_position"))[1],
                    "rank_item_name": row.get("rank_item_name"),
                    "rank_item_value": row.get("rank_item_value"),
                    "snapshot_time": row.get("snapshot_time"),
                }
                for row in ranking_items
            ],
            "exact_product_comparisons": [],
            "quality_flags": ["exact_product_competitor_price_unavailable"],
        }
    meta = _latest_meta(all_results)
    quality_flags = ["exact_product_competitor_price_unavailable"]
    missing = [name for name, result in {"price": price_result, "metrics": metrics_result, "loss": loss_result}.items() if not _rows(result)]
    if missing:
        quality_flags.append("source_missing:" + ",".join(missing))
    return {
        "status": "ok" if by_platform and not missing else "partial" if by_platform else "data_gap",
        "comparison_contract_version": "s7_four_level_v1",
        "comparison_levels": ["exact_product", "peer_aggregate", "loss_context", "own_only"],
        "platforms": by_platform,
        "exact_product_available": False,
        "quality_flags": quality_flags,
        "used_tables": [
            "ctrip_ota_goods_price_mapping/meituan_ota_goods_price_mapping",
            "ctrip_ota_business_metrics/meituan_ota_business_metrics",
            "ctrip_ota_competition_metrics_30d",
            "ctrip_ota_order_loss_monthly/meituan_ota_order_loss_monthly",
            "ctrip_ota_promotion_activity/meituan_ota_promotion_activity",
            "ctrip_ota_activity_product_detail/meituan_ota_activity_product_detail",
            "ctrip_ota_review_ranking/meituan_ota_review_ranking",
        ],
        **meta,
        "direct_price_trigger_allowed": False,
        "live_allowed": False,
    }

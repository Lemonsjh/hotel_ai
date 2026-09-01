from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
        return None if number != number else number
    except (TypeError, ValueError):
        return None


def _ratio(value: Any) -> float | None:
    number = _num(value)
    if number is None:
        return None
    return number / 100 if number > 1 else number


def _date(value: Any) -> str:
    return str(value or "")[:10]


def _month(value: Any) -> str:
    day = _date(value)
    return day[:7] if len(day) >= 7 else "unknown"


def _safe_div(a: float | None, b: float | None) -> float | None:
    if a is None or b in (None, 0):
        return None
    return a / b


def _round(value: float | None, digits: int = 2) -> float | None:
    return round(value, digits) if value is not None else None


def _mom(current: float | None, previous: float | None) -> float | None:
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / previous


def _monthly_from_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trend = []
    for row in sorted(rows, key=lambda item: str(item.get("period_month") or "")):
        month = row.get("period_month")
        if not month:
            continue
        rc = _num(row.get("room_count"))
        rn = _num(row.get("room_nights"))
        rr = _num(row.get("room_revenue"))
        occ = _ratio(row.get("occupancy_rate"))
        adr = _num(row.get("adr")) or _safe_div(rr, rn)
        revpar = _num(row.get("revpar")) or _safe_div(rr, rc)
        trend.append({
            "month": str(month),
            "adr": _round(adr),
            "occupancy_rate": _round(occ if occ is not None else _safe_div(rn, rc), 4),
            "revpar": _round(revpar),
            "room_revenue": _round(rr),
            "room_count": _round(rc),
            "room_nights": _round(rn),
        })
    return trend


def operating_metrics(rows: list[dict[str, Any]], monthly_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if not rows:
        return {"status": "data_gap", "reason": "hotel_daily_missing"}
    ordered = sorted(rows, key=lambda item: _date(item.get("business_date")))
    latest = ordered[-1]
    total_room_count = 0.0
    total_room_nights = 0.0
    total_revenue = 0.0
    revenue_seen = False
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: {"room_count": 0.0, "room_nights": 0.0, "room_revenue": 0.0})
    daily_series = []
    for row in ordered:
        room_count = _num(row.get("room_count")) or 0.0
        room_nights = _num(row.get("room_nights")) or _num(row.get("sold_rooms")) or 0.0
        revenue = _num(row.get("room_revenue"))
        adr_row = _num(row.get("adr"))
        revpar_row = _num(row.get("revpar"))
        if revenue is None and adr_row is not None and room_nights:
            revenue = adr_row * room_nights
        if revenue is None and revpar_row is not None and room_count:
            revenue = revpar_row * room_count
        if revenue is None:
            revenue = 0.0
        else:
            revenue_seen = True
        total_room_count += room_count
        total_room_nights += room_nights
        total_revenue += revenue
        key = _month(row.get("business_date"))
        monthly[key]["room_count"] += room_count
        monthly[key]["room_nights"] += room_nights
        monthly[key]["room_revenue"] += revenue
        occ = _ratio(row.get("occupancy_rate"))
        if occ is None:
            occ = _safe_div(room_nights, room_count)
        adr = adr_row if adr_row is not None else _safe_div(revenue, room_nights)
        revpar = revpar_row if revpar_row is not None else _safe_div(revenue, room_count)
        daily_series.append({
            "business_date": _date(row.get("business_date")),
            "room_count": room_count or None,
            "room_nights": room_nights or None,
            "room_revenue": _round(revenue) if revenue_seen else None,
            "occupancy_rate": _round(occ, 4),
            "adr": _round(adr),
            "revpar": _round(revpar),
        })
    occupancy = _safe_div(total_room_nights, total_room_count)
    adr = _safe_div(total_revenue, total_room_nights) if revenue_seen else None
    revpar = _safe_div(total_revenue, total_room_count) if revenue_seen else None
    monthly_trend = _monthly_from_rows(monthly_rows or [])
    if not monthly_trend:
        for month in sorted(monthly):
            item = monthly[month]
            rc = item["room_count"]
            rn = item["room_nights"]
            rr = item["room_revenue"]
            monthly_trend.append({
                "month": month,
                "adr": _round(_safe_div(rr, rn)),
                "occupancy_rate": _round(_safe_div(rn, rc), 4),
                "revpar": _round(_safe_div(rr, rc)),
                "room_revenue": _round(rr),
                "room_count": _round(rc),
                "room_nights": _round(rn),
            })
    for i, item in enumerate(monthly_trend):
        prev = monthly_trend[i - 1] if i else {}
        item["revpar_mom"] = _round(_mom(_num(item.get("revpar")), _num(prev.get("revpar"))), 4)
        item["revenue_mom"] = _round(_mom(_num(item.get("room_revenue")), _num(prev.get("room_revenue"))), 4)
        item["occupancy_mom"] = _round(_mom(_num(item.get("occupancy_rate")), _num(prev.get("occupancy_rate"))), 4)
    history_days = len({x.get("business_date") for x in daily_series if x.get("business_date")}) or len(ordered)
    latest_daily = daily_series[-1] if daily_series else {}
    return {
        "status": "ok",
        "latest_business_date": latest.get("business_date"),
        "period_start": _date(ordered[0].get("business_date")),
        "period_end": _date(ordered[-1].get("business_date")),
        "room_count": _round(total_room_count),
        "room_nights": _round(total_room_nights),
        "room_revenue": _round(total_revenue) if revenue_seen else None,
        "occupancy_rate": _round(occupancy, 4),
        "adr": _round(adr),
        "revpar": _round(revpar),
        "history_days": history_days,
        "avg_daily_revenue": _round(_safe_div(total_revenue if revenue_seen else None, history_days)),
        "avg_daily_room_nights": _round(_safe_div(total_room_nights, history_days)),
        "avg_daily_available_room_nights": _round(_safe_div(total_room_count, history_days)),
        "latest_daily": latest_daily,
        "daily_series": daily_series[-62:],
        "monthly_trend": monthly_trend[-12:],
    }


def funnel_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "data_gap", "reason": "ota_funnel_missing"}
    exposure = sum(_num(row.get("exposure")) or 0 for row in rows)
    views = sum(_num(row.get("views")) or _num(row.get("visitors")) or 0 for row in rows)
    paid_orders = sum(_num(row.get("paid_orders")) or 0 for row in rows)
    sales_revenue = sum(_num(row.get("sales_revenue")) or 0 for row in rows)
    sold_room_nights = sum(_num(row.get("sold_room_nights")) or 0 for row in rows)
    derived_conversion = _safe_div(paid_orders, views) if views > 0 and paid_orders > 0 else None
    rates = [_ratio(row.get("payment_conversion_rate")) for row in rows if _ratio(row.get("payment_conversion_rate")) is not None]
    conversion = derived_conversion if derived_conversion is not None else (sum(rates) / len(rates) if rates else None)
    exposure_view_rates = [_ratio(row.get("exposure_to_view_rate")) for row in rows if _ratio(row.get("exposure_to_view_rate")) is not None]
    exposure_to_view_rate = _safe_div(views, exposure) if exposure and views else (sum(exposure_view_rates) / len(exposure_view_rates) if exposure_view_rates else None)
    peer_rates = [_ratio(row.get("peer_avg_conversion_rate")) for row in rows if _ratio(row.get("peer_avg_conversion_rate")) is not None]
    peer_avg = sum(peer_rates) / len(peer_rates) if peer_rates else None
    ranks = [_num(row.get("peer_rank")) for row in rows if _num(row.get("peer_rank")) is not None]
    by_platform: dict[str, dict[str, float]] = defaultdict(lambda: {"exposure": 0.0, "views": 0.0, "paid_orders": 0.0, "sales_revenue": 0.0, "sold_room_nights": 0.0})
    for row in rows:
        platform = str(row.get("platform") or "unknown")
        by_platform[platform]["exposure"] += _num(row.get("exposure")) or 0.0
        by_platform[platform]["views"] += _num(row.get("views")) or _num(row.get("visitors")) or 0.0
        by_platform[platform]["paid_orders"] += _num(row.get("paid_orders")) or 0.0
        by_platform[platform]["sales_revenue"] += _num(row.get("sales_revenue")) or 0.0
        by_platform[platform]["sold_room_nights"] += _num(row.get("sold_room_nights")) or 0.0
    platform_rows = []
    for platform, item in sorted(by_platform.items()):
        pv = item["views"]
        pe = item["exposure"]
        po = item["paid_orders"]
        rev = item["sales_revenue"]
        platform_rows.append({
            "platform": platform,
            "exposure": _round(pe),
            "views": _round(pv),
            "paid_orders": _round(po),
            "sales_revenue": _round(rev),
            "sold_room_nights": _round(item["sold_room_nights"]),
            "exposure_share": _round(_safe_div(pe, exposure), 4),
            "view_share": _round(_safe_div(pv, views), 4),
            "order_share": _round(_safe_div(po, paid_orders), 4),
            "revenue_share": _round(_safe_div(rev, sales_revenue), 4),
            "exposure_to_view_rate": _round(_safe_div(pv, pe), 4),
            "payment_conversion_rate": _round(_safe_div(po, pv), 4),
            "avg_order_value": _round(_safe_div(rev, po)),
            "revenue_per_view": _round(_safe_div(rev, pv), 4),
        })
    return {
        "status": "ok",
        "exposure": exposure or None,
        "views": views or None,
        "paid_orders": paid_orders or None,
        "sales_revenue": _round(sales_revenue) if sales_revenue else None,
        "sold_room_nights": sold_room_nights or None,
        "exposure_to_view_rate": _round(exposure_to_view_rate, 4),
        "payment_conversion_rate": _round(conversion, 4),
        "peer_avg_conversion_rate": _round(peer_avg, 4),
        "conversion_vs_peer_gap": _round(conversion - peer_avg, 4) if conversion is not None and peer_avg is not None else None,
        "conversion_vs_peer_ratio": _round(_safe_div(conversion, peer_avg), 4),
        "avg_order_value": _round(_safe_div(sales_revenue, paid_orders)),
        "revenue_per_view": _round(_safe_div(sales_revenue, views), 4),
        "best_peer_rank": min(ranks) if ranks else None,
        "by_platform": platform_rows,
    }


def price_ladder_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "data_gap", "reason": "products_missing"}
    prices = []
    jump_risks = []
    room_types = set()
    by_platform_raw: dict[str, dict[str, Any]] = defaultdict(lambda: {"prices": [], "room_types": set(), "product_count": 0, "group_buy_count": 0, "hour_room_count": 0})
    for row in rows:
        platform = str(row.get("platform") or "unknown")
        listed = _num(row.get("listed_price"))
        final = _num(row.get("final_price")) or _num(row.get("activity_price")) or listed
        is_group = bool(row.get("is_group_buy") or str(row.get("product_type") or "").lower() in {"super_deal", "group_buy", "团购"})
        is_hour = bool(row.get("is_hour_room") or "钟点" in str(row.get("product_name") or ""))
        by_platform_raw[platform]["product_count"] += 1
        if final:
            prices.append(final)
            by_platform_raw[platform]["prices"].append(final)
        if listed and final and final / listed < 0.65:
            risk = {"platform": platform, "product_name": row.get("product_name"), "listed_price": listed, "final_price": final, "ratio": _round(final / listed, 4)}
            jump_risks.append(risk)
        if row.get("room_type_name"):
            room_types.add(str(row.get("room_type_name")))
            by_platform_raw[platform]["room_types"].add(str(row.get("room_type_name")))
        if is_group:
            by_platform_raw[platform]["group_buy_count"] += 1
        if is_hour:
            by_platform_raw[platform]["hour_room_count"] += 1
    group_buy_count = sum(v["group_buy_count"] for v in by_platform_raw.values())
    hour_room_count = sum(v["hour_room_count"] for v in by_platform_raw.values())
    by_platform = {}
    for platform, item in sorted(by_platform_raw.items()):
        p = item["prices"]
        by_platform[platform] = {
            "product_count": item["product_count"],
            "room_type_count": len(item["room_types"]),
            "min_price": min(p) if p else None,
            "max_price": max(p) if p else None,
            "price_span": max(p) - min(p) if len(p) >= 2 else None,
            "group_buy_count": item["group_buy_count"],
            "hour_room_count": item["hour_room_count"],
        }
    return {
        "status": "ok",
        "product_count": len(rows),
        "room_type_count": len(room_types),
        "min_price": min(prices) if prices else None,
        "max_price": max(prices) if prices else None,
        "price_span": max(prices) - min(prices) if len(prices) >= 2 else None,
        "group_buy_count": group_buy_count,
        "hour_room_count": hour_room_count,
        "price_jump_risks": jump_risks,
        "by_platform": by_platform,
    }


def promotion_metrics(rows: list[dict[str, Any]], product_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows and not product_rows:
        return {"status": "data_gap", "reason": "promotion_tables_empty"}
    active_rows = [row for row in rows if str(row.get("activity_status") or "") in {"进行中", "active", "ACTIVE", "有效"}]
    names = [str(row.get("activity_name")) for row in rows if row.get("activity_name")]
    room_type_total = sum(_num(row.get("activity_room_type_count")) or 0 for row in rows)
    activity_products = len(product_rows)
    by_platform = defaultdict(lambda: {"activity_count": 0, "active_activity_count": 0, "activity_product_count": 0})
    for row in rows:
        platform = str(row.get("platform") or "unknown")
        by_platform[platform]["activity_count"] += 1
        if row in active_rows:
            by_platform[platform]["active_activity_count"] += 1
    for row in product_rows:
        platform = str(row.get("platform") or "unknown")
        by_platform[platform]["activity_product_count"] += 1
    has_discount_rule = any("折" in str(row.get("activity_rule_labels") or "") or "减" in str(row.get("activity_rule_labels") or "") for row in rows)
    return {
        "status": "partial",
        "activity_count": len(rows),
        "active_activity_count": len(active_rows),
        "activity_product_count": activity_products,
        "activity_room_type_count_total": int(room_type_total) if room_type_total else None,
        "activity_names": names[:20],
        "has_discount_rule": has_discount_rule,
        "has_cost_roi_fields": False,
        "missing_roi_fields": ["promo_cost", "promo_clicks", "promo_orders", "promo_revenue", "promo_roi"],
        "by_platform": dict(by_platform),
    }


def reputation_metrics(rows: list[dict[str, Any]], overview_rows: list[dict[str, Any]] | None = None, ranking_rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    overview_rows = overview_rows or []
    ranking_rows = ranking_rows or []
    if not rows and not overview_rows:
        return {"status": "data_gap", "reason": "reviews_missing"}
    detail_ratings = [_num(row.get("rating")) for row in rows if _num(row.get("rating")) is not None]
    detail_negative = [row for row in rows if row.get("is_negative") is True or (_num(row.get("rating")) is not None and (_num(row.get("rating")) or 0) < 4)]
    if overview_rows:
        total_reviews = sum(int(_num(row.get("review_count")) or 0) for row in overview_rows)
        negative_count = sum(int(_num(row.get("negative_review_count")) or 0) for row in overview_rows)
        weighted_rating_sum = sum((_num(row.get("rating_avg")) or 0) * int(_num(row.get("review_count")) or 0) for row in overview_rows)
        rating_count = sum(int(_num(row.get("review_count")) or 0) for row in overview_rows if _num(row.get("rating_avg")) is not None)
        rating_avg = weighted_rating_sum / rating_count if rating_count else (sum(detail_ratings) / len(detail_ratings) if detail_ratings else None)
        unreplied = sum(int(_num(row.get("unreplied_review_count")) or 0) for row in overview_rows)
    else:
        total_reviews = len(rows)
        negative_count = len(detail_negative)
        rating_avg = sum(detail_ratings) / len(detail_ratings) if detail_ratings else None
        unreplied = sum(1 for row in rows if row.get("is_replied") is False)
    keywords = []
    for row in rows:
        raw = row.get("keywords")
        if raw:
            keywords.extend([item.strip() for item in str(raw).replace("，", ",").split(",") if item.strip()])
    ranking_keywords = [row.get("rank_item_name") for row in ranking_rows if row.get("rank_item_name")]
    by_platform: dict[str, dict[str, Any]] = defaultdict(lambda: {"review_count": 0, "rating_sum": 0.0, "rating_weight": 0, "negative_count": 0, "unreplied_count": 0})
    for row in overview_rows:
        platform = str(row.get("platform") or "unknown")
        count = int(_num(row.get("review_count")) or 0)
        by_platform[platform]["review_count"] += count
        rating = _num(row.get("rating_avg"))
        if rating is not None and count:
            by_platform[platform]["rating_sum"] += rating * count
            by_platform[platform]["rating_weight"] += count
        by_platform[platform]["negative_count"] += int(_num(row.get("negative_review_count")) or 0)
        by_platform[platform]["unreplied_count"] += int(_num(row.get("unreplied_review_count")) or 0)
    if not overview_rows:
        for row in rows:
            platform = str(row.get("platform") or "unknown")
            by_platform[platform]["review_count"] += 1
            rating = _num(row.get("rating"))
            if rating is not None:
                by_platform[platform]["rating_sum"] += rating
                by_platform[platform]["rating_weight"] += 1
            if row in detail_negative:
                by_platform[platform]["negative_count"] += 1
            if row.get("is_replied") is False:
                by_platform[platform]["unreplied_count"] += 1
    platform_rows = []
    for platform, item in sorted(by_platform.items()):
        count = item["review_count"]
        weight = item["rating_weight"]
        platform_rows.append({
            "platform": platform,
            "review_count": count,
            "rating_avg": _round(_safe_div(item["rating_sum"], weight), 2),
            "negative_review_count": item["negative_count"],
            "negative_review_rate": _round(_safe_div(item["negative_count"], count), 4),
            "unreplied_review_count": item["unreplied_count"],
        })
    return {
        "status": "ok",
        "review_count": total_reviews or len(rows),
        "rating_avg": _round(rating_avg, 2),
        "negative_review_count": negative_count,
        "negative_review_rate": _round(_safe_div(negative_count, total_reviews), 4),
        "unreplied_review_count": unreplied,
        "keywords": sorted(set(keywords + [str(x) for x in ranking_keywords]))[:30],
        "sample_negative_reviews": [row.get("review_text") for row in detail_negative[:3] if row.get("review_text")],
        "by_platform": platform_rows,
    }


def nearby_event_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"status": "data_gap", "reason": "nearby_events_missing"}
    ordered = sorted(rows, key=lambda row: _num(row.get("countdown_days")) if _num(row.get("countdown_days")) is not None else 9999)
    return {
        "status": "ok",
        "event_count": len(rows),
        "upcoming_60d_count": sum(1 for row in rows if (_num(row.get("countdown_days")) or 9999) <= 60),
        "nearest_event": ordered[0].get("event_name") if ordered else None,
        "nearest_countdown_days": _num(ordered[0].get("countdown_days")) if ordered else None,
        "events": [{"event_name": row.get("event_name"), "event_start_date": row.get("event_start_date"), "distance_km": row.get("distance_km"), "countdown_days": row.get("countdown_days")} for row in ordered[:10]],
    }


def competitor_metrics(rows: list[dict[str, Any]], own_min_price: float | None = None) -> dict[str, Any]:
    if not rows:
        return {"status": "data_gap", "reason": "competitors_missing"}
    prices = [_num(row.get("price")) for row in rows if _num(row.get("price")) is not None]
    ranks = [_num(row.get("rank")) for row in rows if _num(row.get("rank")) is not None]
    by_platform = defaultdict(lambda: {"prices": [], "ranks": [], "competitors": set()})
    for row in rows:
        platform = str(row.get("platform") or "unknown")
        price = _num(row.get("price"))
        rank = _num(row.get("rank"))
        if price is not None:
            by_platform[platform]["prices"].append(price)
        if rank is not None:
            by_platform[platform]["ranks"].append(rank)
        if row.get("competitor_name"):
            by_platform[platform]["competitors"].add(str(row.get("competitor_name")))
    avg_price = sum(prices) / len(prices) if prices else None
    gap = own_min_price - avg_price if own_min_price is not None and avg_price else None
    platform_rows = {}
    for platform, item in sorted(by_platform.items()):
        p = item["prices"]
        r = item["ranks"]
        avg = sum(p) / len(p) if p else None
        platform_rows[platform] = {
            "competitor_count": len(item["competitors"]),
            "competitor_avg_price": _round(avg),
            "best_competitor_rank": min(r) if r else None,
            "own_min_price_vs_competitor_avg_gap": _round(own_min_price - avg) if own_min_price is not None and avg else None,
        }
    return {
        "status": "ok",
        "competitor_count": len({str(row.get("competitor_name") or "") for row in rows if row.get("competitor_name")}),
        "competitor_avg_price": _round(avg_price),
        "best_competitor_rank": min(ranks) if ranks else None,
        "own_min_price_vs_competitor_avg_gap": _round(gap),
        "by_platform": platform_rows,
    }

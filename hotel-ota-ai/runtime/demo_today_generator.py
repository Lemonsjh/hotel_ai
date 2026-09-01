from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from runtime.algorithms.time_aware_progress import resolve_progress_at_time
from runtime.common import DEFAULT_DB, PACKAGE_ROOT, emit, json_dumps, today
from runtime.storage import connect, init_schema


PROFILES = {
    "normal",
    "low_occupancy",
    "high_demand",
    "competitor_price_drop",
    "bad_reviews",
    "promotion_needed",
}

BASE_ROOM_TYPES = [
    ("KING", "Demo King Room", 12, 188, 158, 238),
    ("TWIN", "Demo Twin Room", 8, 178, 148, 228),
    ("DUO", "Demo Duo Room", 7, 208, 178, 268),
    ("QUAD", "Demo Quad Room", 6, 328, 268, 398),
    ("FAMILY", "Demo Family Room", 6, 238, 198, 298),
    ("BUNK", "Demo Bunk Room", 4, 168, 138, 218),
    ("LOFT", "Demo Loft Room", 4, 268, 218, 338),
    ("SUITE", "Demo Suite Room", 3, 388, 328, 488),
]


def synthetic_safety_flags(business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    return {
        "demo_dataset_id": dataset_id,
        "hotel_id": hotel_id,
        "business_date": business_date,
        "demo_business_date": business_date,
        "data_business_date": business_date,
        "data_source_type": "synthetic_today_demo",
        "freshness_status": "synthetic_current_day",
        "business_status": "demo_or_historical",
        "synthetic_data": True,
        "real_pms_data": False,
        "real_ota_data": False,
        "today_label_allowed": False,
        "approval_data_allowed": False,
        "approval_preview_allowed": True,
        "formal_approval_allowed": False,
        "live_allowed": False,
        "formal_approval_created": False,
        "live_execution_count": 0,
    }


def _profile_adjustment(profile: str) -> dict[str, float]:
    adjustments = {
        "normal": {"sold_ratio": 0.68, "demand": 76, "price": 1.0, "rating": 4.6, "budget": 500},
        "low_occupancy": {"sold_ratio": 0.44, "demand": 48, "price": 0.94, "rating": 4.5, "budget": 650},
        "high_demand": {"sold_ratio": 0.84, "demand": 91, "price": 1.12, "rating": 4.7, "budget": 380},
        "competitor_price_drop": {"sold_ratio": 0.61, "demand": 72, "price": 0.98, "rating": 4.6, "budget": 560},
        "bad_reviews": {"sold_ratio": 0.58, "demand": 67, "price": 0.97, "rating": 4.1, "budget": 520},
        "promotion_needed": {"sold_ratio": 0.55, "demand": 69, "price": 0.96, "rating": 4.5, "budget": 900},
    }
    return adjustments[profile]


def _allocate_sold_rooms(rng: random.Random, target_sold: int) -> list[int]:
    inventories = [item[2] for item in BASE_ROOM_TYPES]
    weights = [inventory + rng.random() for inventory in inventories]
    total_weight = sum(weights)
    sold = [min(inventory, int(round(target_sold * weight / total_weight))) for inventory, weight in zip(inventories, weights)]
    while sum(sold) > target_sold:
        idx = max(range(len(sold)), key=lambda i: sold[i])
        sold[idx] -= 1
    while sum(sold) < target_sold:
        candidates = [i for i, inventory in enumerate(inventories) if sold[i] < inventory]
        idx = rng.choice(candidates)
        sold[idx] += 1
    return sold


def generate_room_types(*, rng: random.Random, profile: str, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    adj = _profile_adjustment(profile)
    target_sold = round(sum(item[2] for item in BASE_ROOM_TYPES) * adj["sold_ratio"])
    sold_by_room = _allocate_sold_rooms(rng, target_sold)
    rooms: list[dict[str, Any]] = []
    for index, (room_id, room_name, inventory, current_price, floor_price, ceiling_price) in enumerate(BASE_ROOM_TYPES):
        price_factor = adj["price"] + rng.uniform(-0.025, 0.035)
        price = round(current_price * price_factor)
        candidate = round(min(ceiling_price, max(floor_price, price * (1.06 + rng.uniform(0, 0.04)))), 1)
        conservative = round(min(candidate, max(floor_price, price * 1.03)))
        baseline_price = round((price + current_price) / 2, 2)
        rooms.append(
            {
                "synthetic_id": f"room-{room_id.lower()}",
                "room_type_id": room_id,
                "room_type_name": room_name,
                "current_price": price,
                "rack_price": round(current_price * 1.35),
                "candidate_price": candidate,
                "conservative_price": conservative,
                "baseline_price": baseline_price,
                "floor_price": floor_price,
                "ceiling_price": ceiling_price,
                "inventory": inventory,
                "sold_rooms": sold_by_room[index],
                "available_rooms": inventory - sold_by_room[index],
                "expected_sold_rooms_tonight": sold_by_room[index],
                "expected_occupancy_tonight": round(sold_by_room[index] / max(inventory, 1), 4),
                "channel": "Mtop",
                "ota_base_price": conservative,
                "activity_discount_factor": 0.95,
                "max_single_change_pct": 0.15,
                "max_increase_pct": 0.12,
                "max_decrease_pct": 0.15,
                "min_increase_pct": 0.01,
                "min_decrease_pct": 0.01,
                "adapter": "Beyondh",
                "method": "Price.SetPriceByRoomTypeId",
            }
        )
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "room_types": rooms,
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_business_snapshot(room_types_payload: dict[str, Any], *, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    rooms = room_types_payload["room_types"]
    total_rooms = sum(item["inventory"] for item in rooms)
    sold_rooms = sum(item["sold_rooms"] for item in rooms)
    room_revenue = sum(item["sold_rooms"] * item["current_price"] for item in rooms)
    occupancy_ratio = round(sold_rooms / total_rooms, 4)
    adr = round(room_revenue / max(sold_rooms, 1), 2)
    revpar = round(room_revenue / max(total_rooms, 1), 2)
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "hotel_name": "Puyue Synthetic Demo Hotel",
        "data_snapshot_time": f"{business_date} 10:00:00",
        "total_rooms": total_rooms,
        "sold_rooms": sold_rooms,
        "available_rooms": total_rooms - sold_rooms,
        "sellable_rooms": total_rooms,
        "occupancy_rate": round(occupancy_ratio * 100, 2),
        "occupancy_rate_ratio": occupancy_ratio,
        "adr": adr,
        "revpar": revpar,
        "room_revenue": room_revenue,
        "orders_today": max(12, round(sold_rooms * 0.55)),
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_price_history(room_types_payload: dict[str, Any], *, rng: random.Random, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    base_date = dt.date.fromisoformat(business_date)
    history: list[dict[str, Any]] = []
    for room in room_types_payload["room_types"]:
        for offset in range(7, 0, -1):
            day = base_date - dt.timedelta(days=offset)
            swing = rng.uniform(-0.045, 0.055)
            price = round(room["current_price"] * (1 + swing), 2)
            history.append(
                {
                    "synthetic_id": f"price-{room['room_type_id'].lower()}-{day.isoformat()}",
                    "room_type_id": room["room_type_id"],
                    "date": day.isoformat(),
                    "median_deal_price": price,
                    "adr": round(price * rng.uniform(0.96, 1.02), 2),
                    "sold_rooms": max(0, min(room["inventory"], room["sold_rooms"] + rng.randint(-2, 2))),
                    "occupancy": round(max(0, min(1, room["sold_rooms"] / max(room["inventory"], 1) + rng.uniform(-0.08, 0.08))), 4),
                    "day_type_factor": 1.08 if day.weekday() >= 5 else 1.0,
                    "baseline_price": round(price * (1.02 if day.weekday() >= 5 else 1.0), 2),
                }
            )
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "price_history": history,
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_orders_aggregate(*, rng: random.Random, snapshot: dict[str, Any], business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    hourly = []
    remaining = int(snapshot["orders_today"])
    for hour in range(8, 24):
        count = 0 if remaining <= 0 else rng.randint(0, min(3, remaining))
        remaining -= count
        hourly.append({"hour": f"{hour:02d}:00", "synthetic_order_count": count, "synthetic_room_nights": count + rng.randint(0, 1)})
    if remaining > 0:
        hourly[-1]["synthetic_order_count"] += remaining
    stayover_rooms = rng.randint(16, 26)
    departure_rooms = rng.randint(6, 12)
    new_arrival_rooms = rng.randint(8, 16)
    expected_sold_rooms_tonight = min(snapshot["total_rooms"], max(snapshot["sold_rooms"], stayover_rooms + new_arrival_rooms))
    reservation_details = [
        {
            "synthetic_reservation_id": f"res-{index:03d}",
            "business_date": business_date,
            "room_nights": 1 + (index % 2),
            "status": "reserved" if index % 5 else "stayover",
            "channel": ["Mtop", "Ctrip", "PMS", "Douyin"][index % 4],
        }
        for index in range(1, 9)
    ]
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "today_order_count": snapshot["orders_today"],
        "yesterday_order_count": max(0, snapshot["orders_today"] - rng.randint(-2, 4)),
        "last_week_same_day_order_count": max(0, snapshot["orders_today"] - rng.randint(-3, 5)),
        "current_hour_order_count": hourly[-1]["synthetic_order_count"],
        "cancellation_count": rng.randint(0, 3),
        "stayover_count": stayover_rooms,
        "stayover_rooms": stayover_rooms,
        "checkout_count": departure_rooms,
        "departure_rooms": departure_rooms,
        "new_booking_count": new_arrival_rooms,
        "new_arrival_rooms": new_arrival_rooms,
        "expected_sold_rooms_tonight": expected_sold_rooms_tonight,
        "expected_occupancy_tonight": round(expected_sold_rooms_tonight / max(snapshot["total_rooms"], 1), 4),
        "sellable_rooms_tonight": snapshot["total_rooms"],
        "reservation_details": reservation_details,
        "reservation_summary": {
            "reservation_count": len(reservation_details),
            "room_nights": sum(item["room_nights"] for item in reservation_details),
            "stayover_rooms": stayover_rooms,
            "departure_rooms": departure_rooms,
        },
        "room_nights": snapshot["sold_rooms"] + rng.randint(1, 6),
        "hourly_order_progress": hourly,
        "source_channel_mix": {"Mtop": 0.52, "Fliggy": 0.16, "Douyin": 0.11, "Ctrip": 0.14, "PMS": 0.07},
        "repeat_guest_count": rng.randint(4, 9),
        "churn_risk_summary": "Synthetic demo only; no row-level guest data.",
        "no_row_level_order_details": True,
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_sales_baseline(
    *,
    rng: random.Random,
    snapshot: dict[str, Any],
    room_types_payload: dict[str, Any],
    business_date: str,
    hotel_id: str,
    dataset_id: str,
) -> dict[str, Any]:
    target_rooms = max(snapshot["sold_rooms"] + 2, round(snapshot["total_rooms"] * 0.72))
    curve = []
    accumulated = 0
    for hour in range(8, 24):
        accumulated = min(target_rooms, accumulated + rng.randint(1, 4))
        curve.append(
            {
                "business_date": business_date,
                "hour": f"{hour:02d}:00",
                "as_of_time": f"{hour:02d}:00",
                "target_sold_rooms": accumulated,
                "target_room_nights": accumulated,
                "time_grain": "as_of_time",
                "data_source_type": "synthetic_today_demo",
                "freshness_status": "synthetic_current_day",
            }
        )
    checkpoint_targets = [
        {
            "checkpoint_time": item["hour"],
            "as_of_time": item["as_of_time"],
            "target_sold_rooms": item["target_sold_rooms"],
            "target_room_nights": item["target_room_nights"],
        }
        for item in curve
    ]
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "sales_baseline": target_rooms,
        "target_sold_rooms": target_rooms,
        "target_room_nights": target_rooms,
        "daily_target_room_nights": target_rooms,
        "sample_target_room_nights": 15,
        "synthetic_today_target_room_nights": target_rooms,
        "real_business_target_room_nights": None,
        "active_target_source": "synthetic_today_demo",
        "sample_target_active": False,
        "target_revenue": round(target_rooms * snapshot["adr"], 2),
        "target_occupancy_rate": round(target_rooms / snapshot["total_rooms"], 4),
        "hourly_target_curve": curve,
        "checkpoint_targets": checkpoint_targets,
        "baseline_confidence": "synthetic_demo",
        "baseline_price_by_room_type": [
            {
                "room_type_id": room["room_type_id"],
                "room_type_name": room["room_type_name"],
                "baseline_price": room["baseline_price"],
                "floor_price": room["floor_price"],
                "ceiling_price": room["ceiling_price"],
                "history_window_days": 7,
            }
            for room in room_types_payload["room_types"]
        ],
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_progress_deviation(snapshot: dict[str, Any], baseline: dict[str, Any], *, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    progress_gap = round(snapshot["sold_rooms"] - baseline["target_sold_rooms"], 2)
    hourly_business_snapshots = []
    previous_sold = 0
    curve = baseline.get("hourly_target_curve") or []
    for index, checkpoint in enumerate(curve):
        target = int(checkpoint.get("target_sold_rooms") or 0)
        if index < len(curve) - 1:
            projected = max(previous_sold, min(snapshot["sold_rooms"], round(target * 0.88) + (index % 3)))
        else:
            projected = snapshot["sold_rooms"]
        orders_increment = max(0, projected - previous_sold)
        previous_sold = projected
        hourly_business_snapshots.append(
            {
                "business_date": business_date,
                "hour": checkpoint.get("hour"),
                "as_of_time": checkpoint.get("as_of_time") or checkpoint.get("hour"),
                "snapshot_at": f"{business_date} {checkpoint.get('hour')}:00",
                "hotel_id": hotel_id,
                "total_rooms": snapshot["total_rooms"],
                "sold_rooms": projected,
                "available_rooms": max(0, snapshot["total_rooms"] - projected),
                "occupancy_rate": round(projected / max(snapshot["total_rooms"], 1), 4),
                "target_sold_rooms": target,
                "target_room_nights": target,
                "orders_cumulative": projected,
                "orders_increment": orders_increment,
                "ota_views": 80 + index * 18,
                "ota_clicks": 8 + index * 3,
                "paid_orders": max(0, round(projected * 0.55)),
                "conversion_rate": round((max(0, round(projected * 0.55))) / max(80 + index * 18, 1), 4),
                "time_grain": "as_of_time",
                "data_source_type": "synthetic_today_demo",
                "freshness_status": "synthetic_current_day",
            }
        )
    time_progress = resolve_progress_at_time(
        hourly_business_snapshots,
        baseline.get("hourly_target_curve") or [],
        hourly_business_snapshots[-1]["as_of_time"] if hourly_business_snapshots else None,
        daily_target_room_nights=baseline["target_sold_rooms"],
    )
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "current_sold_rooms": snapshot["sold_rooms"],
        "target_sold_rooms": baseline["target_sold_rooms"],
        "daily_target_room_nights": baseline["target_sold_rooms"],
        "progress_gap": progress_gap,
        "progress_status": "behind" if progress_gap < 0 else "ahead_or_on_track",
        **time_progress,
        "deviation_reason_candidates": ["synthetic_channel_mix", "synthetic_competitor_pressure", "synthetic_conversion_gap"],
        "hourly_business_snapshots": hourly_business_snapshots,
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_market_context(*, profile: str, rng: random.Random, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    demand = int(_profile_adjustment(profile)["demand"] + rng.randint(-3, 3))
    weather = rng.choice(["clear", "cloudy", "light_rain"])
    event_signal = rng.choice(["nearby_esports_demo_event", "business_trip_peak", "local_weekend_market"])
    regional_heat_index = max(35, min(95, demand + rng.randint(-6, 8)))
    historical_same_period_score = max(35, min(95, demand + rng.randint(-10, 6)))
    current_traffic_score = max(30, min(95, demand + rng.randint(-8, 8)))
    date_environment_score = 78 if event_signal else (64 if weather else 55)
    traffic_state = "peak" if current_traffic_score >= 72 else "valley" if current_traffic_score <= 45 else "normal"
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "demand_index": demand,
        "demand_level": "strong" if demand >= 75 else "normal" if demand >= 55 else "weak",
        "calculation_source": "synthetic_today_demo_generator",
        "weather": weather,
        "weather_signal": {
            "city": "Shanghai",
            "captured_at": f"{business_date} 10:00:00",
            "weather": "synthetic_weather",
            "source": "synthetic_today_demo_generator",
        },
        "holiday_flag": False,
        "event_signal": event_signal,
        "event_signal_detail": {
            "event_date": business_date,
            "source": "synthetic_today_demo_generator",
            "confidence": "demo",
        },
        "date_environment_score": date_environment_score,
        "regional_heat_index": regional_heat_index,
        "historical_same_period_score": historical_same_period_score,
        "current_traffic_score": current_traffic_score,
        "traffic_state": traffic_state,
        "traffic_peak_valley_window": traffic_state,
        "traffic_peak_window": "19:00-22:00",
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_competitors(*, profile: str, rng: random.Random, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    base_gap = -18 if profile == "competitor_price_drop" else 8
    competitors = []
    for index in range(1, 6):
        gap = base_gap + rng.randint(-12, 18)
        price = max(120, 199 + gap)
        competitors.append(
            {
                "synthetic_id": f"competitor-{index}",
                "competitor_name": f"Synthetic Competitor {index}",
                "competitor_price": price,
                "competitor_rank": index + rng.randint(0, 3),
                "competitor_inventory": rng.randint(2, 12),
                "competitor_activity_label": rng.choice(["limited_coupon", "member_discount", "stay_two_nights", "no_activity"]),
                "competitor_price_gap": gap,
                "captured_at": f"{business_date} 10:00:00",
                "stay_date": business_date,
                "room_type_mapping_status": "synthetic_mapped",
                "competitor_price_freshness": "synthetic_current_day",
            }
        )
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "competitors": competitors,
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_reputation(*, profile: str, rng: random.Random, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    rating = _profile_adjustment(profile)["rating"]
    themes = ["network", "frontdesk_guidance", "cleanliness", "soundproofing", "parking", "breakfast", "room_device"]
    reviews = []
    for index in range(1, 21):
        score = round(max(3.2, min(5.0, rating + rng.uniform(-0.7, 0.35))), 1)
        reviews.append(
            {
                "synthetic_id": f"review-{index:03d}",
                "rating": score,
                "sentiment": "negative" if score < 4.0 else "neutral" if score < 4.5 else "positive",
                "theme": rng.choice(themes),
                "desensitized_text": "Synthetic desensitized review sample; no guest name, phone, room number, or order id.",
                "requires_reply": score < 4.2,
            }
        )
    negative = [item for item in reviews if item["sentiment"] == "negative"]
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "rating": rating,
        "rating_total": rating,
        "rating_service": round(max(3.5, rating - 0.1), 1),
        "negative_review_rate": round(len(negative) / len(reviews), 4),
        "bad_review_rate": round(len(negative) / len(reviews), 4),
        "reply_rate": 0.91 if profile != "bad_reviews" else 0.72,
        "review_reply_preview": "Synthetic reply preview: acknowledge, explain next check, and invite private follow-up.",
        "complaint_risk": "high" if profile == "bad_reviews" else "medium",
        "reviews": reviews,
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_promotion(*, profile: str, rng: random.Random, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    budget = int(_profile_adjustment(profile)["budget"])
    remaining = 0 if profile == "promotion_needed" else rng.randint(80, budget)
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "promotion_budget": budget,
        "budget_remaining": remaining,
        "suggested_campaign_type": "limited_time_bid_boost",
        "bid_suggestion": round(1.0 + rng.uniform(0.1, 0.35), 2),
        "expected_clicks": rng.randint(120, 240),
        "expected_orders": rng.randint(4, 9),
        "expected_roi": round(rng.uniform(1.05, 1.65), 2),
        "budget_guard_status": "blocked_for_demo",
        "dry_run_preview": True,
        "readback_required": True,
        "message_send_attempted": False,
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_customer_segments(*, rng: random.Random, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    segments = [
        ("esports_short_stay", 0.34, "medium"),
        ("repeat_business", 0.18, "low"),
        ("family_weekend", 0.16, "medium"),
        ("price_sensitive", 0.2, "high"),
        ("late_night_walkin", 0.12, "medium"),
    ]
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "customer_segment_summary": {name: share for name, share, _ in segments},
        "segments": [
            {
                "synthetic_id": f"segment-{name}",
                "segment_name": name,
                "share": share,
                "repurchase_risk": risk,
                "suggested_action": "synthetic_follow_up_coupon" if risk in {"medium", "high"} else "standard_service_touch",
            }
            for name, share, risk in segments
        ],
        "repeat_rate": round(rng.uniform(0.2, 0.32), 4),
        "churn_risk": "medium",
        "no_row_level_order_details": True,
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_execution_preview(room_types_payload: dict[str, Any], *, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    room = room_types_payload["room_types"][0]
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "room_type_id": room["room_type_id"],
        "channel": room["channel"],
        "adapter": room["adapter"],
        "method": room["method"],
        "execution_price": room["conservative_price"],
        "candidate_price": room["candidate_price"],
        "conservative_price": room["conservative_price"],
        "floor_price": room["floor_price"],
        "ceiling_price": room["ceiling_price"],
        "approval_id": None,
        "live_switch": False,
        "dry_run": True,
        "source_capability": "read_only",
        "blocked_reason": "synthetic_today_demo_never_live",
        "readback_required": True,
        "dry_run_preview": {
            "action": "price_sync",
            "write_attempted": False,
            "formal_approval_created": False,
            "live_execution_count": 0,
        },
        "message_preview_allowed": True,
        "message_send_attempted": False,
        "approval_card_preview_allowed": True,
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_external_ota_report_fields(*, business_date: str, hotel_id: str, dataset_id: str) -> dict[str, Any]:
    exposure = 2100
    views = 328
    clicks = 116
    submit_orders = 35
    paid_orders = 11
    payment_conversion_rate = round(paid_orders / views, 4)
    required = [
        "exposure",
        "views",
        "clicks",
        "search_conversion_rate",
        "first_conversion_rate",
        "second_conversion_rate",
        "payment_conversion_rate",
        "submit_orders",
        "paid_orders",
        "lost_orders",
        "lost_room_nights",
        "hos_score",
        "merchant_operation_score",
        "peer_competitiveness_score",
        "peer_rank",
        "rating_total",
        "bad_review_rate",
    ]
    available = [item for item in required if item not in {"lost_orders", "lost_room_nights", "bad_review_rate"}]
    return {
        "manifest_ref": "generated_demo_manifest.json",
        "field_contract_source": "contracts/v27/contract.json#N022",
        "ota_funnel": {
            "exposure": exposure,
            "views": views,
            "clicks": clicks,
            "submit_orders": submit_orders,
            "submitted_orders": submit_orders,
            "paid_orders": paid_orders,
            "payment_conversion_rate": payment_conversion_rate,
        },
        "exposure": exposure,
        "views": views,
        "clicks": clicks,
        "submit_orders": submit_orders,
        "submitted_orders": submit_orders,
        "paid_orders": paid_orders,
        "ota_health_score": 83,
        "hos_score": 82,
        "psi_score": 78,
        "content_score": 86,
        "conversion_rate": payment_conversion_rate,
        "payment_conversion_rate": payment_conversion_rate,
        "confirmation_rate": 0.91,
        "ranking": 4,
        "exposure_score": 76,
        "field_coverage_required_fields": required,
        "field_coverage_available_fields": available,
        "field_coverage_missing_fields": ["lost_orders", "lost_room_nights", "bad_review_rate"],
        "field_coverage_partial_fields": [],
        "html_report_preview_available": True,
        "html_report_preview_status": "generated",
        "html_report_preview_note": "Synthetic HTML preview metadata only; no real OTA result.",
        "html_report_sections": ["summary", "field_coverage", "conversion_funnel", "content_reputation", "next_steps"],
        **synthetic_safety_flags(business_date, hotel_id, dataset_id),
    }


def generate_today_demo_dataset(
    *,
    hotel_id: str = "puyue-demo",
    business_date: str | None = None,
    seed: int | None = None,
    profile: str = "normal",
) -> dict[str, Any]:
    if profile not in PROFILES:
        raise ValueError(f"unsupported synthetic profile: {profile}")
    business_date = business_date or today()
    seed_value = seed if seed is not None else int(business_date.replace("-", ""))
    rng = random.Random(seed_value)
    dataset_id = f"synthetic_today_demo_{business_date.replace('-', '')}_{profile}_{seed_value}"
    room_types_payload = generate_room_types(rng=rng, profile=profile, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id)
    snapshot = generate_business_snapshot(room_types_payload, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id)
    generated_at = f"{business_date} 10:00:00"
    baseline = generate_sales_baseline(
        rng=rng,
        snapshot=snapshot,
        room_types_payload=room_types_payload,
        business_date=business_date,
        hotel_id=hotel_id,
        dataset_id=dataset_id,
    )
    return {
        "generated_demo_manifest": {
            "demo_dataset_id": dataset_id,
            "generated_demo_run_id": dataset_id,
            "generated_at": generated_at,
            "hotel_id": hotel_id,
            "hotel_name": "Puyue Synthetic Demo Hotel",
            "generator": "runtime.demo_today_generator",
            "seed": seed_value,
            "profile": profile,
            **synthetic_safety_flags(business_date, hotel_id, dataset_id),
        },
        "business_snapshot": snapshot,
        "room_types": room_types_payload,
        "orders_aggregate": generate_orders_aggregate(rng=rng, snapshot=snapshot, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
        "price_history": generate_price_history(room_types_payload, rng=rng, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
        "sales_baseline": baseline,
        "progress_deviation": generate_progress_deviation(snapshot, baseline, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
        "market_context": generate_market_context(profile=profile, rng=rng, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
        "competitors": generate_competitors(profile=profile, rng=rng, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
        "reputation": generate_reputation(profile=profile, rng=rng, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
        "promotion": generate_promotion(profile=profile, rng=rng, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
        "customer_segments": generate_customer_segments(rng=rng, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
        "execution_preview": generate_execution_preview(room_types_payload, business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
        "external_ota_report_fields": generate_external_ota_report_fields(business_date=business_date, hotel_id=hotel_id, dataset_id=dataset_id),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _copy_default_node_and_scenario_fixtures(output_dir: Path, safety: dict[str, Any]) -> dict[str, int]:
    source_dir = PACKAGE_ROOT / "examples" / "demo_data"
    node_count = 0
    scenario_count = 0
    for source in sorted((source_dir / "nodes").glob("N*.json")):
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["demo_meta"] = {**(payload.get("demo_meta") or {}), **safety}
        payload["synthetic_generated_fixture"] = True
        _write_json(output_dir / "nodes" / source.name, payload)
        node_count += 1
    for source in sorted((source_dir / "scenarios").glob("SC*.json")):
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["demo_meta"] = {**(payload.get("demo_meta") or {}), **safety}
        payload["synthetic_generated_fixture"] = True
        _write_json(output_dir / "scenarios" / source.name, payload)
        scenario_count += 1
    return {"nodes": node_count, "scenarios": scenario_count}


def write_generated_fixtures(dataset: dict[str, Any], output_dir: Path) -> dict[str, Any]:
    written: list[str] = []
    name_map = {
        "generated_demo_manifest": "generated_demo_manifest.json",
        "business_snapshot": "business_snapshot.json",
        "room_types": "room_types.json",
        "orders_aggregate": "orders_aggregate.json",
        "price_history": "price_history.json",
        "sales_baseline": "sales_baseline.json",
        "progress_deviation": "progress_deviation.json",
        "market_context": "market_context.json",
        "competitors": "competitors.json",
        "reputation": "reputation.json",
        "promotion": "promotion.json",
        "customer_segments": "customer_segments.json",
        "execution_preview": "execution_preview.json",
        "external_ota_report_fields": "external_ota_report_fields.json",
    }
    for key, filename in name_map.items():
        target = output_dir / filename
        _write_json(target, dataset[key])
        written.append(str(target))
    copied = _copy_default_node_and_scenario_fixtures(output_dir, dataset["generated_demo_manifest"])
    return {"output_dir": str(output_dir), "written_files": written, "copied_fixture_counts": copied}


def write_generated_sqlite(dataset: dict[str, Any], db_path: str) -> dict[str, Any]:
    manifest = dataset["generated_demo_manifest"]
    ts = manifest.get("generated_at") or f"{manifest['business_date']} 10:00:00"
    inserted_rows = {"hotels": 0, "room_types": 0, "snapshots": 0, "baselines": 0}
    with closing(connect(db_path)) as conn:
        with conn:
            init_schema(conn)
            conn.execute(
                """
                INSERT INTO hotels (hotel_id, name, org_id, pms_vendor, timezone, config_json, created_at, updated_at)
                VALUES (?, ?, '', 'synthetic_today_demo', 'Asia/Shanghai', ?, ?, ?)
                ON CONFLICT(hotel_id) DO UPDATE SET
                  name=excluded.name,
                  pms_vendor=excluded.pms_vendor,
                  config_json=excluded.config_json,
                  updated_at=excluded.updated_at
                """,
                (
                    manifest["hotel_id"],
                    manifest["hotel_name"],
                    json_dumps({"demo_dataset_id": manifest["demo_dataset_id"], "data_source_type": "synthetic_today_demo"}),
                    ts,
                    ts,
                ),
            )
            inserted_rows["hotels"] += 1
            for room in dataset["room_types"]["room_types"]:
                conn.execute(
                    """
                    INSERT INTO room_types (hotel_id, room_type_id, name, floor_price, ceiling_price, inventory, config_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(hotel_id, room_type_id) DO UPDATE SET
                      name=excluded.name,
                      floor_price=excluded.floor_price,
                      ceiling_price=excluded.ceiling_price,
                      inventory=excluded.inventory,
                      config_json=excluded.config_json
                    """,
                    (
                        manifest["hotel_id"],
                        room["room_type_id"],
                        room["room_type_name"],
                        room["floor_price"],
                        room["ceiling_price"],
                        room["inventory"],
                        json_dumps(room),
                    ),
                )
                inserted_rows["room_types"] += 1
            for fact_name, payload in dataset.items():
                conn.execute(
                    "INSERT INTO snapshots (hotel_id, captured_at, source, payload_json) VALUES (?, ?, ?, ?)",
                    (manifest["hotel_id"], ts, f"synthetic_today_demo:{fact_name}", json_dumps(payload)),
                )
                inserted_rows["snapshots"] += 1
            conn.execute(
                """
                INSERT INTO baselines (hotel_id, business_date, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(hotel_id, business_date) DO UPDATE SET
                  payload_json=excluded.payload_json,
                  created_at=excluded.created_at
                """,
                (manifest["hotel_id"], manifest["business_date"], json_dumps(dataset["sales_baseline"]), ts),
            )
            inserted_rows["baselines"] += 1
    return {
        "db_path": db_path,
        "inserted_tables": [key for key, value in inserted_rows.items() if value],
        "inserted_rows": inserted_rows,
        "generated_rows": inserted_rows,
        "latest_business_date": manifest["business_date"],
        "latest_generated_demo_run_id": manifest.get("generated_demo_run_id") or manifest.get("demo_dataset_id"),
        "generated_at": ts,
    }


def generate_today_demo_result(args: argparse.Namespace) -> dict[str, Any]:
    business_date = args.business_date or today()
    output_dir = Path(args.output_dir) if args.output_dir else PACKAGE_ROOT / "examples" / "demo_data" / "generated" / business_date
    dataset = generate_today_demo_dataset(
        hotel_id=args.hotel_id,
        business_date=business_date,
        seed=args.seed,
        profile=args.profile,
    )
    manifest = dataset["generated_demo_manifest"]
    result: dict[str, Any] = {
        "status": "ok",
        "run_id": f"generate-today-demo-{uuid.uuid4().hex[:12]}",
        "business_date": business_date,
        "demo_dataset_id": manifest["demo_dataset_id"],
        "hotel_id": args.hotel_id,
        "seed": manifest["seed"],
        "profile": args.profile,
        "dry_run": bool(args.dry_run),
        "data_source_type": "synthetic_today_demo",
        "freshness_status": "synthetic_current_day",
        "synthetic_data": True,
        "real_pms_data": False,
        "real_ota_data": False,
        "approval_data_allowed": False,
        "live_allowed": False,
        "formal_approval_created": False,
        "live_execution_count": 0,
        "generated_counts": {
            "room_types": len(dataset["room_types"]["room_types"]),
            "competitors": len(dataset["competitors"]["competitors"]),
            "price_history_rows": len(dataset["price_history"]["price_history"]),
            "reviews": len(dataset["reputation"]["reviews"]),
            "customer_segments": len(dataset["customer_segments"]["segments"]),
        },
        "data_label": "Synthetic current-day demo data; not real PMS/OTA business data.",
    }
    manifest["generated_demo_run_id"] = result["run_id"]
    if args.dry_run:
        result["write_fixtures"] = False
        result["write_db"] = False
        return result
    if args.write_fixtures:
        result["fixtures"] = write_generated_fixtures(dataset, output_dir)
    if args.write_db:
        result.update(write_generated_sqlite(dataset, args.db))
    return result


def generate_today_demo(args: argparse.Namespace) -> None:
    emit(generate_today_demo_result(args))

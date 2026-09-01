from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Callable, Mapping


_INSTALLED = False
VERSION = "s5-strong-pricing-rules.v1"

DEFAULT_THRESHOLDS: dict[str, float] = {
    "strong_raise_progress_pp": 8.0,
    "strong_lower_progress_pp": -8.0,
    "inventory_tight_ratio": 0.30,
    "inventory_loose_ratio": 0.50,
    "market_not_cold_ratio": 0.90,
    "browse_weak_ratio": 0.80,
    "browse_healthy_ratio": 0.90,
    "price_high_ratio": 1.08,
    "price_p20_floor_factor": 1.02,
    "raise_pct_min": 0.03,
    "raise_pct_mid": 0.04,
    "raise_pct_max": 0.05,
    "lower_pct_min": 0.05,
    "lower_pct_mid": 0.06,
    "lower_pct_max": 0.08,
    "single_change_hard_cap": 0.10,
}


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _explicitly_false(value: Any) -> bool:
    return value is False or _text(value).lower() in {
        "0",
        "0.0",
        "false",
        "no",
        "n",
        "inactive",
        "offline",
        "disabled",
        "suspended",
        "closed",
    }


def _payload(result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    nested = result.get("payload")
    return dict(nested) if isinstance(nested, Mapping) else dict(result)


def _price_rows(result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    payload = _payload(result)
    rows = payload.get("price_snapshots") or payload.get("rows") or []
    return [dict(row) for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _dynamic(s16_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(s16_result, Mapping):
        return {}
    nested = s16_result.get("dynamic_diagnosis")
    return dict(nested) if isinstance(nested, Mapping) else dict(s16_result)


def _baseline_payload(s15_result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(s15_result, Mapping):
        return {}
    nested = s15_result.get("baseline")
    return dict(nested) if isinstance(nested, Mapping) else dict(s15_result)


def _baseline_package(s15_result: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = _baseline_payload(s15_result)
    package = payload.get("baseline_package")
    return dict(package) if isinstance(package, Mapping) else payload


def _thresholds() -> dict[str, float]:
    values = dict(DEFAULT_THRESHOLDS)
    try:
        from runtime.algorithm_rule_loader import find_algorithm_rule

        configured = (
            (find_algorithm_rule(skill_id="S5").get("algorithm") or {}).get("thresholds")
            or {}
        )
    except Exception:
        configured = {}
    for name in values:
        number = _n(configured.get(name))
        if number is not None:
            values[name] = number
    return values


def _find_by_id(rows: Any, field: str, wanted: str) -> dict[str, Any]:
    if not isinstance(rows, list):
        return {}
    for source in rows:
        if not isinstance(source, Mapping):
            continue
        if _text(source.get(field)) == wanted:
            return dict(source)
    return {}


def _room_evidence(
    s16_result: Mapping[str, Any] | None,
    room_type_id: str,
) -> dict[str, Any]:
    dynamic = _dynamic(s16_result)
    structure = dynamic.get("room_structure")
    structure = dict(structure) if isinstance(structure, Mapping) else {}
    row = _find_by_id(structure.get("room_type_results"), "room_type_id", room_type_id)
    if not row:
        row = _find_by_id(dynamic.get("room_type_results"), "room_type_id", room_type_id)
    if not row and isinstance(s16_result, Mapping):
        row = _find_by_id(s16_result.get("room_type_results"), "room_type_id", room_type_id)

    target_line = row.get("target_line")
    target_line = dict(target_line) if isinstance(target_line, Mapping) else {}
    sales = dynamic.get("sales")
    sales = dict(sales) if isinstance(sales, Mapping) else {}
    sales_delta = _n(
        row.get("sales_progress_delta_pp")
        if row.get("sales_progress_delta_pp") not in (None, "")
        else target_line.get("delta_pp")
    )
    if sales_delta is None:
        sales_delta = _n(sales.get("sales_progress_delta_pp"))

    total_rooms = _n(row.get("total_rooms"))
    committed_sold = _n(row.get("committed_sold"))
    available_rooms = _n(row.get("available_rooms"))
    overbooking_rooms = _n(row.get("overbooking_rooms")) or 0.0
    if available_rooms is not None:
        remaining_rooms = max(available_rooms, 0.0)
    elif total_rooms is not None and committed_sold is not None:
        remaining_rooms = max(total_rooms - committed_sold, 0.0)
    else:
        remaining_rooms = None
    remaining_ratio = (
        remaining_rooms / total_rooms
        if remaining_rooms is not None and total_rooms not in (None, 0)
        else None
    )
    return {
        "room_type_id": room_type_id,
        "sales_progress_delta_pp": sales_delta,
        "total_rooms": total_rooms,
        "committed_sold": committed_sold,
        "remaining_rooms": remaining_rooms,
        "remaining_room_ratio": remaining_ratio,
        "overbooking_rooms": overbooking_rooms,
        "sales_status": row.get("sales_status") or sales.get("status"),
        "room_evidence_source": "room_type" if row else "hotel_fallback",
    }


def _market_evidence(s16_result: Mapping[str, Any] | None) -> dict[str, Any]:
    dynamic = _dynamic(s16_result)
    market = dynamic.get("market")
    market = dict(market) if isinstance(market, Mapping) else {}
    ratio = _n(market.get("market_heat_ratio"))
    source = "current_comparable_market"
    proxy = dynamic.get("meituan_market_proxy")
    proxy = dict(proxy) if isinstance(proxy, Mapping) else {}
    projection = proxy.get("market_projection")
    projection = dict(projection) if isinstance(projection, Mapping) else {}
    if ratio is None:
        ratio = _n(projection.get("projected_ratio_vs_history"))
        source = "linear_market_projection" if ratio is not None else "unavailable"
    status = _text(market.get("status") or projection.get("status") or "unavailable").lower()
    return {
        "market_heat_ratio": ratio,
        "market_status": status,
        "market_evidence_source": source,
    }


def _traffic_evidence(
    s16_result: Mapping[str, Any] | None,
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    dynamic = _dynamic(s16_result)
    browse = dynamic.get("browse")
    browse = dict(browse) if isinstance(browse, Mapping) else {}
    pace = dynamic.get("meituan_pace_insights")
    pace = dict(pace) if isinstance(pace, Mapping) else {}
    projection = pace.get("browse_projection")
    projection = dict(projection) if isinstance(projection, Mapping) else {}
    # Current cumulative browse must not be compared directly with a full-day
    # historical median.  Apply the same completion-ratio-first pace method as
    # market heat, and retain the direct ratio only as a last-resort fallback.
    ratio = _n(projection.get("projected_ratio_vs_history"))
    if ratio is not None:
        source = (
            "linear_browse_projection"
            if projection.get("linear_projection_only")
            else "hourly_completion_browse_projection"
        )
    else:
        ratio = _n(browse.get("ratio"))
        source = "current_comparable_browse" if ratio is not None else "unavailable"

    if ratio is None:
        status = "unavailable"
    elif ratio < thresholds["browse_weak_ratio"]:
        status = "weak"
    elif ratio < thresholds["browse_healthy_ratio"]:
        status = "recovering"
    else:
        status = "healthy"

    second = dynamic.get("second_conversion")
    second = dict(second) if isinstance(second, Mapping) else {}
    second_trend = pace.get("second_conversion_trend")
    second_trend = dict(second_trend) if isinstance(second_trend, Mapping) else {}
    browse_users = _n(second.get("browse_users"))
    pay_orders = _n(second.get("pay_orders"))
    strong_sample = bool(
        _text(second.get("sample_level")).lower() == "strong"
        or (
            browse_users is not None
            and browse_users >= 50
            and pay_orders is not None
            and pay_orders >= 3
        )
    )
    second_current = _n(second.get("current"))
    second_p25 = _n(second.get("baseline_p25"))
    second_peer_index = _n(second.get("conversion_index_vs_market"))
    second_ratio = _n(second.get("ratio"))
    second_status = _text(second.get("status")).lower()
    trend_status = _text(second_trend.get("status")).lower()
    comparison_value = _text(second.get("comparison_allowed")).lower()
    comparison_allowed = comparison_value not in {"0", "false", "no", "n"}
    second_preview_sample = bool(
        not strong_sample
        and (
            _text(second.get("sample_level")).lower() == "weak_reminder"
            or (
                browse_users is not None
                and browse_users >= 30
                and pay_orders is not None
                and pay_orders >= 2
            )
        )
    )
    # S16 provides the typed facts; S5 applies its own documented rule.
    # In particular, S16's is_weak may include extra diagnosis gates such as
    # browse pace, which must not redefine S5's conversion rule.
    second_evidence_available = bool(
        comparison_allowed
        and second_current is not None
        and second_p25 is not None
        and second_peer_index is not None
    )
    conversion_below_reference = bool(
        second_evidence_available
        and second_current < second_p25
        and second_peer_index < 0.85
    )
    second_weak = bool(strong_sample and conversion_below_reference)
    second_weak_signal = bool(second_preview_sample and conversion_below_reference)
    return {
        "browse_ratio": ratio,
        "traffic_status": status,
        "traffic_evidence_source": source,
        "second_conversion_weak": second_weak,
        "second_conversion_weak_signal": second_weak_signal,
        "second_conversion_sample_valid": strong_sample,
        "second_conversion_preview_sample_valid": second_preview_sample,
        "second_conversion_evidence_available": second_evidence_available,
        "second_conversion_current": second_current,
        "second_conversion_baseline_p25": second_p25,
        "second_conversion_peer_index": second_peer_index,
        "second_conversion_ratio": second_ratio,
        "second_conversion_status": second_status or trend_status or "unavailable",
        "second_conversion_decision_source": "s5_from_s16_typed_evidence",
    }


def _room_reference(
    s15_result: Mapping[str, Any] | None,
    room_type_id: str,
) -> dict[str, Any]:
    package = _baseline_package(s15_result)
    reference = _find_by_id(
        package.get("room_type_transaction_references"),
        "room_type_id",
        room_type_id,
    )
    if not reference:
        rooms = package.get("room_types")
        rooms = dict(rooms) if isinstance(rooms, Mapping) else {}
        room = rooms.get(room_type_id)
        room = dict(room) if isinstance(room, Mapping) else {}
        price_baseline = room.get("price_baseline")
        reference = dict(price_baseline) if isinstance(price_baseline, Mapping) else room
    return {
        "baseline_price_avg": _n(reference.get("weighted_avg") or reference.get("avg")),
        "baseline_price_median": _n(reference.get("median")),
        "baseline_price_p20": _n(reference.get("p20")),
        "baseline_price_p80": _n(reference.get("p80")),
        "reference_sample_count": reference.get("sample_count"),
    }


def _dynamic_product(
    s16_result: Mapping[str, Any] | None,
    ota_product_id: str,
) -> dict[str, Any]:
    dynamic = _dynamic(s16_result)
    product = _find_by_id(dynamic.get("product_prices"), "ota_product_id", ota_product_id)
    if product:
        return product
    return _find_by_id(
        dynamic.get("estimated_price_advisories"),
        "ota_product_id",
        ota_product_id,
    )


def _normalize_commission(value: Any) -> float | None:
    number = _n(value)
    if number is None:
        return None
    if number > 1:
        number /= 100.0
    return number if 0 <= number < 1 else None


def _product_evidence(
    candidate: Mapping[str, Any],
    product_row: Mapping[str, Any],
    s15_result: Mapping[str, Any] | None,
    s16_result: Mapping[str, Any] | None,
    thresholds: Mapping[str, float],
) -> dict[str, Any]:
    from runtime.s5_product_type_filter_patch import unsupported_product_type

    product_id = _text(candidate.get("ota_product_id"))
    room_type_id = _text(candidate.get("room_type_id"))
    current_price = _n(candidate.get("current_price")) or 0.0
    dynamic_product = _dynamic_product(s16_result, product_id)
    reference = _room_reference(s15_result, room_type_id)

    estimated_net = _n(
        dynamic_product.get("estimated_activity_net_price")
        or dynamic_product.get("current_activity_net_estimate")
    )
    raw_price = _n(
        dynamic_product.get("raw_price")
        or dynamic_product.get("current_raw_price")
        or dynamic_product.get("current_price")
    )
    commission = _normalize_commission(
        dynamic_product.get("commission_rate") or product_row.get("commission_rate")
    )
    activity_factor = _n(
        dynamic_product.get("combined_activity_factor")
        or product_row.get("combined_activity_factor")
    )
    net_factor = (
        estimated_net / raw_price
        if estimated_net is not None and raw_price not in (None, 0)
        else (1.0 - commission) * activity_factor
        if commission is not None and activity_factor not in (None, 0)
        else None
    )

    # S5's displayed net revenue and historical-price signal share this fixed
    # business assumption. It is not a source-derived settlement amount.
    from runtime.s5_product_net_revenue_patch import MEMBER_EXPECTED_FACTOR

    member_factor = float(MEMBER_EXPECTED_FACTOR)
    if estimated_net is not None:
        estimated_net *= member_factor
    if net_factor is not None:
        net_factor *= member_factor

    median = reference["baseline_price_median"] or reference["baseline_price_avg"]
    if median not in (None, 0):
        if estimated_net is not None:
            price_ratio = estimated_net / median
            price_basis = "activity_net_vs_pms_transaction"
        else:
            # OTA挂牌价与PMS成交价不是同一收入口径。净收缺失时宁可
            # 不判断价格高低，也不能用挂牌价制造虚假的“偏高”信号。
            price_ratio = None
            price_basis = "activity_net_unavailable_no_raw_price_fallback"
    else:
        price_ratio = None
        price_basis = "unavailable"

    p20 = reference["baseline_price_p20"]
    p80 = reference["baseline_price_p80"]
    p80_net_revenue_ceiling = p80 * 0.98 if p80 is not None else None
    if p20 is None:
        p20_raw_equivalent = None
    elif net_factor not in (None, 0):
        p20_raw_equivalent = p20 / net_factor
    else:
        p20_raw_equivalent = p20
    if p80 is None or net_factor in (None, 0):
        p80_raw_equivalent = None
    else:
        p80_raw_equivalent = p80 / net_factor

    configured_floor = _n(candidate.get("configured_floor_price"))
    if configured_floor is None:
        configured_floor = _n(candidate.get("floor_price"))
    configured_ceiling = _n(candidate.get("configured_ceiling_price"))
    if configured_ceiling is None:
        configured_ceiling = _n(candidate.get("ceiling_price"))
    p20_floor = (
        p20_raw_equivalent * thresholds["price_p20_floor_factor"]
        if p20_raw_equivalent is not None
        else None
    )
    floor_values = [value for value in (configured_floor, p20_floor) if value is not None]
    effective_floor = max(floor_values) if floor_values else None
    hard_cap = thresholds["single_change_hard_cap"]
    ceiling_values = [current_price * (1.0 + hard_cap)]
    if configured_ceiling is not None:
        ceiling_values.append(configured_ceiling)
    # The historical P80 is a room-type net-revenue reference. Convert it back
    # to an OTA sale-price ceiling using the current commission/activity factor.
    if p80_raw_equivalent is not None:
        ceiling_values.append(p80_raw_equivalent * 0.98)
    effective_ceiling = min(ceiling_values)

    mapping_valid = bool(candidate.get("s6_task_mapping_ready"))
    guard_valid = bool(
        candidate.get("price_guard_source") == "active_price_guard_policy"
        and configured_floor is not None
        and configured_ceiling is not None
        and _text(candidate.get("price_guard_policy_state") or "active").lower()
        not in {"inactive", "disabled", "expired", "draft"}
    )
    editable = not _explicitly_false(product_row.get("price_editable_flag"))
    status_values = {
        _text(product_row.get(name)).lower()
        for name in ("product_status", "sell_status", "online_status", "status")
        if product_row.get(name) not in (None, "")
    }
    product_type_supported = unsupported_product_type(product_row) is None
    same_product_history_available = bool(
        dynamic_product.get("same_ota_product_history_available") is True
        or product_row.get("same_ota_product_history_available") is True
    )
    product_sellable = bool(
        product_type_supported
        and product_id
        and current_price > 0
        and editable
        and not status_values.intersection(
            {"offline", "disabled", "suspended", "closed", "sold_out", "下线", "停售"}
        )
        and not _explicitly_false(product_row.get("product_sellable"))
        and not _explicitly_false(product_row.get("is_online"))
    )
    product_healthy = bool(
        product_sellable
        and mapping_valid
        and guard_valid
        and same_product_history_available
    )

    return {
        **reference,
        "estimated_activity_net_price": estimated_net,
        "net_price_factor": net_factor,
        "member_expected_factor": member_factor,
        "price_ratio_vs_avg": price_ratio,
        "price_comparison_basis": price_basis,
        "price_high": bool(
            price_ratio is not None and price_ratio >= thresholds["price_high_ratio"]
        ),
        "configured_price_floor": configured_floor,
        "configured_price_ceiling": configured_ceiling,
        "baseline_price_p20_raw_equivalent": p20_raw_equivalent,
        "baseline_price_p80_raw_equivalent": p80_raw_equivalent,
        "raise_price_headroom_basis": "estimated_net_revenue_vs_room_type_p80_x_98pct",
        "raise_net_revenue_ceiling": p80_net_revenue_ceiling,
        "raise_price_has_headroom": bool(
            estimated_net is not None
            and p80_net_revenue_ceiling is not None
            and estimated_net < p80_net_revenue_ceiling
        ),
        "effective_price_floor": effective_floor,
        "effective_price_ceiling": effective_ceiling,
        "product_type_supported": product_type_supported,
        "mapping_valid": mapping_valid,
        "guard_valid": guard_valid,
        "product_sellable": product_sellable,
        "product_healthy": product_healthy,
        "same_ota_product_history_available": same_product_history_available,
    }


def _round_money(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_money_up(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_CEILING))


def _round_money_down(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_FLOOR))


def _observe_until(as_of_time: Any, minutes: int) -> str | None:
    if as_of_time in (None, ""):
        return None
    try:
        moment = dt.datetime.fromisoformat(str(as_of_time).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (moment + dt.timedelta(minutes=minutes)).isoformat()


def _raise_pct(delta_pp: float, remaining_ratio: float, thresholds: Mapping[str, float]) -> float:
    if delta_pp >= 15:
        value = thresholds["raise_pct_max"]
    elif delta_pp >= 12:
        value = thresholds["raise_pct_mid"]
    else:
        value = thresholds["raise_pct_min"]
    if remaining_ratio <= 0.15:
        value = max(value, thresholds["raise_pct_mid"])
    return min(value, thresholds["raise_pct_max"])


def _lower_pct(delta_pp: float, price_ratio: float, thresholds: Mapping[str, float]) -> float:
    if delta_pp <= -25:
        value = thresholds["lower_pct_max"]
    elif delta_pp <= -15:
        value = thresholds["lower_pct_mid"]
    else:
        value = thresholds["lower_pct_min"]
    if price_ratio >= 1.15:
        value = min(value + 0.01, thresholds["lower_pct_max"])
    return min(value, thresholds["lower_pct_max"])


def evaluate_strong_pricing_rule(
    candidate: Mapping[str, Any],
    *,
    product_row: Mapping[str, Any],
    s15_result: Mapping[str, Any] | None,
    s16_result: Mapping[str, Any] | None,
    as_of_time: Any = None,
    thresholds: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    rules = dict(thresholds or _thresholds())
    room = _room_evidence(s16_result, _text(candidate.get("room_type_id")))
    market = _market_evidence(s16_result)
    traffic = _traffic_evidence(s16_result, rules)
    product = _product_evidence(candidate, product_row, s15_result, s16_result, rules)
    current_price = _n(candidate.get("current_price")) or 0.0
    delta_pp = room.get("sales_progress_delta_pp")
    remaining_ratio = room.get("remaining_room_ratio")
    total_rooms = room.get("total_rooms")
    inventory_scope_valid = bool(
        total_rooms is not None
        and total_rooms > 0
        and remaining_ratio is not None
    )
    inventory_tight = bool(
        inventory_scope_valid and remaining_ratio <= rules["inventory_tight_ratio"]
    )
    inventory_loose = bool(
        inventory_scope_valid and remaining_ratio >= rules["inventory_loose_ratio"]
    )
    market_ratio = market.get("market_heat_ratio")
    market_not_cold = bool(
        market_ratio is not None and market_ratio >= rules["market_not_cold_ratio"]
    )
    if market_ratio is None:
        market_not_cold = market.get("market_status") in {
            "normal",
            "hot",
            "near_history",
            "likely_above_history",
        }

    raise_allowed = bool(
        delta_pp is not None
        and delta_pp >= rules["strong_raise_progress_pp"]
        and inventory_tight
        and market_not_cold
        and product["product_healthy"]
        and product["raise_price_has_headroom"]
        and product["effective_price_ceiling"] is not None
        and current_price < product["effective_price_ceiling"]
    )
    down_context = bool(
        delta_pp is not None
        and delta_pp <= rules["strong_lower_progress_pp"]
        and inventory_loose
        and room.get("overbooking_rooms", 0) <= 0
        and product["product_sellable"]
    )
    lower_business_ready = bool(
        down_context
        and traffic["second_conversion_weak"]
        and product["price_high"]
        and product["mapping_valid"]
        and product["guard_valid"]
        and product["effective_price_floor"] is not None
        and current_price > product["effective_price_floor"]
    )
    lower_allowed = bool(
        lower_business_ready and traffic["traffic_status"] == "healthy"
    )

    common = {
        "rule_version": VERSION,
        **room,
        **market,
        **traffic,
        **product,
        "room_type_inventory_tight": inventory_tight,
        "room_type_inventory_loose": inventory_loose,
        "market_not_cold": market_not_cold,
        "raise_rule_allowed": raise_allowed,
        "lower_rule_business_ready": lower_business_ready,
        "lower_rule_allowed": lower_allowed,
    }

    if raise_allowed:
        configured = _raise_pct(float(delta_pp), float(remaining_ratio), rules)
        configured = min(
            configured,
            _n(candidate.get("max_increase_pct")) or rules["single_change_hard_cap"],
            rules["single_change_hard_cap"],
        )
        configured = round(configured, 4)
        raw_target = current_price * (1.0 + configured)
        target = _round_money_down(
            min(float(product["effective_price_ceiling"]), raw_target)
        )
        actual = (target - current_price) / current_price if current_price else 0.0
        if target <= current_price:
            return {
                **common,
                "status": "hold",
                "action_type": "hold",
                "blocked_reason": "raise_target_clamped_to_current_price",
            }
        return {
            **common,
            "status": "triggered",
            "action_type": "raise_price",
            "price_action": "increase",
            "configured_change_pct": configured,
            "target_price": target,
            "actual_change_pct": round(actual, 4),
            "observe_minutes": 120,
            "observe_until": _observe_until(as_of_time, 120),
            "reason_codes": [
                "sales_progress_ahead_8pp",
                "room_type_inventory_tight",
                "market_not_cold",
                "product_healthy",
                "mapping_and_guard_valid",
            ],
        }

    if lower_allowed:
        configured = _lower_pct(
            float(delta_pp),
            float(product["price_ratio_vs_avg"]),
            rules,
        )
        configured = min(
            configured,
            _n(candidate.get("max_decrease_pct")) or rules["single_change_hard_cap"],
            rules["single_change_hard_cap"],
        )
        configured = round(configured, 4)
        raw_target = current_price * (1.0 - configured)
        floor = float(product["effective_price_floor"])
        target = _round_money(max(floor, raw_target))
        if target < floor:
            target = _round_money_up(floor)
        actual = (target - current_price) / current_price if current_price else 0.0
        if target >= current_price:
            return {
                **common,
                "status": "hold",
                "action_type": "hold",
                "blocked_reason": "lower_target_clamped_to_current_price",
            }
        return {
            **common,
            "status": "triggered",
            "action_type": "lower_room_price",
            "price_action": "decrease",
            "configured_change_pct": configured,
            "target_price": target,
            "actual_change_pct": round(actual, 4),
            "observe_minutes": 90,
            "observe_until": _observe_until(as_of_time, 90),
            "reason_codes": [
                "sales_progress_behind_8pp",
                "room_type_inventory_loose",
                "traffic_healthy",
                "second_conversion_weak",
                "product_price_high",
                "product_sellable",
                "mapping_and_guard_valid",
                "effective_price_floor_respected",
            ],
        }

    if down_context and traffic["traffic_status"] == "weak":
        return {
            **common,
            "status": "blocked",
            "action_type": "hold",
            "blocked_reason": "traffic_weak_price_down_forbidden",
            "recommended_alternative_action": "promotion_review",
            "handoff_to": "S8",
        }

    if (
        delta_pp is not None
        and delta_pp <= rules["strong_lower_progress_pp"]
        and room.get("overbooking_rooms", 0) > 0
    ):
        return {
            **common,
            "status": "blocked",
            "action_type": "hold",
            "blocked_reason": "overbooking_price_down_forbidden",
        }

    if down_context and traffic["traffic_status"] == "recovering":
        preview: float | None = None
        preview_change: float | None = None
        if lower_business_ready:
            configured = _lower_pct(
                float(delta_pp),
                float(product["price_ratio_vs_avg"]),
                rules,
            )
            configured = min(
                configured,
                _n(candidate.get("max_decrease_pct")) or rules["single_change_hard_cap"],
                rules["single_change_hard_cap"],
            )
            configured = round(configured, 4)
            floor = float(product["effective_price_floor"])
            preview = _round_money(max(floor, current_price * (1.0 - configured)))
            if preview < floor:
                preview = _round_money_up(floor)
            preview_change = (
                round((preview - current_price) / current_price, 4)
                if current_price
                else 0.0
            )
        return {
            **common,
            "status": "preview_only",
            "action_type": "hold",
            "blocked_reason": "traffic_recovering_manual_preview_only",
            "manual_preview_price": preview,
            "manual_preview_change_pct": preview_change,
            "preview_price_down_allowed": preview is not None,
        }

    missing: list[str] = []
    if delta_pp is None:
        missing.append("sales_progress_delta_pp")
    if not inventory_scope_valid:
        missing.append("room_type_inventory")
    if traffic["traffic_status"] == "unavailable":
        missing.append("browse_ratio")
    if product["baseline_price_p20"] is None:
        missing.append("baseline_price_p20")
    if not product["mapping_valid"]:
        missing.append("mapping_valid")
    if not product["guard_valid"]:
        missing.append("guard_valid")
    return {
        **common,
        "status": "not_triggered",
        "action_type": "hold",
        "blocked_reason": "strong_pricing_rule_not_satisfied",
        "missing_rule_evidence": list(dict.fromkeys(missing)),
    }


def _capture_price_query(
    original_query: Callable[..., dict[str, Any]],
    captured: dict[str, dict[str, Any]],
) -> Callable[..., dict[str, Any]]:
    def query(template: str, hotel_id: str, **kwargs: Any) -> dict[str, Any]:
        result = original_query(template, hotel_id, **kwargs)
        if template == "ota_price_mapping" and isinstance(result, Mapping):
            for row in _price_rows(result):
                product_id = _text(row.get("ota_product_id"))
                if product_id:
                    captured[product_id] = row
        return result

    return query


def _apply_hold(candidate: dict[str, Any], rule: Mapping[str, Any]) -> None:
    current = _n(candidate.get("current_price")) or 0.0
    candidate["legacy_reference_price_action"] = candidate.get("price_action")
    candidate["legacy_reference_candidate_price"] = candidate.get("candidate_price")
    candidate["legacy_reference_actual_change_pct"] = candidate.get("actual_change_pct")
    candidate.update(
        {
            "price_action": "hold",
            "candidate_price": current,
            "conservative_price": current,
            "execution_price": current,
            "actual_change_pct": 0.0,
            "risk_level": "low",
            "auto_execution_eligible": False,
            "approval_required": False,
            "handoff_to": rule.get("handoff_to"),
            "eligibility": "preview_only_strong_rule_not_satisfied",
            "blocked_reason": rule.get("blocked_reason")
            or "strong_pricing_rule_not_satisfied",
            "reference_only": True,
        }
    )
    if rule.get("manual_preview_price") is not None:
        candidate["manual_preview_price"] = rule.get("manual_preview_price")
        candidate["manual_preview_change_pct"] = rule.get("manual_preview_change_pct")
        candidate["preview_price_down_allowed"] = True
    if rule.get("recommended_alternative_action"):
        candidate["recommended_alternative_action"] = rule.get(
            "recommended_alternative_action"
        )


def _apply_trigger(candidate: dict[str, Any], rule: Mapping[str, Any]) -> None:
    target = float(rule["target_price"])
    candidate.update(
        {
            "price_action": rule["price_action"],
            "candidate_price": target,
            "conservative_price": target,
            "execution_price": target,
            "actual_change_pct": rule["actual_change_pct"],
            "configured_change_pct": rule["configured_change_pct"],
            "action_type": rule["action_type"],
            "action_target": {
                "room_type_id": candidate.get("room_type_id"),
                "room_type_name": candidate.get("room_type_name"),
                "channel": candidate.get("channel"),
                "ota_product_id": candidate.get("ota_product_id"),
                "ota_product_name": candidate.get("ota_product_name"),
            },
            "observe_minutes": rule["observe_minutes"],
            "observe_until": rule.get("observe_until"),
            "auto_execution_eligible": True,
            "approval_required": True,
            "handoff_to": "S6",
            "requires_s6_revalidation": True,
            "direct_price_trigger_allowed": False,
            "reason_codes": list(rule.get("reason_codes") or []),
            "risk_level": (
                "medium" if abs(float(rule["actual_change_pct"])) >= 0.08 else "low"
            ),
            "eligibility": "eligible_for_s6_dry_run",
            "blocked_reason": None,
            "reference_only": False,
        }
    )
    if rule["price_action"] == "decrease":
        candidate["effective_price_floor"] = rule.get("effective_price_floor")
    else:
        candidate["effective_price_ceiling"] = rule.get("effective_price_ceiling")
    candidate["calculation_trace"] = {
        "algorithm_mode": "strong_business_rule",
        "rule_version": VERSION,
        "base_price": candidate.get("current_price"),
        "configured_change_pct": rule.get("configured_change_pct"),
        "target_price": target,
        "actual_change_pct": rule.get("actual_change_pct"),
        "single_change_hard_cap": _thresholds()["single_change_hard_cap"],
        "price_bound_adjusted": bool(
            (
                rule["price_action"] == "decrease"
                and target == rule.get("effective_price_floor")
            )
            or (
                rule["price_action"] == "increase"
                and target == rule.get("effective_price_ceiling")
            )
        ),
        "explain_consistent": True,
    }


def _attach_rule_evidence(candidate: dict[str, Any], rule: Mapping[str, Any]) -> None:
    fields = (
        "rule_version",
        "sales_progress_delta_pp",
        "total_rooms",
        "committed_sold",
        "remaining_rooms",
        "remaining_room_ratio",
        "room_type_inventory_tight",
        "room_type_inventory_loose",
        "market_heat_ratio",
        "market_status",
        "market_not_cold",
        "market_evidence_source",
        "browse_ratio",
        "traffic_status",
        "traffic_evidence_source",
        "second_conversion_weak",
        "second_conversion_weak_signal",
        "second_conversion_sample_valid",
        "second_conversion_preview_sample_valid",
        "second_conversion_evidence_available",
        "second_conversion_current",
        "second_conversion_baseline_p25",
        "second_conversion_peer_index",
        "second_conversion_ratio",
        "price_ratio_vs_avg",
        "price_comparison_basis",
        "price_high",
        "baseline_price_median",
        "baseline_price_p20",
        "baseline_price_p20_raw_equivalent",
        "effective_price_floor",
        "effective_price_ceiling",
        "product_type_supported",
        "product_sellable",
        "product_healthy",
        "mapping_valid",
        "guard_valid",
        "raise_rule_allowed",
        "lower_rule_business_ready",
        "lower_rule_allowed",
        "missing_rule_evidence",
    )
    candidate["pricing_rule_mode"] = (
        "strong_business_rule"
        if rule.get("status") == "triggered"
        else "legacy_weighted_reference"
    )
    candidate["strong_pricing_rule_status"] = rule.get("status")
    candidate["strong_pricing_rule_action_type"] = rule.get("action_type")
    for field in fields:
        if field in rule:
            candidate[field] = rule.get(field)


def _rebuild_decision_ref(
    candidate: dict[str, Any],
    *,
    result: Mapping[str, Any],
    hotel_id: str,
    target_stay_date: str,
) -> None:
    from runtime.algorithms.revenue_decision_engine import build_s5_decision_ref

    candidate["decision_ref"] = build_s5_decision_ref(
        candidate,
        freshness_status=result.get("freshness_status"),
        business_date=target_stay_date,
        hotel_id=hotel_id,
        guard_version=str(
            candidate.get("price_guard_policy_version") or "strong-pricing-rule-v1"
        ),
        price_guard_policy_id=candidate.get("price_guard_policy_id"),
    )


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.algorithms import s5_real_candidates as s5_module

    previous_build = s5_module.build_s5_real_candidates
    if getattr(previous_build, "_S5_STRONG_PRICING_RULES_V1", False):
        return

    def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
        original_query = kwargs.get("query")
        if not callable(original_query):
            return previous_build(*args, **kwargs)

        captured: dict[str, dict[str, Any]] = {}
        patched_kwargs = dict(kwargs)
        patched_kwargs["query"] = _capture_price_query(original_query, captured)
        result = dict(previous_build(*args, **patched_kwargs))

        s15_result = kwargs.get("s15_result")
        s16_result = kwargs.get("s16_result")
        as_of_time = kwargs.get("as_of_time") or result.get("as_of_time")
        target_stay_date = _text(
            kwargs.get("target_stay_date") or result.get("target_stay_date")
        )[:10]
        hotel_id = _text(kwargs.get("hotel_id") or result.get("hotel_id"))
        rules = _thresholds()
        strong_count = 0
        reference_count = 0

        for candidate in result.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            product_id = _text(candidate.get("ota_product_id"))
            rule = evaluate_strong_pricing_rule(
                candidate,
                product_row=captured.get(product_id, {}),
                s15_result=s15_result,
                s16_result=s16_result,
                as_of_time=as_of_time,
                thresholds=rules,
            )
            _attach_rule_evidence(candidate, rule)
            if rule.get("status") == "triggered":
                _apply_trigger(candidate, rule)
                strong_count += 1
            else:
                _apply_hold(candidate, rule)
                reference_count += 1
            _rebuild_decision_ref(
                candidate,
                result=result,
                hotel_id=hotel_id,
                target_stay_date=target_stay_date,
            )

        candidates = [
            item for item in (result.get("candidates") or []) if isinstance(item, dict)
        ]
        candidates.sort(
            key=lambda item: (
                item.get("strong_pricing_rule_status") != "triggered",
                item.get("risk_level") != "low",
                _text(item.get("ota_product_name")),
            )
        )
        result["candidates"] = candidates
        result["eligible_for_s6_count"] = sum(
            bool(item.get("auto_execution_eligible"))
            and item.get("eligibility") == "eligible_for_s6_dry_run"
            for item in candidates
        )
        result.update(
            {
                "s5_pricing_algorithm_version": VERSION,
                "s5_pricing_algorithm_mode": "strong_rules_with_legacy_reference",
                "strong_rule_candidate_count": strong_count,
                "legacy_reference_candidate_count": reference_count,
                "traffic_price_down_policy": {
                    "weak_browse_ratio_below": rules["browse_weak_ratio"],
                    "recovering_browse_ratio_below": rules["browse_healthy_ratio"],
                    "healthy_browse_ratio_at_least": rules["browse_healthy_ratio"],
                    "weak_action": "promotion_review_no_price_down",
                    "recovering_action": "manual_preview_only",
                    "healthy_action": "strong_lower_rule_may_handoff_to_s6",
                },
            }
        )
        return result

    build_s5_real_candidates._S5_STRONG_PRICING_RULES_V1 = True  # type: ignore[attr-defined]
    s5_module.build_s5_real_candidates = build_s5_real_candidates

    router = sys.modules.get("runtime.feishu_command_router")
    if router is not None and hasattr(router, "build_s5_real_candidates"):
        router.build_s5_real_candidates = build_s5_real_candidates

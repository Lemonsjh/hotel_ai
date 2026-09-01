from __future__ import annotations

import datetime as dt
import math
import re
from collections import defaultdict
from typing import Any, Mapping, Sequence

VERSION = "meituan-activity-net-price.v1"
_INSTALLED = False
_ACTIVE_STATUSES = {"进行中", "已参与", "active", "running", "enabled"}
_DISCOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*折")
_DATE_RANGE_RE = re.compile(
    r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*至\s*"
    r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})"
)
_CROSS_MIDNIGHT_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*-\s*次日\s*(\d{1,2}):(\d{2})"
)


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_commission_rate(value: Any) -> float | None:
    """Normalize 12.00%, 12, or 0.12 to 0.12."""

    if value in (None, ""):
        return None
    text = str(value).strip()
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    try:
        rate = float(text)
    except (TypeError, ValueError):
        return None
    if percent or rate > 1:
        rate /= 100.0
    if rate < 0 or rate >= 1:
        return None
    return rate


def extract_discount_factors(value: Any) -> list[float]:
    factors: list[float] = []
    for raw in _DISCOUNT_RE.findall(str(value or "")):
        try:
            factor = float(raw) / 10.0
        except ValueError:
            continue
        if 0 < factor <= 1:
            factors.append(factor)
    return factors


def activity_factor(value: Any) -> float | None:
    """Use one factor per activity; tiered activities use their lowest factor."""

    factors = extract_discount_factors(value)
    return min(factors) if factors else None


def _as_date(value: Any) -> dt.date | None:
    text = str(value or "")[:10].replace("/", "-")
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def _as_datetime(value: Any) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        result = value
    elif value in (None, ""):
        return None
    else:
        try:
            result = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return result.replace(tzinfo=None) if result.tzinfo else result


def _date_range_active(value: Any, target_date: dt.date) -> bool:
    text = str(value or "").strip()
    if not text or "全年" in text:
        return True
    match = _DATE_RANGE_RE.search(text)
    if not match:
        return True
    numbers = [int(item) for item in match.groups()]
    try:
        start = dt.date(numbers[0], numbers[1], numbers[2])
        end = dt.date(numbers[3], numbers[4], numbers[5])
    except ValueError:
        return False
    return start <= target_date <= end


def _time_window_active(value: Any, as_of: dt.datetime) -> bool:
    text = str(value or "")
    match = _CROSS_MIDNIGHT_RE.search(text)
    if not match:
        return True
    start = dt.time(int(match.group(1)), int(match.group(2)))
    end = dt.time(int(match.group(3)), int(match.group(4)))
    now = as_of.time()
    return now >= start or now <= end


def _activity_is_active(
    row: Mapping[str, Any],
    *,
    target_date: dt.date,
    as_of: dt.datetime,
) -> bool:
    status = str(row.get("activity_status") or "").strip()
    if status and status.lower() not in _ACTIVE_STATUSES and status not in _ACTIVE_STATUSES:
        return False
    return _date_range_active(row.get("activity_time_range"), target_date) and _time_window_active(
        row.get("activity_rule_labels"), as_of
    )


def _activity_rows(
    repository: Any,
    hotel_id: str,
    as_of_datetime: str,
) -> list[dict[str, Any]]:
    query = getattr(repository, "_query", None)
    if not callable(query):
        return []
    try:
        rows = query(
            """
            SELECT a.hotel_id,
                   a.snapshot_time AS activity_snapshot_time,
                   a.activity_source_type,
                   a.activity_id,
                   a.activity_name,
                   a.activity_status,
                   a.activity_time_range,
                   a.activity_rule_labels,
                   d.snapshot_time AS detail_snapshot_time,
                   d.ota_product_id,
                   d.room_type_id,
                   d.room_type_name,
                   d.remaining_inventory
            FROM meituan_ota_promotion_activity a
            INNER JOIN meituan_ota_activity_product_detail d
              ON d.hotel_id=a.hotel_id
             AND d.activity_id=a.activity_id
            WHERE a.hotel_id=%s
              AND a.snapshot_time=(
                  SELECT MAX(snapshot_time)
                  FROM meituan_ota_promotion_activity
                  WHERE hotel_id=%s AND snapshot_time<=%s
              )
              AND d.snapshot_time=(
                  SELECT MAX(snapshot_time)
                  FROM meituan_ota_activity_product_detail
                  WHERE hotel_id=%s AND snapshot_time<=%s
              )
            ORDER BY d.ota_product_id, a.activity_id
            """,
            (
                hotel_id,
                hotel_id,
                as_of_datetime,
                hotel_id,
                as_of_datetime,
            ),
        )
    except Exception:
        return []
    return [dict(row) for row in rows]


def enrich_product_prices(
    price_rows: Sequence[Mapping[str, Any]],
    activity_rows: Sequence[Mapping[str, Any]],
    *,
    target_date: str,
    as_of_datetime: str,
) -> list[dict[str, Any]]:
    target = _as_date(target_date)
    as_of = _as_datetime(as_of_datetime)
    if target is None or as_of is None:
        return [dict(row) for row in price_rows]

    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for source in activity_rows:
        row = dict(source)
        product_id = str(row.get("ota_product_id") or "").strip()
        factor = activity_factor(row.get("activity_rule_labels"))
        if not product_id or factor is None:
            continue
        if not _activity_is_active(row, target_date=target, as_of=as_of):
            continue
        row["discount_factor"] = factor
        row["all_rule_factors"] = extract_discount_factors(
            row.get("activity_rule_labels")
        )
        by_product[product_id].append(row)

    enriched: list[dict[str, Any]] = []
    for source in price_rows:
        row = dict(source)
        product_id = str(row.get("ota_product_id") or "").strip()
        room_id = str(row.get("room_type_id") or "").strip()
        raw_price = _n(row.get("ota_sale_price"))
        commission_rate = normalize_commission_rate(row.get("commission_rate"))
        matched: list[dict[str, Any]] = []
        seen_activity_ids: set[str] = set()
        for candidate in by_product.get(product_id, []):
            candidate_room = str(candidate.get("room_type_id") or "").strip()
            if candidate_room and room_id and candidate_room != room_id:
                continue
            activity_id = str(candidate.get("activity_id") or "")
            if not activity_id or activity_id in seen_activity_ids:
                continue
            seen_activity_ids.add(activity_id)
            matched.append(candidate)
        matched.sort(key=lambda item: str(item.get("activity_id") or ""))
        factors = [float(item["discount_factor"]) for item in matched]
        combined_factor = math.prod(factors) if factors else 1.0
        commission_amount = (
            raw_price * commission_rate
            if raw_price is not None and commission_rate is not None
            else None
        )
        commission_net_base = (
            raw_price * (1.0 - commission_rate)
            if raw_price is not None and commission_rate is not None
            else None
        )
        activity_net = (
            commission_net_base * combined_factor
            if commission_net_base is not None
            else None
        )
        row.update(
            {
                "commission_rate_normalized": commission_rate,
                "commission_amount": commission_amount,
                "commission_net_base_price": commission_net_base,
                "matched_activity_count": len(matched),
                "combined_activity_factor": combined_factor,
                "estimated_activity_net_price": activity_net,
                "activity_calculation_order": (
                    "raw_price_then_commission_then_compound_all_matched_activities"
                ),
                "activity_factors_compounded": True,
                "user_coupon_included": False,
                "applied_activities": [
                    {
                        "activity_id": item.get("activity_id"),
                        "activity_name": item.get("activity_name"),
                        "activity_rule_labels": item.get("activity_rule_labels"),
                        "discount_factor": item.get("discount_factor"),
                        "all_rule_factors": item.get("all_rule_factors") or [],
                    }
                    for item in matched
                ],
            }
        )
        enriched.append(row)
    return enriched


def _current_room_prices(
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> list[dict[str, Any]]:
    query = getattr(repository, "_query", None)
    if not callable(query):
        return []
    try:
        rows = query(
            """
            SELECT g.hotel_id, g.business_date, g.snapshot_time,
                   g.ota_product_id, g.ota_product_name, g.rate_plan_name,
                   g.is_super_deal, g.ota_sale_price, g.commission_rate,
                   g.room_type_id, g.room_type_name,
                   m.mapping_status, m.is_active AS mapping_active,
                   m.is_hour_room, m.price_editable_flag
            FROM meituan_ota_goods_price_mapping g
            INNER JOIN hotel_room_type_mapping m
              ON m.hotel_id=g.hotel_id
             AND m.source_product_id=g.ota_product_id
             AND m.source_platform IN ('美团','meituan')
             AND m.mapping_status='AUTO'
             AND m.is_active=1
            WHERE g.hotel_id=%s AND g.business_date=%s
              AND g.snapshot_time<=%s
              AND g.room_type_id IS NOT NULL AND g.room_type_id<>''
            ORDER BY g.snapshot_time DESC, g.ota_sale_price ASC
            """,
            (hotel_id, target_date, as_of_datetime),
        )
    except Exception:
        return []
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for source in rows:
        row = dict(source)
        room_id = str(row.get("room_type_id") or "")
        product_id = str(row.get("ota_product_id") or "")
        if not room_id or not product_id or (room_id, product_id) in seen:
            continue
        seen.add((room_id, product_id))
        result.append(row)
    activities = _activity_rows(repository, hotel_id, as_of_datetime)
    return enrich_product_prices(
        result,
        activities,
        target_date=target_date,
        as_of_datetime=as_of_datetime,
    )


def _reference_status(value: Any, median: Any) -> tuple[str, float | None]:
    left = _n(value)
    right = _n(median)
    if left is None or right in (None, 0):
        return "unavailable", None
    ratio = left / right
    if ratio >= 1.08:
        return "above_reference", ratio
    if ratio <= 0.95:
        return "below_reference", ratio
    return "near_reference", ratio


def _price_analysis_wrapper(previous: Any) -> Any:
    def analyze(
        payload: Mapping[str, Any],
        current_rows: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        result = dict(previous(payload, current_rows))
        rows_by_product = {
            str(row.get("ota_product_id") or ""): dict(row)
            for row in current_rows
            if row.get("ota_product_id") not in (None, "")
        }
        reference_product_ids: list[str] = []
        for room in result.get("room_results") or []:
            baseline_median = _n(room.get("baseline_median"))
            for product in room.get("product_results") or []:
                enriched = rows_by_product.get(
                    str(product.get("ota_product_id") or ""), {}
                )
                estimate = _n(enriched.get("estimated_activity_net_price"))
                reference_status, reference_ratio = _reference_status(
                    estimate, baseline_median
                )
                product.update(
                    {
                        "raw_price": _n(enriched.get("ota_sale_price")),
                        "commission_rate": enriched.get(
                            "commission_rate_normalized"
                        ),
                        "commission_net_base_price": _n(
                            enriched.get("commission_net_base_price")
                        ),
                        "matched_activity_count": int(
                            enriched.get("matched_activity_count") or 0
                        ),
                        "combined_activity_factor": _n(
                            enriched.get("combined_activity_factor")
                        ),
                        "estimated_activity_net_price": estimate,
                        "applied_activities": enriched.get(
                            "applied_activities"
                        )
                        or [],
                        "user_coupon_included": False,
                        "reference_status": reference_status,
                        "reference_ratio_vs_pms_transaction": reference_ratio,
                        "price_status": "reference_only",
                        "comparison_allowed": False,
                        "action_eligible": False,
                        "comparison_reason": (
                            "activity_net_estimate_vs_pms_transaction_reference"
                        ),
                    }
                )
                if estimate is not None:
                    reference_product_ids.append(
                        str(product.get("ota_product_id") or "")
                    )
            selected = rows_by_product.get(
                str(room.get("ota_product_id") or ""), {}
            )
            estimate = _n(selected.get("estimated_activity_net_price"))
            room.update(
                {
                    "raw_current_price": _n(selected.get("ota_sale_price")),
                    "commission_rate": selected.get(
                        "commission_rate_normalized"
                    ),
                    "commission_net_base_price": _n(
                        selected.get("commission_net_base_price")
                    ),
                    "matched_activity_count": int(
                        selected.get("matched_activity_count") or 0
                    ),
                    "combined_activity_factor": _n(
                        selected.get("combined_activity_factor")
                    ),
                    "estimated_activity_net_price": estimate,
                    "price_status": "reference_only",
                    "action_eligible": False,
                }
            )
        result.update(
            {
                "comparison_rule": (
                    "product_raw_price_then_commission_then_all_matched_activity_factors_compounded"
                ),
                "price_evidence_level": "reference_only",
                "reference_product_ids": reference_product_ids,
                "high_room_type_ids": [],
                "low_room_type_ids": [],
                "action_eligible_product_ids": [],
            }
        )
        return result

    analyze._MEITUAN_ACTIVITY_NET_PRICE_V1 = True  # type: ignore[attr-defined]
    return analyze


def _product_facts(
    repository: Any,
    hotel_id: str,
    target_date: str,
    as_of_datetime: str,
) -> list[dict[str, Any]]:
    rows = _current_room_prices(
        repository,
        hotel_id,
        target_date,
        as_of_datetime,
    )
    facts: list[dict[str, Any]] = []
    for row in rows:
        raw = _n(row.get("ota_sale_price"))
        if raw is None:
            continue
        facts.append(
            {
                "platform": "meituan",
                "ota_product_id": row.get("ota_product_id"),
                "ota_product_name": row.get("ota_product_name"),
                "room_type_id": row.get("room_type_id"),
                "room_type_name": row.get("room_type_name"),
                "product_type": (
                    "钟点房"
                    if str(row.get("is_hour_room") or "").lower()
                    in {"1", "true", "yes"}
                    else "超级团购"
                    if str(row.get("is_super_deal") or "").lower()
                    in {"1", "true", "yes"}
                    else "普通全天房"
                ),
                "current_price": raw,
                "raw_price": raw,
                "commission_rate": row.get("commission_rate_normalized"),
                "commission_net_base_price": _n(
                    row.get("commission_net_base_price")
                ),
                "matched_activity_count": int(
                    row.get("matched_activity_count") or 0
                ),
                "combined_activity_factor": _n(
                    row.get("combined_activity_factor")
                ),
                "estimated_activity_net_price": _n(
                    row.get("estimated_activity_net_price")
                ),
                "applied_activities": row.get("applied_activities") or [],
                "activity_factors_compounded": True,
                "user_coupon_included": False,
                "history_status": "unavailable",
                "price_status": "reference_only",
                "comparison_allowed": False,
                "action_eligible": False,
                "comparison_reason": (
                    "exact_product_history_unavailable_activity_net_is_reference_only"
                ),
            }
        )
    return facts


def _money(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"¥{number:,.0f}"


def _pct(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.1f}%"


def _dynamic_message_wrapper(previous: Any) -> Any:
    def render(report: Mapping[str, Any]) -> str:
        text = previous(report)
        dynamic = report.get("dynamic_diagnosis") or {}
        products = dynamic.get("product_prices") or []
        for product in products[:5]:
            name = (
                product.get("ota_product_name")
                or product.get("ota_product_id")
                or "未命名商品"
            )
            old = (
                f"  - {product.get('product_type')}｜{name}："
                f"{_money(product.get('current_price'))}。"
            )
            activities = product.get("applied_activities") or []
            factor_text = " × ".join(
                f"{float(item.get('discount_factor')):.2f}"
                for item in activities
                if _n(item.get("discount_factor")) is not None
            )
            if not factor_text:
                factor_text = "1.00"
            new = (
                f"  - {product.get('product_type')}｜{name}："
                f"美团底价 {_money(product.get('raw_price'))}；"
                f"扣佣金率 {_pct(product.get('commission_rate'))} 后底价 "
                f"{_money(product.get('commission_net_base_price'))}；"
                f"匹配 {product.get('matched_activity_count') or 0} 个活动，"
                f"系数 {factor_text} 连续相乘；"
                f"活动后预计酒店收入 "
                f"{_money(product.get('estimated_activity_net_price'))}；"
                "不含用户券。"
            )
            text = text.replace(old, new)
        return text

    render._MEITUAN_ACTIVITY_NET_PRICE_V1 = True  # type: ignore[attr-defined]
    return render


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import (
        s15_price_scope_patch,
        s15_s16_responsibility_patch,
        s15_technical_analysis,
        s15_technical_sources,
        s16_dynamic_diagnosis,
    )

    s15_technical_sources._current_room_prices = _current_room_prices
    s15_technical_analysis._current_room_prices = _current_room_prices
    s16_dynamic_diagnosis._current_room_prices = _current_room_prices
    s16_dynamic_diagnosis._product_facts = _product_facts

    previous_analysis = s15_price_scope_patch.analyze_price_scopes
    if not getattr(previous_analysis, "_MEITUAN_ACTIVITY_NET_PRICE_V1", False):
        wrapped_analysis = _price_analysis_wrapper(previous_analysis)
        s15_price_scope_patch.analyze_price_scopes = wrapped_analysis
        s15_technical_sources._price_analysis = wrapped_analysis
        s15_technical_analysis._price_analysis = wrapped_analysis

    previous_message = s15_s16_responsibility_patch._dynamic_message
    if not getattr(previous_message, "_MEITUAN_ACTIVITY_NET_PRICE_V1", False):
        s15_s16_responsibility_patch._dynamic_message = _dynamic_message_wrapper(
            previous_message
        )

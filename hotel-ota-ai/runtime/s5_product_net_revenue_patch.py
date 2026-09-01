from __future__ import annotations

import datetime as dt
import re
import sys
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, Callable, Mapping, Sequence


VERSION = "s5-meituan-net-revenue.v2"
MEMBER_EXPECTED_FACTOR = Decimal("0.85")
FORMULA = (
    "ota_sale_price * (1 - commission_rate) * product(activity_factors) "
    "* member_expected_factor"
)
_ACTIVE_STATUSES = {"进行中", "已参与", "active", "running", "enabled"}
_DISCOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*折")
_DATE_RANGE_RE = re.compile(
    r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*至\s*"
    r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})"
)
_CROSS_MIDNIGHT_RE = re.compile(
    r"(\d{1,2}):(\d{2})\s*-\s*次日\s*(\d{1,2}):(\d{2})"
)
_INSTALLED = False


def _text(value: Any) -> str:
    return str(value or "").strip()


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None


def normalize_commission_rate_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    rate = _decimal(text)
    if rate is None:
        return None
    if percent or rate > Decimal("1"):
        rate /= Decimal("100")
    if rate < 0 or rate >= 1:
        return None
    return rate


def extract_activity_factors_decimal(value: Any) -> list[Decimal]:
    result: list[Decimal] = []
    for raw in _DISCOUNT_RE.findall(str(value or "")):
        factor = _decimal(raw)
        if factor is None:
            continue
        factor /= Decimal("10")
        if 0 < factor <= 1:
            result.append(factor)
    return result


def select_activity_factor_decimal(value: Any) -> Decimal | None:
    factors = extract_activity_factors_decimal(value)
    return min(factors) if factors else None


def _activity_factor_from_row(row: Mapping[str, Any]) -> Decimal | None:
    for key in ("discount_factor", "activity_factor", "factor"):
        factor = _decimal(row.get(key))
        if factor is not None and 0 < factor <= 1:
            return factor
    return select_activity_factor_decimal(row.get("activity_rule_labels"))


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
    values = [int(item) for item in match.groups()]
    try:
        start = dt.date(values[0], values[1], values[2])
        end = dt.date(values[3], values[4], values[5])
    except ValueError:
        return False
    return start <= target_date <= end


def _time_window_active(value: Any, as_of: dt.datetime) -> bool:
    match = _CROSS_MIDNIGHT_RE.search(str(value or ""))
    if not match:
        return True
    start = dt.time(int(match.group(1)), int(match.group(2)))
    end = dt.time(int(match.group(3)), int(match.group(4)))
    current = as_of.time()
    return current >= start or current <= end


def _activity_is_active(
    row: Mapping[str, Any],
    *,
    target_date: dt.date,
    as_of: dt.datetime,
) -> bool:
    status = _text(row.get("activity_status"))
    if status and status not in _ACTIVE_STATUSES and status.lower() not in _ACTIVE_STATUSES:
        return False
    return _date_range_active(
        row.get("activity_time_range"), target_date
    ) and _time_window_active(row.get("activity_rule_labels"), as_of)


def calculate_net_revenue(
    ota_sale_price: Any,
    commission_rate: Any,
    activity_factors: Sequence[Any],
    member_expected_factor: Any = MEMBER_EXPECTED_FACTOR,
) -> dict[str, Any]:
    price = _decimal(ota_sale_price)
    if price is None or price < 0:
        return {"status": "unavailable", "reason": "ota_sale_price_invalid"}

    commission = normalize_commission_rate_decimal(commission_rate)
    if commission is None:
        return {"status": "unavailable", "reason": "commission_rate_missing_or_invalid"}

    factors: list[Decimal] = []
    for value in activity_factors:
        factor = _decimal(value)
        if factor is None or factor <= 0 or factor > 1:
            return {"status": "unavailable", "reason": "activity_factor_invalid"}
        factors.append(factor)

    member_factor = _decimal(member_expected_factor)
    if member_factor is None or member_factor <= 0 or member_factor > 1:
        return {"status": "unavailable", "reason": "member_expected_factor_invalid"}

    with localcontext() as context:
        context.prec = 50
        combined = Decimal("1")
        for factor in factors:
            combined *= factor
        commission_net_base = price * (Decimal("1") - commission)
        estimated_revenue = commission_net_base * combined * member_factor
    return {
        "status": "ok",
        "ota_sale_price_exact": format(price, "f"),
        "commission_rate_exact": format(commission, "f"),
        "commission_net_base_price_exact": format(commission_net_base, "f"),
        "combined_activity_factor_exact": format(combined, "f"),
        "member_expected_factor_exact": format(member_factor, "f"),
        "estimated_hotel_revenue_exact": format(estimated_revenue, "f"),
        "ota_sale_price": float(price),
        "commission_rate": float(commission),
        "commission_net_base_price": float(commission_net_base),
        "combined_activity_factor": float(combined),
        "member_expected_factor": float(member_factor),
        "estimated_hotel_revenue": float(estimated_revenue),
    }


def _payload(result: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {}
    value = result.get("payload")
    return dict(value) if isinstance(value, Mapping) else {}


def _rows(result: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    payload = _payload(result)
    values = (
        payload.get("rows")
        or payload.get("price_snapshots")
        or payload.get("activity_rows")
        or payload.get("activity_summaries")
        or payload.get("activity_product_details")
        or []
    )
    return [dict(item) for item in values if isinstance(item, Mapping)]


def _source_available(result: Mapping[str, Any] | None) -> bool:
    if not isinstance(result, Mapping) or result.get("status") != "ok":
        return False
    status = _text(_payload(result).get("source_status")).lower()
    return status not in {
        "unavailable",
        "data_gap",
        "schema_drift",
        "error",
        "failed",
    }


def _platform(row: Mapping[str, Any]) -> str:
    table_hint = _text(
        row.get("table_key") or row.get("source_table") or row.get("table_name")
    ).lower()
    if "meituan" in table_hint:
        return "meituan"
    if "ctrip" in table_hint:
        return "ctrip"
    value = _text(
        row.get("source_platform")
        or row.get("channel_source")
        or row.get("platform")
        or row.get("activity_source_type")
    ).lower()
    return "meituan" if value in {"美团", "meituan", "mt"} else value


def _product_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("ota_product_id") or row.get("source_product_id"))


def _room_type_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("room_type_id") or row.get("pms_room_type_id"))


def _activity_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("activity_id"))


def _query_template(
    query: Callable[..., dict[str, Any]],
    template: str,
    *,
    hotel_id: str,
    target_stay_date: str,
    as_of_time: str | None,
) -> dict[str, Any]:
    try:
        return query(template, hotel_id, as_of_time=as_of_time)
    except TypeError:
        try:
            return query(
                template,
                hotel_id,
                date=target_stay_date,
                as_of_time=as_of_time,
            )
        except Exception as exc:
            return {
                "status": "data_gap",
                "reason": f"{template}_query_failed:{exc.__class__.__name__}",
                "payload": {"source_status": "unavailable", "rows": []},
            }
    except Exception as exc:
        return {
            "status": "data_gap",
            "reason": f"{template}_query_failed:{exc.__class__.__name__}",
            "payload": {"source_status": "unavailable", "rows": []},
        }


def _capture_price_query(
    query: Callable[..., dict[str, Any]],
    captured: dict[str, Any],
) -> Callable[..., dict[str, Any]]:
    def wrapped(template: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        result = query(template, *args, **kwargs)
        if template == "ota_price_mapping":
            captured["price_result"] = result
        return result

    return wrapped


def _find_price_row(
    rows: Sequence[Mapping[str, Any]],
    *,
    product_id: str,
    room_type_id: str,
) -> dict[str, Any]:
    product_rows = [row for row in rows if _product_id(row) == product_id]
    exact = [row for row in product_rows if _room_type_id(row) == room_type_id]
    selected = exact or product_rows
    return dict(selected[0]) if selected else {}


def _activity_evidence(
    summary_result: Mapping[str, Any],
    detail_result: Mapping[str, Any],
    *,
    product_id: str,
    room_type_id: str,
    target_stay_date: str,
    as_of_time: str | None,
) -> dict[str, Any]:
    target_date = _as_date(target_stay_date)
    as_of = _as_datetime(as_of_time or target_stay_date)
    if target_date is None or as_of is None:
        return {"status": "unavailable", "reason": "activity_time_context_invalid"}
    if not _source_available(summary_result):
        return {"status": "unavailable", "reason": "activity_summary_source_unavailable"}

    summaries = [
        row for row in _rows(summary_result) if _platform(row) in {"", "meituan"}
    ]
    if not summaries:
        return {
            "status": "ok",
            "matched_activity_count": 0,
            "activity_factors": [],
            "applied_activities": [],
        }
    if not _source_available(detail_result):
        return {
            "status": "unavailable",
            "reason": "activity_product_detail_source_unavailable",
        }
    raw_details = _rows(detail_result)
    if not raw_details:
        return {
            "status": "unavailable",
            "reason": "activity_product_detail_rows_missing",
        }

    details = [
        row
        for row in raw_details
        if _platform(row) in {"", "meituan"} and _product_id(row) == product_id
    ]
    summary_by_id: dict[str, dict[str, Any]] = {}
    for row in summaries:
        activity_id = _activity_id(row)
        if activity_id and activity_id not in summary_by_id:
            summary_by_id[activity_id] = dict(row)

    applied: list[dict[str, Any]] = []
    seen: set[str] = set()
    for detail in details:
        candidate_room = _room_type_id(detail)
        if candidate_room and room_type_id and candidate_room != room_type_id:
            continue
        activity_id = _activity_id(detail)
        if not activity_id or activity_id in seen:
            continue
        summary = summary_by_id.get(activity_id)
        if not summary:
            continue
        merged = dict(detail)
        merged.update(
            {
                key: value
                for key, value in summary.items()
                if value not in (None, "")
            }
        )
        if not _activity_is_active(merged, target_date=target_date, as_of=as_of):
            continue
        selected_factor = _activity_factor_from_row(merged)
        if selected_factor is None:
            return {
                "status": "unavailable",
                "reason": "active_activity_factor_unavailable",
                "activity_id": activity_id,
            }
        seen.add(activity_id)
        all_factors = extract_activity_factors_decimal(
            merged.get("activity_rule_labels")
        )
        applied.append(
            {
                "activity_id": activity_id,
                "activity_name": merged.get("activity_name"),
                "activity_rule_labels": merged.get("activity_rule_labels"),
                "discount_factor": float(selected_factor),
                "discount_factor_exact": format(selected_factor, "f"),
                "all_rule_factors_exact": [
                    format(item, "f") for item in all_factors
                ],
                "factor_selection_rule": "minimum_factor_per_activity",
            }
        )
    applied.sort(key=lambda item: str(item.get("activity_id") or ""))
    return {
        "status": "ok",
        "matched_activity_count": len(applied),
        "activity_factors": [
            item["discount_factor_exact"] for item in applied
        ],
        "applied_activities": applied,
    }


def _append_quality_flag(candidate: dict[str, Any], flag: str) -> None:
    candidate["quality_flags"] = list(
        dict.fromkeys(
            [
                *[str(item) for item in (candidate.get("quality_flags") or [])],
                flag,
            ]
        )
    )


def _display_price(candidate: Mapping[str, Any]) -> Any:
    if candidate.get("limited_evidence_preview"):
        return candidate.get("manual_preview_price")
    return candidate.get("candidate_price") or candidate.get("execution_price")


def _enrich_candidate(
    candidate: dict[str, Any],
    *,
    price_rows: Sequence[Mapping[str, Any]],
    summary_result: Mapping[str, Any],
    detail_result: Mapping[str, Any],
    target_stay_date: str,
    as_of_time: str | None,
) -> None:
    candidate.update(
        {
            "s5_net_revenue_formula_version": VERSION,
            "s5_net_revenue_formula": FORMULA,
            "s5_repricing_price_basis": "ota_original_sale_price",
            "s5_net_revenue_display_only": True,
            "s5_net_revenue_user_coupon_included": False,
        }
    )
    channel = _text(candidate.get("channel")).lower()
    if channel not in {"meituan", "美团", "mt"}:
        candidate["s5_net_revenue_calculation_status"] = (
            "not_applicable_non_meituan"
        )
        return

    product_id = _text(candidate.get("ota_product_id"))
    room_type_id = _text(candidate.get("room_type_id"))
    price_row = _find_price_row(
        price_rows,
        product_id=product_id,
        room_type_id=room_type_id,
    )
    commission_value = (
        price_row.get("commission_rate")
        if price_row.get("commission_rate") not in (None, "")
        else candidate.get("commission_rate")
    )
    activity = _activity_evidence(
        summary_result,
        detail_result,
        product_id=product_id,
        room_type_id=room_type_id,
        target_stay_date=target_stay_date,
        as_of_time=as_of_time,
    )
    candidate["s5_activity_evidence_status"] = activity.get("status")
    candidate["s5_activity_evidence_reason"] = activity.get("reason")
    candidate["matched_activity_count"] = int(
        activity.get("matched_activity_count") or 0
    )
    candidate["applied_activities"] = activity.get("applied_activities") or []

    if activity.get("status") != "ok":
        candidate["s5_net_revenue_calculation_status"] = "unavailable"
        candidate["s5_net_revenue_calculation_reason"] = activity.get("reason")
        _append_quality_flag(
            candidate,
            f"net_revenue_unavailable:{activity.get('reason') or 'activity_evidence'}",
        )
        return

    current = calculate_net_revenue(
        candidate.get("current_price"),
        commission_value,
        activity.get("activity_factors") or [],
    )
    candidate["s5_net_revenue_calculation_status"] = current.get("status")
    candidate["s5_net_revenue_calculation_reason"] = current.get("reason")
    if current.get("status") != "ok":
        _append_quality_flag(
            candidate,
            f"net_revenue_unavailable:{current.get('reason') or 'calculation'}",
        )
        return

    candidate.update(
        {
            "commission_rate": current.get("commission_rate"),
            "commission_rate_exact": current.get("commission_rate_exact"),
            "commission_net_base_price": current.get(
                "commission_net_base_price"
            ),
            "commission_net_base_price_exact": current.get(
                "commission_net_base_price_exact"
            ),
            "combined_activity_factor": current.get(
                "combined_activity_factor"
            ),
            "combined_activity_factor_exact": current.get(
                "combined_activity_factor_exact"
            ),
            "member_expected_factor": current.get("member_expected_factor"),
            "member_expected_factor_exact": current.get(
                "member_expected_factor_exact"
            ),
            "estimated_hotel_revenue": current.get(
                "estimated_hotel_revenue"
            ),
            "estimated_hotel_revenue_exact": current.get(
                "estimated_hotel_revenue_exact"
            ),
        }
    )

    proposed_price = _display_price(candidate)
    proposed = calculate_net_revenue(
        proposed_price,
        commission_value,
        activity.get("activity_factors") or [],
    )
    if proposed.get("status") == "ok":
        candidate.update(
            {
                "proposed_ota_sale_price": proposed.get("ota_sale_price"),
                "proposed_ota_sale_price_exact": proposed.get(
                    "ota_sale_price_exact"
                ),
                "proposed_estimated_hotel_revenue": proposed.get(
                    "estimated_hotel_revenue"
                ),
                "proposed_estimated_hotel_revenue_exact": proposed.get(
                    "estimated_hotel_revenue_exact"
                ),
            }
        )


def apply_s5_product_net_revenue(
    result: Mapping[str, Any],
    *,
    price_result: Mapping[str, Any] | None,
    activity_summary_result: Mapping[str, Any],
    activity_detail_result: Mapping[str, Any],
) -> dict[str, Any]:
    copied = dict(result)
    price_rows = _rows(price_result)
    candidates = [
        dict(item)
        for item in (copied.get("candidates") or [])
        if isinstance(item, Mapping)
    ]
    for candidate in candidates:
        _enrich_candidate(
            candidate,
            price_rows=price_rows,
            summary_result=activity_summary_result,
            detail_result=activity_detail_result,
            target_stay_date=_text(copied.get("target_stay_date")),
            as_of_time=copied.get("as_of_time"),
        )
    copied["candidates"] = candidates
    copied["s5_net_revenue_formula_version"] = VERSION
    copied["s5_net_revenue_formula"] = FORMULA
    copied["s5_repricing_price_basis"] = "ota_original_sale_price"
    copied["s5_net_revenue_display_only"] = True
    copied["s5_activity_summary_source_available"] = _source_available(
        activity_summary_result
    )
    copied["s5_activity_detail_source_available"] = _source_available(
        activity_detail_result
    )
    copied["s5_net_revenue_available_count"] = sum(
        item.get("s5_net_revenue_calculation_status") == "ok"
        for item in candidates
    )
    return copied


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.algorithms import s5_real_candidates as s5_module

    previous_build = s5_module.build_s5_real_candidates
    if getattr(previous_build, "_S5_PRODUCT_NET_REVENUE_V1", False):
        return

    def build_s5_real_candidates(*args: Any, **kwargs: Any) -> dict[str, Any]:
        original_query = kwargs.get("query")
        if not callable(original_query):
            return previous_build(*args, **kwargs)

        captured: dict[str, Any] = {}
        patched_kwargs = dict(kwargs)
        patched_kwargs["query"] = _capture_price_query(
            original_query,
            captured,
        )
        result = previous_build(*args, **patched_kwargs)
        hotel_id = _text(kwargs.get("hotel_id") or result.get("hotel_id"))
        target_stay_date = _text(
            kwargs.get("target_stay_date") or result.get("target_stay_date")
        )
        as_of_time = kwargs.get("as_of_time") or result.get("as_of_time")
        summary_result = _query_template(
            original_query,
            "ota_activity_summary",
            hotel_id=hotel_id,
            target_stay_date=target_stay_date,
            as_of_time=as_of_time,
        )
        detail_result = _query_template(
            original_query,
            "ota_activity_product_detail",
            hotel_id=hotel_id,
            target_stay_date=target_stay_date,
            as_of_time=as_of_time,
        )
        return apply_s5_product_net_revenue(
            result,
            price_result=captured.get("price_result"),
            activity_summary_result=summary_result,
            activity_detail_result=detail_result,
        )

    build_s5_real_candidates._S5_PRODUCT_NET_REVENUE_V1 = True  # type: ignore[attr-defined]
    s5_module.build_s5_real_candidates = build_s5_real_candidates

    router = sys.modules.get("runtime.feishu_command_router")
    if router is not None and hasattr(router, "build_s5_real_candidates"):
        router.build_s5_real_candidates = build_s5_real_candidates

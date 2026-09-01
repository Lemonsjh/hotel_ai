from __future__ import annotations

import math
import sys
from typing import Any, Mapping

_INSTALLED = False
VERSION = "s15-market-metric.v5"


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _market_order_total(peer_average: float, peer_hotel_count: int) -> int:
    """Infer an integer competition-circle total from its reported average."""

    return int(math.floor(peer_average * peer_hotel_count + 0.5))


def _rank(value: Any) -> tuple[int | None, int | None]:
    text = str(value or "").strip()
    if not text:
        return None, None
    if "/" in text:
        left, right = text.split("/", 1)
        try:
            return int(float(left.strip())), int(float(right.strip()))
        except (TypeError, ValueError):
            return None, None
    try:
        return int(float(text)), None
    except (TypeError, ValueError):
        return None, None


def _same_batch(
    anchor_row: Mapping[str, Any],
    candidate_row: Mapping[str, Any],
) -> bool:
    anchor_date = str(anchor_row.get("business_date") or "").strip()
    candidate_date = str(candidate_row.get("business_date") or "").strip()
    anchor_snapshot = str(anchor_row.get("snapshot_time") or "").strip()
    candidate_snapshot = str(candidate_row.get("snapshot_time") or "").strip()
    return bool(
        anchor_date
        and anchor_snapshot
        and anchor_date == candidate_date
        and anchor_snapshot == candidate_snapshot
    )


def _same_batch_peer_hotel_count(
    codes: Mapping[str, Mapping[str, Any]],
    pay_row: Mapping[str, Any],
) -> tuple[int | None, tuple[str, ...]]:
    """Read only the peer-set denominator from other metrics in the PAY batch.

    competitor rank numerators are metric-specific, but the denominator is the
    shared peer-hotel count for one Meituan snapshot batch.  Conflicting
    denominators are treated as unavailable instead of guessing.
    """

    candidates: list[tuple[str, int]] = []
    for code, row in codes.items():
        metric_code = str(code or "").strip()
        if not metric_code or metric_code == "PAY_ORDER_CNT":
            continue
        if not _same_batch(pay_row, row):
            continue
        _, hotel_count = _rank(row.get("competitor_rank"))
        if hotel_count is not None and hotel_count > 0:
            candidates.append((metric_code, hotel_count))

    if not candidates:
        return None, ()
    counts = {hotel_count for _, hotel_count in candidates}
    if len(counts) != 1:
        return None, ()
    hotel_count = next(iter(counts))
    source_codes = tuple(sorted(code for code, _ in candidates))
    return hotel_count, source_codes


def market_point(
    codes: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Build the only Meituan market-order point used by S15/S16/S5.

    PAY_ORDER_CNT is primary for own orders and peer average.  Missing PAY
    metric_value/peer_average may use FLOW_PAY_ORDER_CNT only from the exact
    same business_date and snapshot_time.  The peer-hotel count may come from
    the denominator of any competitor_rank in that same snapshot batch because
    the peer set is shared across Meituan metrics.  Cross-day and cross-snapshot
    fallback is forbidden.
    """

    pay_row = codes.get("PAY_ORDER_CNT") or {}
    if not pay_row:
        return None

    flow_row = codes.get("FLOW_PAY_ORDER_CNT") or {}
    same_batch_flow = flow_row if _same_batch(pay_row, flow_row) else {}
    fallback_fields: list[str] = []

    own_orders = _n(pay_row.get("metric_value"))
    own_code = "PAY_ORDER_CNT"
    if own_orders is None:
        own_orders = _n(same_batch_flow.get("metric_value"))
        if own_orders is None:
            return None
        own_code = "FLOW_PAY_ORDER_CNT"
        fallback_fields.append("metric_value")

    peer_average = _n(pay_row.get("peer_average"))
    peer_average_code = "PAY_ORDER_CNT"
    if peer_average is None:
        peer_average = _n(same_batch_flow.get("peer_average"))
        if peer_average is None:
            return None
        peer_average_code = "FLOW_PAY_ORDER_CNT"
        fallback_fields.append("peer_average")

    rank, hotel_count = _rank(pay_row.get("competitor_rank"))
    peer_hotel_count_codes: tuple[str, ...] = ("PAY_ORDER_CNT",) if hotel_count else ()
    if hotel_count is None or hotel_count <= 0:
        hotel_count, peer_hotel_count_codes = _same_batch_peer_hotel_count(
            codes,
            pay_row,
        )
        if hotel_count is None or hotel_count <= 0:
            return None
        fallback_fields.append("peer_hotel_count")

    estimated_market_orders = _market_order_total(peer_average, hotel_count)
    estimated_share = (
        own_orders / estimated_market_orders
        if estimated_market_orders > 0
        else None
    )
    flow_peer_fields_used = (
        peer_average_code == "FLOW_PAY_ORDER_CNT"
        or "FLOW_PAY_ORDER_CNT" in peer_hotel_count_codes
    )
    competitor_rank_code = "PAY_ORDER_CNT" if rank is not None else None
    peer_hotel_count_code = (
        peer_hotel_count_codes[0] if peer_hotel_count_codes else None
    )
    same_batch_flow_fallback_fields = tuple(
        field
        for field in fallback_fields
        if field in {"metric_value", "peer_average"}
    )
    return {
        "own_orders": own_orders,
        "peer_average_orders": peer_average,
        "peer_rank": rank,
        "peer_hotel_count": hotel_count,
        "estimated_market_orders": estimated_market_orders,
        "estimated_market_share": estimated_share,
        "estimation_method": (
            "peer_average_times_peer_hotel_count"
        ),
        "peer_average_includes_self": True,
        "metric_code_used": own_code,
        "own_order_metric_code": own_code,
        "own_order_fallback_used": own_code == "FLOW_PAY_ORDER_CNT",
        "peer_context_metric_code": "PAY_ORDER_CNT",
        "peer_average_metric_code": peer_average_code,
        "competitor_rank_metric_code": competitor_rank_code,
        "peer_hotel_count_metric_code": peer_hotel_count_code,
        "peer_hotel_count_metric_codes": peer_hotel_count_codes,
        "same_batch_fallback_fields": tuple(fallback_fields),
        "same_batch_flow_fallback_fields": same_batch_flow_fallback_fields,
        "flow_peer_fields_ignored": not flow_peer_fields_used,
        "own_order_snapshot_time": pay_row.get("snapshot_time"),
        "peer_context_snapshot_time": pay_row.get("snapshot_time"),
        "peer_context_business_date": pay_row.get("business_date"),
        "estimated": True,
        "market_metric_contract_version": VERSION,
    }


def _replace_prebound_references(previous: Any) -> None:
    """Replace module globals created by ``from ... import _market_point``."""

    for name, module in tuple(sys.modules.items()):
        if not name.startswith("runtime.") or module is None:
            continue
        if getattr(module, "_market_point", None) is previous:
            setattr(module, "_market_point", market_point)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import (
        s15_technical_analysis,
        s15_technical_sources,
        s16_dynamic_diagnosis,
    )

    previous = s15_technical_sources._market_point
    s15_technical_sources._market_point = market_point
    s15_technical_analysis._market_point = market_point
    s16_dynamic_diagnosis._market_point = market_point
    _replace_prebound_references(previous)

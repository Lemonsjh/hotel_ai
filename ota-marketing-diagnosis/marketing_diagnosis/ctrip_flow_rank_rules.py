from __future__ import annotations

import math
from typing import Any

from marketing_diagnosis import ctrip_flow as upstream


_COUNT_FIELD = "competition_circle_hotel_count"
_PLATFORM_FIELDS = ("platform_scope", "platform", "source_platform")


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).strip().replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(number) else number


def _ratio_level(value: Any) -> float | None:
    ratio = _number(value)
    if ratio is None:
        return None
    if ratio >= 2:
        return 1.0
    if ratio >= 1.5:
        return 0.8
    if ratio >= 1:
        return 0.6
    return 0.0


def _rank_level(value: Any) -> float | None:
    percentile = _number(value)
    if percentile is None:
        return None
    if percentile >= 0.8:
        return 1.0
    if percentile >= 0.6:
        return 0.8
    if percentile >= 0.4:
        return 0.6
    return 0.0


def _ratio(hotel_value: Any, peer_value: Any) -> float | None:
    hotel = _number(hotel_value)
    peer = _number(peer_value)
    if hotel is None or peer is None or peer < 0:
        return None
    if peer == 0:
        return float("inf") if hotel > 0 else None
    return hotel / peer


def _explicit_platform(row: dict[str, Any]) -> str | None:
    raw = upstream._first(row, *_PLATFORM_FIELDS)
    if raw in (None, ""):
        return None
    platform = upstream._platform(raw)
    return platform if platform in {"ctrip", "qunar"} else None


def _count_candidates(sections: dict[str, Any]) -> tuple[dict[str, float], float | None]:
    """Find the confirmed hotel total even when it is stored outside funnel rows."""

    by_platform: dict[str, float] = {}
    shared: float | None = None
    for section in (sections or {}).values():
        if not isinstance(section, list):
            continue
        for source in section:
            if not isinstance(source, dict):
                continue
            count = _number(source.get(_COUNT_FIELD))
            if count is None or count <= 0:
                continue
            platform = _explicit_platform(source)
            if platform:
                by_platform[platform] = count
            else:
                shared = count
    return by_platform, shared


def _strict_rank_count_sections(sections: dict[str, Any]) -> dict[str, Any]:
    """Make rank scoring use only competition_circle_hotel_count."""

    normalized = dict(sections or {})
    platform_counts, shared_count = _count_candidates(sections)
    rows: list[dict[str, Any]] = []
    for source in sections.get("ctrip_business_metrics_funnel") or []:
        if not isinstance(source, dict):
            continue
        row = dict(source)

        for alias in upstream._COUNT_ALIASES:
            if alias != _COUNT_FIELD:
                row.pop(alias, None)

        count = _number(row.get(_COUNT_FIELD))
        if count is None or count <= 0:
            platform = _explicit_platform(row) or "ctrip"
            candidate = platform_counts.get(platform)
            if candidate is None:
                candidate = shared_count
            if candidate is not None:
                row[_COUNT_FIELD] = candidate

        # Do not obtain the denominator from legacy "rank/count" strings.
        for _, rank_key in upstream._RANK_METRICS:
            raw_rank = row.get(rank_key)
            if isinstance(raw_rank, str) and "/" in raw_rank:
                row[rank_key] = raw_rank.split("/", 1)[0].strip()

        rows.append(row)

    normalized["ctrip_business_metrics_funnel"] = rows
    return normalized


def _rescore_ratio_subitem(subitem: dict[str, Any]) -> None:
    metrics = [metric for metric in subitem.get("metrics") or [] if isinstance(metric, dict)]
    complete = bool(metrics)
    score = 0.0
    fallback_full = (_number(subitem.get("full_score")) or 3.0) / max(len(metrics), 1)

    for metric in metrics:
        ratio = _ratio(metric.get("hotel_value"), metric.get("peer_value"))
        level = _ratio_level(ratio)
        metric_full = _number(metric.get("metric_full_score")) or fallback_full
        metric_score = None if level is None else metric_full * level
        metric["ratio"] = ratio
        metric["score_level"] = level
        metric["metric_full_score"] = metric_full
        metric["metric_score"] = None if metric_score is None else round(metric_score, 4)
        if metric_score is None:
            complete = False
        else:
            score += metric_score

    subitem["subitem_score"] = round(score, 4) if complete else None
    subitem["score_status"] = "success" if complete else "missing"


def _rescore_rank_subitem(
    subitem: dict[str, Any],
    competition_circle_hotel_count: float | None,
) -> None:
    metrics = [metric for metric in subitem.get("metrics") or [] if isinstance(metric, dict)]
    complete = bool(metrics)
    score = 0.0
    fallback_full = (_number(subitem.get("full_score")) or 3.0) / max(len(metrics), 1)

    for metric in metrics:
        rank = _number(metric.get("rank"))
        count = _number(metric.get(_COUNT_FIELD))
        if count is None:
            count = _number(metric.get("competition_hotel_count"))
        if count is None:
            count = competition_circle_hotel_count

        percentile = None
        if rank is not None and count is not None and count > 0:
            percentile = max(0.0, min(1.0, 1 - (rank - 1) / count))
        level = _rank_level(percentile)
        metric_full = _number(metric.get("metric_full_score")) or fallback_full
        metric_score = None if level is None else metric_full * level
        metric["competition_hotel_count"] = count
        metric[_COUNT_FIELD] = count
        metric["rank_percentile"] = percentile
        metric["score_level"] = level
        metric["metric_full_score"] = metric_full
        metric["metric_score"] = None if metric_score is None else round(metric_score, 4)
        if metric_score is None:
            complete = False
        else:
            score += metric_score

    subitem["subitem_score"] = round(score, 4) if complete else None
    subitem["score_status"] = "success" if complete else "missing"


def _rescore_platform(payload: dict[str, Any]) -> None:
    subitems = [item for item in payload.get("subitems") or [] if isinstance(item, dict)]
    record = payload.get("record") if isinstance(payload.get("record"), dict) else {}
    platform_count = _number(record.get(_COUNT_FIELD))
    if platform_count is None:
        platform_count = _number(payload.get(_COUNT_FIELD))

    for subitem in subitems:
        metrics = [metric for metric in subitem.get("metrics") or [] if isinstance(metric, dict)]
        is_rank = any(str(metric.get("value_type") or "") == "rank" for metric in metrics)
        if is_rank:
            _rescore_rank_subitem(subitem, platform_count)
        else:
            _rescore_ratio_subitem(subitem)

    calculated = [
        _number(subitem.get("subitem_score"))
        for subitem in subitems
        if _number(subitem.get("subitem_score")) is not None
    ]
    connected = any(
        any(
            metric.get(key) not in (None, "")
            for key in ("hotel_value", "peer_value", "rank")
        )
        for subitem in subitems
        for metric in subitem.get("metrics") or []
        if isinstance(metric, dict)
    )
    complete = bool(subitems) and len(calculated) == len(subitems)
    payload["item_score"] = round(sum(calculated), 4) if calculated else None
    payload["data_status"] = "success" if complete else "partial" if connected else "missing"


def build_flow_item(
    sections: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item = upstream.build_flow_item(
        _strict_rank_count_sections(sections),
        existing,
    )

    platforms = item.get("platforms")
    if isinstance(platforms, dict):
        for payload in platforms.values():
            if isinstance(payload, dict):
                _rescore_platform(payload)

        main = platforms.get("ctrip")
        if isinstance(main, dict):
            item["item_score"] = main.get("item_score")
            item["data_status"] = main.get("data_status")
            item["fields"] = [
                {
                    "label": subitem.get("name"),
                    "value": subitem.get("subitem_score"),
                    "note": "满分3分",
                }
                for subitem in main.get("subitems") or []
                if isinstance(subitem, dict)
            ]

    scoring_rule = item.setdefault("scoring_rule", {})
    scoring_rule["ratio"] = (
        "ratio = 酒店指标 / 竞争圈平均指标；"
        ">=2得100%，>=1.5得80%，>=1得60%，<1得0%"
    )
    scoring_rule["rank_count_field"] = _COUNT_FIELD
    scoring_rule["rank"] = (
        "rank_percentile = 1-(排名-1)/competition_circle_hotel_count；"
        ">=80%得100%，>=60%得80%，>=40%得60%，<40%得0%"
    )
    scoring_rule["aggregation"] = (
        "每个评分子项满分3分；子项内各指标等分，分别按比例或排名档位计分后相加"
    )
    return item


__all__ = ["build_flow_item"]

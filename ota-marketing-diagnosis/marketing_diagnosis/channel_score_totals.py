from __future__ import annotations

import re
from typing import Any, Iterable


_MEITUAN_TOTAL_RE = re.compile(
    r"(<div class='total-score-v17'>[\s\S]*?<strong>)[^<]*(</strong>)",
    re.IGNORECASE,
)
_CTRIP_TOTAL_RE = re.compile(
    r"(<div class='ctrip-overview-score'>[\s\S]*?<strong>)[^<]*(</strong>)",
    re.IGNORECASE,
)
_CROWN_TOTAL_FUNCTION_RE = re.compile(
    r"  function updateTotal\(score\)\{[\s\S]*?\n  \}\n  function apply\(data\)\{",
)


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(value)
        return None if number != number else number
    except (TypeError, ValueError):
        return None


def _values(value: Any) -> Iterable[dict[str, Any]]:
    rows = value.values() if isinstance(value, dict) else value if isinstance(value, list) else []
    return (row for row in rows if isinstance(row, dict))


def _keyed_values(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return list(_values(value))
    output: list[dict[str, Any]] = []
    for key, row in value.items():
        if not isinstance(row, dict):
            continue
        if row.get("standard_item_id") in (None, ""):
            row = {**row, "standard_item_id": key}
        output.append(row)
    return output


def _item_score(item: dict[str, Any]) -> float | None:
    for key in ("item_score", "diagnosis_score", "score", "current_score"):
        score = _number(item.get(key))
        if score is not None:
            return score
    return None


def _item_id(item: dict[str, Any]) -> int:
    try:
        return int(item.get("standard_item_id") or item.get("item_no") or 0)
    except (TypeError, ValueError):
        return 0


def _sum_items(rows: Iterable[dict[str, Any]], *, exclude_ids: set[int] | None = None) -> float:
    excluded = exclude_ids or set()
    total = 0.0
    for item in rows:
        if _item_id(item) in excluded or item.get("participates_in_score") is False:
            continue
        score = _item_score(item)
        if score is not None:
            total += score
    return round(total, 4)


def meituan_direct_total(result: dict[str, Any], *, exclude_manual: bool = True) -> float:
    visual = result.get("visual_diagnosis") or {}
    rows = visual.get("items") if isinstance(visual, dict) else []
    return _sum_items(_values(rows), exclude_ids={22} if exclude_manual else set())


def ctrip_direct_total(result: dict[str, Any], *, exclude_ids: set[int] | None = None) -> float:
    excluded = exclude_ids or set()
    visual = result.get("visual_diagnosis") or {}
    visual_rows = visual.get("items") if isinstance(visual, dict) else []
    # Ctrip items 01 and 02 are the PMS cards rendered from visual_diagnosis.
    pms_rows = (item for item in _values(visual_rows) if _item_id(item) in {1, 2})
    ctrip_rows = _keyed_values(result.get("ctrip_items"))
    if ctrip_rows:
        ctrip_subtotal = _sum_items(ctrip_rows, exclude_ids=excluded)
    else:
        # Compatibility for historical serialized results that only retained
        # the channel subtotal. New reports always prefer item-level scores.
        summary = result.get("ctrip_summary") or {}
        ctrip_subtotal = _number(summary.get("total_score")) or 0.0
    return round(
        _sum_items(pms_rows, exclude_ids=excluded)
        + ctrip_subtotal,
        4,
    )


def score_text(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".") or "0"


def patch_channel_score_totals(document: str, result: dict[str, Any]) -> str:
    """Render both channel totals as the direct sum of their displayed item scores."""

    meituan_total = meituan_direct_total(result)
    ctrip_total = ctrip_direct_total(result)
    document = _MEITUAN_TOTAL_RE.sub(
        lambda match: match.group(1) + score_text(meituan_total) + match.group(2),
        document,
        count=1,
    )
    document = _CTRIP_TOTAL_RE.sub(
        lambda match: match.group(1) + score_text(ctrip_total) + match.group(2),
        document,
        count=1,
    )
    crown_update = """  function updateTotal(score){
    const node=document.querySelector('.total-score-v17 strong');
    if(!node)return;
    const total=BASE_RAW+(score===null?0:score);
    node.textContent=Number(total.toFixed(2)).toString();
  }
  function apply(data){"""
    return _CROWN_TOTAL_FUNCTION_RE.sub(crown_update, document, count=1)


__all__ = [
    "ctrip_direct_total",
    "meituan_direct_total",
    "patch_channel_score_totals",
    "score_text",
]

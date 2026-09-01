"""Final Meituan item-03 mapping for the monthly exposure source table."""

from __future__ import annotations

import re
from typing import Any


SOURCE_TABLE = "hotel_puyue.meituan_ota_exposure_source_monthly"
SOURCE_FIELDS = [
    "business_date",
    "total_exposure",
    "non_ad_exposure",
    "ad_exposure",
    "ad_exposure_ratio_pct",
]


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None


def _ratio(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return number / 100 if number > 1 else number


def _latest_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    return max(
        rows,
        key=lambda row: (
            str(row.get("business_date") or "")[:10],
            str(row.get("snapshot_time") or "")[:19],
            str(row.get("updated_at") or "")[:19],
        ),
    )


def _field(label: str, value: Any, source_field: str) -> dict[str, Any]:
    return {
        "label": label,
        "value": value,
        "note": f"直接读取 {source_field}",
        "origin": "数据库原值",
    }


def _find_item(items: Any, item_no: int) -> dict[str, Any] | None:
    values = items.values() if isinstance(items, dict) else items if isinstance(items, list) else []
    for item in values:
        if not isinstance(item, dict):
            continue
        try:
            current = int(item.get("standard_item_id") or item.get("item_no") or 0)
        except (TypeError, ValueError):
            continue
        if current == item_no:
            return item
    return None


def _refresh_summary(visual: dict[str, Any]) -> None:
    rows = visual.get("items") or []
    values = rows.values() if isinstance(rows, dict) else rows
    scored = [row for row in values if isinstance(row, dict)]
    raw_score = round(sum(float(row["item_score"]) for row in scored if row.get("item_score") is not None), 2)
    connected_base = sum(
        float(row.get("base_score") or 0)
        for row in scored
        if row.get("participates_in_score") and row.get("item_score") is not None
    )
    visual["raw_score"] = raw_score
    visual["connected_base_score"] = connected_base
    visual["normalized_score"] = round(raw_score / connected_base * 100, 2) if connected_base else None


def patch_visual_diagnosis(result: dict[str, Any], sections: dict[str, Any]) -> dict[str, Any]:
    """Make item 03 read all four displayed values from one latest aligned row."""

    visual = result.get("visual_diagnosis")
    if not isinstance(visual, dict):
        return result
    item = _find_item(visual.get("items"), 3)
    if item is None:
        return result

    rows = [row for row in (sections.get("exposure_daily") or []) if isinstance(row, dict)]
    row = _latest_row(rows)
    total = _number(row.get("total_exposure"))
    non_ad = _number(row.get("non_ad_exposure"))
    ad = _number(row.get("ad_exposure"))
    ad_ratio = _ratio(row.get("ad_exposure_ratio_pct"))

    if not row or total is None or non_ad is None or ad is None or ad_ratio is None:
        status, score_ratio, score = "missing", None, None
    elif total == 0 or ad == 0:
        status, score_ratio, score = "zero", 0.0, 0.0
    elif ad_ratio <= 0.2:
        status, score_ratio, score = "success", 0.5, 2.0
    else:
        status, score_ratio, score = "success", 1.0, 4.0

    item.update({
        "data_status": status,
        "score_ratio": score_ratio,
        "item_score": score,
        "fields": [
            # The established renderer resolves this metric by its historical
            # label.  Keep that internal lookup key and rewrite only the final
            # visible copy in ``patch_report_html`` below.
            _field("整体曝光（近30天）", total, "total_exposure"),
            _field("非广告曝光", non_ad, "non_ad_exposure"),
            _field("广告曝光", ad, "ad_exposure"),
            _field("广告曝光占比", ad_ratio, "ad_exposure_ratio_pct"),
        ],
        "records": [row] if row else [],
        "source_table": SOURCE_TABLE,
        "source_fields": SOURCE_FIELDS,
        "note": "只读取昨天的最新快照；四项数据来自同一条记录。",
    })
    _refresh_summary(visual)
    return result


_ITEM03_RE = re.compile(
    r"(<article\b[^>]*\bid=['\"]rule-3['\"][^>]*>)([\s\S]*?)(</article>)",
    re.IGNORECASE,
)


def patch_report_html(document: str) -> str:
    """Align item-03 labels and period copy with the yesterday snapshot."""

    document = document.replace(
        "展示整体曝光、非广告曝光、广告曝光及每日广告曝光占比。",
        "展示截至昨日的近30天总曝光、非广告曝光、广告曝光及广告曝光占比。",
    )

    def replace_article(match: re.Match[str]) -> str:
        body = match.group(2).replace("整体曝光（近30天）", "总曝光（近30天）", 1)
        return match.group(1) + body + match.group(3)

    return _ITEM03_RE.sub(replace_article, document, count=1)


__all__ = ["patch_report_html", "patch_visual_diagnosis"]

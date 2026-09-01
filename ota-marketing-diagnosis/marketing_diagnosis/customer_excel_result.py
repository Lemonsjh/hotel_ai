from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _latest(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if not rows:
        return {}
    return max(rows, key=lambda row: str(row.get(key) or ""))


def enrich_customer_excel_result(
    result: dict[str, Any],
    raw_dataset: dict[str, Any],
) -> dict[str, Any]:
    """Add customer-only Excel fields without changing shared diagnosis rules.

    Scan-order and crown inputs do not currently have database-backed rules.
    They are therefore displayed for Excel reports, but their score remains
    pending instead of inventing a scoring threshold.
    """
    visual = result.get("visual_diagnosis")
    if not isinstance(visual, dict):
        return result
    items = visual.get("items")
    if not isinstance(items, list):
        return result
    by_no = {
        int(item.get("standard_item_id") or 0): item
        for item in items
        if isinstance(item, dict)
    }

    scan_rows = [row for row in raw_dataset.get("scan_orders", []) if isinstance(row, dict)]
    scan_item = by_no.get(7)
    if scan_rows and isinstance(scan_item, dict):
        counts = [_number(row.get("order_count")) for row in scan_rows]
        clean = [value for value in counts if value is not None]
        if clean:
            total: int | float = sum(clean)
        else:
            total = len({str(row.get("order_id")) for row in scan_rows if row.get("order_id")})
        if isinstance(total, float) and total.is_integer():
            total = int(total)
        scan_item.update({
            "data_status": "pending_rule",
            "score_ratio": None,
            "item_score": None,
            "fields": [
                {
                    "label": "月扫码订单",
                    "value": total,
                    "note": "Excel已导入记录汇总",
                    "origin": "Excel条件汇总",
                },
                {
                    "label": "有效记录数",
                    "value": len(scan_rows),
                    "note": "是否导入=是的记录数",
                    "origin": "Excel行数统计",
                },
            ],
            "records": scan_rows,
            "note": "已展示Excel扫码订单；评分阈值尚未冻结，因此不擅自计分。",
        })

    crown_rows = [row for row in raw_dataset.get("manual_inputs", []) if isinstance(row, dict)]
    crown_item = by_no.get(22)
    crown = _latest(crown_rows, "recorded_at")
    if crown and isinstance(crown_item, dict):
        crown_item.update({
            "data_status": "pending_rule",
            "score_ratio": None,
            "item_score": None,
            "fields": [
                {
                    "label": "挂冠类型",
                    "value": crown.get("crown_type"),
                    "note": "客户Excel人工录入",
                    "origin": "Excel人工录入",
                },
                {
                    "label": "录入人",
                    "value": crown.get("operator"),
                    "note": "",
                    "origin": "Excel人工录入",
                },
                {
                    "label": "录入时间",
                    "value": crown.get("recorded_at"),
                    "note": "",
                    "origin": "Excel人工录入",
                },
            ],
            "note": "已展示Excel挂冠信息；不同挂冠类型的得分口径尚未冻结，因此不擅自计分。",
        })

    # The two Excel-only items intentionally keep item_score=None, so the
    # existing aggregate score remains unchanged and comparable with database
    # reports. No database section or shared scoring rule is modified here.
    return result

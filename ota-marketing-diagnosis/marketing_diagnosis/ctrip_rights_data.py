from __future__ import annotations

from typing import Any


_ACTIVE_MARKERS = (
    "已生效",
    "已报名",
    "生效中",
    "active",
    "enabled",
    "joined",
    "open",
)
_INACTIVE_MARKERS = (
    "已取消",
    "未生效",
    "已失效",
    "取消",
    "失效",
    "cancelled",
    "canceled",
    "inactive",
    "disabled",
    "closed",
)


def _text(value: Any) -> str:
    return "" if value in (None, "") else str(value).strip()


def _status_kind(value: Any) -> str:
    text = _text(value).lower()
    if not text:
        return "pending"
    if any(marker in text for marker in _INACTIVE_MARKERS):
        return "inactive"
    if any(marker in text for marker in _ACTIVE_MARKERS):
        return "active"
    return "pending"


def _latest_right_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for index, source in enumerate(rows):
        row = dict(source)
        name = _text(row.get("right_name")) or f"权益{index + 1}"
        if name not in selected:
            order.append(name)
        selected[name] = row
    return [selected[name] for name in order]


def build_rights_item(
    sections: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = [
        dict(row)
        for row in sections.get("ctrip_joined_rights") or []
        if isinstance(row, dict)
    ]
    rows = _latest_right_rows(rows)
    source = "ctrip_ota_joined_rights"

    if not rows:
        return {
            "standard_item_id": 13,
            "item_name": "权益中心",
            "participates_in_score": True,
            "full_score": 4,
            "item_score": None,
            "data_status": "missing",
            "source": source,
            "fields": [],
            "fields_complete": True,
            "rights_list": [],
            "rights_details": [],
            "active_rights_count": 0,
            "total_rights_count": 0,
            "note": "等待权益中心快照数据。",
        }

    details: list[dict[str, Any]] = []
    has_status = False
    active_count = 0
    for index, row in enumerate(rows):
        status = _text(row.get("right_status"))
        kind = _status_kind(status)
        has_status = has_status or bool(status)
        if kind == "active":
            active_count += 1
        details.append(
            {
                "right_name": _text(row.get("right_name")) or f"权益{index + 1}",
                "rights_rules": _text(row.get("rights_rules")) or "规则待补充",
                "applicable_room_types": _text(row.get("applicable_room_types")) or "参与房型待补充",
                "right_status": status or "状态待确认",
                "status_kind": kind,
            }
        )

    # Older snapshots may not contain right_status. In that case retain the
    # established count-based scoring instead of treating every row as inactive.
    scored_count = active_count if has_status else len(details)
    score = 4.0 if scored_count >= 5 else 2.4 if scored_count >= 3 else 0.0
    names = [detail["right_name"] for detail in details]
    note = (
        "按已生效权益数量计分：不少于5项得4分，3-4项得2.4分，少于3项得0分；"
        "已取消权益保留展示但不计分。"
        if has_status
        else "权益数量不少于5项得4分，3-4项得2.4分，少于3项得0分。"
    )

    item = {
        "standard_item_id": 13,
        "item_name": "权益中心",
        "participates_in_score": True,
        "full_score": 4,
        "item_score": score,
        "data_status": "success",
        "source": source,
        "fields": [
            {"label": "已报名权益", "value": f"{scored_count}项", "note": "按当前生效状态统计"},
            {"label": "权益清单", "value": "、".join(names) or None},
        ],
        "fields_complete": True,
        "rights_list": names,
        "rights_details": details,
        "active_rights_count": scored_count,
        "total_rights_count": len(details),
        "note": note,
    }
    if isinstance(existing, dict):
        for key in ("source_path",):
            if existing.get(key) not in (None, ""):
                item[key] = existing[key]
    return item


__all__ = ["build_rights_item"]

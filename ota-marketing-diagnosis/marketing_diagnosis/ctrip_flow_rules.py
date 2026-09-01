from __future__ import annotations

from typing import Any

from marketing_diagnosis.ctrip_flow_rank_rules import build_flow_item
from marketing_diagnosis.ctrip_rights_data import build_rights_item
from marketing_diagnosis.meituan_exposure_monthly import patch_visual_diagnosis
from marketing_diagnosis.rules_v5 import _refresh_ctrip_summary
from marketing_diagnosis.rules_v5 import process as upstream_process


_INACTIVE_POINTS_STATES = {"未报名", "未参与"}


def _zero_inactive_points_metrics(items: dict[str, Any]) -> None:
    item = items.get("14") or items.get(14)
    if not isinstance(item, dict):
        return

    fields = [field for field in item.get("fields") or [] if isinstance(field, dict)]
    status = next(
        (
            str(field.get("value") or "").strip()
            for field in fields
            if str(field.get("label") or "").strip() in {"报名状态", "参与状态"}
        ),
        "",
    )
    if status not in _INACTIVE_POINTS_STATES:
        return

    for field in fields:
        if str(field.get("label") or "").strip() in {"近30天订单", "成交金额"}:
            field["value"] = 0
    item["item_score"] = 0.0
    item["data_status"] = "success"


def process(data: dict[str, Any]) -> dict[str, Any]:
    """Apply final Ctrip rule corrections after the established rule pipeline."""

    result = upstream_process(data)
    sections = data.get("sections") or {}
    patch_visual_diagnosis(result, sections)
    items = result.setdefault("ctrip_items", {})

    existing_flow = items.get("3") or items.get(3)
    items["3"] = build_flow_item(
        sections,
        existing_flow if isinstance(existing_flow, dict) else None,
    )

    existing_rights = items.get("13") or items.get(13)
    items["13"] = build_rights_item(
        sections,
        existing_rights if isinstance(existing_rights, dict) else None,
    )

    _zero_inactive_points_metrics(items)
    _refresh_ctrip_summary(result)
    return result


__all__ = ["process"]

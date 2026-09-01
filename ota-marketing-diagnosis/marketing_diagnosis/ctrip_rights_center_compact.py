from __future__ import annotations

import json
import re
from typing import Any

from marketing_diagnosis import ctrip_report as stable_report
from marketing_diagnosis import ctrip_report_v54 as report


_ORIGINAL_GENERIC_CARD = report.generic_card
_RESULT_AREA_RE = re.compile(
    r"(<div class='result-area'>).*?(<div class='ctrip-source-v55'>)",
    re.S,
)

RIGHTS_STYLE = """
<style id='CTRIP_RIGHTS_CENTER_COMPACT'>
.ctrip-rights-overview-v66{display:grid;gap:12px}
.ctrip-rights-summary-v66{display:flex;align-items:center;justify-content:space-between;gap:18px;padding:14px 18px;border:1px solid #d6e8df;border-radius:11px;background:linear-gradient(135deg,#edf8f3,#fbfdfc)}
.ctrip-rights-summary-main-v66{display:flex;align-items:baseline;gap:12px}
.ctrip-rights-summary-main-v66 small{color:#587067;font-size:12px;font-weight:800}
.ctrip-rights-summary-main-v66 strong{color:#16845b;font-size:28px;line-height:1;font-variant-numeric:tabular-nums}
.ctrip-rights-summary-v66>span{color:#74827c;font-size:12px}
.ctrip-rights-table-wrap-v66{overflow-x:auto;border:1px solid #dfe7e4;border-radius:11px;background:#fff}
.ctrip-rights-table-v66{width:100%;min-width:860px;border-collapse:collapse;table-layout:fixed}
.ctrip-rights-table-v66 th,.ctrip-rights-table-v66 td{padding:12px 18px;border-bottom:1px solid #e8efec;text-align:left;vertical-align:middle}
.ctrip-rights-table-v66 th{background:#f4f9f6;color:#5f6e67;font-size:12px;font-weight:800;line-height:1.3}
.ctrip-rights-table-v66 td{min-height:54px}
.ctrip-rights-table-v66 tbody tr:last-child td{border-bottom:0}
.ctrip-rights-table-v66 tbody tr.inactive{background:#fafafa}
.ctrip-rights-table-v66 tbody tr.pending{background:#fffdf8}
.ctrip-rights-table-v66 .col-name{width:20%}
.ctrip-rights-table-v66 .col-rule{width:30%}
.ctrip-rights-table-v66 .col-room{width:34%}
.ctrip-rights-table-v66 .col-status{width:16%;text-align:center}
.ctrip-rights-name-v66{display:flex;align-items:center;gap:9px;color:#293b33;font-size:13px;font-weight:850;line-height:1.45}
.ctrip-rights-dot-v66{width:8px;height:8px;flex:0 0 8px;border-radius:50%;background:#2fa66a}
tr.inactive .ctrip-rights-dot-v66{background:#9aa5a0}
tr.pending .ctrip-rights-dot-v66{background:#e0a23b}
.ctrip-rights-rule-v66,.ctrip-rights-room-v66{color:#53645c;font-size:12px;line-height:1.55;overflow-wrap:anywhere}
.ctrip-rights-room-v66{color:#425b50;font-weight:700}
.ctrip-rights-room-text-v66{display:-webkit-box;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:2}
tr.inactive .ctrip-rights-rule-v66,tr.inactive .ctrip-rights-room-v66{color:#87928d}
.ctrip-rights-status-v66{display:inline-flex;align-items:center;justify-content:center;min-width:58px;padding:5px 10px;border-radius:999px;background:#e1f4ea;color:#16845b;font-size:11px;font-style:normal;font-weight:850;white-space:nowrap}
.ctrip-rights-status-v66.inactive{background:#ecefee;color:#6f7974}
.ctrip-rights-status-v66.pending{background:#fff1d8;color:#9b6517}
.ctrip-rights-empty-v66{padding:20px!important;text-align:center!important;color:#8a9791!important;font-size:12px!important}
@media(max-width:860px){.ctrip-rights-summary-v66{align-items:flex-start;flex-direction:column;gap:8px}.ctrip-rights-table-v66{min-width:780px}}
</style>
"""


def _format_count(value: Any, fallback: int | None = None) -> str:
    if value not in (None, ""):
        text = str(value).strip()
        if text.endswith("项"):
            return text
        try:
            number = float(text)
            return f"{int(number) if number.is_integer() else number:g}项"
        except (TypeError, ValueError):
            return text
    return f"{fallback}项" if fallback is not None else "待接入"


def _status_kind(value: Any) -> str:
    text = str(value or "").strip().lower()
    if any(word in text for word in ("已取消", "未生效", "已失效", "取消", "失效", "inactive", "disabled", "closed", "cancelled", "canceled")):
        return "inactive"
    if any(word in text for word in ("已生效", "已报名", "生效中", "active", "enabled", "joined", "open")):
        return "active"
    return "pending"


def _room_type_parts(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, list):
        candidates = [str(item).strip() for item in parsed]
    else:
        candidates = [part.strip() for part in re.split(r"[；;|\n]+", text)]
    result: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in result:
            result.append(candidate)
    return result


def _room_types_display(value: Any) -> tuple[str, str]:
    full_text = str(value or "").strip() or "参与房型待补充"
    parts = _room_type_parts(full_text)
    if len(parts) > 2:
        return f"{'、'.join(parts[:2])} 等 {len(parts)} 个房型", full_text
    if parts:
        return "、".join(parts), full_text
    return full_text, full_text


def _rights_data(
    item_spec: tuple[Any, ...],
    payload: dict[str, Any],
) -> tuple[list[dict[str, str]], str, str]:
    rows = report.fields(item_spec, payload)
    raw_details = payload.get("rights_details")
    details: list[dict[str, str]] = []

    if isinstance(raw_details, list):
        for index, value in enumerate(raw_details):
            if not isinstance(value, dict):
                continue
            name = str(value.get("right_name") or value.get("name") or f"权益{index + 1}").strip()
            status = str(value.get("right_status") or value.get("status") or "状态待确认").strip()
            details.append(
                {
                    "name": name,
                    "rules": str(value.get("rights_rules") or value.get("rules") or "规则待补充").strip(),
                    "room_types": str(value.get("applicable_room_types") or value.get("room_types") or "参与房型待补充").strip(),
                    "status": status,
                    "kind": str(value.get("status_kind") or _status_kind(status)).strip(),
                }
            )

    if not details:
        rights = payload.get("rights_list")
        if not isinstance(rights, list):
            raw = next(
                (row.get("value") for row in rows if row.get("label") == "权益清单"),
                "",
            )
            rights = [value.strip() for value in str(raw or "").split("、") if value.strip()]
        details = [
            {
                "name": str(value).strip(),
                "rules": "规则待补充",
                "room_types": "参与房型待补充",
                "status": "状态待确认",
                "kind": "pending",
            }
            for value in rights
            if str(value).strip()
        ]

    count_field = next(
        (row.get("value") for row in rows if row.get("label") == "已报名权益"),
        None,
    )
    active_value = payload.get("active_rights_count")
    active_count = _format_count(
        active_value if active_value not in (None, "") else count_field,
        sum(detail["kind"] == "active" for detail in details) if details else None,
    )
    total_count = _format_count(payload.get("total_rights_count"), len(details))
    return details, active_count, total_count


def _rights_content(item_spec: tuple[Any, ...], payload: dict[str, Any]) -> str:
    details, active_count, total_count = _rights_data(item_spec, payload)
    table_rows: list[str] = []
    for detail in details:
        kind = detail["kind"] if detail["kind"] in {"active", "inactive", "pending"} else "pending"
        room_display, room_full = _room_types_display(detail["room_types"])
        table_rows.append(
            f"<tr class='{kind}'>"
            "<td><div class='ctrip-rights-name-v66'>"
            "<span class='ctrip-rights-dot-v66'></span>"
            f"<strong>{report.e(detail['name'])}</strong></div></td>"
            f"<td class='ctrip-rights-rule-v66'>{report.e(detail['rules'])}</td>"
            "<td class='ctrip-rights-room-v66'>"
            f"<span class='ctrip-rights-room-text-v66' title='{report.e(room_full)}'>{report.e(room_display)}</span>"
            "</td>"
            "<td class='col-status'>"
            f"<em class='ctrip-rights-status-v66 {kind}'>{report.e(detail['status'])}</em>"
            "</td></tr>"
        )

    if not table_rows:
        empty_text = "待接入权益清单" if payload.get("data_status") == "missing" else "暂无已报名权益"
        table_rows.append(
            f"<tr><td colspan='4' class='ctrip-rights-empty-v66'>{report.e(empty_text)}</td></tr>"
        )

    return (
        "<div class='ctrip-rights-overview-v66'>"
        "<div class='ctrip-rights-summary-v66'>"
        "<div class='ctrip-rights-summary-main-v66'>"
        f"<small>已生效权益</small><strong>{report.e(active_count)}</strong></div>"
        f"<span>共 {report.e(total_count)}记录，已取消权益不计入当前得分</span>"
        "</div>"
        "<div class='ctrip-rights-table-wrap-v66'>"
        "<table class='ctrip-rights-table-v66'>"
        "<thead><tr>"
        "<th class='col-name'>权益名称</th>"
        "<th class='col-rule'>权益规则</th>"
        "<th class='col-room'>参与房型</th>"
        "<th class='col-status'>当前状态</th>"
        "</tr></thead>"
        f"<tbody>{''.join(table_rows)}</tbody></table></div></div>"
    )


def generic_card(result: dict[str, Any], item_spec: tuple[Any, ...]) -> str:
    html_text = _ORIGINAL_GENERIC_CARD(result, item_spec)
    if item_spec[0] != 13:
        return html_text

    payload = report.item_payload(result, item_spec)
    content = _rights_content(item_spec, payload)
    return _RESULT_AREA_RE.sub(
        lambda match: match.group(1) + content + match.group(2),
        html_text,
        count=1,
    )


report.generic_card = generic_card
stable_report.generic_card = generic_card
report.CTRIP_STYLE += RIGHTS_STYLE


__all__ = ["RIGHTS_STYLE", "generic_card"]

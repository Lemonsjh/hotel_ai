from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

_INSTALLED = False
VERSION = "s15-baseline-detail.v2"


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> str:
    value = _n(value)
    return "—" if value is None else f"{value * 100:.0f}%"


def _current_hour(payload: Mapping[str, Any]) -> int | None:
    text = str(payload.get("as_of_datetime") or "")
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).hour
    except ValueError:
        return None


def _point_map(points: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    for point in points:
        try:
            hour = int(point.get("hour"))
        except (TypeError, ValueError):
            continue
        result[hour] = point
    return result


def _room_hourly_block(payload: Mapping[str, Any]) -> str:
    current = _current_hour(payload)
    requested = {9, 12, 14, 16, 18, 20, 22}
    if current is not None:
        requested.add(current)
    lines = [
        "二点五、全部房型小时销售进度（优先保留）",
        "- 格式：小时 容量线/最终完成线/样本天数；无精确样本明确标缺口。",
    ]
    rooms = payload.get("room_types") or {}
    if not rooms:
        lines.append("- 当前没有可展示的 canonical 房型小时基准。")
        return "\n".join(lines)
    for room_id, room in sorted(rooms.items(), key=lambda item: str(item[0])):
        name = str(room.get("room_type_name") or room_id)
        points = _point_map(room.get("hourly_points") or [])
        cells: list[str] = []
        for hour in sorted(requested):
            point = points.get(hour) or {}
            capacity = point.get("capacity") or {}
            completion = point.get("target_completion") or {}
            sample_count = max(
                int(capacity.get("sample_count") or 0),
                int(completion.get("sample_count") or 0),
            )
            exact_count = int(point.get("exact_sample_count") or 0)
            if sample_count <= 0 or ("exact_sample_count" in point and exact_count <= 0):
                cells.append(f"{hour:02d}缺口")
                continue
            cells.append(
                f"{hour:02d} 容{_pct(capacity.get('median'))}/"
                f"完{_pct(completion.get('median'))}/样{sample_count}"
            )
        lines.append(f"- {name}：" + "｜".join(cells))
    return "\n".join(lines)


def _append_details(base: str, payload: Mapping[str, Any]) -> str:
    if payload.get("status") != "ok":
        return base
    block = _room_hourly_block(payload)
    marker = "\n\n三、大盘订单基准线（估算）"
    if marker in base:
        return base.replace(marker, "\n\n" + block + marker, 1)
    return block + "\n\n" + base


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from runtime import s15_s16_complete_output_patch
    from runtime.sales_progress import presentation

    previous = s15_s16_complete_output_patch.s15_message
    if getattr(previous, "_S15_BASELINE_DETAIL_V2", False):
        return

    def s15_message(payload: Mapping[str, Any]) -> str:
        return _append_details(previous(payload), payload)

    s15_message._S15_BASELINE_DETAIL_V2 = True  # type: ignore[attr-defined]
    s15_s16_complete_output_patch.s15_message = s15_message
    presentation.build_s15_user_message = s15_message

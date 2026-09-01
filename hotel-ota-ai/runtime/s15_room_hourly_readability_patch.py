from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

_INSTALLED = False
VERSION = "s15-room-hourly-readability.v1"


def _n(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(value: Any) -> str:
    number = _n(value)
    return "—" if number is None else f"{number * 100:.0f}%"


def _point_map(points: Sequence[Mapping[str, Any]]) -> dict[int, Mapping[str, Any]]:
    result: dict[int, Mapping[str, Any]] = {}
    for point in points:
        try:
            result[int(point.get("hour"))] = point
        except (TypeError, ValueError):
            continue
    return result


def _display_hours(payload: Mapping[str, Any]) -> list[int]:
    hours = {9, 12, 14, 16, 18, 20, 22}
    try:
        hours.add(
            dt.datetime.fromisoformat(
                str(payload.get("as_of_datetime") or "").replace("Z", "+00:00")
            ).hour
        )
    except ValueError:
        pass
    return sorted(hours)


def readable_room_hourly_block(payload: Mapping[str, Any]) -> str:
    hours = _display_hours(payload)
    lines = [
        "二、各房型历史小时销售进度",
        "- 读法：百分比表示历史同类日到该时点通常已完成该房型最终销售目标的比例。",
    ]
    rooms = payload.get("room_types") or {}
    if not rooms:
        return "\n".join(lines + ["- 当前没有可展示的房型小时基准。"])

    for room_id, raw_room in sorted(rooms.items(), key=lambda item: str(item[0])):
        room = raw_room if isinstance(raw_room, Mapping) else {}
        points = _point_map(room.get("hourly_points") or [])
        cells: list[str] = []
        for hour in hours:
            point = points.get(hour) or {}
            exact = int(point.get("exact_sample_count") or 0)
            completion = point.get("target_completion") or {}
            median = _n(completion.get("median"))
            if not point or ("exact_sample_count" in point and exact <= 0) or median is None:
                cells.append(f"{hour:02d}点 缺口")
            else:
                cells.append(f"{hour:02d}点 {_pct(median)}")
        lines.append(
            f"- {room.get('room_type_name') or room_id}：" + " → ".join(cells)
        )

    hotel_points = _point_map(
        ((payload.get("hotel") or {}).get("hourly_points") or [])
    )
    quality: list[str] = []
    for hour in hours:
        point = hotel_points.get(hour) or {}
        exact = int(point.get("exact_sample_count") or 0)
        fallback = int(point.get("fallback_sample_count") or 0)
        if exact:
            text = f"{hour:02d}点 {exact}天精确"
            if fallback:
                text += f"＋{fallback}天回退"
        elif fallback:
            text = f"{hour:02d}点 无精确样本（{fallback}天回退）"
        else:
            total = max(
                int((point.get("capacity") or {}).get("sample_count") or 0),
                int((point.get("target_completion") or {}).get("sample_count") or 0),
            )
            text = f"{hour:02d}点 {total}天样本" if total else f"{hour:02d}点 缺口"
        quality.append(text)
    lines.extend(
        [
            "- 样本质量（以上房型共用）：" + "；".join(quality) + "。",
            "- 房型明细只展开最终目标完成线；房量消化偏差在当前销售进度诊断中单独判断。",
        ]
    )
    return "\n".join(lines)


def replace_room_hourly_block(text: str, payload: Mapping[str, Any]) -> str:
    starts = (
        "二、全部房型小时销售进度（优先保留）",
        "二点五、全部房型小时销售进度（优先保留）",
        "二、各房型历史小时销售进度",
    )
    positions = [text.find(marker) for marker in starts]
    positions = [position for position in positions if position >= 0]
    if not positions:
        return text
    start = min(positions)
    end_markers = (
        "\n\n三、全店小时销售基准",
        "\n\n三、大盘订单基准线（估算）",
    )
    end_positions = [text.find(marker, start) for marker in end_markers]
    end_positions = [position for position in end_positions if position >= 0]
    end = min(end_positions) if end_positions else -1
    block = readable_room_hourly_block(payload)
    return text[:start] + block + (text[end:] if end >= 0 else "")


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime import s15_s16_complete_output_patch as complete
    from runtime import s15_s16_responsibility_patch as responsibility
    from runtime.sales_progress import presentation

    previous = responsibility._baseline_message
    if getattr(previous, "_ROOM_HOURLY_READABLE_V1", False):
        return

    def s15_message(payload: Mapping[str, Any]) -> str:
        return replace_room_hourly_block(previous(payload), payload)

    s15_message._ROOM_HOURLY_READABLE_V1 = True  # type: ignore[attr-defined]
    responsibility._baseline_message = s15_message
    presentation.build_s15_user_message = s15_message
    complete.s15_message = s15_message

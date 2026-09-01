from __future__ import annotations

from typing import Any, Mapping

_INSTALLED = False


def _replace_structure_section(text: str, report: Mapping[str, Any]) -> str:
    lines = str(text or "").splitlines()
    try:
        start = lines.index("三、房型结构")
    except ValueError:
        return text
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("数据时效：") or lines[index].startswith("数据提醒：") or lines[index].startswith("本结果只说明"):
            end = index
            break

    structure = report.get("structure_summary") or {}
    total = int(structure.get("room_type_count") or len(report.get("room_type_results") or []))
    capacity_available = int(structure.get("capacity_line_available_count") or 0)
    capacity_slow = int(structure.get("capacity_slow_room_type_count") or 0)
    capacity_fast = int(structure.get("capacity_fast_room_type_count") or 0)
    target_available = int(structure.get("target_line_available_count") or 0)
    target_slow = int(structure.get("target_slow_room_type_count") or 0)
    target_fast = int(structure.get("target_fast_room_type_count") or 0)

    replacement = [
        "三、房型结构",
        f"- 容量线：可判断 {capacity_available}/{total} 个房型；滞后 {capacity_slow} 个，超前 {capacity_fast} 个。",
        f"- 参考完成线：可判断 {target_available}/{total} 个房型；滞后 {target_slow} 个，超前 {target_fast} 个。",
    ]
    if target_available < total:
        replacement.append(
            f"- 其余 {max(total - target_available, 0)} 个房型缺少可用的历史最终已售分母，不能据此判断参考完成节奏。"
        )
    labels = structure.get("labels") or structure.get("structure_labels") or []
    label_map = {
        "broad_based_slowdown": "多数房型普遍滞后",
        "room_type_structural_lag": "重要房型存在结构性滞后",
        "mix_offset_detected": "快慢房型相互抵消，全店平均掩盖结构差异",
    }
    rendered_labels = [label_map.get(str(item), str(item)) for item in labels]
    replacement.append(
        "- 结构判断："
        + ("；".join(rendered_labels) if rendered_labels else "暂未形成额外结构标签；请分别看容量线和参考完成线。")
    )
    return "\n".join(lines[:start] + replacement + lines[end:])


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from runtime.sales_progress import presentation

    if getattr(presentation, "_S16_STRUCTURE_PRESENTATION_PATCHED", False):
        return
    original = presentation.build_s16_user_message

    def build_s16_user_message(report: Mapping[str, Any]) -> str:
        return _replace_structure_section(original(report), report)

    presentation.build_s16_user_message = build_s16_user_message
    presentation._S16_STRUCTURE_PRESENTATION_PATCHED = True

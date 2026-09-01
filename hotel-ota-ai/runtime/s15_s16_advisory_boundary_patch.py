from __future__ import annotations

from typing import Any, Mapping

_INSTALLED = False
_OLD_BOUNDARY = (
    "边界  只判断销售节奏与房型结构；"
    "不推断晚间剩余需求，不自动生成调价或推广建议。"
)
_NEW_BOUNDARY = (
    "建议边界  可基于当前节奏、剩余可售、历史 pickup 和数据成熟度给出"
    "晚间需求、调价或推广建议；建议不等于自动执行，执行仍需对应能力、"
    "护栏和审批流程。"
)


def allow_advisory_s16(text: str) -> str:
    return str(text).replace(_OLD_BOUNDARY, _NEW_BOUNDARY)


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    from runtime.sales_progress import presentation

    previous_s16 = presentation.build_s16_user_message

    def advisory_s16(report: Mapping[str, Any]) -> str:
        return allow_advisory_s16(previous_s16(report))

    presentation.build_s16_user_message = advisory_s16

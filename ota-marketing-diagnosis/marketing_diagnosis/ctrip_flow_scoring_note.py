from __future__ import annotations

from typing import Any

from marketing_diagnosis import ctrip_flow_report as report


_ORIGINAL_PLATFORM_PANEL = report._platform_panel
_OLD_NOTE = (
    "<div class='ctrip-flow-note'>"
    "<b>计分说明：</b>比例类先计算 ratio，再按档位换算为指标得分；同一子项内各指标得分相加。"
    "排名类按 rank_percentile 分档后相加。当前数据终点为“提交订单”。"
    "</div>"
)
_NEW_NOTE = (
    "<div class='ctrip-flow-note'>"
    "<b>比例类：</b>ratio = 酒店指标 / 竞争圈平均指标；"
    "ratio ≥ 2 得满分，1.5–2 得80%，1–1.5 得60%，低于1得0分。<br>"
    "<b>排名类：</b>rank_percentile = 1 - (排名 - 1) / 竞争圈酒店数；"
    "排名分位 ≥80% 得满分，60%–80% 得80%，40%–60% 得60%，低于40%得0分。"
    "竞争圈酒店数读取 competition_circle_hotel_count；同一评分子项内各指标得分相加。"
    "</div>"
)


def _platform_panel(platform: str, payload: dict[str, Any], *, hidden: bool) -> str:
    html_text = _ORIGINAL_PLATFORM_PANEL(platform, payload, hidden=hidden)
    return html_text.replace(_OLD_NOTE, _NEW_NOTE, 1)


report._platform_panel = _platform_panel


__all__ = []

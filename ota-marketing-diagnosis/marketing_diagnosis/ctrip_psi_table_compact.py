from __future__ import annotations

import re
from typing import Any

from marketing_diagnosis import ctrip_psi_v53 as psi
from marketing_diagnosis import ctrip_report as stable_report
from marketing_diagnosis import ctrip_report_v54 as report


psi.METRICS = tuple(
    (
        code,
        group,
        label,
        unit,
        "间夜量" if code == "historical_room_nights" else short_label,
    )
    for code, group, label, unit, short_label in psi.METRICS
)

_ORIGINAL_CARD = report.psi_card
_OLD_HEADER = (
    "<th>指标类型</th><th>诊断指标</th><th>实际值</th>"
    "<th>权重</th><th>PSI得分</th>"
)
_NEW_HEADER = (
    "<th class='psi-col-type-v53'>指标类型</th>"
    "<th class='psi-col-index-v53'>诊断指标</th>"
    "<th class='psi-col-unit-v53'>单位</th>"
    "<th class='psi-col-value-v53'>实际值</th>"
    "<th class='psi-col-weight-v53'>权重</th>"
    "<th class='psi-col-score-v53'>PSI得分</th>"
)
_COMPETITION_CARD_RE = re.compile(
    r"<div class='psi-summary-card-v53'><small>竞争圈排名</small>.*?</div>",
    re.S,
)
_TOTAL_DETAILS_RE = re.compile(
    r"(<div class='psi-total-v53'><small>PSI 服务质量总分</small>"
    r"<strong>.*?</strong>)<em>.*?</em><b>.*?</b>(</div>)",
    re.S,
)


def rows(data: dict[str, Any]) -> str:
    metric_values = psi._metric_map(data)
    groups = {metric[1] for metric in psi.METRICS}
    counts = {
        group: sum(
            1
            for _, metric_group, _, _, _ in psi.METRICS
            if metric_group == group
        )
        for group in groups
    }
    seen: set[str] = set()
    output: list[str] = []

    for code, group, label, default_unit, _ in psi.METRICS:
        value = metric_values.get(code) or {}
        unit = str(value.get("unit") or default_unit)
        group_cell = ""
        if group not in seen:
            seen.add(group)
            group_cell = (
                f"<td class='psi-type-v53' rowspan='{counts[group]}'>"
                f"{psi.e(group)}</td>"
            )

        weight = psi.num(value.get("weight_pct"))
        weight_text = "待接入" if weight is None else f"{weight:g}%"
        score_text = psi._plain(value.get("psi_score"))
        actual_value = psi._metric_value(value.get("metric_value"), unit)

        output.append(
            f"<tr>{group_cell}"
            f"<td class='psi-index-v53'>{psi.e(value.get('metric_name') or label)}</td>"
            f"<td class='psi-unit-v53'>{psi.e(unit)}</td>"
            f"<td class='psi-value-v53'>{psi.e(actual_value)}</td>"
            f"<td class='psi-weight-v53'>{psi.e(weight_text)}</td>"
            f"<td class='psi-score-v53'><strong>{psi.e(score_text)}</strong></td></tr>"
        )

    return "".join(output)


def card(result: dict[str, Any], anchor: str) -> str:
    html_text = _ORIGINAL_CARD(result, anchor).replace(_OLD_HEADER, _NEW_HEADER, 1)
    html_text = _COMPETITION_CARD_RE.sub("", html_text, count=1)
    return _TOTAL_DETAILS_RE.sub(r"\1\2", html_text, count=1)


psi.rows = rows
psi.card = card
report.psi_card = card
stable_report.psi_card = card
report.PSI_STYLE += """
<style id='CTRIP_PSI_COMPACT_TABLE'>
.psi-overview-v53{
  grid-template-columns:minmax(210px,.72fr) minmax(0,1.8fr);
  gap:10px;
  align-items:stretch;
  padding:12px 14px 10px;
}
.psi-total-v53{
  min-height:126px;
  padding:15px 18px;
  justify-content:center;
}
.psi-total-v53 strong{
  margin-top:6px;
  font-size:42px;
}
.psi-summary-grid-v53{
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:10px;
  align-items:stretch;
}
.psi-summary-card-v53{
  display:flex;
  min-height:126px;
  flex-direction:column;
  justify-content:center;
  padding:14px 16px;
}
.psi-summary-card-v53 strong{margin-top:7px;font-size:20px}
.psi-summary-card-v53 span{margin-top:5px}
.psi-table-v53{min-width:680px;table-layout:fixed}
.psi-table-v53 th,.psi-table-v53 td{padding:12px 14px}
.psi-table-v53 .psi-col-type-v53{width:16%}
.psi-table-v53 .psi-col-index-v53{width:27%}
.psi-table-v53 .psi-col-unit-v53{width:11%}
.psi-table-v53 .psi-col-value-v53{width:18%}
.psi-table-v53 .psi-col-weight-v53{width:13%}
.psi-table-v53 .psi-col-score-v53{width:15%}
.psi-table-v53 .psi-col-unit-v53,
.psi-table-v53 .psi-col-value-v53,
.psi-table-v53 .psi-col-weight-v53,
.psi-table-v53 .psi-col-score-v53,
.psi-table-v53 .psi-unit-v53,
.psi-table-v53 .psi-value-v53,
.psi-table-v53 .psi-weight-v53,
.psi-table-v53 .psi-score-v53{text-align:center}
.psi-table-v53 .psi-unit-v53{color:#718078}
@media(max-width:1100px){
  .psi-overview-v53{grid-template-columns:1fr}
  .psi-summary-grid-v53{grid-template-columns:repeat(3,minmax(0,1fr))}
}
@media(max-width:760px){
  .psi-summary-grid-v53{grid-template-columns:1fr}
  .psi-total-v53,.psi-summary-card-v53{min-height:auto}
}
</style>
"""


__all__ = ["card", "rows"]

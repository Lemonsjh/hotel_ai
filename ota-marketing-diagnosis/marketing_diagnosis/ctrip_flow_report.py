from __future__ import annotations

import math
from typing import Any

from marketing_diagnosis import ctrip_report_v54 as upstream


STYLE = """
<style id='CTRIP_FLOW_SCORE_TABLE_STABLE'>
.ctrip-flow-tabs{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:14px;align-items:center;margin-bottom:16px}
.ctrip-flow-tab{min-height:46px;padding:8px 18px;border:1px solid #d8e2de;border-radius:9px;background:#fff;color:#52616c;font:inherit;font-size:14px;font-weight:850;cursor:pointer}
.ctrip-flow-tab.active{border-color:#27a86d;background:linear-gradient(135deg,#168a55,#22a865);color:#fff;box-shadow:0 5px 14px rgba(24,142,87,.16)}
.ctrip-flow-current{grid-column:1/-1;text-align:right;color:#68747f;font-size:12px}.ctrip-flow-current strong{color:#26343d}
.ctrip-flow-panel[hidden]{display:none!important}
.ctrip-flow-table-shell{padding:14px;border:1px solid #dfe7e4;border-radius:10px;background:#fff}
.ctrip-flow-table-shell h4{margin:0 0 12px;color:#26343d;font-size:16px}
.ctrip-flow-table-scroll{overflow-x:auto;border:1px solid #dfe7e4;border-radius:8px}
.ctrip-flow-table{width:100%;min-width:1040px;border-collapse:collapse;table-layout:fixed;background:#fff}
.ctrip-flow-table th,.ctrip-flow-table td{padding:9px 10px;border-right:1px solid #e2e8e5;border-bottom:1px solid #e2e8e5;text-align:center;color:#34424b;font-size:12px;line-height:1.35}
.ctrip-flow-table th:last-child,.ctrip-flow-table td:last-child{border-right:0}.ctrip-flow-table tbody tr:last-child td{border-bottom:0}
.ctrip-flow-table th{background:#f4f7f6;color:#53616b;font-weight:850}
.ctrip-flow-table .flow-index{width:54px;font-size:15px;font-weight:900;color:#20303a}
.ctrip-flow-table .flow-subitem{width:155px;font-weight:850;color:#26343d}
.ctrip-flow-table .flow-metric{text-align:left;padding-left:18px}
.ctrip-flow-table .flow-number{font-variant-numeric:tabular-nums;white-space:nowrap}
.ctrip-flow-table .flow-ratio{font-variant-numeric:tabular-nums;color:#34424b;white-space:nowrap}
.ctrip-flow-table .flow-score{width:105px;color:#16845b;font-size:16px;font-weight:900;white-space:nowrap}
.ctrip-flow-table .flow-score span{color:#77848d;font-size:12px;font-weight:650}
.ctrip-flow-table .flow-missing{color:#8a969e;font-weight:650}
.ctrip-flow-rank-shell{margin-top:14px}
.ctrip-flow-rank-table{width:100%;min-width:1040px;border-collapse:collapse;table-layout:fixed;background:#fff}
.ctrip-flow-rank-table th,.ctrip-flow-rank-table td{padding:10px 12px;border-right:1px solid #e2e8e5;border-bottom:1px solid #e2e8e5;text-align:center;color:#34424b;font-size:12px;line-height:1.35}
.ctrip-flow-rank-table th:last-child,.ctrip-flow-rank-table td:last-child{border-right:0}.ctrip-flow-rank-table tbody tr:last-child td{border-bottom:0}
.ctrip-flow-rank-table th{background:#f1f8f5;color:#53616b;font-weight:850}
.ctrip-flow-rank-table .flow-rank-index{width:54px;font-size:15px;font-weight:900;color:#20303a}
.ctrip-flow-rank-table .flow-rank-subitem{width:155px;font-weight:850;color:#26343d}
.ctrip-flow-rank-table .flow-rank-metric{text-align:left;padding-left:18px;font-weight:800}
.ctrip-flow-rank-table .flow-rank-number,.ctrip-flow-rank-table .flow-rank-count,.ctrip-flow-rank-table .flow-rank-percentile{font-variant-numeric:tabular-nums;white-space:nowrap}
.ctrip-flow-rank-table .flow-score{width:105px;color:#16845b;font-size:16px;font-weight:900;white-space:nowrap}
.ctrip-flow-rank-table .flow-score span{color:#77848d;font-size:12px;font-weight:650}
.ctrip-flow-rank-table .flow-missing{color:#8a969e;font-weight:650}
.ctrip-flow-platform-status{margin-bottom:10px;padding:9px 11px;border-radius:8px;background:#f4faf7;color:#315b4c;font-size:12px}
@media(max-width:760px){.ctrip-flow-tabs{grid-template-columns:1fr}.ctrip-flow-current{grid-column:auto;text-align:left}.ctrip-flow-tab{width:100%}}
@media print{.ctrip-flow-tabs{display:none}.ctrip-flow-panel[hidden]{display:block!important}.ctrip-flow-panel+.ctrip-flow-panel{margin-top:18px}.ctrip-flow-table,.ctrip-flow-rank-table{min-width:0;font-size:9px}.ctrip-flow-table th,.ctrip-flow-table td,.ctrip-flow-rank-table th,.ctrip-flow-rank-table td{padding:5px 4px;font-size:9px}}
</style>
"""


SCRIPT = r"""
<script id='CTRIP_FLOW_SCORE_TABLE_SCRIPT_STABLE'>
(function(){
  document.addEventListener('click',function(event){
    const button=event.target.closest('[data-flow-tab]');
    if(!button) return;
    const root=button.closest('[data-ctrip-flow-card]');
    if(!root) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    const platform=button.getAttribute('data-flow-tab');
    root.querySelectorAll('[data-flow-tab]').forEach(function(item){
      const active=item.getAttribute('data-flow-tab')===platform;
      item.classList.toggle('active',active);
      item.setAttribute('aria-selected',active?'true':'false');
    });
    root.querySelectorAll('[data-flow-panel]').forEach(function(panel){
      panel.hidden=panel.getAttribute('data-flow-panel')!==platform;
    });
    const current=root.querySelector('[data-flow-current]');
    if(current) current.textContent=platform==='ctrip'?'携程':'去哪儿';
  },true);
})();
</script>
"""


def _number(value: Any) -> float | None:
    return upstream.number(value)


def _trim_number(value: Any, decimals: int = 1) -> str:
    number = _number(value)
    if number is None:
        return "待接入"
    text = f"{number:.{decimals}f}"
    return text.rstrip("0").rstrip(".")


def _value(value: Any, value_type: str) -> str:
    number = _number(value)
    if number is None:
        return "待接入"
    if value_type == "percent":
        return f"{number:.2f}%"
    if value_type == "rank":
        return f"第 {number:g} 名"
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"


def _ratio(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "--"
    if math.isinf(number):
        return "∞"
    return f"{number:.2f}"


def _percentile(value: Any) -> str:
    number = _number(value)
    return "--" if number is None else f"{number * 100:.2f}%"


def _score(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "<span class='flow-missing'>待接入</span>"
    return f"{upstream.e(_trim_number(number, 1))} <span>/ 3</span>"


def _ratio_rows(subitems: list[dict[str, Any]]) -> str:
    rows: list[str] = []
    for subitem in subitems:
        metrics = [
            metric
            for metric in subitem.get("metrics") or []
            if isinstance(metric, dict) and str(metric.get("value_type") or "count") != "rank"
        ]
        if not metrics:
            continue
        rowspan = len(metrics)
        for offset, metric in enumerate(metrics):
            value_type = str(metric.get("value_type") or "count")
            hotel_text = _value(metric.get("hotel_value"), value_type)
            peer_text = _value(metric.get("peer_value"), value_type)
            ratio_text = _ratio(metric.get("ratio"))
            missing_class = " flow-missing" if "待接入" in {hotel_text, peer_text} else ""
            cells: list[str] = []
            if offset == 0:
                cells.extend(
                    [
                        f"<td class='flow-index' rowspan='{rowspan}'>{upstream.e(subitem.get('index'))}</td>",
                        f"<td class='flow-subitem' rowspan='{rowspan}'>{upstream.e(subitem.get('name') or '')}</td>",
                    ]
                )
            cells.extend(
                [
                    f"<td class='flow-metric'>{upstream.e(metric.get('label') or '指标')}</td>",
                    f"<td class='flow-number{missing_class}'>{upstream.e(hotel_text)}</td>",
                    f"<td class='flow-number{missing_class}'>{upstream.e(peer_text)}</td>",
                    f"<td class='flow-ratio'>{upstream.e(ratio_text)}</td>",
                ]
            )
            if offset == 0:
                cells.append(f"<td class='flow-score' rowspan='{rowspan}'>{_score(subitem.get('subitem_score'))}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
    return "".join(rows)


def _rank_table(subitems: list[dict[str, Any]]) -> str:
    rank_subitem = next(
        (
            subitem
            for subitem in subitems
            if any(
                isinstance(metric, dict) and str(metric.get("value_type") or "") == "rank"
                for metric in subitem.get("metrics") or []
            )
        ),
        {},
    )
    metrics = [
        metric
        for metric in rank_subitem.get("metrics") or []
        if isinstance(metric, dict) and str(metric.get("value_type") or "") == "rank"
    ]
    rows: list[str] = []
    rowspan = max(len(metrics), 1)
    for offset, metric in enumerate(metrics):
        rank_text = _value(metric.get("rank"), "rank")
        count = _number(metric.get("competition_hotel_count"))
        count_text = "待接入" if count is None else f"{count:g} 家"
        percentile_text = _percentile(metric.get("rank_percentile"))
        missing_class = " flow-missing" if "待接入" in {rank_text, count_text} else ""
        cells: list[str] = []
        if offset == 0:
            cells.extend(
                [
                    f"<td class='flow-rank-index' rowspan='{rowspan}'>{upstream.e(rank_subitem.get('index') or 5)}</td>",
                    f"<td class='flow-rank-subitem' rowspan='{rowspan}'>{upstream.e(rank_subitem.get('name') or '竞争圈排名表现')}</td>",
                ]
            )
        cells.extend(
            [
                f"<td class='flow-rank-metric'>{upstream.e(metric.get('label') or '排名指标')}</td>",
                f"<td class='flow-rank-number{missing_class}'>{upstream.e(rank_text)}</td>",
                f"<td class='flow-rank-count{missing_class}'>{upstream.e(count_text)}</td>",
                f"<td class='flow-rank-percentile'>{upstream.e(percentile_text)}</td>",
            ]
        )
        if offset == 0:
            cells.append(f"<td class='flow-score' rowspan='{rowspan}'>{_score(rank_subitem.get('subitem_score'))}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    if not rows:
        rows.append("<tr><td colspan='7' class='flow-missing'>竞争圈排名数据待接入</td></tr>")
    return (
        "<div class='ctrip-flow-rank-shell'>"
        "<div class='ctrip-flow-table-scroll'><table class='ctrip-flow-rank-table'>"
        "<thead><tr><th>序号</th><th>评分子项</th><th>子项指标</th><th>竞争圈排名</th>"
        "<th>竞争圈酒店数</th><th>排名分位</th><th>子项得分</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div></div>"
    )


def _platform_panel(platform: str, payload: dict[str, Any], *, hidden: bool) -> str:
    subitems = [subitem for subitem in payload.get("subitems") or [] if isinstance(subitem, dict)]
    ratio_rows = _ratio_rows(subitems)
    if not ratio_rows:
        ratio_rows = "<tr><td colspan='7' class='flow-missing'>该平台比例类数据待接入</td></tr>"
    platform_name = str(payload.get("platform_name") or ("携程" if platform == "ctrip" else "去哪儿"))
    score = _number(payload.get("item_score"))
    status_text = (
        f"{platform_name}得分：{'待接入' if score is None else _trim_number(score, 1) + ' / 15分'}"
        + ("，计入携程综合总分" if platform == "ctrip" else "，仅补充展示，不计入携程综合总分")
    )
    hidden_attr = " hidden" if hidden else ""
    return (
        f"<div class='ctrip-flow-panel' data-flow-panel='{upstream.e(platform)}'{hidden_attr}>"
        f"<div class='ctrip-flow-platform-status'>{upstream.e(status_text)}</div>"
        "<div class='ctrip-flow-table-shell'><h4>关键指标评分明细表</h4>"
        "<div class='ctrip-flow-table-scroll'><table class='ctrip-flow-table'>"
        "<thead><tr><th>序号</th><th>评分子项</th><th>子项指标</th><th>我的酒店</th>"
        "<th>竞争圈平均</th><th>ratio对比值</th><th>子项得分</th></tr></thead>"
        f"<tbody>{ratio_rows}</tbody></table></div>"
        f"{_rank_table(subitems)}"
        "</div></div>"
    )


def card(result: dict[str, Any]) -> str:
    item_spec = upstream.spec(3)
    payload = upstream.item_payload(result, item_spec)
    key, text, css = upstream.status(payload)
    score_class = "ok" if upstream.score_value(payload) is not None else "pending"
    platforms = payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}
    ctrip = dict(platforms.get("ctrip") or {})
    qunar = dict(platforms.get("qunar") or {})
    return (
        f"<article class='diagnosis-card' data-status='{upstream.e(key)}' data-title='平台流量漏斗分析' id='rule-3' data-ctrip-flow-card>"
        "<div class='card-top'><div class='rule-no'>03</div>"
        "<div class='card-title'><h3>平台流量漏斗分析</h3><p>展示曝光、访客、订单页、提交订单链路，并对比竞争圈平均水平。</p></div>"
        "<div class='card-tags'>"
        "<div class='title-meta-item title-period'><small>统计周期</small><strong>近30天</strong></div>"
        f"<div class='title-meta-item title-score {score_class}'><small>当前得分</small>"
        f"<div class='title-score-value'><strong>{upstream.e(upstream.score_text(item_spec, payload))}</strong>"
        f"<span>满分 {upstream.e(upstream.full_text(item_spec, payload))}</span></div></div>"
        f"<span class='status-badge {css}'>{upstream.e(text)}</span></div></div>"
        "<div class='result-area'>"
        "<div class='ctrip-flow-tabs' role='tablist'>"
        "<button type='button' class='ctrip-flow-tab active' data-flow-tab='ctrip' role='tab' aria-selected='true'>携程（主平台，计入总分）</button>"
        "<button type='button' class='ctrip-flow-tab' data-flow-tab='qunar' role='tab' aria-selected='false'>去哪儿（补充平台，不计入总分）</button>"
        "<div class='ctrip-flow-current'>当前展示：<strong data-flow-current>携程</strong></div></div>"
        f"{_platform_panel('ctrip', ctrip, hidden=False)}"
        f"{_platform_panel('qunar', qunar, hidden=True)}"
        "</div></article>"
    )


__all__ = ["SCRIPT", "STYLE", "card"]

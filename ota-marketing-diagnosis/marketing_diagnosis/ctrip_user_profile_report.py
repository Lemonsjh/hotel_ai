from __future__ import annotations

import html
import math
from typing import Any

from marketing_diagnosis import ctrip_report_v54 as upstream


COLORS = ("#2fa66a", "#3f8fe8", "#f2a521", "#9368d8", "#ef6a4c", "#2aa8b8")

STYLE = """
<style id='CTRIP_USER_PROFILE_STABLE'>
.ctrip-profile-tabs{display:flex;gap:8px;margin-bottom:12px;padding:4px;border-radius:10px;background:#f1f6f4}
.ctrip-profile-tab{flex:1;min-height:42px;padding:8px 16px;border:1px solid transparent;border-radius:8px;background:transparent;color:#68757e;font-size:13px;font-weight:850;cursor:pointer}
.ctrip-profile-tab:hover{background:#f8fbfa;color:#16845b}
.ctrip-profile-tab.active{border-color:#91cdb4;background:#fff;color:#16845b;box-shadow:0 2px 8px rgba(31,91,69,.08)}
.ctrip-profile-tab:focus-visible,.ctrip-profile-toggle:focus-visible{outline:3px solid rgba(22,132,91,.18);outline-offset:2px}
.ctrip-profile-panel[hidden],.ctrip-profile-detail-row[hidden]{display:none!important}
.ctrip-profile-table-scroll{width:100%;max-width:100%;overflow-x:auto;overscroll-behavior-inline:contain;padding-bottom:2px}
.ctrip-profile-table{width:100%;min-width:820px;border:1px solid #dfe7e4;border-radius:10px;border-collapse:separate;border-spacing:0;overflow:hidden;background:#fff}
.ctrip-profile-table th,.ctrip-profile-table td{position:static;padding:15px 14px;border:0;border-bottom:1px solid #e8eeeb;vertical-align:middle;background:#fff}
.ctrip-profile-table th{background:#f5f9f7;color:#52616b;font-size:12px;font-weight:800;text-align:left}
.ctrip-profile-table th:nth-child(1){width:170px}.ctrip-profile-table th:nth-child(2){width:260px}.ctrip-profile-table th:nth-child(3){width:100px;text-align:right}.ctrip-profile-table th:nth-child(4){width:auto}.ctrip-profile-table th:nth-child(5){width:118px;text-align:right}
.ctrip-profile-table tbody tr:last-child td{border-bottom:0}
.ctrip-profile-summary-row:hover td:not(.ctrip-profile-dimension){background:#f8fbfa}
.ctrip-profile-dimension{background:#fbfdfc!important;color:#27343d;font-size:13px;font-weight:850}
.ctrip-profile-dimension-inner{display:flex;min-height:48px;flex-direction:column;justify-content:center;gap:5px}
.ctrip-profile-average{color:#16845b;font-size:11px;font-weight:750;line-height:1.35}
.ctrip-profile-main{color:#34424b;font-size:13px;font-weight:800}
.ctrip-profile-main-line{display:flex;align-items:center;gap:8px}
.ctrip-profile-secondary{display:block;margin-top:7px;color:#7a8790;font-size:11px;line-height:1.45}
.ctrip-profile-dot{width:8px;height:8px;flex:0 0 8px;border-radius:50%;background:var(--profile-color)}
.ctrip-profile-value{text-align:right;color:#34434d;font-size:13px;font-weight:800;font-variant-numeric:tabular-nums;white-space:nowrap}
.ctrip-profile-bar-track{width:100%;min-width:150px;height:10px;overflow:hidden;border-radius:999px;background:#edf2f0}
.ctrip-profile-bar-fill{display:block;height:100%;min-width:3px;border-radius:inherit;background:var(--profile-color)}
.ctrip-profile-action{text-align:right}
.ctrip-profile-toggle{display:inline-flex;align-items:center;justify-content:center;min-width:88px;padding:7px 11px;border:1px solid #cfe2da;border-radius:7px;background:#f5faf8;color:#16845b;font-size:11px;font-weight:800;cursor:pointer;white-space:nowrap}
.ctrip-profile-toggle:hover{border-color:#91cdb4;background:#eaf6f0}
.ctrip-profile-table-empty{padding:22px!important;color:#87939b!important;text-align:center}
.ctrip-profile-detail-row td{padding-top:10px;padding-bottom:10px;background:#fafcfb;color:#4c5962}
.ctrip-profile-detail-row:hover td{background:#f5faf7}
.ctrip-profile-detail-label{color:#8a969e;font-size:10px;font-weight:750}
.ctrip-profile-detail-item{font-size:12px;font-weight:650}
.ctrip-profile-detail-item-line{display:flex;align-items:center;gap:8px}
.ctrip-profile-detail-value{text-align:right;font-size:12px;font-weight:750;font-variant-numeric:tabular-nums;white-space:nowrap}
.ctrip-profile-detail-row .ctrip-profile-bar-track{height:8px}
.ctrip-profile-bottom{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:12px;margin-top:12px}
.ctrip-profile-city,.ctrip-profile-peak{min-width:0;padding:14px;border:1px solid #dfe7e4;border-radius:10px;background:#fff}
.ctrip-profile-city h4,.ctrip-profile-peak h4{margin:0 0 12px;color:#27343d;font-size:14px}
.ctrip-profile-city-row{display:grid;grid-template-columns:22px minmax(52px,84px) minmax(90px,1fr) 58px;align-items:center;gap:8px;margin:8px 0;font-size:11px}
.ctrip-profile-city-rank{width:18px;height:18px;display:flex;align-items:center;justify-content:center;border-radius:50%;background:var(--profile-color);color:#fff;font-size:10px;font-weight:800}
.ctrip-profile-city-name{min-width:0;color:#3d4a54;white-space:normal;overflow-wrap:anywhere}
.ctrip-profile-city-track{height:7px;overflow:hidden;border-radius:99px;background:#edf2f0}
.ctrip-profile-city-bar{display:block;height:100%;border-radius:inherit;background:var(--profile-color)}
.ctrip-profile-city-value{text-align:right;color:#4e5c66;font-variant-numeric:tabular-nums;white-space:nowrap}
.ctrip-profile-empty{min-height:120px;display:flex;align-items:center;justify-content:center;border:1px dashed #dce5e1;border-radius:8px;background:#fafcfb;color:#83909b;font-size:13px}
.ctrip-profile-peak-layout{display:grid;grid-template-columns:minmax(105px,118px) minmax(0,1fr);align-items:stretch;gap:12px;min-width:0}
.ctrip-profile-peak-summary{display:flex;min-height:152px;flex-direction:column;align-items:center;justify-content:center;border-radius:9px;background:#f4faf7;text-align:center}
.ctrip-profile-peak-summary small{color:#687780;font-size:11px}
.ctrip-profile-peak-summary strong{margin:7px 0 3px;color:#16845b;font-size:28px;line-height:1}
.ctrip-profile-peak-summary b{color:#16845b;font-size:17px}
.ctrip-profile-hourly-scroll{max-width:100%;overflow-x:auto;overscroll-behavior-inline:contain}
.ctrip-profile-hourly-scroll .ctrip-profile-hourly-svg{display:block;width:100%;min-width:560px;height:auto}
.ctrip-profile-hourly-empty{min-height:152px;display:flex;align-items:center;justify-content:center;border:1px dashed #dce5e1;border-radius:8px;color:#89959e;font-size:12px}
.ctrip-profile-source{margin-top:12px;padding:10px 12px;border:1px solid #d9e6e1;border-radius:9px;background:#f4faf7;color:#315b4c;font-size:12px;overflow-wrap:anywhere}
.ctrip-profile-source b{margin-right:6px}
@media(max-width:760px){
  .ctrip-profile-tabs{overflow-x:auto;justify-content:flex-start}
  .ctrip-profile-tab{min-width:120px;flex:0 0 auto}
  .ctrip-profile-table{min-width:760px}
  .ctrip-profile-bottom{grid-template-columns:1fr}
  .ctrip-profile-peak-layout{grid-template-columns:1fr}
  .ctrip-profile-peak-summary{min-height:92px}
}
@media(max-width:480px){
  .ctrip-profile-city-row{grid-template-columns:22px minmax(50px,72px) minmax(72px,1fr) 54px}
}
@media print{
  .ctrip-profile-tabs,.ctrip-profile-toggle{display:none!important}
  .ctrip-profile-panel[hidden]{display:block!important}
  .ctrip-profile-panel{margin-top:10px}
  .ctrip-profile-detail-row{display:none!important}
}
</style>
"""

SCRIPT = """
<script id='CTRIP_USER_PROFILE_INTERACTION'>
(function(){
  document.querySelectorAll('[data-ctrip-profile]').forEach(function(root){
    var tabs = Array.prototype.slice.call(root.querySelectorAll('[data-profile-tab]'));
    var panels = Array.prototype.slice.call(root.querySelectorAll('[data-profile-panel]'));
    function activate(name){
      tabs.forEach(function(tab){
        var active = tab.getAttribute('data-profile-tab') === name;
        tab.classList.toggle('active', active);
        tab.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      panels.forEach(function(panel){
        panel.hidden = panel.getAttribute('data-profile-panel') !== name;
      });
    }
    tabs.forEach(function(tab){
      tab.addEventListener('click', function(){ activate(tab.getAttribute('data-profile-tab')); });
    });
    root.querySelectorAll('[data-profile-toggle]').forEach(function(button){
      button.addEventListener('click', function(){
        var code = button.getAttribute('data-profile-toggle');
        var expanded = button.getAttribute('aria-expanded') === 'true';
        root.querySelectorAll('[data-profile-detail="' + code + '"]').forEach(function(row){
          row.hidden = expanded;
        });
        button.setAttribute('aria-expanded', expanded ? 'false' : 'true');
        button.textContent = expanded ? '展开详情' : '收起详情';
      });
    });
    activate('basic');
  });
})();
</script>
"""


def e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(str(value).replace(",", "").rstrip("%"))
    except (TypeError, ValueError):
        return None
    return None if math.isnan(parsed) or math.isinf(parsed) else parsed


def pct(value: Any) -> str:
    parsed = number(value)
    return "—" if parsed is None else f"{parsed:.2f}%"


def _average_html(value: str | None) -> str:
    return f"<span class='ctrip-profile-average'>{e(value)}</span>" if value else ""


def _dimension_entries(charts: dict[str, Any], code: str) -> list[dict[str, Any]]:
    chart = charts.get(code) if isinstance(charts.get(code), dict) else {}
    entries = [
        dict(entry)
        for entry in list(chart.get("entries") or [])
        if isinstance(entry, dict) and (number(entry.get("rate_pct")) or 0) > 0
    ]
    entries.sort(key=lambda entry: -(number(entry.get("rate_pct")) or 0))
    return entries


def _dimension_rows(
    charts: dict[str, Any],
    dimensions: tuple[tuple[str, str, str | None], ...],
) -> str:
    rows: list[str] = []
    for code, label, average in dimensions:
        entries = _dimension_entries(charts, code)
        if not entries:
            rows.append(
                "<tr class='ctrip-profile-summary-row'>"
                f"<td class='ctrip-profile-dimension'><div class='ctrip-profile-dimension-inner'><span>{e(label)}</span>{_average_html(average)}</div></td>"
                "<td class='ctrip-profile-table-empty' colspan='4'>待接入</td></tr>"
            )
            continue

        main = entries[0]
        secondary = entries[1] if len(entries) > 1 else None
        main_value = number(main.get("rate_pct")) or 0
        width = min(100.0, max(0.0, main_value))
        secondary_html = (
            f"<span class='ctrip-profile-secondary'>次要：{e(secondary.get('label'))} {e(pct(secondary.get('rate_pct')))}</span>"
            if secondary
            else ""
        )
        toggle = (
            f"<button class='ctrip-profile-toggle' type='button' aria-expanded='false' data-profile-toggle='{e(code)}'>展开详情</button>"
            if len(entries) > 1
            else ""
        )
        rows.append(
            "<tr class='ctrip-profile-summary-row'>"
            f"<td class='ctrip-profile-dimension'><div class='ctrip-profile-dimension-inner'><span>{e(label)}</span>{_average_html(average)}</div></td>"
            "<td class='ctrip-profile-main'><div class='ctrip-profile-main-line' style='--profile-color:#2fa66a'>"
            f"<i class='ctrip-profile-dot'></i><span>{e(main.get('label'))}</span></div>{secondary_html}</td>"
            f"<td class='ctrip-profile-value'>{e(pct(main_value))}</td>"
            f"<td><div class='ctrip-profile-bar-track'><i class='ctrip-profile-bar-fill' style='--profile-color:#2fa66a;width:{width:.2f}%'></i></div></td>"
            f"<td class='ctrip-profile-action'>{toggle}</td></tr>"
        )

        for index, entry in enumerate(entries):
            value = number(entry.get("rate_pct")) or 0
            detail_width = min(100.0, max(0.0, value))
            color = COLORS[index % len(COLORS)]
            detail_label = "完整明细" if index == 0 else ""
            rows.append(
                f"<tr class='ctrip-profile-detail-row' data-profile-detail='{e(code)}' hidden>"
                f"<td class='ctrip-profile-detail-label'>{detail_label}</td>"
                f"<td class='ctrip-profile-detail-item'><div class='ctrip-profile-detail-item-line' style='--profile-color:{color}'>"
                f"<i class='ctrip-profile-dot'></i><span>{e(entry.get('label'))}</span></div></td>"
                f"<td class='ctrip-profile-detail-value'>{e(pct(value))}</td>"
                f"<td><div class='ctrip-profile-bar-track'><i class='ctrip-profile-bar-fill' style='--profile-color:{color};width:{detail_width:.2f}%'></i></div></td>"
                "<td></td></tr>"
            )
    return "".join(rows)


def _profile_panel(
    key: str,
    charts: dict[str, Any],
    dimensions: tuple[tuple[str, str, str | None], ...],
    *,
    hidden: bool,
) -> str:
    hidden_attr = " hidden" if hidden else ""
    return (
        f"<div class='ctrip-profile-panel' data-profile-panel='{e(key)}'{hidden_attr}>"
        "<div class='ctrip-profile-table-scroll'><table class='ctrip-profile-table'><thead><tr>"
        "<th>画像维度</th><th>主要细分项</th><th>占比</th><th>占比展示</th><th>操作</th>"
        "</tr></thead><tbody>"
        f"{_dimension_rows(charts, dimensions)}"
        "</tbody></table></div></div>"
    )


def profile_table(
    charts: dict[str, Any],
    average_advance: float | None,
    average_stay: float | None,
) -> str:
    categories = (
        (
            "basic",
            "基础画像",
            (
                ("gender", "性别", None),
                ("age_group", "年龄段", None),
                ("city_origin", "本地 / 异地", None),
            ),
        ),
        (
            "preference",
            "消费偏好",
            (
                ("travel_type", "出行目的", None),
                ("travel_time", "工作日 / 周末偏好", None),
                ("consumption_price", "消费价格带", None),
            ),
        ),
        (
            "booking",
            "预订行为",
            (
                (
                    "booking_advance_days",
                    "提前预订天数",
                    f"平均提前 {average_advance:g} 天" if average_advance is not None else None,
                ),
                (
                    "stay_days",
                    "入住晚数",
                    f"平均入住 {average_stay:g} 晚" if average_stay is not None else None,
                ),
            ),
        ),
    )
    tabs = "".join(
        f"<button class='ctrip-profile-tab{' active' if index == 0 else ''}' type='button' role='tab' "
        f"aria-selected='{'true' if index == 0 else 'false'}' data-profile-tab='{e(key)}'>{e(label)}</button>"
        for index, (key, label, _) in enumerate(categories)
    )
    panels = "".join(
        _profile_panel(key, charts, dimensions, hidden=index != 0)
        for index, (key, _, dimensions) in enumerate(categories)
    )
    return (
        "<div class='ctrip-profile-explorer' data-ctrip-profile>"
        f"<div class='ctrip-profile-tabs' role='tablist'>{tabs}</div>{panels}</div>"
    )


def city_card(entries: list[dict[str, Any]]) -> str:
    visible = [
        entry
        for entry in entries
        if (number(entry.get("rate_pct")) or 0) > 0 or (number(entry.get("count")) or 0) > 0
    ][:5]
    if not visible:
        rows = "<div class='ctrip-profile-empty'>待接入</div>"
    else:
        maximum = max(
            number(entry.get("rate_pct")) or number(entry.get("count")) or 0
            for entry in visible
        ) or 1
        rendered = []
        for index, entry in enumerate(visible):
            value = number(entry.get("rate_pct"))
            raw = value if value is not None else number(entry.get("count")) or 0
            width = max(2.0, raw / maximum * 100)
            display = pct(value) if value is not None else f"{raw:g}"
            color = COLORS[index % len(COLORS)]
            rendered.append(
                f"<div class='ctrip-profile-city-row' style='--profile-color:{color}'>"
                f"<span class='ctrip-profile-city-rank'>{index+1}</span>"
                f"<span class='ctrip-profile-city-name'>{e(entry.get('label'))}</span>"
                f"<span class='ctrip-profile-city-track'><i class='ctrip-profile-city-bar' style='width:{width:.2f}%'></i></span>"
                f"<span class='ctrip-profile-city-value'>{e(display)}</span></div>"
            )
        rows = "".join(rendered)
    return f"<section class='ctrip-profile-city'><h4>主要客源城市（Top5）</h4>{rows}</section>"


def _hour(label: Any) -> float:
    text = str(label or "").strip()
    try:
        hour, minute = text.split(":", 1)
        return float(hour) + float(minute) / 60
    except (ValueError, TypeError):
        parsed = number(text)
        return parsed if parsed is not None else 0.0


def hourly_chart(entries: list[dict[str, Any]], peak: dict[str, Any] | None) -> str:
    visible = [entry for entry in entries if (number(entry.get("rate_pct")) or 0) > 0]
    if not visible:
        return "<div class='ctrip-profile-hourly-empty'>小时分布实时字段待接入</div>"

    width, height = 620.0, 168.0
    left, right, top, bottom = 36.0, 12.0, 18.0, 28.0
    chart_w, chart_h = width - left - right, height - top - bottom
    maximum = (max(number(entry.get("rate_pct")) or 0 for entry in visible) or 1) * 1.15
    points: list[tuple[float, float, dict[str, Any]]] = []
    for entry in visible:
        x = left + min(24.0, max(0.0, _hour(entry.get("label")))) / 24.0 * chart_w
        y = top + (1 - (number(entry.get("rate_pct")) or 0) / maximum) * chart_h
        points.append((x, y, entry))
    points.sort(key=lambda item: item[0])
    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y, _ in points)
    area = f"{left:.2f},{top+chart_h:.2f} {polyline} {points[-1][0]:.2f},{top+chart_h:.2f}"

    grid = []
    for fraction in (0, .5, 1):
        y = top + (1 - fraction) * chart_h
        grid.append(
            f"<line x1='{left:g}' y1='{y:.2f}' x2='{left+chart_w:.2f}' y2='{y:.2f}' stroke='#e8eeeb' stroke-width='1'/>"
        )
        grid.append(
            f"<text x='{left-5:g}' y='{y:.2f}' text-anchor='end' dominant-baseline='middle' fill='#7d8991' font-size='9'>{maximum*fraction:.0f}%</text>"
        )
    x_labels = []
    for hour in (0, 6, 12, 18, 24):
        x = left + hour / 24 * chart_w
        x_labels.append(
            f"<text x='{x:.2f}' y='{height-7:g}' text-anchor='middle' fill='#7d8991' font-size='9'>{hour:02d}:00</text>"
        )

    peak_label = str((peak or {}).get("label") or "")
    peak_point = (
        min(points, key=lambda item: abs(_hour(item[2].get("label")) - _hour(peak_label)))
        if peak_label
        else max(points, key=lambda item: number(item[2].get("rate_pct")) or 0)
    )
    px, py, pentry = peak_point
    marker = (
        f"<line x1='{px:.2f}' y1='{py:.2f}' x2='{px:.2f}' y2='{top+chart_h:.2f}' stroke='#16845b' stroke-width='1' stroke-dasharray='3 3'/>"
        f"<circle cx='{px:.2f}' cy='{py:.2f}' r='4' fill='#16845b' stroke='#fff' stroke-width='2'/>"
        f"<rect x='{px-22:.2f}' y='{max(1,py-29):.2f}' width='44' height='20' rx='5' fill='#16845b'/>"
        f"<text x='{px:.2f}' y='{max(11,py-19):.2f}' text-anchor='middle' dominant-baseline='middle' fill='#fff' font-size='9.5' font-weight='750'>{e(pentry.get('label'))}</text>"
    )
    svg = (
        f"<svg class='ctrip-profile-hourly-svg' viewBox='0 0 {width:g} {height:g}' role='img' aria-label='主要预订时段小时分布'>"
        + "".join(grid)
        + f"<polygon points='{area}' fill='#dff3e8' opacity='.72'/>"
        + f"<polyline points='{polyline}' fill='none' stroke='#16845b' stroke-width='2.2' stroke-linejoin='round' stroke-linecap='round'/>"
        + "".join(f"<circle cx='{x:.2f}' cy='{y:.2f}' r='2.2' fill='#16845b'/>" for x, y, _ in points)
        + marker
        + "".join(x_labels)
        + "</svg>"
    )
    return f"<div class='ctrip-profile-hourly-scroll'>{svg}</div>"


def peak_card(peak: dict[str, Any] | None, hourly: list[dict[str, Any]]) -> str:
    peak_label = (peak or {}).get("label") or "待接入"
    peak_rate = pct((peak or {}).get("rate_pct"))
    summary = (
        "<div class='ctrip-profile-peak-summary'><small>高峰时段</small>"
        f"<strong>{e(peak_label)}</strong><small>该时段订单占比</small><b>{e(peak_rate)}</b></div>"
    )
    return (
        "<section class='ctrip-profile-peak'><h4>主要预订时段</h4>"
        f"<div class='ctrip-profile-peak-layout'>{summary}{hourly_chart(hourly, peak)}</div></section>"
    )


def card(result: dict[str, Any]) -> str:
    item_spec = upstream.spec(4)
    no, title, _, period, description, source, _ = item_spec
    payload = upstream.item_payload(result, item_spec)
    key, text, css = upstream.status(payload)
    charts = payload.get("charts") if isinstance(payload.get("charts"), dict) else {}
    average_advance = number(payload.get("average_advance_days"))
    average_stay = number(payload.get("average_stay_nights"))
    source_text = payload.get("source") or source
    source_path = payload.get("source_path") or "携程 eBooking -> 数据中心 -> 用户行为"

    return (
        f"<article class='diagnosis-card' data-status='{e(key)}' data-title='{e(title)}' id='rule-{no}'>"
        "<div class='card-top'>"
        f"<div class='rule-no'>{no:02d}</div>"
        f"<div class='card-title'><h3>{e(title)}</h3><p>{e(description)}</p></div>"
        "<div class='card-tags'>"
        f"<div class='title-meta-item title-period'><small>统计周期</small><strong>{e(period)}</strong></div>"
        "<div class='title-meta-item title-score display-only'><small>当前得分</small>"
        f"<div class='title-score-value'><strong>{e(upstream.score_text(item_spec, payload))}</strong>"
        f"<span>满分 {e(upstream.full_text(item_spec, payload))}</span></div></div>"
        f"<span class='status-badge {css}'>{e(text)}</span></div></div>"
        "<div class='result-area'>"
        f"{profile_table(charts, average_advance, average_stay)}"
        f"<div class='ctrip-profile-bottom'>{city_card(list(payload.get('city_top5') or []))}"
        f"{peak_card(payload.get('peak_time') if isinstance(payload.get('peak_time'), dict) else None, list(payload.get('hourly_distribution') or []))}</div>"
        f"<div class='ctrip-profile-source'><b>携程数据来源：</b>{e(source_path)}（{e(source_text)}）</div>"
        f"</div>{SCRIPT}</article>"
    )


__all__ = ["STYLE", "SCRIPT", "card", "profile_table"]

from __future__ import annotations

from datetime import datetime
from typing import Any

from marketing_diagnosis import reporting_v30, reporting_v35, reporting_v37
from marketing_diagnosis import ctrip_report_v54 as upstream
from marketing_diagnosis import ctrip_reputation_report as _ctrip_reputation_report
from marketing_diagnosis.ctrip_psi_v53 import card as psi_card
from marketing_diagnosis.ctrip_user_profile_report import STYLE as PROFILE_STYLE
from marketing_diagnosis.ctrip_user_profile_report import card as profile_card


SPECS = upstream.SPECS

COMPETITION_STYLE = """
<style id='CTRIP_COMPETITION_STABLE'>
.ctrip-overview-grid{grid-template-columns:minmax(0,1.65fr) minmax(300px,.75fr);align-items:stretch;gap:30px}
.ctrip-overview-copy{display:flex;min-width:0;flex-direction:column;justify-content:center;padding:12px 0}
.ctrip-overview-copy h2{font-size:32px;line-height:1.25}
.ctrip-overview-copy p{max-width:780px;margin-top:12px;font-size:16px;line-height:1.65}
.ctrip-overview-period{display:inline-flex;width:max-content;max-width:100%;align-items:center;gap:14px;margin-top:26px;padding:14px 18px;border:1px solid rgba(255,255,255,.22);border-radius:12px;background:rgba(255,255,255,.12)}
.ctrip-overview-period small{color:rgba(255,255,255,.72);font-size:13px;font-weight:700}
.ctrip-overview-period strong{color:#fff;font-size:18px;line-height:1.35;overflow-wrap:anywhere}
.ctrip-overview-score{display:flex;min-height:230px;flex-direction:column;justify-content:center;padding:32px 38px;border-radius:20px;background:#fff;color:#1f2933;box-shadow:0 14px 34px rgba(14,48,39,.12)}
.ctrip-overview-score small{color:#68747f;font-size:15px;font-weight:800}
.ctrip-overview-score strong{display:block;margin-top:14px;font-size:54px;line-height:1;font-variant-numeric:tabular-nums}
.ctrip-overview-score span{display:block;margin-top:15px;color:#68747f;font-size:17px}
.ctrip-summary-head{align-items:center}
.ctrip-summary-head>div{min-width:0}
.ctrip-summary-toggle{display:inline-flex;min-width:116px;height:40px;align-items:center;justify-content:center;padding:0 16px;border:1px solid #bdd8cc;border-radius:9px;background:#f3faf7;color:#16845b;font-weight:850;cursor:pointer;white-space:nowrap}
.ctrip-summary-toggle:hover{background:#e8f5ef}
.ctrip-summary-toggle:focus-visible{outline:3px solid rgba(22,132,91,.2);outline-offset:2px}
.ctrip-summary-toolbar-row{display:flex;justify-content:flex-end;padding:15px 18px 0}
.ctrip-summary-content[hidden]{display:none!important}
.ctrip-summary-section.is-collapsed .section-head{border-bottom:0}
.ctrip-funnel-panel{padding:15px;border:1px solid #dfe7e4;border-radius:10px;background:#fff}
.ctrip-funnel-head{display:grid;grid-template-columns:minmax(150px,1fr) 150px minmax(150px,1fr);align-items:center;gap:12px;margin-bottom:10px;text-align:center;font-size:13px;font-weight:850}
.ctrip-funnel-head .hotel{color:#2563eb}.ctrip-funnel-head .peer{color:#16845b}.ctrip-funnel-head .stage{color:#53616b}
.ctrip-funnel-row{display:grid;grid-template-columns:minmax(150px,1fr) 150px minmax(150px,1fr);align-items:center;gap:12px;min-height:48px;border-bottom:1px solid #edf2f0}
.ctrip-funnel-row:last-child{border-bottom:0}
.ctrip-funnel-side{display:flex;align-items:center;justify-content:center;min-width:0}
.ctrip-funnel-block{display:flex;height:40px;align-items:center;justify-content:center;clip-path:polygon(7% 0,93% 0,86% 100%,14% 100%);font-size:16px;font-weight:900}
.ctrip-funnel-block.hotel{margin-left:auto;background:linear-gradient(90deg,#dfeaff,#83aef5);color:#173b7a}
.ctrip-funnel-block.peer{margin-right:auto;background:linear-gradient(90deg,#b8ead8,#dff5eb);color:#126546}
.ctrip-funnel-stage{color:#2e3c46;text-align:center;font-size:13px;font-weight:800;overflow-wrap:anywhere}
.ctrip-funnel-empty-value{color:#81909a;font-size:12px;font-weight:750}
.ctrip-competition-bottom{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.15fr);gap:12px}
.ctrip-competition-card{min-width:0;padding:14px;border:1px solid #dfe7e4;border-radius:10px;background:#fff}
.ctrip-competition-card h4{margin:0 0 11px;color:#26343d;font-size:15px}
.ctrip-competition-table-scroll{max-width:100%;overflow-x:auto}
.ctrip-competition-table{width:100%;min-width:520px;border-collapse:collapse}
.ctrip-competition-table th,.ctrip-competition-table td{padding:9px 10px;border-bottom:1px solid #eaf0ed;text-align:left;font-size:12px}
.ctrip-competition-table th{background:#f7faf9;color:#63707a;font-weight:800}
.ctrip-competition-table td{color:#34424b}
.ctrip-competition-table td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ctrip-rank-pill{display:inline-flex;min-width:44px;justify-content:center;padding:3px 8px;border-radius:999px;background:#e8f5ef;color:#16845b;font-weight:850}
.ctrip-loss-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-bottom:12px}
.ctrip-loss-stat{padding:11px 12px;border:1px solid #e1e9e6;border-radius:8px;background:#f8fbfa}
.ctrip-loss-stat small{display:block;color:#7a8790;font-size:11px;font-weight:700}
.ctrip-loss-stat strong{display:block;margin-top:6px;color:#27343d;font-size:20px}
.ctrip-loss-tabs{display:flex;gap:8px;margin-bottom:9px;padding:4px;border-radius:8px;background:#f3f7f5}
.ctrip-loss-tab{flex:1;padding:8px 12px;border:1px solid transparent;border-radius:6px;background:transparent;color:#68767f;font-size:12px;font-weight:800;cursor:pointer}
.ctrip-loss-tab.active{border-color:#94cdb5;background:#fff;color:#16845b;box-shadow:0 1px 4px rgba(27,91,67,.08)}
.ctrip-loss-platform{overflow:hidden;border:1px solid #e1e9e6;border-radius:8px;background:#fff}
.ctrip-loss-platform[hidden]{display:none}
.ctrip-loss-platform h5{margin:0;padding:9px 11px;border-bottom:1px solid #e8eeeb;background:#f6faf8;color:#31584b;font-size:12px}
.ctrip-loss-list{margin:0;padding:0;list-style:none}
.ctrip-loss-list li{display:grid;grid-template-columns:25px minmax(0,1fr);gap:7px;align-items:start;padding:8px 10px;border-bottom:1px solid #eef2f1;font-size:11px}
.ctrip-loss-list li:last-child{border-bottom:0}
.ctrip-loss-rank{width:20px;height:20px;display:grid;place-items:center;border-radius:50%;background:#e8f5ef;color:#16845b;font-size:10px;font-weight:900}
.ctrip-loss-name{color:#3c4953;line-height:1.4;overflow-wrap:anywhere}
.ctrip-competition-source{margin-top:12px;padding:10px 12px;border:1px solid #eadfc9;border-radius:9px;background:#fff9ef;color:#876429;font-size:12px;overflow-wrap:anywhere}
.ctrip-competition-empty{padding:18px;color:#89959e;text-align:center}
@media(max-width:1100px){.ctrip-overview-grid{grid-template-columns:minmax(0,1.35fr) minmax(260px,.65fr)}.ctrip-overview-copy h2{font-size:28px}.ctrip-overview-score{min-height:205px;padding:28px}.ctrip-overview-score strong{font-size:48px}}
@media(max-width:980px){.ctrip-overview-grid,.ctrip-competition-bottom{grid-template-columns:1fr}.ctrip-overview-score{min-height:auto}.ctrip-overview-period{width:100%;justify-content:space-between}}
@media(max-width:760px){.ctrip-overview-copy h2{font-size:24px}.ctrip-overview-copy p{font-size:14px}.ctrip-overview-period{align-items:flex-start;flex-direction:column;gap:4px}.ctrip-summary-head{align-items:stretch;flex-direction:column}.ctrip-summary-toggle{width:100%}.ctrip-summary-toolbar-row{justify-content:stretch}.ctrip-summary-toolbar-row .toolbar{width:100%}.ctrip-summary-toolbar-row .search,.ctrip-summary-toolbar-row .filter{width:100%;min-width:0}.ctrip-funnel-panel{overflow-x:auto}.ctrip-funnel-head,.ctrip-funnel-row{min-width:650px}.ctrip-loss-summary{grid-template-columns:1fr}}
</style>
"""

LOSS_TAB_SCRIPT = """
<script id='CTRIP_LOSS_TAB_SCRIPT'>
(function(){
  document.querySelectorAll('[data-ctrip-loss-card]').forEach(function(card){
    card.querySelectorAll('[data-loss-tab]').forEach(function(button){
      button.addEventListener('click', function(){
        var platform = button.getAttribute('data-loss-tab');
        card.querySelectorAll('[data-loss-tab]').forEach(function(item){
          item.classList.toggle('active', item === button);
          item.setAttribute('aria-selected', item === button ? 'true' : 'false');
        });
        card.querySelectorAll('[data-loss-panel]').forEach(function(panel){
          panel.hidden = panel.getAttribute('data-loss-panel') !== platform;
        });
      });
    });
  });
})();
</script>
"""

SUMMARY_TOGGLE_SCRIPT = """
<script id='CTRIP_SUMMARY_TOGGLE_SCRIPT'>
(function(){
  document.querySelectorAll('[data-ctrip-summary]').forEach(function(section){
    var button = section.querySelector('[data-summary-toggle]');
    var content = section.querySelector('[data-summary-content]');
    if(!button || !content) return;
    function setExpanded(expanded){
      content.hidden = !expanded;
      section.classList.toggle('is-collapsed', !expanded);
      button.setAttribute('aria-expanded', expanded ? 'true' : 'false');
      button.textContent = expanded ? '收起总览' : '展开总览';
    }
    button.addEventListener('click', function(){
      setExpanded(button.getAttribute('aria-expanded') !== 'true');
    });
    setExpanded(false);
  });
})();
</script>
"""


def _number(value: Any) -> float | None:
    return upstream.number(value)


def _plain_number(value: Any, *, decimals: int | None = None) -> str:
    number = _number(value)
    if number is None:
        return "待接入"
    if decimals is not None:
        return f"{number:,.{decimals}f}"
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"


def _metric_value(value: Any, unit: str = "") -> str:
    number = _number(value)
    if number is None:
        return "待接入"
    if unit == "%":
        percent = number * 100 if abs(number) <= 1 else number
        return f"{percent:.2f}"
    if unit == "元":
        return f"{number:,.2f}"
    return f"{number:,.0f}" if number.is_integer() else f"{number:,.2f}"


def overview_html(result: dict[str, Any]) -> str:
    payload = upstream.summary_payload(result)
    total = _number(payload.get("total_score") or payload.get("score"))
    total_text = "0.0" if total is None else f"{total:.1f}"
    full_score = sum(float(item[2]) for item in SPECS if item[2] is not None)
    start = result.get("period_start") or "未标注"
    end = result.get("period_end") or "未标注"
    return (
        "<section id='overview'><div class='hero'>"
        "<div class='hero-grid ctrip-overview-grid'>"
        "<div class='ctrip-overview-copy'>"
        "<h2>携程渠道经营与服务质量诊断</h2>"
        "<p>覆盖经营趋势、流量、客群、推广、口碑及平台配置等22项诊断内容。</p>"
        "<div class='ctrip-overview-period'><small>诊断周期</small>"
        f"<strong>{upstream.e(start)} 至 {upstream.e(end)}</strong></div>"
        "</div>"
        "<div class='ctrip-overview-score'>"
        "<small>携程综合得分</small>"
        f"<strong>{upstream.e(total_text)}</strong>"
        f"<span>满分{full_score:g}分</span>"
        "</div></div></div></section>"
    )


def summary_html(result: dict[str, Any]) -> str:
    rows = "".join(upstream.summary_row(result, item_spec) for item_spec in SPECS)
    return (
        "<section id='summary' class='ctrip-summary-section is-collapsed' data-ctrip-summary>"
        "<div class='section-head ctrip-summary-head'><div>"
        "<h2>携程诊断结果总览</h2>"
        "<p>携程目录、满分、得分和数据状态独立于美团页面。</p></div>"
        "<button class='ctrip-summary-toggle' type='button' aria-expanded='false' "
        "aria-controls='ctripSummaryContent' data-summary-toggle>展开总览</button></div>"
        "<div class='ctrip-summary-content' id='ctripSummaryContent' data-summary-content hidden>"
        "<div class='ctrip-summary-toolbar-row'><div class='toolbar'>"
        "<input class='search' id='ruleSearch' placeholder='搜索诊断项'/>"
        "<select class='filter' id='statusFilter'><option value='all'>全部状态</option>"
        "<option value='success'>已形成结果</option><option value='missing'>数据待接入</option>"
        "<option value='pending_rule'>规则待确认</option></select></div></div>"
        "<div class='section-body'><div class='table-scroll'><table class='summary-table'>"
        "<thead><tr><th>编号</th><th>携程诊断项目</th><th>满分</th><th>当前得分</th>"
        "<th>当前状态</th><th>数据来源/诊断内容</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></div></div></section>"
    )


def _funnel_content(payload: dict[str, Any]) -> str:
    stages = [stage for stage in payload.get("funnel_stages") or [] if isinstance(stage, dict)]
    if not stages:
        stages = [
            {"label": "列表页曝光量", "hotel_value": None, "competitor_avg": None},
            {"label": "详情页访客量", "hotel_value": None, "competitor_avg": None},
            {"label": "订单页访客量", "hotel_value": None, "competitor_avg": None},
            {"label": "订单提交人数", "hotel_value": None, "competitor_avg": None},
            {"label": "成交订单数", "hotel_value": None, "competitor_avg": None},
        ]

    rows: list[str] = []
    total = max(len(stages), 1)
    for index, stage in enumerate(stages):
        width = max(52, 100 - index * (42 / total))
        hotel_value = _plain_number(stage.get("hotel_value"))
        competitor_value = _plain_number(stage.get("competitor_avg"))
        hotel_class = " ctrip-funnel-empty-value" if hotel_value == "待接入" else ""
        peer_class = " ctrip-funnel-empty-value" if competitor_value == "待接入" else ""
        rows.append(
            "<div class='ctrip-funnel-row'>"
            f"<div class='ctrip-funnel-side'><div class='ctrip-funnel-block hotel{hotel_class}' style='width:{width:.1f}%'>{upstream.e(hotel_value)}</div></div>"
            f"<div class='ctrip-funnel-stage'>{upstream.e(stage.get('label') or '漏斗阶段')}</div>"
            f"<div class='ctrip-funnel-side'><div class='ctrip-funnel-block peer{peer_class}' style='width:{width:.1f}%'>{upstream.e(competitor_value)}</div></div>"
            "</div>"
        )
    return (
        "<div class='ctrip-funnel-panel'>"
        "<div class='ctrip-funnel-head'><span class='hotel'>我的酒店</span><span class='stage'>漏斗阶段</span><span class='peer'>竞争圈平均</span></div>"
        + "".join(rows)
        + "</div>"
    )


def _competition_rankings(payload: dict[str, Any]) -> str:
    entries = [entry for entry in payload.get("competition_metrics") or [] if isinstance(entry, dict)]
    if not entries:
        body = "<div class='ctrip-competition-empty'>竞争圈指标待接入</div>"
    else:
        rows = []
        for entry in entries:
            unit = str(entry.get("unit") or "")
            label = str(entry.get("label") or entry.get("metric_code") or "指标")
            label_with_unit = f"{label}（{unit}）" if unit else label
            rank = _number(entry.get("competitor_rank"))
            count = _number(entry.get("competitor_count"))
            rank_text = "待接入" if rank is None else f"第 {rank:g} 名" + (f" / {count:g}家" if count is not None else "")
            rows.append(
                "<tr>"
                f"<td>{upstream.e(label_with_unit)}</td>"
                f"<td class='num'>{upstream.e(_metric_value(entry.get('hotel_value'), unit))}</td>"
                f"<td class='num'>{upstream.e(_metric_value(entry.get('competitor_avg'), unit))}</td>"
                f"<td class='num'><span class='ctrip-rank-pill'>{upstream.e(rank_text)}</span></td>"
                "</tr>"
            )
        body = (
            "<div class='ctrip-competition-table-scroll'><table class='ctrip-competition-table'>"
            "<thead><tr><th>竞争圈指标（单位见指标名）</th><th>我的数据</th><th>竞争圈平均</th><th>竞争圈排名</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table></div>"
        )
    return f"<section class='ctrip-competition-card'><h4>竞争圈核心指标与排名</h4>{body}</section>"


def _competitor_list(entries: list[dict[str, Any]], title: str, platform: str, *, hidden: bool) -> str:
    if not entries:
        rows = "<li><span class='ctrip-loss-rank'>—</span><span class='ctrip-loss-name'>待接入</span></li>"
    else:
        rendered = []
        for index, entry in enumerate(entries[:5]):
            rank = _number(entry.get("ranking_position"))
            rank_text = f"{rank:g}" if rank is not None else str(index + 1)
            rendered.append(
                "<li>"
                f"<span class='ctrip-loss-rank'>{upstream.e(rank_text)}</span>"
                f"<span class='ctrip-loss-name'>{upstream.e(entry.get('competitor_hotel_name') or '未命名竞对')}</span>"
                "</li>"
            )
        rows = "".join(rendered)
    hidden_attr = " hidden" if hidden else ""
    return (
        f"<div class='ctrip-loss-platform' data-loss-panel='{upstream.e(platform)}'{hidden_attr}>"
        f"<h5>{upstream.e(title)} Top5</h5><ol class='ctrip-loss-list'>{rows}</ol></div>"
    )


def _loss_competitors(payload: dict[str, Any]) -> str:
    summary = payload.get("loss_summary") if isinstance(payload.get("loss_summary"), dict) else {}
    competitors = payload.get("loss_competitors") if isinstance(payload.get("loss_competitors"), dict) else {}
    date_text = str(summary.get("business_date") or "数据库昨日")
    return (
        "<section class='ctrip-competition-card' data-ctrip-loss-card><h4>昨日流失与主要流失竞对</h4>"
        "<div class='ctrip-loss-summary'>"
        f"<div class='ctrip-loss-stat'><small>流失订单量（单）｜{upstream.e(date_text)}</small><strong>{upstream.e(_plain_number(summary.get('order_count')))}</strong></div>"
        f"<div class='ctrip-loss-stat'><small>流失订单金额（元）｜{upstream.e(date_text)}</small><strong>{upstream.e(_plain_number(summary.get('order_amount'), decimals=2))}</strong></div>"
        "</div>"
        "<div class='ctrip-loss-tabs' role='tablist'>"
        "<button class='ctrip-loss-tab active' type='button' role='tab' aria-selected='true' data-loss-tab='ctrip'>携程 Top5</button>"
        "<button class='ctrip-loss-tab' type='button' role='tab' aria-selected='false' data-loss-tab='qunar'>去哪儿 Top5</button>"
        "</div>"
        f"{_competitor_list(list(competitors.get('ctrip') or []), '携程', 'ctrip', hidden=False)}"
        f"{_competitor_list(list(competitors.get('qunar') or []), '去哪儿', 'qunar', hidden=True)}"
        "</section>"
    )


def _card_header(item_spec: tuple[Any, ...], payload: dict[str, Any]) -> tuple[str, str, str, str]:
    no, title, _, period, description, _, _ = item_spec
    key, text, css = upstream.status(payload)
    score_class = "ok" if upstream.score_value(payload) is not None else "pending"
    html = (
        "<div class='card-top'>"
        f"<div class='rule-no'>{no:02d}</div>"
        f"<div class='card-title'><h3>{upstream.e(title)}</h3><p>{upstream.e(description)}</p></div>"
        "<div class='card-tags'>"
        f"<div class='title-meta-item title-period'><small>统计周期</small><strong>{upstream.e(period)}</strong></div>"
        f"<div class='title-meta-item title-score {score_class}'><small>当前得分</small>"
        f"<div class='title-score-value'><strong>{upstream.e(upstream.score_text(item_spec, payload))}</strong>"
        f"<span>满分 {upstream.e(upstream.full_text(item_spec, payload))}</span></div></div>"
        f"<span class='status-badge {css}'>{upstream.e(text)}</span></div></div>"
    )
    return html, str(no), str(title), str(key)


def funnel_card(result: dict[str, Any]) -> str:
    item_spec = upstream.spec(3)
    payload = upstream.item_payload(result, item_spec)
    header, no, title, key = _card_header(item_spec, payload)
    source_path = payload.get("source_path") or "携程 eBooking -> 数据中心 -> 流量与转化"
    source_text = payload.get("source") or "待确认"
    return (
        f"<article class='diagnosis-card' data-status='{upstream.e(key)}' data-title='{upstream.e(title)}' id='rule-{no}'>"
        f"{header}<div class='result-area'>{_funnel_content(payload)}"
        f"<div class='ctrip-competition-source'><b>数据口径：</b>{upstream.e(source_path)}；数据表与字段映射：{upstream.e(source_text)}</div>"
        "</div></article>"
    )


def competition_analysis_card(result: dict[str, Any]) -> str:
    item_spec = upstream.spec(5)
    payload = upstream.item_payload(result, item_spec)
    header, no, title, key = _card_header(item_spec, payload)
    source_path = payload.get("source_path") or "携程 eBooking -> 数据中心 -> 竞争圈动态"
    source_text = payload.get("source") or "待确认"
    return (
        f"<article class='diagnosis-card' data-status='{upstream.e(key)}' data-title='{upstream.e(title)}' id='rule-{no}'>"
        f"{header}<div class='result-area'>"
        f"<div class='ctrip-competition-bottom'>{_competition_rankings(payload)}{_loss_competitors(payload)}</div>"
        f"<div class='ctrip-competition-source'><b>数据口径：</b>{upstream.e(source_path)}；数据表与字段映射：{upstream.e(source_text)}</div>"
        "</div></article>"
    )


def cards_html(result: dict[str, Any]) -> str:
    item_one = upstream.pms_item(result, 1)
    item_two = upstream.pms_item(result, 2)
    cards = [
        reporting_v37._performance_card(item_one),
        reporting_v35._clean_customer_html(reporting_v30._room_type_card(item_two)),
    ]
    for item_spec in SPECS[2:]:
        no = item_spec[0]
        if no == 3:
            cards.append(funnel_card(result))
        elif no == 4:
            cards.append(profile_card(result))
        elif no == 5:
            cards.append(competition_analysis_card(result))
        elif no == 6:
            cards.append(upstream.patch_psi_score(psi_card(result, "rule-6"), result))
        else:
            cards.append(upstream.generic_card(result, item_spec))
    return "".join(cards)


def build_head() -> str:
    head = upstream.build_head()
    return head.replace("</head>", COMPETITION_STYLE + PROFILE_STYLE + "</head>", 1)


def build_html(result: dict[str, Any]) -> str:
    """Generate the Ctrip report with stable custom renderers."""

    hotel = result.get("hotel_name") or result.get("hotel_id") or "酒店"
    start = result.get("period_start") or "未标注"
    end = result.get("period_end") or "未标注"
    body = (
        "<body><header class='topbar'><div class='topbar-inner'>"
        "<div class='brand'><h1>酒店 OTA 全面诊断报告</h1>"
        f"<p>{upstream.e(hotel)}｜诊断周期：{upstream.e(start)} 至 {upstream.e(end)}｜生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
        "</div><div class='top-actions'>"
        "<select class='scope-select'><option>携程综合诊断</option><option>PMS经营数据</option>"
        "<option>携程 eBooking 数据</option></select>"
        "<button class='btn primary' onclick='window.print()'>导出报告</button>"
        "</div></div></header>"
        f"<div class='page'>{upstream.nav_html()}<main>{overview_html(result)}{summary_html(result)}"
        f"{cards_html(result)}</main></div>{upstream.search_script()}{reporting_v37._script()}"
        f"{LOSS_TAB_SCRIPT}{SUMMARY_TOGGLE_SCRIPT}</body></html>"
    )
    return build_head() + body


competition_card = funnel_card

__all__ = [
    "SPECS",
    "build_html",
    "cards_html",
    "competition_analysis_card",
    "competition_card",
    "funnel_card",
    "overview_html",
    "summary_html",
]

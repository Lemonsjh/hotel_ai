from __future__ import annotations

import json
import re
from typing import Any

from marketing_diagnosis.channel_score_totals import ctrip_direct_total


_ARTICLE_RE = re.compile(
    r"<article class='diagnosis-card'(?=[^>]*\bid='ctrip-rule-21')[\s\S]*?</article>",
    re.IGNORECASE,
)
_SUMMARY_ROW_RE = re.compile(
    r"<tr(?P<attrs>[^>]*)>(?P<body>[\s\S]*?href='#module-21'[\s\S]*?)</tr>",
    re.IGNORECASE,
)


STYLE = """
<style id='CTRIP_MANUAL_LISTING_STYLE'>
.ctrip-manual-listing{display:grid;gap:16px}
.ctrip-manual-listing-form{display:grid;grid-template-columns:minmax(260px,1fr) auto auto;gap:12px;align-items:end;padding:16px;border:1px solid #dce8e3;border-radius:12px;background:#f7fbf9}
.ctrip-manual-listing-field{display:grid;gap:7px;color:#52616b;font-size:12px;font-weight:800}
.ctrip-manual-listing-field select{width:100%;height:42px;padding:0 12px;border:1px solid #cbd9d3;border-radius:8px;background:#fff;color:#26343d;font:inherit;font-size:14px}
.ctrip-manual-listing-button{height:42px;padding:0 18px;border:1px solid #16845b;border-radius:8px;background:#16845b;color:#fff;font:inherit;font-weight:850;cursor:pointer}
.ctrip-manual-listing-button.secondary{border-color:#c9d6d1;background:#fff;color:#52616b}
.ctrip-manual-listing-message{min-height:18px;color:#16845b;font-size:12px;font-weight:750}
@media(max-width:760px){.ctrip-manual-listing-form{grid-template-columns:1fr}.ctrip-manual-listing-button{width:100%}}
@media print{.ctrip-manual-listing-form{grid-template-columns:1fr}.ctrip-manual-listing-button{display:none}}
</style>
"""


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _item_21(result: dict[str, Any]) -> dict[str, Any]:
    items = result.get("ctrip_items") or {}
    if isinstance(items, dict):
        item = items.get("21") or items.get(21)
        return item if isinstance(item, dict) else {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and str(item.get("standard_item_id")) == "21":
                return item
    return {}


def _summary_base_total(result: dict[str, Any]) -> float:
    return ctrip_direct_total(result, exclude_ids={21})


def _storage_key(result: dict[str, Any]) -> str:
    parts = (
        result.get("hotel_id") or result.get("hotel_name") or "hotel",
        result.get("period_start") or "start",
        result.get("period_end") or "end",
    )
    return "s14:ctrip-listing:" + ":".join(str(value) for value in parts)


def _card_html() -> str:
    return """<article class='diagnosis-card' data-status='missing' data-title='挂牌 / 委托分销' id='ctrip-rule-21' data-channel-anchor='module-21'>
<div class='card-top'><div class='rule-no'>21</div><div class='card-title'><h3>挂牌 / 委托分销</h3><p>改为人工录入，按原有挂牌等级规则计分。</p></div>
<div class='card-tags'><div class='title-meta-item title-period'><small>统计周期</small><strong>当前值</strong></div><div class='title-meta-item title-score pending'><small>当前得分</small><div class='title-score-value'><strong data-ctrip-listing-card-score>待计算</strong><span>满分 6分</span></div></div><span class='status-badge pending' data-ctrip-listing-card-status>待人工录入</span></div></div>
<div class='result-area ctrip-manual-listing'><div class='ctrip-grid-v55'><div class='ctrip-metric-v55'><small>人工录入结果</small><strong class='ctrip-pending-v55' data-ctrip-listing-result>待录入</strong><span>本项仅使用手工保存的结果</span></div><div class='ctrip-metric-v55'><small>评分规则</small><strong>0 / 3 / 6分</strong><span>满分6分，不改变原评分档位</span></div></div>
<div class='ctrip-manual-listing-form'><label class='ctrip-manual-listing-field'>挂牌 / 委托分销等级<select data-ctrip-listing-select><option value=''>请选择实际情况</option><option value='premium'>高级 / 金牌（6分）</option><option value='standard'>普通 / 基础（3分）</option><option value='none'>未挂牌 / 未参加委托分销（0分）</option></select></label><button type='button' class='ctrip-manual-listing-button' data-ctrip-listing-save>保存并计分</button><button type='button' class='ctrip-manual-listing-button secondary' data-ctrip-listing-clear>清除</button></div>
<div class='ctrip-manual-listing-message' data-ctrip-listing-message></div></div></article>"""


def _pending_summary_row(match: re.Match[str]) -> str:
    row = match.group(0)
    row = re.sub(r"data-status='[^']*'", "data-status='missing'", row, count=1)
    cells = list(re.finditer(r"<td[^>]*>[\s\S]*?</td>", row, re.IGNORECASE))
    if len(cells) < 5:
        return row
    replacements = {
        3: "<td>待计算</td>",
        4: "<td><span class='status-badge pending'>待人工录入</span></td>",
    }
    for index in sorted(replacements, reverse=True):
        cell = cells[index]
        row = row[: cell.start()] + replacements[index] + row[cell.end() :]
    return row


def _script(result: dict[str, Any]) -> str:
    base_total = _summary_base_total(result)
    key = json.dumps(_storage_key(result), ensure_ascii=False).replace("</", "<\\/")
    return f"""
<script id='CTRIP_MANUAL_LISTING_SCRIPT'>
(function(){{
  const SCORE_RULES=Object.freeze({{
    premium:{{score:6,label:'高级 / 金牌'}},
    standard:{{score:3,label:'普通 / 基础'}},
    none:{{score:0,label:'未挂牌 / 未参加委托分销'}}
  }});
  const BASE_TOTAL={base_total!r};
  const STORAGE_KEY={key};
  function setup(){{
    const card=document.getElementById('ctrip-rule-21');
    if(!card||card.dataset.manualListingBound==='1') return;
    card.dataset.manualListingBound='1';
    const select=card.querySelector('[data-ctrip-listing-select]');
    const save=card.querySelector('[data-ctrip-listing-save]');
    const clear=card.querySelector('[data-ctrip-listing-clear]');
    const message=card.querySelector('[data-ctrip-listing-message]');
    const resultText=card.querySelector('[data-ctrip-listing-result]');
    const scoreText=card.querySelector('[data-ctrip-listing-card-score]');
    const status=card.querySelector('[data-ctrip-listing-card-status]');
    const scoreBox=scoreText.closest('.title-score');
    const summaryLink=document.querySelector("#ctrip-summary a[href='#module-21']");
    const summaryRow=summaryLink?summaryLink.closest('tr'):null;
    const totalText=document.querySelector("[data-channel-view='ctrip'] .ctrip-overview-score strong")||document.querySelector('.ctrip-overview-score strong');
    function total(value){{
      if(totalText) totalText.textContent=Number((BASE_TOTAL+(value||0)).toFixed(2)).toString();
    }}
    function apply(code,announce){{
      const rule=SCORE_RULES[code];
      select.value=rule?code:'';
      card.dataset.status=rule?'success':'missing';
      scoreText.textContent=rule?rule.score+'分':'待计算';
      resultText.textContent=rule?rule.label:'待录入';
      resultText.classList.toggle('ctrip-pending-v55',!rule);
      status.textContent=rule?'已人工录入':'待人工录入';
      status.className='status-badge '+(rule?'ok':'pending');
      if(scoreBox) scoreBox.className='title-meta-item title-score '+(rule?'ok':'pending');
      if(summaryRow){{
        summaryRow.dataset.status=rule?'success':'missing';
        const cells=summaryRow.querySelectorAll('td');
        if(cells[3]) cells[3].textContent=rule?rule.score+'分':'待计算';
        if(cells[4]) cells[4].innerHTML=rule?"<span class='status-badge ok'>已人工录入</span>":"<span class='status-badge pending'>待人工录入</span>";
      }}
      total(rule?rule.score:0);
      if(announce) message.textContent=rule?'已保存，本项按原规则计 '+rule.score+' 分。':'已清除人工录入，本项恢复待计算。';
    }}
    save.addEventListener('click',function(){{
      if(!SCORE_RULES[select.value]){{message.textContent='请先选择挂牌 / 委托分销等级。';return;}}
      try{{localStorage.setItem(STORAGE_KEY,select.value);}}catch(error){{}}
      apply(select.value,true);
    }});
    clear.addEventListener('click',function(){{
      try{{localStorage.removeItem(STORAGE_KEY);}}catch(error){{}}
      apply('',true);
    }});
    let saved='';
    try{{saved=localStorage.getItem(STORAGE_KEY)||'';}}catch(error){{}}
    apply(saved,false);
  }}
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',setup);
  else setup();
}})();
</script>
"""


def patch_html(document: str, result: dict[str, Any]) -> str:
    """Replace only Ctrip item 21 with a manual entry that keeps 0/3/6 scoring."""

    if "id='ctrip-rule-21'" not in document or "CTRIP_MANUAL_LISTING_SCRIPT" in document:
        return document
    document, count = _ARTICLE_RE.subn(_card_html(), document, count=1)
    if not count:
        return document
    document = _SUMMARY_ROW_RE.sub(_pending_summary_row, document, count=1)
    document = document.replace("</head>", STYLE + "</head>", 1)
    document = document.replace("</body>", _script(result) + "</body>", 1)
    return document


__all__ = ["patch_html"]

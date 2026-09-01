from __future__ import annotations

import re
from typing import Any

from marketing_diagnosis import ctrip_report as stable_ctrip_report
from marketing_diagnosis import dual_channel_report_v56 as upstream
from marketing_diagnosis.ctrip_flow_report import SCRIPT as FLOW_SCRIPT
from marketing_diagnosis.ctrip_flow_report import STYLE as FLOW_STYLE
from marketing_diagnosis.ctrip_flow_report import card as flow_card


build_ctrip_page = stable_ctrip_report.build_html


SIDEBAR_STYLE = """
<style id='OTA_COLLAPSIBLE_SIDEBAR_STABLE'>
.page.channel-view-v58{transition:grid-template-columns .2s ease,gap .2s ease}
.side-collapse-button{width:calc(100% - 16px);min-height:34px;margin:8px;padding:6px 9px;display:flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--line,#dfe7e4);border-radius:8px;background:#f7faf9;color:var(--green,#16845b);font:inherit;font-size:12px;font-weight:800;cursor:pointer}
.side-collapse-button:hover{background:var(--mint2,#f2faf6)}
.side-collapse-button .side-collapse-arrow{font-size:17px;line-height:1}
.page.sidebar-collapsed{grid-template-columns:58px minmax(0,1fr);gap:12px}
.page.sidebar-collapsed .side{overflow-x:hidden}
.page.sidebar-collapsed .side-title,.page.sidebar-collapsed .side-collapse-label{display:none}
.page.sidebar-collapsed .side-collapse-button{width:42px;margin:8px;padding:4px}
.page.sidebar-collapsed .side>a{justify-content:center;gap:0;padding:9px 4px;font-size:0}
.page.sidebar-collapsed .side>a span{width:32px;height:26px;font-size:11px;flex:0 0 auto}
.page.sidebar-collapsed main{min-width:0}
@media(max-width:900px){
  .page.channel-view-v58,.page.channel-view-v58.sidebar-collapsed{grid-template-columns:1fr;gap:12px}
  .page.channel-view-v58 .side{position:relative;top:auto;max-height:260px}
  .page.channel-view-v58.sidebar-collapsed .side{max-height:52px;overflow:hidden}
  .page.channel-view-v58.sidebar-collapsed .side-collapse-button{width:calc(100% - 16px);margin:8px}
  .page.channel-view-v58.sidebar-collapsed .side-collapse-label{display:inline}
  .page.channel-view-v58.sidebar-collapsed .side>a,.page.channel-view-v58.sidebar-collapsed .side-title{display:none}
}
</style>
"""


CTRIP_CLEANUP_STYLE = """
<style id='CTRIP_VISIBLE_EXPLANATION_CLEANUP_STYLE'>
.page[data-channel-view='ctrip'] .ctrip-source-v55,
.page[data-channel-view='ctrip'] .ctrip-competition-source,
.page[data-channel-view='ctrip'] .psi-source-v53{
  display:none!important;
}
.page[data-channel-view='ctrip'] .ctrip-loss-platform h5{
  display:flex;
  align-items:center;
  gap:8px;
}
.page[data-channel-view='ctrip'] .ctrip-loss-period-tag{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  padding:2px 7px;
  border:1px solid #b9dfcf;
  border-radius:999px;
  background:#eaf7f1;
  color:#16845b;
  font-size:10px;
  font-weight:800;
  line-height:1.2;
  white-space:nowrap;
}
</style>
"""


SIDEBAR_SCRIPT = r"""
<script id='OTA_COLLAPSIBLE_SIDEBAR_SCRIPT_STABLE'>
(function(){
  function setup(){
    document.querySelectorAll('.page[data-channel-view]').forEach(function(view){
      const side=view.querySelector('.side');
      if(!side||side.querySelector('.side-collapse-button')) return;
      const channel=view.dataset.channelView||'report';
      const key='ota-sidebar-collapsed-'+channel;
      const button=document.createElement('button');
      button.type='button';
      button.className='side-collapse-button';
      side.insertBefore(button,side.firstChild);

      function apply(collapsed){
        view.classList.toggle('sidebar-collapsed',collapsed);
        button.setAttribute('aria-expanded',collapsed?'false':'true');
        button.setAttribute('title',collapsed?'展开左侧目录':'收起左侧目录');
        button.innerHTML='<span class="side-collapse-arrow">'+(collapsed?'›':'‹')+'</span><span class="side-collapse-label">'+(collapsed?'展开目录':'收起目录')+'</span>';
        try{localStorage.setItem(key,collapsed?'1':'0');}catch(error){}
        requestAnimationFrame(function(){window.dispatchEvent(new Event('resize'));});
      }

      let collapsed=false;
      try{collapsed=localStorage.getItem(key)==='1';}catch(error){}
      apply(collapsed);
      button.addEventListener('click',function(){apply(!view.classList.contains('sidebar-collapsed'));});
    });
  }
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',setup);
  else setup();
})();
</script>
"""


PROFILE_INTERACTION_FIX_SCRIPT = r"""
<script id='CTRIP_USER_PROFILE_INTERACTION_FIX_STABLE'>
(function(){
  function profileRoot(node){
    return node && node.closest ? node.closest('[data-ctrip-profile]') : null;
  }

  document.addEventListener('click',function(event){
    const toggle=event.target.closest('[data-profile-toggle]');
    if(toggle){
      const root=profileRoot(toggle);
      if(!root) return;
      event.preventDefault();
      event.stopImmediatePropagation();

      const code=toggle.getAttribute('data-profile-toggle');
      const expanded=toggle.getAttribute('aria-expanded')==='true';
      root.querySelectorAll('[data-profile-detail="'+CSS.escape(code)+'"]').forEach(function(row){
        row.hidden=expanded;
      });
      toggle.setAttribute('aria-expanded',expanded?'false':'true');
      toggle.textContent=expanded?'展开详情':'收起详情';
      return;
    }

    const tab=event.target.closest('[data-profile-tab]');
    if(tab){
      const root=profileRoot(tab);
      if(!root) return;
      event.preventDefault();
      event.stopImmediatePropagation();

      const name=tab.getAttribute('data-profile-tab');
      root.querySelectorAll('[data-profile-tab]').forEach(function(item){
        const active=item.getAttribute('data-profile-tab')===name;
        item.classList.toggle('active',active);
        item.setAttribute('aria-selected',active?'true':'false');
      });
      root.querySelectorAll('[data-profile-panel]').forEach(function(panel){
        panel.hidden=panel.getAttribute('data-profile-panel')!==name;
      });
    }
  },true);
})();
</script>
"""


CTRIP_CONTENT_CLEANUP_SCRIPT = r"""
<script id='CTRIP_VISIBLE_EXPLANATION_CLEANUP_SCRIPT'>
(function(){
  const labels=[
    '携程数据来源',
    '数据来源',
    '数据口径',
    '页面数据来源',
    '数据库来源与计分口径',
    '重点结论'
  ];
  const boundaries='article,.result-area,main,.page';

  function cleanText(value){
    return String(value||'').replace(/\s+/g,' ').trim();
  }

  function matchedLabel(node){
    const text=cleanText(node&&node.textContent);
    return labels.find(function(label){return text.startsWith(label);})||'';
  }

  function safeContainer(node,label,root){
    let target=node;
    while(target.parentElement&&target.parentElement!==root){
      const parent=target.parentElement;
      if(parent.matches(boundaries)) break;
      if(!cleanText(parent.textContent).startsWith(label)) break;
      target=parent;
    }
    if(target.matches('b,strong,span,small,h1,h2,h3,h4,h5,h6')){
      const parent=target.parentElement;
      if(parent&&parent!==root&&!parent.matches(boundaries)) target=parent;
    }
    return target;
  }

  function removeSummarySourceColumn(root){
    root.querySelectorAll('table').forEach(function(table){
      const headers=Array.from(table.querySelectorAll('thead th'));
      const index=headers.findIndex(function(header){
        return cleanText(header.textContent).includes('数据来源');
      });
      if(index<0) return;
      table.querySelectorAll('tr').forEach(function(row){
        const cells=row.children;
        if(cells&&cells[index]) cells[index].remove();
      });
    });
  }

  function setup(){
    const root=document.querySelector('.page[data-channel-view="ctrip"]');
    if(!root) return;

    root.querySelectorAll('.ctrip-source-v55,.ctrip-competition-source,.psi-source-v53').forEach(function(node){
      node.remove();
    });
    removeSummarySourceColumn(root);

    let changed=true;
    while(changed){
      changed=false;
      const candidates=Array.from(root.querySelectorAll('section,aside,div,p,h1,h2,h3,h4,h5,h6,b,strong,span,small'));
      for(const node of candidates){
        if(!node.isConnected) continue;
        const label=matchedLabel(node);
        if(!label) continue;
        const target=safeContainer(node,label,root);
        if(target&&target!==root&&!target.matches(boundaries)){
          target.remove();
          changed=true;
          break;
        }
      }
    }
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',setup);
  else setup();
})();
</script>
"""


_PSI_SOURCE_RE = re.compile(
    r"<div class=['\"]psi-source-v53['\"]>\s*"
    r"<div><b>页面数据来源</b>.*?</div>\s*"
    r"<div><b>数据库来源与计分口径</b>.*?</div>\s*"
    r"</div>",
    re.DOTALL | re.IGNORECASE,
)
_CTRIP_SOURCE_RE = re.compile(
    r"<div class=['\"]ctrip-source-v55['\"]>.*?</div>",
    re.DOTALL | re.IGNORECASE,
)
_CTRIP_COMPETITION_SOURCE_RE = re.compile(
    r"<div class=['\"]ctrip-competition-source['\"]>.*?</div>",
    re.DOTALL | re.IGNORECASE,
)


def _strip_hidden_source_details(document: str) -> str:
    """Remove known Ctrip source/scope blocks from visible report HTML only."""

    document = _PSI_SOURCE_RE.sub("", document)
    document = _CTRIP_SOURCE_RE.sub("", document)
    document = _CTRIP_COMPETITION_SOURCE_RE.sub("", document)

    # Mark the monthly time scope directly beside each competitor Top5 title.
    document = document.replace(
        "<h5>携程 Top5</h5>",
        "<h5><span>携程 Top5</span><small class='ctrip-loss-period-tag'>上月</small></h5>",
    )
    document = document.replace(
        "<h5>去哪儿 Top5</h5>",
        "<h5><span>去哪儿 Top5</span><small class='ctrip-loss-period-tag'>上月</small></h5>",
    )

    # The collapsed diagnosis summary is cleaned in the browser by removing the
    # whole source column. These replacements prevent the two previously known
    # strings from appearing before that script runs.
    document = document.replace("ctrip_ota_psi_score、ctrip_ota_psi_metric<br>", "")
    document = document.replace("携程 eBooking / YOYO卡或扫码住<br>", "")
    return document


def build_html(result: dict[str, Any]) -> str:
    """Build the existing dual report and add stable shared interactions in place."""

    # ctrip_report.cards_html resolves funnel_card at runtime. Replacing this
    # global keeps the stable Ctrip report while rendering item 03 with the exact
    # ctrip_ota_flow_conversion_30d score table.
    stable_ctrip_report.funnel_card = flow_card
    upstream.build_ctrip_page = build_ctrip_page
    output = upstream.build_html(result)
    output = _strip_hidden_source_details(output)
    output = output.replace(
        "</head>",
        SIDEBAR_STYLE + FLOW_STYLE + CTRIP_CLEANUP_STYLE + "</head>",
        1,
    )
    output = output.replace(
        "</body>",
        SIDEBAR_SCRIPT
        + PROFILE_INTERACTION_FIX_SCRIPT
        + FLOW_SCRIPT
        + CTRIP_CONTENT_CLEANUP_SCRIPT
        + "</body>",
        1,
    )
    return output


__all__ = ["build_html"]

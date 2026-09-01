from marketing_diagnosis import dual_channel_report_v56 as report


def _channel_html(channel: str, count: int) -> str:
    nav = "".join(
        f"<a href='#rule-{no}'><span>{no:02d}</span>{channel}项目{no:02d}</a>"
        for no in range(1, count + 1)
    )
    cards = "".join(
        f"<article class='diagnosis-card' id='rule-{no}'>{channel}模块{no:02d}</article>"
        for no in range(1, count + 1)
    )
    return f"""<!doctype html><html><head><title>{channel}</title>
<style>.{channel}-only{{display:block}}</style></head><body>
<header class='topbar'><div class='top-actions'><button onclick='window.print()'>导出</button></div></header>
<div class='page'><nav class='side'>{nav}</nav><main>
<section id='overview'>{channel}概览</section>
<section id='summary'><input id='ruleSearch'><select id='statusFilter'></select></section>
{cards}</main></div>
<script>
document.addEventListener('DOMContentLoaded',function(){{
  const search=document.getElementById('ruleSearch');
  document.querySelectorAll('.diagnosis-card').forEach(function(card){{card.hidden=false;}});
}});
</script>
</body></html>"""


MEITUAN_HTML = _channel_html("美团", 23)
CTRIP_HTML = _channel_html("携程", 22)


def _build(monkeypatch) -> str:
    monkeypatch.setattr(report.meituan_report, "build_html", lambda result: MEITUAN_HTML)
    monkeypatch.setattr(report, "build_ctrip_page", lambda result: CTRIP_HTML)
    return report.build_html({"hotel_name": "测试酒店"})


def test_existing_meituan_document_remains_the_single_page_base(monkeypatch):
    output = _build(monkeypatch)

    assert output.count("<!doctype html>") == 1
    assert output.count("<header class='topbar'>") == 1
    assert ".美团-only{display:block}" in output
    assert "美团概览" in output
    assert "美团模块23" in output
    assert "id='rule-23' data-channel-anchor='module-23'" in output

    assert "data-channel-view='meituan'" in output
    assert "data-channel-view='ctrip'" in output
    assert "data-channel-target='meituan'" in output
    assert "data-channel-target='ctrip'" in output

    assert "ctrip_report.html" not in output
    assert "双渠道诊断报告预览.html" not in output


def test_complete_23_item_meituan_and_22_item_ctrip_views_are_present(monkeypatch):
    output = _build(monkeypatch)

    for no in range(1, 24):
        assert f"美团模块{no:02d}" in output
        assert f"id='rule-{no}' data-channel-anchor='module-{no}'" in output

    for no in range(1, 23):
        assert f"携程模块{no:02d}" in output
        assert f"id='ctrip-rule-{no}' data-channel-anchor='module-{no}'" in output

    assert "携程模块23" not in output
    assert "id='ctrip-rule-23'" not in output


def test_channel_hashes_ids_and_filters_do_not_conflict(monkeypatch):
    output = _build(monkeypatch)

    assert "href='#module-3'" in output
    assert "id='rule-3' data-channel-anchor='module-3'" in output
    assert "id='ctrip-rule-3' data-channel-anchor='module-3'" in output

    # The existing Meituan filter keeps its original IDs. Only Ctrip is scoped.
    assert "id='ruleSearch'" in output
    assert "id='statusFilter'" in output
    assert "ctripRuleSearch" in output
    assert "ctripStatusFilter" in output

    # Each filter searches only inside its own .page view.
    assert "(search.closest('.page')||document).querySelectorAll('.diagnosis-card')" in output
    assert "new URLSearchParams(window.location.search).get('channel')" in output

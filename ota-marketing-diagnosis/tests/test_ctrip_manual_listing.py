from __future__ import annotations

from marketing_diagnosis.ctrip_manual_listing import patch_html


def _document() -> str:
    return """<html><head></head><body>
<div data-channel-view='ctrip'><div class='ctrip-overview-score'><strong>23.0</strong></div>
<section id='ctrip-summary'><table><tbody><tr data-status='success'><td>21</td><td><a href='#module-21'>挂牌 / 委托分销</a></td><td>6分</td><td>3分</td><td><span class='status-badge ok'>已形成结果</span></td><td>来源</td></tr></tbody></table></section>
<article class='diagnosis-card' data-status='success' data-title='挂牌 / 委托分销' id='ctrip-rule-21' data-channel-anchor='module-21'><div>旧数据卡片</div></article></div>
</body></html>"""


def test_item_21_becomes_manual_and_ignores_old_database_score() -> None:
    result = {
        "hotel_id": "hotel-a",
        "period_start": "2026-07-01",
        "period_end": "2026-07-30",
        "ctrip_summary": {"total_score": 23.0},
        "ctrip_items": {"21": {"item_score": 3.0}},
    }
    output = patch_html(_document(), result)
    assert "旧数据卡片" not in output
    assert "待人工录入" in output
    assert "const BASE_TOTAL=0.0" in output


def test_original_listing_score_bands_are_unchanged() -> None:
    output = patch_html(_document(), {"ctrip_summary": {"total_score": 0}, "ctrip_items": {}})
    assert "premium:{score:6" in output
    assert "standard:{score:3" in output
    assert "none:{score:0" in output
    assert "满分 6分" in output
    assert "原评分规则（未改变）" not in output
    assert "未挂牌或未参加委托分销 = 0分" not in output


def test_patch_is_idempotent_and_does_not_touch_non_ctrip_reports() -> None:
    result = {"ctrip_summary": {"total_score": 0}, "ctrip_items": {}}
    once = patch_html(_document(), result)
    assert patch_html(once, result) == once
    meituan = "<html><head></head><body><article id='rule-21'>自动接单</article></body></html>"
    assert patch_html(meituan, result) == meituan

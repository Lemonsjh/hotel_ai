from __future__ import annotations

from marketing_diagnosis.channel_score_totals import (
    ctrip_direct_total,
    meituan_direct_total,
    patch_channel_score_totals,
)


def _result() -> dict:
    return {
        "visual_diagnosis": {
            "normalized_score": 69.2,
            "items": [
                {"standard_item_id": 1, "item_score": 10, "participates_in_score": True},
                {"standard_item_id": 2, "item_score": 4.8, "participates_in_score": True},
                {"standard_item_id": 3, "item_score": 2, "participates_in_score": True},
                {"standard_item_id": 5, "item_score": None, "participates_in_score": False},
                {"standard_item_id": 22, "item_score": None, "participates_in_score": True},
            ],
        },
        "ctrip_items": {
            "3": {"standard_item_id": 3, "item_score": 3.5, "participates_in_score": True},
            "5": {"standard_item_id": 5, "item_score": 8, "participates_in_score": False},
            "21": {"standard_item_id": 21, "item_score": 3, "participates_in_score": True},
        },
    }


def test_both_channel_totals_are_direct_item_score_sums() -> None:
    result = _result()
    assert meituan_direct_total(result) == 16.8
    assert ctrip_direct_total(result) == 21.3
    assert ctrip_direct_total(result, exclude_ids={21}) == 18.3


def test_report_headers_and_manual_crown_use_direct_totals() -> None:
    html = """<html><body>
<div class='total-score-v17'><small>总得分</small><strong>69.2</strong><span>满分100分</span></div>
<div class='ctrip-overview-score'><small>携程综合得分</small><strong>18.2</strong><span>满分100分</span></div>
<script>  function updateTotal(score){
    const node=document.querySelector('.total-score-v17 strong');
    if(!node)return;
    const raw=BASE_RAW+(score===null?0:score);
    const connected=BASE_CONNECTED+(score===null?0:CROWN_BASE);
    node.textContent=connected>0?(raw/connected*100).toFixed(1):'待计算';
  }
  function apply(data){}</script></body></html>"""
    output = patch_channel_score_totals(html, _result())
    assert "<strong>16.8</strong>" in output
    assert "<strong>21.3</strong>" in output
    assert "const total=BASE_RAW+(score===null?0:score);" in output
    assert "raw/connected*100" not in output

from marketing_diagnosis.ctrip_promotion_v67 import build_promotion_item
from marketing_diagnosis.ctrip_report import build_html


def _row(**values):
    return {
        "snapshot_time": "2026-07-22 09:00:00",
        "spend_amount": 1000,
        "return_on_ad_spend": 10,
        "exposure_count": 10000,
        "click_count": 300,
        "booking_order_count": 12,
        "booking_order_amount": 10000,
        **values,
    }


def test_ctrip_promotion_score_uses_spend_and_roi_thresholds():
    full = build_promotion_item({"ctrip_promotion_performance_30d": [_row()]})
    middle = build_promotion_item(
        {"ctrip_promotion_performance_30d": [_row(return_on_ad_spend=5)]}
    )
    low_spend = build_promotion_item(
        {"ctrip_promotion_performance_30d": [_row(spend_amount=999, return_on_ad_spend=20)]}
    )

    assert full["item_score"] == 8
    assert middle["item_score"] == 4.8
    assert low_spend["item_score"] == 0
    assert [field["label"] for field in full["fields"]] == [
        "推广投入", "推广曝光", "推广点击", "推广订单", "推广订单金额", "ROI",
    ]


def test_ctrip_promotion_card_only_shows_key_metrics():
    item = build_promotion_item({"ctrip_promotion_performance_30d": [_row()]})
    output = build_html({"hotel_name": "测试酒店", "ctrip_items": {"9": item}})
    card = output.split("id='rule-9'", 1)[1].split("id='rule-10'", 1)[0]

    assert "推广投入" in card and "ROI" in card
    assert "平均曝光排名" not in card and "赠款" not in card

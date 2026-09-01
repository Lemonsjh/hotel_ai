from marketing_diagnosis.ctrip_competition import build_competition_item
from marketing_diagnosis.ctrip_report import competition_analysis_card, funnel_card
from marketing_diagnosis.rules_v5 import (
    _competition_metric_entries,
    _split_competition_payload,
)


def sections():
    return {
        "ota_funnel": [
            {
                "platform": "ctrip",
                "business_date": "2026-07-20",
                "period_type": "近30天",
                "exposure": 5160,
                "peer_exposure": 22347,
                "views": 736,
                "peer_views": 4793,
                "paid_orders": 9,
                "peer_paid_orders": 78,
            }
        ],
        "ctrip_business_metrics_funnel": [],
        "ctrip_competition_metrics_30d": [
            {
                "metric_code": "competition_rank",
                "metric_name": "竞争圈排名",
                "competitor_rank": 6,
            },
            {
                "metric_code": "booking_order_count",
                "hotel_value": 54,
                "competitor_avg": 1457,
                "competitor_rank": 8,
                "competitor_count": 48,
            },
            {
                "metric_code": "booking_sales_amount",
                "hotel_value": 11354.26,
                "competitor_avg": 712560,
                "competitor_rank": 10,
                "competitor_count": 48,
            },
            {
                "metric_code": "occupancy_ratet",
                "hotel_value": 63.2,
                "competitor_avg": 82.1,
                "competitor_rank": 9,
                "competitor_count": 48,
            },
            {
                "metric_code": "ctrip_app_conversion_ratet",
                "hotel_value": 2.4,
                "competitor_avg": 2.68,
                "competitor_rank": 7,
                "competitor_count": 48,
            },
            {
                "metric_code": "inhouse_room_night",
                "hotel_value": 63,
                "competitor_avg": 665.09,
                "competitor_rank": 22,
                "competitor_count": 48,
            },
            {
                "metric_code": "ctrip_app_visitor_count",
                "hotel_value": 916,
                "competitor_avg": 5576.3,
                "competitor_rank": 22,
                "competitor_count": 48,
            },
            {
                "metric_code": "unrelated_metric",
                "metric_name": "不应展示",
                "competitor_avg": 999,
                "competitor_rank": 1,
            },
        ],
        "ctrip_business_metrics_loss": [
            {
                "business_date": "2026-07-20 00:00:00",
                "metric_group": "流失诊断",
                "metric_name": "流失订单量",
                "metric_value": 13,
            },
            {
                "business_date": "2026-07-20 00:00:00",
                "metric_group": "流失诊断",
                "metric_name": "流失订单金额",
                "metric_value": 4567.89,
            },
        ],
        "ctrip_order_loss_monthly": [
            {
                "platform_scope": "ctrip",
                "period_month": "2026-07",
                "ranking_position": index,
                "competitor_hotel_name": f"携程竞对酒店{index}",
            }
            for index in range(1, 7)
        ]
        + [
            {
                "platform_scope": "qunar",
                "period_month": "2026-07",
                "ranking_position": index,
                "competitor_hotel_name": f"去哪儿竞对酒店{index}",
            }
            for index in range(1, 7)
        ],
    }


def split_items():
    source = sections()
    combined = build_competition_item(source, {"item_score": 11.4})
    combined["competition_metrics"] = _competition_metric_entries(source)
    return _split_competition_payload(combined, {"item_score": 11.4})


def test_item_03_keeps_only_funnel_and_score():
    item_three, item_five = split_items()

    assert item_three["standard_item_id"] == 3
    assert item_three["item_score"] == 11.4
    assert len(item_three["funnel_stages"]) == 5
    assert "competition_metrics" not in item_three
    assert "loss_competitors" not in item_three

    output = funnel_card({"ctrip_items": {"3": item_three}})
    assert "我的酒店" in output
    assert "竞争圈平均" in output
    assert "列表页曝光量" in output
    assert "成交订单数" in output
    assert "竞争圈核心指标与排名" not in output
    assert "昨日流失与主要流失竞对" not in output


def test_item_05_uses_exact_six_metrics_without_generic_rank_row():
    _, item_five = split_items()

    assert item_five["standard_item_id"] == 5
    assert item_five["participates_in_score"] is False
    assert [entry["metric_code"] for entry in item_five["competition_metrics"]] == [
        "booking_order_count",
        "booking_sales_amount",
        "occupancy_ratet",
        "ctrip_app_conversion_ratet",
        "inhouse_room_night",
        "ctrip_app_visitor_count",
    ]
    assert [entry["label"] for entry in item_five["competition_metrics"]] == [
        "竞争圈平均预订订单量",
        "竞争圈平均预订销售额",
        "竞争圈平均出租率",
        "竞争圈平均携程APP转化率",
        "竞争圈平均在店间夜",
        "竞争圈平均携程APP访客",
    ]
    assert item_five["competition_metrics"][0]["hotel_value"] == 54
    assert item_five["competition_metrics"][0]["competitor_avg"] == 1457
    assert item_five["competition_metrics"][0]["competitor_rank"] == 8
    assert item_five["loss_summary"]["order_count"] == 13
    assert item_five["loss_summary"]["order_amount"] == 4567.89
    assert len(item_five["loss_competitors"]["ctrip"]) == 5
    assert len(item_five["loss_competitors"]["qunar"]) == 5

    output = competition_analysis_card({"ctrip_items": {"5": item_five}})
    assert "竞争圈核心指标与排名" in output
    assert "昨日流失与主要流失竞对" in output
    assert "data-loss-tab='ctrip'" in output
    assert "data-loss-tab='qunar'" in output
    assert "携程竞对酒店5" in output
    assert "去哪儿竞对酒店5" in output
    assert "竞争圈平均预订订单量（单）" in output
    assert "竞争圈平均预订销售额（元）" in output
    assert "竞争圈平均在店间夜（间夜）" in output
    assert "竞争圈平均携程APP访客（人）" in output
    assert ">竞争圈排名（" not in output
    assert ">竞争圈排名</td>" not in output
    assert "competition_rank" not in output
    assert "不应展示" not in output
    assert "CNY" not in output
    assert "room_night" not in output
    assert "person" not in output
    assert "流量漏斗" not in output


def test_confirmed_metric_code_aliases_remain_compatible():
    source = sections()
    source["ctrip_competition_metrics_30d"] = [
        {
            "metric_code": "occupancy_rate",
            "competitor_avg": 80,
            "competitor_rank": 3,
        },
        {
            "metric_code": "ctrip_app_conversion_rate",
            "competitor_avg": 4.2,
            "competitor_rank": 4,
        },
    ]
    entries = _competition_metric_entries(source)

    occupancy = next(entry for entry in entries if entry["metric_code"] == "occupancy_ratet")
    conversion = next(
        entry
        for entry in entries
        if entry["metric_code"] == "ctrip_app_conversion_ratet"
    )
    assert occupancy["competitor_avg"] == 80
    assert conversion["competitor_avg"] == 4.2

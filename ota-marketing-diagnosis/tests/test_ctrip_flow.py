from marketing_diagnosis.ctrip_flow import (
    build_flow_item,
    rank_score_level,
    ratio_score_level,
)
from marketing_diagnosis.ctrip_flow_report import card
from marketing_diagnosis.ctrip_flow_rules import process


def flow_row(platform="ctrip"):
    return {
        "platform": platform,
        "snapshot_time": "2026-07-21 10:00:00",
        "period_start_date": "2026-06-22",
        "period_end_date": "2026-07-21",
        "list_exposure": 245000,
        "peer_list_exposure": 980000,
        "app_visitors": 6200,
        "peer_app_visitors": 40000,
        "detail_exposure": 8000,
        "peer_detail_exposure": 42000,
        "exposure_to_detail_rate_pct": 13.8,
        "peer_exposure_to_detail_rate_pct": 21,
        "order_filling_count": 3000,
        "peer_order_filling_count": 11500,
        "detail_to_order_rate_pct": 14,
        "peer_detail_to_order_rate_pct": 20,
        "order_submit_count": 900,
        "peer_order_submit_count": 3600,
        "order_to_submit_rate_pct": 50,
        "peer_order_to_submit_rate_pct": 50,
        "list_exposure_peer_rank": 22,
        "detail_exposure_peer_rank": 18,
        "detail_to_order_rate_peer_rank": 20,
        "competition_circle_hotel_count": 48,
    }


def test_ratio_and_rank_thresholds():
    assert ratio_score_level(2) == 1
    assert ratio_score_level(1.5) == 0.8
    assert ratio_score_level(1) == 0.6
    assert ratio_score_level(0.99) == 0

    assert rank_score_level(0.8) == 1
    assert rank_score_level(0.6) == 0.8
    assert rank_score_level(0.4) == 0.6
    assert rank_score_level(0.39) == 0


def test_item_03_uses_exact_wide_fields_and_scores_each_metric_then_sums():
    item = build_flow_item(
        {"ctrip_business_metrics_funnel": [flow_row(), flow_row("qunar")]}
    )
    ctrip = item["platforms"]["ctrip"]

    assert item["source"] == "ctrip_ota_flow_conversion_30d"
    assert item["full_score"] == 15
    assert ctrip["participates_in_score"] is True
    assert item["platforms"]["qunar"]["participates_in_score"] is False
    assert [row["name"] for row in ctrip["subitems"]] == [
        "列表曝光 / 访客规模",
        "曝光到详情转化",
        "详情到订单页转化",
        "订单页到提交转化",
        "竞争圈排名表现",
    ]
    assert ctrip["subitems"][0]["subitem_score"] == 0
    assert ctrip["subitems"][1]["subitem_score"] == 0
    assert ctrip["subitems"][2]["subitem_score"] == 0
    assert ctrip["subitems"][3]["subitem_score"] == 0.9
    assert ctrip["subitems"][4]["subitem_score"] == 2.2
    assert item["item_score"] == 3.1


def test_flow_table_splits_ranking_into_a_separate_header():
    item = build_flow_item({"ctrip_business_metrics_funnel": [flow_row()]})
    output = card({"ctrip_items": {"3": item}})

    assert "关键指标评分明细表" in output
    assert "ratio对比值" in output
    assert (
        "<thead><tr><th>序号</th><th>评分子项</th><th>子项指标</th>"
        "<th>竞争圈排名</th><th>竞争圈酒店数</th><th>排名分位</th>"
        "<th>子项得分</th></tr></thead>"
    ) in output
    assert "class='flow-rank-index' rowspan='3'>5</td>" in output
    assert "class='flow-rank-subitem' rowspan='3'>竞争圈排名表现</td>" in output
    assert "ratio得分" not in output
    assert "ratio / 排名分位" not in output
    assert "计分说明" not in output
    assert "比例类先计算" not in output
    assert "订单页到提交转化" in output
    assert "成交订单" not in output
    assert "data-flow-tab='ctrip'" in output
    assert "data-flow-tab='qunar'" in output


def test_final_rule_wrapper_replaces_old_item_03_and_refreshes_total():
    data = {
        "sections": {
            "ctrip_business_metrics_funnel": [flow_row()],
            "ctrip_competition_metrics_30d": [],
            "ctrip_business_metrics_loss": [],
            "ctrip_order_loss_monthly": [],
        }
    }
    result = process(data)
    item = result["ctrip_items"]["3"]
    rank_subitem = item["platforms"]["ctrip"]["subitems"][4]

    assert item["source"] == "ctrip_ota_flow_conversion_30d"
    assert item["item_score"] == 3.1
    assert rank_subitem["subitem_score"] == 2.2
    assert all(
        metric["competition_circle_hotel_count"] == 48
        for metric in rank_subitem["metrics"]
    )
    assert "platforms" in item

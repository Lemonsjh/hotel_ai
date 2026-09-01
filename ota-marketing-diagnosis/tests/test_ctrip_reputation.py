from marketing_diagnosis.ctrip_reputation_v64 import build_reputation_item
from marketing_diagnosis.ctrip_report import build_html


def _overview(channel, score, total, **values):
    return {
        "channel_source": channel,
        "review_score": score,
        "total_review_count": total,
        "unreplied_review_count": values.pop("unreplied", 0),
        "negative_review_count": values.pop("negative", 0),
        **values,
    }


def test_ctrip_reputation_scores_platforms_and_reply_rate():
    item = build_reputation_item(
        {
            "ctrip_review_overview": [
                _overview("携程", 4.46, 925, environment_score=4.42, facility_score=4.40, service_score=4.55, hygiene_score=4.48),
                _overview("去哪儿", 4.80, 1077, environment_score=None, facility_score=None, service_score=4.90, hygiene_score=4.80),
                _overview("同程旅行", 4.60, 460, unreplied=10),
                _overview("智行", 4.40, 159),
            ],
            "ctrip_review_yesterday": [
                {"platform_scope": "ctrip", "yesterday_new_review_count": 2},
            ],
        }
    )

    assert item["item_score"] == 3.8
    assert [entry["platform_name"] for entry in item["platforms"]] == ["携程", "去哪儿", "同程旅行", "智行"]
    assert item["platforms"][0]["yesterday_new_review_count"] == 2
    assert item["platforms"][0]["reply_rate"] == 1
    assert item["platforms"][2]["score"] == 0.8
    assert item["platforms"][1]["environment_score"] is None


def test_ctrip_reputation_page_uses_a_cross_platform_detail_table():
    item = build_reputation_item(
        {
            "ctrip_review_overview": [
                _overview("携程", 4.8, 100),
                _overview("去哪儿", 4.8, 100, environment_score=None, facility_score=None),
                _overview("同程旅行", 4.6, 100),
                _overview("智行", 4.4, 100),
            ],
            "ctrip_review_yesterday": [],
        }
    )
    output = build_html({"hotel_name": "测试酒店", "ctrip_items": {"12": item}})
    card = output.split("id='rule-12'", 1)[1].split("id='rule-13'", 1)[0]

    assert "rep-table" in card
    assert card.count("<tr>") >= 5
    assert "回复率" in card and "未回复" in card
    assert "环境" in card and "设施" in card and "服务" in card and "卫生" in card
    assert "<svg" not in card and "雷达图" not in card
    assert "—" in card
    assert "ENABLED" not in card and "NOT_JOINED" not in card

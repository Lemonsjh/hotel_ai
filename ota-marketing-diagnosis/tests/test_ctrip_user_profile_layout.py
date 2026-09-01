from marketing_diagnosis.ctrip_report import build_html
from marketing_diagnosis.ctrip_user_profile_report import profile_table
from marketing_diagnosis.ctrip_user_profile_v58 import build_user_profile_item


def profile_rows():
    return [
        {"dimension_code": "gender", "bucket_label": "男", "rate_pct": 62.03},
        {"dimension_code": "gender", "bucket_label": "女", "rate_pct": 37.97},
        {"dimension_code": "age_group", "bucket_label": "25-34", "rate_pct": 42.68},
        {"dimension_code": "age_group", "bucket_label": "25岁以下", "rate_pct": 35.67},
        {"dimension_code": "age_group", "bucket_label": ">=55", "rate_pct": 2.55},
        {"dimension_code": "city_origin", "bucket_label": "异地", "rate_pct": 84.93},
        {"dimension_code": "city_origin", "bucket_label": "本地", "rate_pct": 15.07},
        {"dimension_code": "travel_type", "bucket_label": "休闲型", "rate_pct": 68.99},
        {"dimension_code": "travel_type", "bucket_label": "商务型", "rate_pct": 31.01},
        {"dimension_code": "travel_time", "bucket_label": "工作日", "rate_pct": 65.08},
        {"dimension_code": "travel_time", "bucket_label": "节假日", "rate_pct": 34.92},
        {"dimension_code": "consumption_price", "bucket_label": "<=200", "rate_pct": 76.96},
        {"dimension_code": "consumption_price", "bucket_label": "201-500", "rate_pct": 20.53},
        {"dimension_code": "consumption_price", "bucket_label": "501-1000", "rate_pct": 2.51},
        {"dimension_code": "consumption_price", "bucket_label": "1001-2000", "rate_pct": 0},
        {"dimension_code": "booking_advance_days", "bucket_label": "当天预订", "rate_pct": 70.84},
        {"dimension_code": "booking_advance_days", "bucket_label": "提前1天", "rate_pct": 9.98},
        {"dimension_code": "booking_advance_days", "bucket_label": "avg_advance_booking_days", "metric_value": 1.6, "metric_unit": "days"},
        {"dimension_code": "stay_days", "bucket_label": "1天", "rate_pct": 84.87},
        {"dimension_code": "stay_days", "bucket_label": "2天", "rate_pct": 8.25},
        {"dimension_code": "stay_days", "bucket_label": "6天以上", "rate_pct": 0.14},
        {"dimension_code": "stay_days", "bucket_label": "平均入住晚数", "metric_value": 1.2, "metric_unit": "nights"},
        {"dimension_code": "city_origin_top5", "bucket_label": "贵阳", "rate_pct": 15.07, "rank_position": 1},
        {"dimension_code": "city_origin_top5", "bucket_label": "毕节", "rate_pct": 5.14, "rank_position": 2},
        {"dimension_code": "order_peak_time", "bucket_label": "17:00", "rate_pct": 9.70},
        {"dimension_code": "order_hourly_distribution", "bucket_label": "16:00", "rate_pct": 7.20},
        {"dimension_code": "order_hourly_distribution", "bucket_label": "17:00", "rate_pct": 9.70},
        {"dimension_code": "order_hourly_distribution", "bucket_label": "18:00", "rate_pct": 5.10},
    ]


def test_zero_percent_is_omitted_and_tiny_values_are_preserved():
    item = build_user_profile_item(profile_rows())
    prices = item["charts"]["consumption_price"]["entries"]
    stays = item["charts"]["stay_days"]["entries"]

    assert [entry["label"] for entry in prices] == ["200元及以下", "201–500元", "501–1000元"]
    assert all(entry["rate_pct"] > 0 for entry in prices)
    assert next(entry for entry in stays if entry["label"] == "6晚以上")["rate_pct"] == 0.14
    assert item["average_advance_days"] == 1.6
    assert item["average_stay_nights"] == 1.2
    assert item["peak_time"]["label"] == "17:00"
    assert len(item["hourly_distribution"]) == 3


def test_profile_table_uses_tabs_summaries_and_expandable_details():
    item = build_user_profile_item(profile_rows())
    output = profile_table(
        item["charts"],
        item["average_advance_days"],
        item["average_stay_nights"],
    )

    assert "data-ctrip-profile" in output
    assert "data-profile-tab='basic'" in output
    assert "data-profile-tab='preference'" in output
    assert "data-profile-tab='booking'" in output
    assert "基础画像" in output
    assert "消费偏好" in output
    assert "预订行为" in output
    assert "主要细分项" in output
    assert "次要：女 37.97%" in output
    assert "次要：25岁以下 35.67%" in output
    assert "展开详情" in output
    assert "data-profile-detail='age_group' hidden" in output
    assert "501–1000元" in output
    assert "1001–2000元" not in output
    assert "0.14%" in output
    assert "平均提前 1.6 天" in output
    assert "平均入住 1.2 晚" in output
    assert "rowspan=" not in output


def test_report_keeps_city_peak_and_profile_interaction():
    item = build_user_profile_item(profile_rows())
    output = build_html(
        {
            "hotel_name": "测试酒店",
            "period_start": "2026-06-22",
            "period_end": "2026-07-21",
            "ctrip_items": {"4": item},
        }
    )

    assert "CTRIP_USER_PROFILE_STABLE" in output
    assert "CTRIP_USER_PROFILE_INTERACTION" in output
    assert "activate('basic')" in output
    assert "button.textContent = expanded ? '展开详情' : '收起详情'" in output
    assert ".ctrip-profile-panel[hidden]{display:block!important}" in output
    assert ".ctrip-profile-detail-row{display:none!important}" in output
    assert "overflow-x:auto" in output
    assert "主要客源城市（Top5）" in output
    assert "主要预订时段" in output
    assert "17:00" in output
    assert "order_hourly_distribution" not in output

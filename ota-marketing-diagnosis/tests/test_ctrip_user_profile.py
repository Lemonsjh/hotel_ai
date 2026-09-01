from marketing_diagnosis.ctrip_user_profile_v58 import (
    DIMENSIONS,
    build_user_profile_item,
)
from marketing_diagnosis.data_v4 import normalize_dataset
from marketing_diagnosis.db_loader_v16 import latest_distribution_rows
from marketing_diagnosis.ctrip_report_v54 import build_html


def profile_rows():
    return [
        {"dimension_code": "gender", "bucket_label": "男性", "bucket_value": 0.56},
        {"dimension_code": "gender", "bucket_label": "女性", "bucket_value": 0.44},
        {"dimension_code": "age_group", "bucket_label": "25-34岁", "bucket_ratio": 0.42},
        {"dimension_code": "city_origin", "bucket_label": "异地", "percentage": 68},
        {"dimension_code": "travel_type", "bucket_label": "商务出行", "ratio": 0.35},
        {"dimension_code": "travel_time", "bucket_label": "周末", "ratio": 0.61},
        {"dimension_code": "consumption_price", "bucket_label": "300-399元", "ratio": 0.47},
        {"dimension_code": "booking_advance_days", "bucket_label": "提前1-3天", "ratio": 0.52},
        {"dimension_code": "stay_days", "bucket_label": "1晚", "bucket_value": 0.7},
        {"dimension_code": "stay_days", "bucket_label": "平均入住晚数", "bucket_value": 1.8},
        {"dimension_code": "orider_peak_time", "bucket_label": "20:00-22:00", "ratio": 0.31},
        {"dimension_code": "city_origin_top5", "bucket_label": "成都", "user_count": 120, "rank": 1},
        {"dimension_code": "city_origin_top5", "bucket_label": "重庆", "user_count": 98, "rank": 2},
    ]


def test_user_profile_builds_all_ten_display_dimensions():
    item = build_user_profile_item(profile_rows())
    values = {field["label"]: field["value"] for field in item["fields"]}

    assert len(DIMENSIONS) == 10
    assert len(item["fields"]) == 10
    assert item["participates_in_score"] is False
    assert item["full_score"] == 0
    assert item["item_score"] == 0
    assert item["data_status"] == "success"
    assert item["source"] == "ctrip_ota_userprofile_distribution"

    assert "男性" in values["性别"] and "女性" in values["性别"]
    assert "25-34岁" in values["年龄段"]
    assert "异地" in values["本地 / 异地"]
    assert "商务出行" in values["出行目的"]
    assert "周末" in values["工作日 / 周末偏好"]
    assert "300-399元" in values["消费价格带"]
    assert "提前1-3天" in values["提前预订天数"]
    assert "平均入住晚数" in values["平均入住晚数"]
    assert "1晚" not in values["平均入住晚数"]
    assert "20:00-22:00" in values["主要预订时段"]
    assert "成都" in values["主要客源城市"] and "重庆" in values["主要客源城市"]


def test_latest_rows_are_selected_per_dimension_and_bucket():
    rows = [
        {
            "id": 1,
            "dimension_code": "gender",
            "bucket_label": "男性",
            "bucket_value": 0.50,
            "snapshot_time": "2026-07-20 10:00:00",
        },
        {
            "id": 2,
            "dimension_code": "gender",
            "bucket_label": "男性",
            "bucket_value": 0.56,
            "snapshot_time": "2026-07-21 10:00:00",
        },
        {
            "id": 3,
            "dimension_code": "age_group",
            "bucket_label": "25-34岁",
            "bucket_value": 0.42,
            "snapshot_time": "2026-07-20 09:00:00",
        },
    ]
    selected = latest_distribution_rows(rows)

    assert len(selected) == 2
    male = next(row for row in selected if row["dimension_code"] == "gender")
    assert male["bucket_value"] == 0.56
    assert any(row["dimension_code"] == "age_group" for row in selected)


def test_normalization_preserves_profile_rows_and_report_renders_every_field():
    raw = {
        "ctrip_userprofile_distribution": profile_rows(),
    }
    normalized = normalize_dataset(raw)
    assert len(normalized["sections"]["ctrip_userprofile_distribution"]) == len(profile_rows())

    item = build_user_profile_item(
        normalized["sections"]["ctrip_userprofile_distribution"]
    )
    output = build_html(
        {
            "hotel_name": "测试酒店",
            "ctrip_items": {"4": item},
        }
    )

    for label in (
        "性别",
        "年龄段",
        "本地 / 异地",
        "出行目的",
        "工作日 / 周末偏好",
        "消费价格带",
        "提前预订天数",
        "平均入住晚数",
        "主要预订时段",
        "主要客源城市",
    ):
        assert label in output

    assert "ctrip_ota_userprofile_distribution" in output
    assert "男性" in output
    assert "成都" in output
    assert "仅展示" in output

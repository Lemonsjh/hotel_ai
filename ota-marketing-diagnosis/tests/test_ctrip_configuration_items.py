from marketing_diagnosis.ctrip_configuration_v63 import build_configuration_items
from marketing_diagnosis.rules_v5 import process


def _row(code, **values):
    return {"activity_code": code, "enabled": 1, "status": "ENABLED", **values}


def test_configuration_scores_follow_ctrip_rules():
    sections = {
        "ctrip_joined_rights": [
            {"right_name": name}
            for name in ("免费取消", "提前入住", "延迟退房", "欢迎水果", "早餐")
        ],
        "ctrip_promotion_status": [
            _row("information_completeness", metric_value=100),
            _row("points_alliance", orders_30d=2, platform_scope="携程,Trip.com,去哪儿"),
            _row("preferred_club", status_detail="PSI restricted"),
            _row("business_travel_price", room_type_count=0),
            _row("hourly_room", orders_30d=3, room_type_count=2),
            _row("travel_photo", status="UPLOADED", status_detail="claimed"),
            _row("homepage_video", status="UPLOADED"),
            _row("listing_pass", status_detail="GOLD"),
        ],
    }

    items = build_configuration_items(sections)

    assert items["8"]["item_score"] == 4
    assert items["8"]["fields"] == [
        {"label": "信息完整度", "value": "100%", "note": ""},
        {"label": "完整度结果", "value": "已达标", "note": ""},
    ]
    assert items["13"]["item_score"] == 4
    assert {field["label"] for field in items["13"]["fields"]} == {"已报名权益", "权益清单"}
    assert items["13"]["fields"][0]["value"] == "5项"
    assert items["13"]["fields"][1]["value"] == "免费取消、提前入住、延迟退房、欢迎水果、早餐"
    assert items["13"]["rights_list"] == ["免费取消", "提前入住", "延迟退房", "欢迎水果", "早餐"]
    assert items["13"]["fields_complete"] is True
    assert all("right_name" not in str(field.get("note")) for field in items["13"]["fields"])
    assert items["14"]["item_score"] == 3
    assert items["14"]["fields"][-1]["value"] == "携程,Trip.com,去哪儿"
    assert items["15"]["item_score"] == 1.8
    assert {field["label"] for field in items["15"]["fields"]} == {"参加状态", "标签状态"}
    assert items["16"]["item_score"] == 1
    assert {field["label"] for field in items["16"]["fields"]} == {"开通状态", "参与房型", "近30天订单", "成交金额"}
    assert items["17"]["data_status"] == "pending_rule"
    assert items["18"]["item_score"] == 2
    assert items["19"]["item_score"] == 2
    assert items["20"]["item_score"] == 1
    assert items["21"]["item_score"] == 6
    assert all(
        field["value"] not in {"ENABLED", "UPLOADED", "GOLD"}
        for item in items.values()
        for field in item.get("fields", [])
    )


def test_unjoined_and_missing_rows_are_not_scored_as_connected():
    items = build_configuration_items(
        {
            "ctrip_promotion_status": [
                _row("points_alliance", enabled=0, status="NOT_JOINED"),
                _row("homepage_video", enabled=0, status="NOT_UPLOADED"),
            ]
        }
    )

    assert items["13"]["data_status"] == "missing"
    assert items["14"]["item_score"] == 0
    assert items["20"]["item_score"] == 0
    assert items["15"]["data_status"] == "missing"


def test_unjoined_business_price_hides_extra_fields_and_zeroes_rooms():
    items = build_configuration_items(
        {
            "ctrip_promotion_status": [
                _row("business_travel_price", enabled=0, status="NOT_JOINED", room_type_count=8, orders_30d=4),
                _row("travel_photo", enabled=0, status="NOT_UPLOADED", metric_value=12),
            ]
        }
    )

    assert items["16"]["fields"] == [
        {"label": "开通状态", "value": "未开通", "note": ""},
        {"label": "参与房型", "value": 0, "note": ""},
    ]
    assert items["19"]["fields"][-1]["value"] == 0


def test_hourly_orders_use_detail_count_when_available():
    items = build_configuration_items(
        {
            "ctrip_promotion_status": [_row("hourly_room", orders_30d=9, room_type_count=2)],
            "ctrip_hourly_orders": [{"orders_30d": 0}],
        }
    )

    assert items["18"]["item_score"] == 1
    assert items["18"]["fields"][-1]["value"] == 0


def test_rules_attach_ctrip_configuration_items_to_report_result():
    result = process(
        {
            "sections": {
                "ctrip_joined_rights": [{"right_name": "免费取消"}] * 3,
                "ctrip_promotion_status": [_row("points_alliance", orders_30d=0)],
            }
        }
    )

    assert result["ctrip_items"]["13"]["item_score"] == 2.4
    assert result["ctrip_items"]["14"]["item_score"] == 1.8
    assert result["ctrip_items"]["17"]["participates_in_score"] is False

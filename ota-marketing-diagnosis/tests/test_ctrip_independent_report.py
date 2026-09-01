from marketing_diagnosis.ctrip_report_v54 import build_html


def result_fixture():
    return {
        "hotel_name": "测试酒店",
        "period_start": "2026-07-01",
        "period_end": "2026-07-30",
        "visual_diagnosis": {
            "items": [
                {
                    "standard_item_id": 1,
                    "item_name": "月度经营趋势 YOY",
                    "participates_in_score": True,
                    "base_score": 10,
                    "item_score": 9,
                    "data_status": "success",
                    "trend_periods": [
                        {
                            "current_range": "2026-07-01—2026-07-30",
                            "previous_range": "2025-07-01—2025-07-30",
                            "metrics": [
                                {"key": "revenue", "current": 123456, "previous": 100000, "yoy": 0.23456},
                                {"key": "adr", "current": 288, "previous": 260, "yoy": 0.10769},
                                {"key": "occupancy", "current": 0.72, "previous": 0.68, "yoy": 0.05882},
                                {"key": "revpar", "current": 207.36, "previous": 176.8, "yoy": 0.17285},
                            ],
                        }
                    ],
                },
                {
                    "standard_item_id": 2,
                    "item_name": "房型 RevPAR 与低效房型",
                    "participates_in_score": True,
                    "base_score": 8,
                    "item_score": 6,
                    "data_status": "success",
                    "fields": [
                        {"label": "房型数", "value": 2},
                        {"label": "房间总数", "value": 20},
                        {"label": "低效房型数", "value": 1},
                        {"label": "低效房型占比", "value": 0.5},
                    ],
                    "records": [
                        {
                            "room_type_name": "测试大床房",
                            "room_count": 10,
                            "room_nights": 120,
                            "occupancy_points": 75,
                            "room_revenue": 30000,
                            "average_room_price": 250,
                            "revpar": 187.5,
                            "is_low": False,
                        },
                        {
                            "room_type_name": "测试双床房",
                            "room_count": 10,
                            "room_nights": 60,
                            "occupancy_points": 45,
                            "room_revenue": 12000,
                            "average_room_price": 200,
                            "revpar": 90,
                            "is_low": True,
                        },
                    ],
                },
            ]
        },
        "ctrip_summary": {"total_score": 72.5, "connected_items": 4},
        "ctrip_items": {
            "1": {"item_score": 7, "full_score": 12},
            "2": {"item_score": 5, "full_score": 9},
            "3": {"fields": {"列表曝光": 1200}, "item_score": 8},
            "6": {"item_score": 6.5},
        },
        "ctrip_psi": {
            "base_score": 4.15,
            "yesterday_change": 0.01,
            "weak_item_count": 0,
            "metrics": {"A": {"score": 4.2}},
        },
    }


def test_ctrip_page_is_directly_generated_and_independent():
    output = build_html(result_fixture())

    assert "CTRIP_CODE_GENERATED_V55" in output
    assert "携程诊断目录" in output
    assert "平台流量漏斗分析" in output
    assert "YOYO 卡 / 扫码住" in output
    assert "携程渠道经营与服务质量诊断" in output

    # 01/02 are newly rendered from the same PMS result, not copied from a Meituan page.
    assert "123,456.00" in output
    assert "测试大床房" in output
    assert "测试双床房" in output
    assert "7分</strong><span>满分 12分" in output
    assert "5分</strong><span>满分 9分" in output

    # Ctrip summary and PSI scores remain independent.
    assert "携程综合得分" in output
    assert "72.5" in output
    assert "PSI 服务质量分" in output
    assert "基础分" in output
    assert "6.5分</strong><span>满分 8分" in output

    # Header/layout uses the same production class system as Meituan.
    assert "<header class='topbar'>" in output
    assert "<div class='page'>" in output
    assert "class='diagnosis-card performance-card-v54'" in output
    assert "class='diagnosis-card room-type-card-v30'" in output


def test_missing_ctrip_data_never_invents_or_reuses_meituan_values():
    output = build_html({"hotel_name": "测试酒店"})

    assert "待接入" in output
    assert "¥328,650" not in output
    assert "73.9" not in output
    assert "美团曝光内容" not in output
    assert "美团总分" not in output


def test_configuration_cards_only_render_business_facing_fields():
    output = build_html(
        {
            "hotel_name": "测试酒店",
            "ctrip_items": {
                "13": {
                    "item_score": 4,
                    "data_status": "success",
                    "fields_complete": True,
                    "fields": [
                        {"label": "已报名权益", "value": "5项"},
                        {"label": "权益清单", "value": "免费取消、早餐"},
                    ],
                    "rights_list": ["免费取消", "早餐"],
                },
                "15": {
                    "item_score": 3,
                    "data_status": "success",
                    "fields_complete": True,
                    "fields": [
                        {"label": "参加状态", "value": "已参加"},
                        {"label": "标签状态", "value": "正常展示"},
                    ],
                },
                "16": {
                    "item_score": 0,
                    "data_status": "success",
                    "fields_complete": True,
                    "fields": [
                        {"label": "开通状态", "value": "未开通"},
                        {"label": "参与房型", "value": 0},
                    ],
                },
                "19": {
                    "item_score": 0,
                    "data_status": "success",
                    "fields_complete": True,
                    "fields": [
                        {"label": "旅拍上传", "value": "未上传"},
                        {"label": "认领状态", "value": "未上传"},
                        {"label": "旅拍数量", "value": 0},
                    ],
                },
            },
        }
    )

    rights_card = output.split("id='rule-13'", 1)[1].split("id='rule-14'", 1)[0]
    preferred_card = output.split("id='rule-15'", 1)[1].split("id='rule-16'", 1)[0]
    business_card = output.split("id='rule-16'", 1)[1].split("id='rule-17'", 1)[0]
    photo_card = output.split("id='rule-19'", 1)[1].split("id='rule-20'", 1)[0]

    # 权益中心可能由基础渲染器输出 v63，也可能由生产补丁升级为 v66。
    # 测试业务结构，不绑定展示组件的内部版本号。
    assert "ctrip-rights-table-" in rights_card
    if "ctrip-rights-table-v66" in rights_card:
        assert "ctrip-rights-summary-v66" in rights_card
    else:
        assert rights_card.count("class='ctrip-metric-v55'") == 1
    assert "免费取消" in rights_card and "早餐" in rights_card
    assert "参与房型" not in preferred_card and "近30天订单" not in preferred_card
    assert "参与房型" in business_card and ">0</strong>" in business_card
    assert "近30天订单" not in business_card and "成交金额" not in business_card
    assert "旅拍数量" in photo_card and ">0</strong>" in photo_card
    assert "ENABLED" not in output and "NOT_JOINED" not in output and "NOT_UPLOADED" not in output

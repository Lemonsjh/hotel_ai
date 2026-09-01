from __future__ import annotations

from runtime.s09_feishu_presentation_patch import render_s09_operator_report


def test_operator_report_is_clear_and_hides_internal_statuses() -> None:
    report = {
        "status": "ok",
        "as_of_datetime": "2026-08-17T15:53:00+08:00",
        "platforms": {
            "meituan": {
                "algorithm_platform": "meituan",
                "daily": {
                    "business_date": "2026-08-17",
                    "first_stage_quality": "stable",
                    "second_stage_quality": "stable",
                    "stages": {
                        "exposure_uv": 860,
                        "browse_uv": 129,
                        "pay_orders": 6,
                        "exposure_to_browse_ratio": 0.15,
                        "browse_to_pay_ratio": 6 / 129,
                    },
                },
                "rolling_30d": {
                    "period_start_date": "2026-07-19",
                    "period_end_date": "2026-08-17",
                    "stages": {
                        "exposure_to_browse_ratio": 0.08,
                        "browse_to_pay_ratio": 0.056,
                        "peer_exposure_to_browse_ratio": 0.104,
                        "peer_browse_to_pay_ratio": 0.071,
                    },
                },
                "diagnosis": {
                    "second_stage_status": "weak_signal",
                    "second_conversion_peer_index": 0.66,
                    "conclusion": "主要短板信号：浏览→支付",
                    "suggestions": ["建议检查房型可售、价格权益和下单阻力。"],
                    "historical_baseline": {
                        "sample_count": 4,
                        "maturity": "weak",
                        "second_p25": 0.0492,
                    },
                },
            },
            "ctrip": {
                "algorithm_platform": "ctrip",
                "daily": {
                    "business_date": "2026-07-27",
                    "stages": {
                        "list_exposure_count": None,
                        "detail_visitor_count": None,
                        "submit_orders": None,
                    },
                },
            },
        },
    }

    text = render_s09_operator_report(report)

    assert "当日漏斗：曝光 860 人 → 浏览 129 人 → 支付 6 单" in text
    assert "浏览→支付观察：当日 4.7%，低于历史低位 4.9%" in text
    assert "历史可比样本 4 天，样本较少，仅作观察" in text
    assert "当日暂无可用流量与转化数据；最近业务日为 2026-07-27" in text
    assert "缺少关键指标：列表曝光、详情访客、提交订单。" in text
    assert "stable" not in text
    assert "weak_signal" not in text
    assert "missing_metric" not in text
    assert "same_weekday_holiday_registry_unavailable" not in text


def test_stale_platform_does_not_render_empty_funnel() -> None:
    text = render_s09_operator_report({
        "status": "ok",
        "as_of_datetime": "2026-08-17T10:00:00+08:00",
        "platforms": {
            "ctrip": {
                "algorithm_platform": "ctrip",
                "daily": {"business_date": "2026-08-16", "stages": {}},
            }
        },
    })

    assert "非当前业务日，本轮不作诊断" in text
    assert "当日漏斗：" not in text

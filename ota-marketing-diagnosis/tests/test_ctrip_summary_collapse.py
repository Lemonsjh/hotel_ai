from marketing_diagnosis.ctrip_report import build_html, summary_html


def fixture():
    return {
        "hotel_name": "测试酒店",
        "period_start": "2026-06-22",
        "period_end": "2026-07-21",
        "ctrip_summary": {"total_score": 13.8},
        "ctrip_items": {
            "3": {
                "standard_item_id": 3,
                "item_name": "平台流量漏斗分析",
                "participates_in_score": True,
                "full_score": 15,
                "item_score": 2.4,
                "data_status": "success",
                "funnel_stages": [],
            }
        },
    }


def test_summary_is_collapsed_by_default_and_retains_controls():
    output = summary_html(fixture())

    assert "data-ctrip-summary" in output
    assert "class='ctrip-summary-section is-collapsed'" in output
    assert "data-summary-content hidden" in output
    assert "aria-expanded='false'" in output
    assert "展开总览" in output
    assert "id='ruleSearch'" in output
    assert "id='statusFilter'" in output
    assert "携程诊断结果总览" in output
    assert "平台流量漏斗分析" in output


def test_final_report_uses_stable_collapsible_summary_script():
    output = build_html(fixture())

    assert "CTRIP_SUMMARY_TOGGLE_SCRIPT" in output
    assert "button.textContent = expanded ? '收起总览' : '展开总览'" in output
    assert "{summary_html(result)}" not in output

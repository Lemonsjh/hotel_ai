from marketing_diagnosis.ctrip_psi import METRIC_SPECS, build_psi_item, score_psi
from marketing_diagnosis.ctrip_psi_v53 import card
from marketing_diagnosis.ctrip_report_v54 import patch_psi_score
from marketing_diagnosis.rules_v5 import process


def psi_sections(total_score=5.62):
    return {
        "ctrip_psi_score": [
            {
                "psi_total_score": total_score,
                "psi_basic_score": 4.8,
                "psi_basic_score_max": 5,
                "psi_reward_score": 1.1,
                "psi_reward_score_max": 2,
                "psi_deduction_score": 0.28,
                "service_deduction_score": 0.1,
                "integrity_deduction_score": 0.08,
                "financial_deduction_score": 0.1,
                "psi_rank": 8,
                "psi_competition_circle_count": 48,
                "psi_history": [
                    {"business_date": "2026-07-19", "psi_total_score": 5.51},
                    {"business_date": "2026-07-20", "psi_total_score": total_score},
                ],
            }
        ],
        "ctrip_psi_metric": [
            {
                "metric_code": code,
                "metric_name": label,
                "metric_value": index * 10 + 1,
                "metric_unit": raw_unit,
                "weight_pct": 10,
                "psi_score": 4.5,
                "competition_rank": "竞争圈第8名",
                "score_gap": 0.2,
                "score_gap_unit": "index",
                "period_start_date": "2026-06-21",
                "period_end_date": "2026-07-20",
                "business_date": "2026-07-20",
            }
            for index, (code, _, label, unit) in enumerate(METRIC_SPECS)
            for raw_unit in [
                "room_night" if unit == "间夜" else "CNY" if unit == "元" else "%" if unit == "%" else "index"
            ]
        ],
    }


def test_psi_score_thresholds():
    assert score_psi(5.5) == 8
    assert score_psi(5.0) == 6.4
    assert score_psi(4.5) == 4.8
    assert score_psi(4.49) == 0
    assert score_psi(None) is None


def test_psi_item_uses_total_score_once_and_keeps_nine_diagnostic_metrics():
    item = build_psi_item(psi_sections())

    assert item["item_score"] == 8
    assert item["full_score"] == 8
    assert len(item["metrics"]) == 9
    assert item["metrics"][0]["metric_code"] == "historical_room_nights"
    assert item["metrics"][0]["unit"] == "间夜"
    assert item["metrics"][1]["unit"] == "元"
    assert item["service_deduction_score"] == 0.1
    assert "仅用于诊断解释" in item["scoring_note"]


def test_psi_card_matches_hos_style_and_displays_real_fields():
    item = build_psi_item(psi_sections())
    result = {"ctrip_items": {"6": item}, "ctrip_psi": item}
    output = patch_psi_score(card(result, "rule-6"), result)

    assert "PSI 服务质量总分" in output
    assert "基础分" in output
    assert "奖励分" in output
    assert "总扣分" in output
    assert "历史间夜量" in output
    assert "历史营业额" in output
    assert "即时确认订单占比" in output
    assert "服务扣分" in output
    assert "诚信扣分" in output
    assert "财务扣分" in output
    assert "ctrip_ota_psi_score" in output
    assert "ctrip_ota_psi_metric" in output
    assert "8分" in output
    assert "A." not in output


def test_rules_put_psi_score_into_ctrip_total_without_metric_double_counting():
    sections = psi_sections()
    result = process({"sections": sections, "hotel_name": "测试酒店"})

    assert result["ctrip_items"]["6"]["item_score"] == 8
    assert result["ctrip_summary"]["total_score"] >= 8
    assert result["channel_scores"]["ctrip"]["items"]["6"]["item_score"] == 8

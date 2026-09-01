from __future__ import annotations

from runtime.feishu_output_renderer import render_feishu_output
from runtime.s11_readonly_plan_patch import _adapt_s11_promotion_result


def _promotion_result(*, s8_status: str = "ok", observations: list[dict] | None = None) -> dict:
    return {
        "status": "suggestion_only",
        "skill_id": "S11",
        "demo_dataset_id": "hotel_ota_demo_v1",
        "demo_business_date": "2026-06-11",
        "data_business_date": "2026-06-11",
        "data_source_type": "demo_data",
        "freshness_status": "demo_data",
        "promotion_plan": {
            "type": "PromotionPlan",
            "channel": "meituan",
            "window": {
                "target_date": "2026-08-09",
                "as_of_time": "2026-08-09T18:56:00+08:00",
            },
            "source_alignment": {
                "sources": {
                    "S8": s8_status,
                    "S9": "ok",
                    "S10": "ok",
                    "S16": "ok",
                }
            },
            "observation_metrics": observations or [],
            "read_only": True,
            "write_performed": False,
        },
        "read_only": True,
        "write_performed": False,
    }


def _render(result: dict) -> str:
    result = dict(result)
    result.update(
        {
            "intent": "promotion_suggestion",
            "output_profile": "owner_business",
            "auth_role": "owner",
        }
    )
    return render_feishu_output(result, "owner_business")["text"]


def test_real_promotion_plan_overwrites_demo_metadata_and_renders_observations():
    result = _adapt_s11_promotion_result(
        _promotion_result(
            observations=[
                {
                    "source": "S8",
                    "plan_id": "p1",
                    "launch_id": "l1",
                    "promotion_name": "计划1",
                    "spend_amount": 1191.09,
                    "roas": 3.1,
                },
                {
                    "source": "S8",
                    "plan_id": "p2",
                    "launch_id": "l2",
                    "promotion_name": "计划2",
                    "spend_amount": 300,
                    "roas": 7.3,
                },
                {
                    "source": "S9",
                    "exposure_uv": 2224,
                    "intention_uv": 276,
                    "pay_order_count": 15,
                },
                {
                    "source": "S10",
                    "plan_id": "p1",
                    "plan_name": "计划1",
                    "period_start_date": "2026-07-12",
                    "period_end_date": "2026-08-10",
                    "snapshot_time": "2026-08-11 15:44:01",
                    "observed_roas": 3.1,
                    "cpa": 79.4,
                    "spend_amount": 1191.09,
                },
                {
                    "source": "S10",
                    "plan_id": "p2",
                    "plan_name": "计划2",
                    "period_start_date": "2026-07-12",
                    "period_end_date": "2026-08-10",
                    "snapshot_time": "2026-08-11 15:44:01",
                    "observed_roas": 7.3,
                    "cpa": 20.0,
                    "spend_amount": 300,
                },
            ]
        )
    )

    assert result["data_source_type"] == "mysql_db"
    assert result["business_date"] == "2026-08-09"
    assert result["data_business_date"] == "2026-08-09"
    assert result["freshness_status"] == "fresh"
    assert result["business_result_generated"] is True
    assert result["live_allowed"] is False
    assert "demo_dataset_id" not in result
    assert "demo_business_date" not in result

    text = _render(result)
    assert "demo_data" not in text
    assert "2026-06-11" not in text
    assert "2026-08-09" in text
    assert "推广计划：2 个" in text
    assert "曝光 2224" in text
    assert "浏览 276" in text
    assert "支付 15 单" in text
    assert "ROAS 3.1" in text
    assert "ROAS 7.3" in text
    assert "经营状态：" in text
    assert "推广表现（平台归因观察，非净利润；统计窗口 2026-07-12 至 2026-08-10）" in text
    assert "统计窗口 2026-07-12 至 2026-08-10" in text
    assert "当日流量（仅作参考）：" in text
    assert "推广建议（只读）" in text
    assert "未创建任务、未执行投放" in text


def test_s8_data_gap_is_unknown_not_zero():
    result = _adapt_s11_promotion_result(
        _promotion_result(
            s8_status="data_gap",
            observations=[
                {
                    "source": "S9",
                    "exposure_uv": 2224,
                    "intention_uv": 276,
                    "pay_order_count": 15,
                }
            ],
        )
    )

    text = _render(result)
    assert "推广计划：无法确认" in text
    assert "推广计划：0 个" not in text
    assert "不要把数据缺口当成 0" in text


def test_s10_plan_rows_keep_s11_usable_when_s8_snapshot_is_missing():
    result = _adapt_s11_promotion_result(
        _promotion_result(
            s8_status="data_gap",
            observations=[
                {
                    "source": "S10",
                    "plan_id": "p1",
                    "launch_id": "l1",
                    "launch_name": "门店推广20240905099",
                    "promotion_status": "RUNNING",
                    "observed_roas": 2.86,
                    "spend_amount": 1291.09,
                },
                {
                    "source": "S10",
                    "plan_id": "p2",
                    "launch_id": "l2",
                    "launch_name": "极速推202604167df",
                    "promotion_status": "PAUSED",
                    "observed_roas": 5.48,
                    "spend_amount": 397.98,
                },
            ],
        )
    )

    context = result["evidence"]["promotion_context"]
    assert context["active_campaign_count"] == "2 个"
    assert context["count_basis"] == "S10 推广表现"


def test_confirmed_empty_s8_renders_zero_with_zero_specific_recommendation():
    result = _adapt_s11_promotion_result(_promotion_result(s8_status="ok", observations=[]))

    text = _render(result)
    assert "推广计划：0 个" in text
    assert "当前未观测到进行中的推广计划" in text
    assert "结合 S15 经营基准和 S16 当前进度" in text
    assert "核对推广计划覆盖对象与主力售卖房型是否一致" not in text


def test_all_real_sources_missing_never_falls_back_to_demo():
    result = _promotion_result(s8_status="data_gap", observations=[])
    result["promotion_plan"]["source_alignment"]["sources"] = {
        "S8": "data_gap",
        "S9": "data_gap",
        "S10": "data_gap",
        "S16": "data_gap",
    }
    result["status"] = "data_gap"

    adapted = _adapt_s11_promotion_result(result)
    assert adapted["data_source_type"] == "unavailable"
    assert adapted["freshness_status"] == "missing_real_data"
    assert adapted["business_result_generated"] is False
    assert adapted["blocked_reason"] == "s11_real_sources_data_gap"
    assert adapted.get("data_business_date") is None
    assert adapted.get("allow_demo_fallback") is False
    assert adapted.get("allow_sample_evidence") is False

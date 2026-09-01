from __future__ import annotations

from runtime.feishu_output_renderer import render_feishu_output
from runtime.s11_readonly_plan_patch import _adapt_s11_promotion_result


def test_s11_feishu_renders_s15_as_operating_evidence_and_s9_as_reference() -> None:
    result = _adapt_s11_promotion_result(
        {
            "status": "suggestion_only",
            "skill_id": "S11",
            "promotion_plan": {
                "type": "PromotionPlan",
                "channel": "meituan",
                "window": {
                    "target_date": "2026-08-09",
                    "as_of_time": "2026-08-09T20:00:00+08:00",
                },
                "source_alignment": {
                    "sources": {"S8": "ok", "S10": "ok", "S15": "ok", "S16": "ok"},
                    "reference_sources": {"S9": "ok"},
                },
                "observation_metrics": [
                    {"source": "S8", "plan_id": "p1", "launch_id": "l1", "promotion_name": "计划1"},
                    {
                        "source": "S9",
                        "role": "advisory_reference",
                        "reference_only": True,
                        "exposure_uv": 2224,
                        "intention_uv": 276,
                        "pay_order_count": 15,
                    },
                    {"source": "S10", "plan_id": "p1", "plan_name": "计划1", "observed_roas": 3.1, "cpa": 79.4},
                    {
                        "source": "S15",
                        "role": "operating_evidence",
                        "operating_evidence": True,
                        "target_room_nights": 31,
                        "sample_count": 3,
                    },
                    {
                        "source": "S16",
                        "sales_status": "ahead",
                        "actual_room_nights": 31,
                        "checkpoint_target_room_nights": 22.6,
                        "checkpoint_room_gap": 8.4,
                    },
                ],
            },
        }
    )
    result.update(
        {
            "intent": "promotion_suggestion",
            "output_profile": "owner_business",
            "auth_role": "owner",
        }
    )

    text = render_feishu_output(result, "owner_business")["text"]

    assert "S9 流量（参考）：曝光 2224" in text
    assert "S16 销售进度：进度 超前" in text
    assert "当前 31 间夜" in text
    assert "时点目标 22.6 间夜" in text
    assert "S15 销售基准：最终目标 31 间夜" in text
    assert "历史样本 3 天" in text
    assert "经营证据之一，不单独触发推广动作" in text
    assert "S9 仅作流量参考" in text
    assert "S15 是经营证据之一" in text
    assert "仅建议，未执行" in text

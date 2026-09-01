from __future__ import annotations

import unittest

from runtime.algorithms import s5_real_candidates as s5_module
from runtime.algorithms import s5_real_reply as reply_module
from runtime.s5_s15_baseline_contract_patch import inspect_s15_evidence


def _source(payload: dict) -> dict:
    return {"status": "ok", "payload": {"source_status": "ok", **payload}}


def _s15(maturity: str = "trend_only") -> dict:
    return {
        "status": "ok",
        "baseline": {
            "status": "ok",
            "business_date": "2026-08-04",
            "target_room_nights": 28,
            "hourly_curve_policy": {"s16_deviation_allowed": True},
            "hotel": {
                "effective_target_room_nights": 28,
                "baseline_health": {"object_maturity": maturity},
                "capacity_series_confidence": 0.25,
                "target_series_confidence": 0.40,
            },
        },
    }


def _s16() -> dict:
    return {
        "status": "ok",
        "target_date": "2026-08-04",
        "as_of_checkpoint_gap": 1.0,
        "daily_remaining_gap": 2.0,
    }


class S5S15BaselineContractPatchTest(unittest.TestCase):
    def test_trend_only_keeps_final_target_available(self) -> None:
        evidence = inspect_s15_evidence(
            _s15(),
            target_stay_date="2026-08-04",
        )
        self.assertTrue(evidence["final_target_available"])
        self.assertEqual(evidence["target_room_nights"], 28)
        self.assertFalse(evidence["hourly_evidence_qualified"])
        self.assertEqual(evidence["hourly_evidence_maturity"], "trend_only")

        _payload, available, reason = s5_module._s15_baseline(
            _s15(),
            target_stay_date="2026-08-04",
        )
        self.assertTrue(available)
        self.assertIsNone(reason)

    def test_s5_does_not_report_false_missing_s15(self) -> None:
        def query(template: str, _hotel_id: str, **_kwargs: object) -> dict:
            data = {
                "operating_snapshot": _source(
                    {
                        "committed_occupancy_rate": 0.8,
                        "room_type_forecasts": [
                            {
                                "room_type_id": "R1",
                                "total_rooms": 4,
                                "committed_sold_rooms": 3,
                            }
                        ],
                    }
                ),
                "ota_price_mapping": _source(
                    {
                        "price_snapshots": [
                            {
                                "channel": "meituan",
                                "ota_product_id": "MT-1",
                                "ota_product_name": "普通全天房",
                                "room_type_id": "R1",
                                "room_type_name": "测试房型",
                                "current_price": 400,
                                "business_date": "2026-08-04",
                                "snapshot_time": "2026-08-04 23:15:00",
                            }
                        ]
                    }
                ),
                "ota_business_metrics": _source({"rows": []}),
                "ctrip_competition_metrics_30d": _source({"rows": []}),
                "ota_order_loss_monthly": _source({"rows": []}),
            }
            return data[template]

        result = s5_module.build_s5_real_candidates(
            query=query,
            resolve_guard=lambda *_args, **_kwargs: {
                "source": "active_price_guard_policy",
                "policy_id": "guard-1",
                "version": 1,
                "floor_price": 300,
                "ceiling_price": 500,
            },
            control_db_path=":memory:",
            hotel_id="hotel-a",
            target_stay_date="2026-08-04",
            as_of_time="2026-08-04 23:15:00",
            s15_result=_s15(),
            s16_result=_s16(),
        )

        self.assertEqual(result["s15_status"], "ok")
        self.assertTrue(result["s15_final_target_available"])
        self.assertIsNone(result["s15_blocked_reason"])
        self.assertIn("已取得 S15 最终销售参考", result["s15_quality_warning"])
        self.assertFalse(
            any(
                str(flag).startswith("source_missing:s15:")
                for flag in result.get("quality_flags") or []
            )
        )
        candidate = result["candidates"][0]
        self.assertNotIn(
            "missing_s15_sales_baseline",
            candidate.get("quality_flags") or [],
        )
        self.assertIn(
            "已取得 S15 最终销售参考",
            candidate["s15_hourly_evidence_note"],
        )
        self.assertFalse(
            any(
                str(flag).startswith("s15_hourly_evidence_")
                for flag in candidate.get("quality_flags") or []
            )
        )
        self.assertEqual(candidate["candidate_strength"], "partial")

        rendered = reply_module.render_s5_real_reply(result)
        self.assertIn("证据说明：S15 已取得 S15 最终销售参考", rendered)
        self.assertLess(rendered.index("当前经营信号"), rendered.index("边界"))
        self.assertLess(rendered.index("边界"), rendered.index("证据说明：S15"))
        self.assertNotIn("缺 S15 销售基准", rendered)
        self.assertNotIn("s15_hourly_evidence_maturity_trend_only", rendered)


if __name__ == "__main__":
    unittest.main()

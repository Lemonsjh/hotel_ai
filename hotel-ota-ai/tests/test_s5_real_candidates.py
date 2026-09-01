from __future__ import annotations

import unittest
from unittest import mock

from runtime.algorithms.s5_real_candidates import build_s5_real_candidates
from runtime.algorithms.s5_real_reply import render_s5_real_reply
from runtime.feishu_command_router import route_feishu_command


def _result(payload: dict) -> dict:
    return {"status": "ok", "payload": {"source_status": "ok", **payload}}


def _s16() -> dict:
    return {
        "status": "ok",
        "target_date": "2026-08-04",
        "as_of_checkpoint_gap": 1.0,
        "daily_remaining_gap": 0.0,
    }


def _s15() -> dict:
    return {
        "status": "ok",
        "baseline": {
            "status": "ok",
            "business_date": "2026-08-04",
            "target_room_nights": 28,
            "hourly_curve_policy": {"s16_deviation_allowed": True},
        },
    }


class TestS5RealCandidates(unittest.TestCase):
    def _query(self, template: str, _hotel_id: str, **_kwargs: object) -> dict:
        data = {
            "operating_snapshot": _result(
                {"committed_occupancy_rate": 0.9, "room_type_forecasts": [{"room_type_id": "py01", "total_rooms": 4, "committed_sold_rooms": 4}]}
            ),
            "ota_price_mapping": _result(
                {"price_snapshots": [{"channel": "meituan", "ota_product_id": "mt-1", "ota_product_name": "电竞单人间挂牌", "room_type_id": "py01", "room_type_name": "电竞单人间", "current_price": 404, "business_date": "2026-08-03", "snapshot_time": "2026-08-03 18:57:25"}]}
            ),
            "ota_business_metrics": _result(
                {"rows": [{"table_key": "meituan_business_metrics", "metric_code": "DAY_ROOM_LOWEST_PRICE_AVG", "metric_value": 205, "metric_unit": "CNY", "peer_average": 244.35, "competitor_rank": "13/20", "business_date": "2026-08-03", "snapshot_time": "2026-08-03 18:57:25"}]}
            ),
            "sales_baseline": _result({"rows": []}),
            "ctrip_competition_metrics_30d": _result({"rows": []}),
            "ota_order_loss_monthly": _result({"rows": []}),
        }
        return data[template]

    def test_active_product_guard_keeps_hold_without_strong_business_trigger(self) -> None:
        def guard(*_args: object, **kwargs: object) -> dict:
            self.assertEqual(kwargs["ota_product_id"], "mt-1")
            return {"source": "active_price_guard_policy", "policy_id": "guard-1", "version": 2, "policy_state": "active", "floor_price": 360, "ceiling_price": 460, "max_increase_pct": 0.15, "max_decrease_pct": 0.15, "min_increase_pct": 0, "min_decrease_pct": 0}

        result = build_s5_real_candidates(
            query=self._query, resolve_guard=guard, control_db_path=":memory:", hotel_id="puyue",
            target_stay_date="2026-08-04", as_of_time="2026-08-03T19:00:00", channel="meituan",
            s15_result=_s15(), s16_result=_s16(),
        )

        item = result["candidates"][0]
        self.assertEqual(item["eligibility"], "preview_only_strong_rule_not_satisfied")
        self.assertEqual(item["decision_ref"]["ota_product_id"], "mt-1")
        self.assertFalse(result["direct_price_trigger_allowed"])
        self.assertFalse(result["live_allowed"])
        reply = render_s5_real_reply(result)
        self.assertIn("美团酒店级引流价（仅作市场背景）", reply)
        self.assertIn("本店低于同行约 16.1%", reply)
        self.assertIn("不代表具体房型或竞店商品价", reply)
        self.assertIn("业务日：2026-08-03", reply)

    def test_default_guard_keeps_visible_preview_but_blocks_s6(self) -> None:
        result = build_s5_real_candidates(
            query=self._query,
            resolve_guard=lambda *_args, **_kwargs: {"source": "default_policy", "max_increase_pct": 0.15, "max_decrease_pct": 0.15},
            control_db_path=":memory:", hotel_id="puyue", target_stay_date="2026-08-04", as_of_time=None,
            ota_product_id="mt-1", s15_result=_s15(), s16_result=_s16(),
        )

        item = result["candidates"][0]
        self.assertEqual(item["eligibility"], "preview_only_strong_rule_not_satisfied")
        self.assertEqual(item["pricing_bound_source"], "algorithm_single_change_hard_cap_only")

    def test_missing_s16_keeps_a_reference_only_candidate_visible(self) -> None:
        result = build_s5_real_candidates(
            query=self._query,
            resolve_guard=lambda *_args, **_kwargs: {
                "source": "active_price_guard_policy", "policy_id": "guard-1", "version": 1,
                "floor_price": 360, "ceiling_price": 460,
            },
            control_db_path=":memory:", hotel_id="puyue", target_stay_date="2026-08-04", as_of_time=None,
        )

        item = result["candidates"][0]
        self.assertEqual(item["eligibility"], "preview_only_strong_rule_not_satisfied")
        self.assertTrue(item["reference_only"])
        self.assertEqual(item["candidate_strength"], "partial")
        self.assertIn("missing_s16_progress_deviation", item["quality_flags"])
        self.assertIn("source_missing:s16:s16_unavailable", result["quality_flags"])

    def test_missing_s15_keeps_a_reference_only_candidate_visible(self) -> None:
        result = build_s5_real_candidates(
            query=self._query,
            resolve_guard=lambda *_args, **_kwargs: {
                "source": "active_price_guard_policy", "policy_id": "guard-1", "version": 1,
                "floor_price": 360, "ceiling_price": 460,
            },
            control_db_path=":memory:", hotel_id="puyue", target_stay_date="2026-08-04", as_of_time=None,
            s16_result=_s16(),
        )

        item = result["candidates"][0]
        self.assertEqual(item["eligibility"], "preview_only_strong_rule_not_satisfied")
        self.assertTrue(item["reference_only"])
        self.assertEqual(item["candidate_strength"], "partial")
        self.assertIn("missing_s15_sales_baseline", item["quality_flags"])
        self.assertIn("source_missing:s15:s15_unavailable", result["quality_flags"])

    def test_low_confidence_s15_is_not_accepted_as_pricing_evidence(self) -> None:
        low_confidence = _s15()
        low_confidence["baseline"]["hotel"] = {
            "baseline_health": {"object_maturity": "trend_only"},
            "capacity_series_confidence": 0.08,
            "target_series_confidence": 0.17,
        }
        result = build_s5_real_candidates(
            query=self._query,
            resolve_guard=lambda *_args, **_kwargs: {
                "source": "active_price_guard_policy", "policy_id": "guard-1", "version": 1,
                "floor_price": 360, "ceiling_price": 460,
            },
            control_db_path=":memory:", hotel_id="puyue", target_stay_date="2026-08-04", as_of_time=None,
            s15_result=low_confidence, s16_result=_s16(),
        )

        self.assertEqual(result["candidates"][0]["eligibility"], "preview_only_strong_rule_not_satisfied")
        self.assertTrue(result["candidates"][0]["reference_only"])
        self.assertEqual(result["candidates"][0]["candidate_strength"], "partial")
        self.assertEqual(result["s15_blocked_reason"], "s15_baseline_maturity_trend_only")

    def test_untrusted_mapping_is_visible_but_does_not_hide_readonly_candidate(self) -> None:
        def query(template: str, hotel_id: str, **kwargs: object) -> dict:
            result = self._query(template, hotel_id, **kwargs)
            if template == "ota_price_mapping":
                result["payload"]["price_snapshots"][0].update(
                    {"mapping_status": "PENDING", "match_rule": "NONE", "mapping_active": True}
                )
            return result

        result = build_s5_real_candidates(
            query=query,
            resolve_guard=lambda *_args, **_kwargs: {
                "source": "active_price_guard_policy", "policy_id": "guard-1", "version": 1,
                "floor_price": 360, "ceiling_price": 460,
            },
            control_db_path=":memory:", hotel_id="puyue", target_stay_date="2026-08-04", as_of_time=None,
            s15_result=_s15(), s16_result=_s16(),
        )

        item = result["candidates"][0]
        self.assertEqual(item["eligibility"], "preview_only_strong_rule_not_satisfied")
        self.assertFalse(item["s6_task_mapping_ready"])
        self.assertIn("room_type_mapping_not_trusted", item["quality_flags"])

    def test_real_route_uses_readonly_candidate_not_demo_chain(self) -> None:
        with mock.patch("runtime.feishu_command_router.database_source_enabled", return_value=True), mock.patch(
            "runtime.feishu_command_router.database_template_result", side_effect=self._query
        ), mock.patch(
            "runtime.feishu_command_router.resolve_price_guard_policy",
            return_value={"source": "active_price_guard_policy", "policy_id": "guard-1", "version": 1, "policy_state": "active", "floor_price": 360, "ceiling_price": 460, "max_increase_pct": 0.15, "max_decrease_pct": 0.15},
        ), mock.patch("runtime.feishu_command_router._query_s15_baseline", return_value=_s15()), mock.patch("runtime.feishu_command_router._query_s16_progress", return_value=_s16()):
            result = route_feishu_command("收益决策 美团 商品ID mt-1", role="owner", render=True)

        self.assertEqual(result["intent"], "revenue_decision")
        self.assertEqual(result["runtime_command"], "s5-revenue-candidate --read-only")
        self.assertEqual(result["candidates"][0]["ota_product_id"], "mt-1")
        self.assertEqual(result["data_source_type"], "mysql_db")
        self.assertNotIn("demo_dataset_id", result)
        self.assertIn("S5 收益候选", result["send_payload"]["text"])

    def test_production_menu_nine_uses_real_s15_result(self) -> None:
        auth_context = {"auth_status": "authorized", "user_role": "owner", "principal_id": "owner-1", "resolved_hotel_id": "puyue", "auth_backend": "test", "tenant_status": "active"}
        with mock.patch("runtime.feishu_command_router.database_source_enabled", return_value=True), mock.patch(
            "runtime.feishu_command_router.database_template_result", side_effect=self._query
        ), mock.patch(
            "runtime.feishu_command_router.resolve_price_guard_policy",
            return_value={"source": "default_policy", "max_increase_pct": 0.15, "max_decrease_pct": 0.15},
        ), mock.patch("runtime.feishu_command_router._query_s15_baseline", return_value=_s15()), mock.patch("runtime.feishu_command_router._query_s16_progress", return_value=_s16()), mock.patch("runtime.feishu_command_router.build_auth_context", return_value=auth_context), mock.patch(
            "runtime.feishu_command_router.tenant_scope_gate", return_value={"allowed": True}
        ), mock.patch("runtime.feishu_command_router.permission_gate", return_value={"allowed": True}):
            result = route_feishu_command("9", role="owner", hotel_id="puyue", force_feishu_auth=True)

        self.assertEqual(result["intent"], "revenue_decision")
        self.assertEqual(result["runtime_command"], "s5-revenue-candidate --read-only")
        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(result["s15_status"], "ok")
        self.assertIn("missing_s15_sales_baseline", result["candidates"][0]["quality_flags"])


if __name__ == "__main__":
    unittest.main()

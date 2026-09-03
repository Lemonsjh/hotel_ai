from __future__ import annotations

import unittest

from runtime.feishu_command_router import route_feishu_command
from runtime.feishu_output_renderer import build_feishu_send_payload, render_feishu_output


class TestFeishuOutputRenderer(unittest.TestCase):
    def test_developer_debug_shows_internal_fields(self) -> None:
        result = route_feishu_command("developer detail", role="admin", output_profile="developer_debug")
        result["model"] = "demo-model"
        result["provider"] = "demo-provider"
        rendered = render_feishu_output(result)
        text = rendered["text"]
        self.assertIn("run_id", text)
        self.assertIn("generated_by_runtime", text)
        self.assertNotIn("model=demo-model", text)
        self.assertNotIn("provider=demo-provider", text)

    def test_owner_business_hides_internal_fields(self) -> None:
        result = route_feishu_command("演示模式：检查 N001-N022", role="owner")
        result["model"] = "demo-model"
        result["provider"] = "demo-provider"
        rendered = render_feishu_output(result, "owner_business")
        text = rendered["text"]
        for forbidden in ["run_id", "generated_by_runtime", "fixture", "raw JSON", "demo-model", "demo-provider"]:
            self.assertNotIn(forbidden, text)

    def test_operator_frontdesk_guest_profiles(self) -> None:
        result = route_feishu_command("菜单", role="operator")
        operator = render_feishu_output(result, "operator_workbench")
        self.assertIn("操作清单", operator["text"])
        frontdesk = render_feishu_output(result, "frontdesk_task")
        self.assertNotIn("调价算法", frontdesk["text"])
        guest = render_feishu_output(result, "guest_limited")
        self.assertIn("无权限", guest["text"])

    def test_price_execution_preview_hides_internal_fields_for_owner(self) -> None:
        result = route_feishu_command("调价执行预览 dry-run", role="owner")
        rendered = render_feishu_output(result, "owner_business")
        self.assertIn("dry-run", rendered["text"])
        self.assertIn("没有创建正式审批", rendered["text"])
        self.assertNotIn("run_id", rendered["text"])

    def test_s6_preview_shows_directional_change_limits_not_price_bounds(self) -> None:
        rendered = build_feishu_send_payload(
            {
                "intent": "price_execution_dry_run",
                "runtime_command": "s6-price-dry-run --real-product",
                "status": "dry_run",
                "auth_role": "owner",
                "business_date": "2026-08-10",
                "execution_price": 720,
                "guard": {"max_increase_pct": 0.10, "max_decrease_pct": 0.10},
                "selected_product": {"ota_product_name": "测试商品", "current_price": 743, "channel": "meituan"},
            },
            role="owner",
        )
        self.assertIn("上调、下调均不超过 10%（与 S5 一致）", rendered["text"])
        self.assertNotIn("区间 ¥", rendered["text"])

    def test_s6_preview_shortens_marketing_suffix_in_product_name(self) -> None:
        rendered = build_feishu_send_payload(
            {
                "intent": "price_execution_dry_run",
                "runtime_command": "s6-price-dry-run --real-product",
                "status": "dry_run",
                "auth_role": "owner",
                "business_date": "2026-08-11",
                "execution_price": 433,
                "guard": {"max_increase_pct": 0.10, "max_decrease_pct": 0.10},
                "selected_product": {
                    "ota_product_id": "2360632683",
                    "ota_product_name": "璞韵大床房 - 不含早 - 入住当天 18:00 前免费取消",
                    "ota_room_type_name": "璞韵大床房",
                    "room_type_name": "璞韵大床房",
                    "current_price": 569,
                },
                "channel_source": "meituan",
            },
            role="owner",
        )

        self.assertIn("商品：璞韵大床房（meituan，OTA 商品 ID 2360632683）", rendered["text"])
        self.assertNotIn("入住当天 18:00 前免费取消", rendered["text"])

    def test_s6_net_target_shows_matching_net_and_listing_change_rates(self) -> None:
        rendered = build_feishu_send_payload(
            {
                "intent": "price_execution_dry_run",
                "runtime_command": "s6-price-dry-run --real-product",
                "status": "dry_run",
                "auth_role": "owner",
                "business_date": "2026-08-11",
                "execution_price": 433,
                "net_revenue_current": 249.60,
                "net_revenue_target": 190,
                "input_price_mode": "net_revenue_target",
                "guard": {"max_increase_pct": 0.10, "max_decrease_pct": 0.10},
                "selected_product": {"ota_product_name": "璞韵大床房", "current_price": 569},
                "channel_source": "meituan",
            },
            role="owner",
        )

        self.assertIn("净收：¥249.60 → ¥190.00（-23.9%）", rendered["text"])
        self.assertIn("挂牌价同步：¥569.00 → ¥433.00（-23.9%）", rendered["text"])

    def test_s6_listing_target_shows_estimated_net_revenue(self) -> None:
        rendered = build_feishu_send_payload(
            {
                "intent": "price_execution_dry_run",
                "runtime_command": "s6-price-dry-run --real-product",
                "status": "dry_run",
                "auth_role": "owner",
                "business_date": "2026-08-11",
                "execution_price": 332,
                "input_price_mode": "listing_price_target",
                "net_revenue_preview_status": "ok",
                "net_revenue_current": 275.14,
                "net_revenue_target": 248.21,
                "guard": {"max_increase_pct": 0.10, "max_decrease_pct": 0.10},
                "selected_product": {"ota_product_name": "测试商品", "current_price": 368},
                "channel_source": "meituan",
            },
            role="owner",
        )

        self.assertIn("预计净收：¥275.14 → ¥248.21（-9.8%）", rendered["text"])

    def test_s6_batch_preview_shows_full_product_ids_and_one_confirmation(self) -> None:
        rendered = build_feishu_send_payload(
            {
                "intent": "price_execution_dry_run",
                "runtime_command": "s6-price-dry-run --real-product",
                "status": "dry_run",
                "batch_dry_run": True,
                "batch_direction": "decrease",
                "batch_change_amount": 30,
                "data_snapshot_time": "2026-08-11T09:58:00",
                "confirmation_command": "确认调价 PRC-BATCH01",
                "confirmation_expires_at": "2026-08-11T10:00:00",
                "batch_items": [
                    {
                        "status": "dry_run", "execution_price": 374,
                        "net_revenue_current": 300, "net_revenue_target": 278,
                        "selected_product": {"ota_product_id": "2360632683", "room_type_name": "大床房", "current_price": 404},
                    }
                ],
            },
            role="owner",
        )

        self.assertIn("每个可执行商品挂牌价下调 ¥30", rendered["text"])
        self.assertIn("价格快照：2026-08-11T09:58:00", rendered["text"])
        self.assertIn("通过预览 1 个，未通过 0 个", rendered["text"])
        self.assertIn("OTA 商品 ID 2360632683", rendered["text"])
        self.assertIn("确认调价 PRC-BATCH01", rendered["text"])

    def test_s6_batch_preview_explains_actual_exclusions(self) -> None:
        rendered = build_feishu_send_payload(
            {
                "intent": "price_execution_dry_run",
                "status": "data_gap",
                "batch_dry_run": True,
                "blocked_reason": "no_eligible_standard_ota_products",
                "excluded_product_reasons": ["hour_room", "hour_room", "mapping_not_ready"],
            },
            role="owner",
        )

        self.assertIn("钟点房 2 个", rendered["text"])
        self.assertIn("商品映射未就绪 1 个", rendered["text"])
        self.assertNotIn("no_eligible_standard_ota_products", rendered["text"])

    def test_s6_default_guard_dry_run_has_no_default_guard_confirmation_path(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "price_execution_dry_run",
                "status": "dry_run",
                "blocked_reason": "active_price_guard_policy_required_before_live",
                "price_guard_policy": {"source": "default_policy"},
                "auth_role": "owner",
            },
            role="owner",
        )

        self.assertIn("默认护栏层", payload["text"])
        self.assertIn("不能创建调价任务", payload["text"])
        self.assertIn("确认也不能把默认护栏升级为可执行护栏", payload["text"])
        self.assertIn("必须明确单日或起止日期区间", payload["text"])
        self.assertNotIn("确认接受默认护栏", payload["text"])

    def test_s6_missing_confirmation_token_returns_an_actionable_reply(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "price_execution_confirm",
                "status": "blocked",
                "reason": "s6_confirmation_token_required",
                "auth_role": "owner",
            },
            role="owner",
        )

        self.assertIn("\u672a\u627e\u5230\u552f\u4e00\u6709\u6548\u7684\u8c03\u4ef7\u9884\u89c8", payload["text"])
        self.assertIn("\u786e\u8ba4\u8c03\u4ef7 PRC-xxxx", payload["text"])
        self.assertNotIn("\u5df2\u5199\u5165", payload["text"])

    def test_s6_rejected_preview_shows_single_change_limit_without_token(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "price_execution_dry_run",
                "runtime_command": "s6-price-dry-run --real-product",
                "status": "dry_run",
                "execution_price": 509.41,
                "business_date": "2026-08-11",
                "confirmation_blocked_reason": "s6_single_change_decrease_limit_exceeded",
                "confirmation_blocked_details": {
                    "actual_change_pct": -0.105,
                    "max_decrease_pct": 0.10,
                },
                "selected_product": {"ota_product_name": "测试商品", "current_price": 569},
                "channel_source": "meituan",
                "auth_role": "owner",
            },
            role="owner",
        )

        self.assertIn("超过单次下调 10%的上限", payload["text"])
        self.assertIn("未生成确认令牌", payload["text"])

    def test_s6_rejected_preview_confirmation_explains_single_change_limit(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "price_execution_confirm",
                "status": "blocked",
                "reason": "s6_latest_preview_not_confirmable",
                "preview": {"actual_change_pct": -0.105, "max_decrease_pct": 0.10},
                "auth_role": "owner",
            },
            role="owner",
        )

        self.assertIn("超过单次下调 10%的上限", payload["text"])
        self.assertIn("未生成 PRC 确认令牌", payload["text"])

    def test_s6_outbox_confirmation_returns_without_plugin_waiting(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "price_task_outbox_write",
                "status": "queued",
                "execute_status": "PENDING",
                "auth_role": "owner",
            },
            role="owner",
        )

        self.assertIn("PENDING", payload["text"])
        self.assertIn("\u4e0d\u7b49\u5f85\u63d2\u4ef6\u6267\u884c", payload["text"])

    def test_promotion_suggestion_renders_real_data_metadata(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "promotion_suggestion",
                "status": "ok",
                "auth_role": "owner",
                "data_source_type": "mysql_db",
                "data_business_date": "2026-08-04",
                "data_snapshot_time": "2026-08-04 17:34:00",
                "freshness_status": "fresh",
                "evidence": {
                    "promotion_context": {
                        "active_campaign_count": 5,
                        "campaign_room_type_count": 11,
                        "campaign_platforms": ["meituan"],
                    },
                    "s10_promotion_observation": {"observations": ["计划 A：观测 ROAS 2.1，CPA 80"]},
                },
            },
            role="owner",
        )

        self.assertIn("mysql_db", payload["text"])
        self.assertIn("fresh", payload["text"])
        self.assertIn("5 个", payload["text"])
        self.assertIn("观测 ROAS 2.1", payload["text"])
        self.assertNotIn("演示数据", payload["text"])

    def test_send_payload_is_final_safe_shape_without_runtime_result(self) -> None:
        result = route_feishu_command("developer detail", role="owner", output_profile="developer_debug")
        result["raw_json"] = {"secret": "not-for-feishu"}
        result["fixture_path"] = "examples/demo_data/nodes/N001.json"
        result["model"] = "demo-model"
        result["provider"] = "demo-provider"
        result["context_warnings"] = ["generated_today_demo_not_found"]

        payload = build_feishu_send_payload(result, role="owner")

        self.assertEqual(
            set(payload),
            {"text", "card", "send_allowed", "output_profile", "warnings", "data_source_type", "freshness_status"},
        )
        self.assertTrue(payload["send_allowed"])
        self.assertIsNone(payload["card"])
        self.assertEqual(payload["warnings"], ["generated_today_demo_not_found"])
        for forbidden in ["raw_json", "fixture_path", "demo-model", "demo-provider", "run_id"]:
            self.assertNotIn(forbidden, str(payload))

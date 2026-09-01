from __future__ import annotations

import os
import tempfile
import unittest

from runtime.feishu_command_router import route_feishu_command


class TestFeishuCommandRouter(unittest.TestCase):
    def test_identity_does_not_default_to_admin(self) -> None:
        result = route_feishu_command("你是谁", role="operator", render=True)
        self.assertEqual(result["intent"], "identity")
        self.assertEqual(result["auth_role"], "operator")
        self.assertNotEqual(result["auth_role"], "admin")
        self.assertIn("单总控 Agent + A0-A6", result["rendered"]["text"])

    def test_run_s02_without_demo_returns_data_gap(self) -> None:
        result = route_feishu_command("运行 S02 看看", role="operator")
        self.assertEqual(result["intent"], "run_s02")
        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["blocked_reason"], "database_source_disabled")

    def test_run_s02_with_demo_returns_demo_facts(self) -> None:
        result = route_feishu_command("用演示数据运行 S02 看看", role="operator")
        self.assertEqual(result["intent"], "run_s02")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["core_metrics"]["total_rooms"], 50)
        self.assertEqual(result["core_metrics"]["sold_rooms"], 34)

    def test_seed_demo_is_runtime_backed(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = os.path.join(tmp, "hotel_ops.sqlite")
            result = route_feishu_command("generate-today-demo", role="operator", db_path=db_path)
        self.assertEqual(result["status"], "ok")
        self.assertIn("run_id", result)
        self.assertIn("inserted_rows", result)
        self.assertEqual(result["runtime_command"], "generate-today-demo --write-db")
        self.assertTrue(result["generated_today_demo_ready"])
        self.assertTrue(result["generated_by_runtime"])

    def test_feishu_generated_today_is_used_by_following_demo_chain(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = os.path.join(tmp, "hotel_ops.sqlite")
            generated = route_feishu_command("generate today demo data", role="operator", db_path=db_path)
            self.assertEqual(generated["status"], "ok")

            chains = route_feishu_command("full chain demo", role="operator", db_path=db_path)

        self.assertEqual(chains["status"], "failed")
        self.assertEqual(chains["run_context"]["context_source"], "sqlite_synthetic_today_demo")
        self.assertFalse(chains["run_context"]["fallback_used"])
        self.assertEqual(chains["passed_scenarios"], 8)
        self.assertEqual(chains["failed_scenarios"], 2)

    def test_demo_node_and_chain_are_runtime_backed(self) -> None:
        nodes = route_feishu_command("演示模式：检查 N001-N022", role="operator")
        self.assertEqual(nodes["total_nodes"], 22)
        self.assertFalse(nodes["formal_approval_created"])
        self.assertEqual(nodes["live_execution_count"], 0)
        chains = route_feishu_command("演示模式：跑一遍 SC01-SC10", role="operator")
        self.assertEqual(chains["total_scenarios"], 10)
        self.assertFalse(chains["formal_approval_created"])
        self.assertEqual(chains["live_execution_count"], 0)

    def test_enter_demo_mode_is_runtime_backed(self) -> None:
        result = route_feishu_command("进入演示模式", role="operator")
        self.assertEqual(result["intent"], "enter_demo_mode")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mode"], "demo")
        self.assertFalse(result["approval_data_allowed"])
        self.assertFalse(result["live_allowed"])

    def test_developer_detail_forces_debug_profile(self) -> None:
        result = route_feishu_command("开发者详情", role="owner")
        self.assertEqual(result["intent"], "developer_detail")
        self.assertEqual(result["output_profile"], "developer_debug")
        self.assertTrue(result["generated_by_runtime"])
        self.assertEqual(result["total_scenarios"], 10)

    def test_price_execution_dry_run_without_real_source_returns_data_gap(self) -> None:
        result = route_feishu_command("调价执行预览 dry-run", role="operator")
        self.assertEqual(result["intent"], "price_execution_dry_run")
        self.assertEqual(result["node_id"], "N016")
        self.assertEqual(result["skill_id"], "S6")
        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["blocked_reason"], "database_source_disabled")
        self.assertFalse(result["live_allowed"])

    def test_demo_live_execution_request_is_rejected(self) -> None:
        result = route_feishu_command("用演示数据直接执行调价 live", role="admin")
        self.assertEqual(result["status"], "blocked")
        self.assertIn("demo_data_never_live", result["blocked_reasons"])
        self.assertIn("approval_id_required", result["blocked_reasons"])
        self.assertIn("live_switch_disabled", result["blocked_reasons"])

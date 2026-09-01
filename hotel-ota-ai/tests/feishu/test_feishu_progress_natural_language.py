from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from runtime.demo_today_generator import generate_today_demo_result
from runtime.feishu_command_router import route_feishu_command


def _seed_synthetic_today(db_path: str, *, business_date: str = "2026-06-16") -> None:
    generate_today_demo_result(
        argparse.Namespace(
            business_date=business_date,
            seed=20260616,
            profile="normal",
            hotel_id="puyue-demo",
            write_db=True,
            write_fixtures=False,
            dry_run=False,
            output_dir=None,
            db=db_path,
        )
    )


class TestFeishuProgressNaturalLanguage(unittest.TestCase):
    def test_progress_phrases_route_to_n011_runtime_result(self) -> None:
        phrases = ["进度诊断", "进度偏差", "完成率", "还差几间", "今天间夜进度"]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    result = route_feishu_command(phrase, role="operator", db_path=db_path, as_of_time="22:00")

                    self.assertEqual(result["intent"], "progress_deviation_demo")
                    self.assertEqual(result["node_id"], "N011")
                    self.assertEqual(result["skill_id"], "S16")
                    self.assertEqual(result["context_source"], "sqlite_synthetic_today_demo")
                    self.assertEqual(result["data_source_type"], "synthetic_today_demo")
                    self.assertGreaterEqual(len(result["actual_hourly_sales"]), 8)
                    self.assertGreaterEqual(len(result["target_hourly_curve"]), 8)
                    self.assertNotEqual(result.get("blocked_reason"), "database_source_disabled")

    def test_hourly_sales_phrases_use_runtime_data_but_render_compact_checkpoint(self) -> None:
        phrases = ["分时实际销售", "小时销售", "每小时卖了多少"]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    result = route_feishu_command(phrase, role="operator", db_path=db_path, render=True, as_of_time="22:00")
                    rendered_text = result["rendered"]["text"]

                    self.assertEqual(result["intent"], "progress_deviation_demo")
                    self.assertEqual(result["node_id"], "N011")
                    self.assertGreaterEqual(len(result["actual_hourly_sales"]), 8)
                    self.assertIn("当前检查点", rendered_text)
                    self.assertNotIn("actual_hourly_sales", rendered_text)
                    self.assertNotIn("target_hourly_curve", rendered_text)
                    self.assertNotIn("没有分时实际销售", rendered_text)

    def test_business_snapshot_phrases_route_to_n005(self) -> None:
        phrases = ["当前已售", "出租率", "今日经营"]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    result = route_feishu_command(phrase, role="operator", db_path=db_path)

                    self.assertEqual(result["intent"], "run_s02")
                    self.assertEqual(result["node_id"], "N005")
                    self.assertEqual(result["skill_id"], "S2")
                    self.assertEqual(result["context_source"], "sqlite_synthetic_today_demo")
                    self.assertIn("sold_rooms", result["core_metrics"])

    def test_target_baseline_phrases_route_to_n010(self) -> None:
        phrases = ["销售目标", "小时目标", "基准线"]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    result = route_feishu_command(phrase, role="operator", db_path=db_path)

                    self.assertEqual(result["intent"], "sales_baseline_demo")
                    self.assertEqual(result["node_id"], "N010")
                    self.assertEqual(result["skill_id"], "S15")
                    self.assertEqual(result["context_source"], "sqlite_synthetic_today_demo")
                    self.assertGreaterEqual(len(result["hourly_target_curve"]), 8)

    def test_status_source_phrases_route_to_runtime_status(self) -> None:
        phrases = ["当前模式", "数据日期", "为什么还是旧数据", "DB_SOURCE_ENABLE影响吗"]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _seed_synthetic_today(db_path)

            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    result = route_feishu_command(phrase, role="operator", db_path=db_path)

                    self.assertEqual(result["intent"], "runtime_status")
                    self.assertEqual(result["context_source"], "sqlite_synthetic_today_demo")
                    self.assertFalse(result["db_source_enable_required_for_demo"])
                    self.assertEqual(result["demo_chain_context_date"], "2026-06-16")

from __future__ import annotations

import argparse
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.demo_today_generator import generate_today_demo_result
from runtime.feishu_command_router import route_feishu_command


class TestFeishuRuntimeStatusDates(unittest.TestCase):
    def test_runtime_status_distinguishes_demo_chain_date_from_snapshot_default(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "generated.sqlite")
            generate_today_demo_result(
                argparse.Namespace(
                    business_date="2026-06-15",
                    seed=20260615,
                    profile="normal",
                    hotel_id="puyue-demo",
                    write_db=True,
                    write_fixtures=False,
                    dry_run=False,
                    output_dir=None,
                    db=db_path,
                )
            )
            with mock.patch.dict(os.environ, {"HOTEL_OTA_DB_SOURCE_ENABLE": "0"}, clear=False):
                result = route_feishu_command("当前模式是什么，数据日期是", role="operator", db_path=db_path)

        self.assertEqual(result["intent"], "runtime_status")
        self.assertEqual(result["demo_chain_context_date"], "2026-06-15")
        self.assertEqual(result["snapshot_default_date"], "2026-06-11")
        self.assertEqual(result["context_source"], "sqlite_synthetic_today_demo")
        self.assertFalse(result["fallback_used"])
        self.assertFalse(result["db_source_enable_required_for_demo"])
        self.assertIn("真实经营数据", result["db_source_enable_note"])
        self.assertNotIn("打开 DB_SOURCE_ENABLE", result["suggested_next_step"])


if __name__ == "__main__":
    unittest.main()

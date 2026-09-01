from __future__ import annotations

import unittest

from runtime.feishu_command_router import route_feishu_command
from runtime.feishu_output_renderer import render_feishu_output


class TestDemoRealDataIsolation(unittest.TestCase):
    def test_demo_output_does_not_claim_real_today_or_mysql(self) -> None:
        result = route_feishu_command("完整演示全链路", role="owner")
        rendered = render_feishu_output(result, "owner_business")
        self.assertEqual(result["data_source_type"], "demo_data")
        self.assertFalse(result["today_label_allowed"])
        self.assertFalse(result["formal_approval_created"])
        self.assertEqual(result["live_execution_count"], 0)
        self.assertNotIn("今日真实经营", rendered["text"])
        self.assertNotIn("MySQL", rendered["text"])
        self.assertIn("业务日期", rendered["text"])

    def test_historical_path_requires_explicit_request_marker(self) -> None:
        result = route_feishu_command("运行 S02 看看", role="operator")
        self.assertEqual(result["status"], "data_gap")
        self.assertNotIn("historical", result.get("summary", ""))

from __future__ import annotations

import unittest
from pathlib import Path

from runtime.feishu_command_router import route_feishu_command
from runtime.feishu_output_renderer import TEMPLATE_DIR, render_feishu_output


class TestFeishuTemplates(unittest.TestCase):
    def test_required_template_files_exist(self) -> None:
        expected = {
            "identity.md",
            "menu.md",
            "business_snapshot.md",
            "full_chain_demo.md",
            "revenue_decision.md",
            "execution_dry_run.md",
            "live_blocked.md",
            "external_ota_report.md",
            "node_check_summary.md",
            "scenario_check_summary.md",
            "developer_debug.md",
            "guest_limited.md",
        }
        actual = {path.name for path in Path(TEMPLATE_DIR).glob("*.md")}
        self.assertTrue(expected.issubset(actual))

    def test_business_output_has_stable_sections_and_hides_internal_fields(self) -> None:
        result = route_feishu_command("完整演示全链路", role="owner")
        result["model"] = "internal-model"
        result["provider"] = "internal-provider"
        rendered = render_feishu_output(result, "owner_business")
        text = rendered["text"]
        for section in ["数据标签", "一、结论", "二、关键指标", "阻断与边界"]:
            self.assertIn(section, text)
        for forbidden in ["run_id", "generated_by_runtime", "internal-model", "internal-provider", "raw JSON"]:
            self.assertNotIn(forbidden, text)

    def test_developer_debug_shows_internal_fields(self) -> None:
        result = route_feishu_command("developer detail", role="admin", output_profile="developer_debug")
        result["model"] = "internal-model"
        result["provider"] = "internal-provider"
        rendered = render_feishu_output(result, "developer_debug")
        self.assertIn("run_id:", rendered["text"])
        self.assertIn("generated_by_runtime:", rendered["text"])
        self.assertNotIn("model=internal-model", rendered["text"])
        self.assertNotIn("provider=internal-provider", rendered["text"])

    def test_synthetic_today_demo_uses_short_data_label_and_blocks_live(self) -> None:
        result = {
            "intent": "full_chain_demo",
            "data_source_type": "synthetic_today_demo",
            "freshness_status": "synthetic_current_day",
            "business_date": "2026-06-12",
            "approval_data_allowed": False,
            "live_allowed": False,
            "passed_scenarios": 10,
            "total_scenarios": 10,
            "covered_nodes": [f"N{index:03d}" for index in range(1, 23)],
            "uncovered_nodes": [],
        }
        rendered = render_feishu_output(result, "owner_business")
        text = rendered["text"]
        self.assertIn("synthetic_today_demo", text)
        self.assertIn("是否允许 live：否", text)
        self.assertNotIn("数据不新鲜", text)

    def test_partial_revenue_preview_says_not_formal_price_decision(self) -> None:
        result = route_feishu_command("\u6536\u76ca\u51b3\u7b56", role="operator")
        rendered = render_feishu_output(result, "operator_workbench")
        text = rendered["text"]

        self.assertIn("\u8c03\u4ef7\u7b97\u6cd5\u9884\u89c8", text)
        self.assertNotIn("\u3010\u6536\u76ca\u5efa\u8bae\u9884\u89c8\u3011", text)
        self.assertIn("\u7ed3\u8bba\u5f3a\u5ea6", text)
        self.assertIn("\u4e0d\u6784\u6210\u6b63\u5f0f\u4ef7\u683c\u51b3\u7b56", text)
        self.assertNotIn("\u6b63\u5f0f\u8c03\u4ef7\u5efa\u8bae", text)
        self.assertIn("Dry-run", text)
        self.assertIn("\u6b63\u5f0f\u5ba1\u6279\u521b\u5efa\uff1a\u7981\u6b62", text)

    def test_identity_template_does_not_discuss_demo_or_mysql_data_source(self) -> None:
        rendered = render_feishu_output(
            {
                "intent": "identity",
                "personal_role": "owner",
                "auth_backend": "sqlite_active_auth",
                "auth_status": "ok",
                "tenant_status": "bound",
                "chat_type": "group",
                "chat_bound": True,
                "resolved_hotel_id": "puyue",
            },
            "owner_business",
        )
        text = rendered["text"]

        self.assertIn("身份", text)
        self.assertNotIn("demo", text.lower())
        self.assertNotIn("sample", text.lower())
        self.assertNotIn("MySQL", text)

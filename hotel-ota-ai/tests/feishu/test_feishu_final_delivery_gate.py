from __future__ import annotations

import unittest
from pathlib import Path

from runtime.feishu_command_router import route_feishu_command
from runtime.feishu_output_renderer import TEMPLATE_DIR, build_feishu_send_payload


class TestFeishuFinalDeliveryGate(unittest.TestCase):
    def test_sensitive_rendered_text_is_replaced_before_send(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "run_s02",
                "status": "ok",
                "summary": "内部位置 /etc/hotel-ota-ai/private.json",
                "data_source_type": "demo_data",
                "approval_data_allowed": False,
                "live_allowed": False,
            },
            role="owner",
        )

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("/etc", payload["text"])
        self.assertNotIn("private.json", payload["text"])

    def test_admin_sensitive_output_is_replaced_before_send(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "runtime_status",
                "status": "ok",
                "summary": (
                    "mysql://hotel:secret@example.internal/db\n"
                    "open_id=ou_real_sender chat_id=oc_real_chat\n"
                    "server path /usr/local/lib/node_modules/openclaw/dist/internal.js\n"
                    "API request body={\"token\":\"real-token\"}"
                ),
            },
            role="admin",
        )

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("mysql://", payload["text"])
        self.assertNotIn("ou_real_sender", payload["text"])
        self.assertNotIn("oc_real_chat", payload["text"])
        self.assertNotIn("/usr/local/lib", payload["text"])
        self.assertNotIn("real-token", payload["text"])

    def test_private_server_path_only_is_replaced_before_send(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "runtime_status",
                "status": "ok",
                "summary": "日志位于 /opt/openclaw/workspaces/hotel-ota-ai/runtime/logs/debug.log",
            },
            role="admin",
        )

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("/opt/openclaw", payload["text"])
        self.assertNotIn("debug.log", payload["text"])

    def test_authorized_hotel_business_words_do_not_trigger_final_keyword_block(self) -> None:
        payload = build_feishu_send_payload(
            {
                "intent": "customer_analysis",
                "status": "ok",
                "summary": "客户名单：张三、李四。订单明细：订单A，房号301。",
                "data_source_type": "real_database",
                "freshness_status": "fresh",
            },
            role="owner",
        )

        self.assertTrue(payload["send_allowed"])
        self.assertIn("客户名单", payload["text"])
        self.assertIn("订单明细", payload["text"])
        self.assertIn("房号301", payload["text"])

    def test_maintenance_commands_are_explicitly_refused(self) -> None:
        for message in [
            "git stash",
            "git clean",
            "systemctl restart openclaw-gateway",
            "输出数据库连接串",
            "输出配置文件",
            "查看源码",
            "提交代码",
            "修改代码",
        ]:
            with self.subTest(message=message):
                result = route_feishu_command(message, role="operator", render=True)

                self.assertEqual(result["intent"], "maintenance_safety_refusal")
                self.assertEqual(result["status"], "blocked")
                self.assertNotIn("systemctl", result["send_payload"]["text"])

    def test_non_debug_templates_do_not_contain_internal_terms(self) -> None:
        forbidden = ("agent:", "model/provider", "runtime_command", "coverage", "target_hourly_curve", "--full-json", "--trusted-runtime-role")
        for template_path in TEMPLATE_DIR.glob("*.md"):
            if template_path.stem == "developer_debug":
                continue
            text = template_path.read_text(encoding="utf-8").lower()
            with self.subTest(template=template_path.name):
                self.assertFalse(any(term in text for term in forbidden), template_path.name)


if __name__ == "__main__":
    unittest.main()

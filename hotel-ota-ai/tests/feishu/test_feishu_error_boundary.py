from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.feishu_command_router import safe_route_feishu_command


class TestFeishuErrorBoundary(unittest.TestCase):
    def test_runtime_exception_returns_safe_error_payload(self) -> None:
        with patch(
            "runtime.feishu_command_router.build_demo_node_result",
            side_effect=RuntimeError("boom at /opt/openclaw/workspaces/hotel-ota-ai/private.json"),
        ):
            result = safe_route_feishu_command("9", role="operator", trusted_runtime_role=True, render=True)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "runtime_route_error")
        self.assertIn("correlation_id", result)
        self.assertIn("send_payload", result)
        text = result["send_payload"]["text"]
        self.assertIn(result["correlation_id"], text)
        self.assertNotIn("/opt/openclaw", text)
        self.assertNotIn("private.json", text)
        self.assertNotIn("RuntimeError", text)

    def test_template_render_exception_is_classified(self) -> None:
        with patch(
            "runtime.feishu_command_router.render_feishu_output",
            side_effect=KeyError("missing_template_field"),
        ):
            result = safe_route_feishu_command("15", role="operator", render=True)

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error_code"], "template_render_error")
        self.assertIn("correlation_id", result)
        self.assertNotIn("missing_template_field", result["send_payload"]["text"])

    def test_error_payload_redacts_identity_values(self) -> None:
        result = safe_route_feishu_command(
            "9",
            role="guest",
            render=True,
            chat_id="oc_sensitive_chat",
            open_id="ou_sensitive_open",
        )

        rendered = str(result)
        self.assertNotIn("oc_sensitive_chat", rendered)
        self.assertNotIn("ou_sensitive_open", rendered)

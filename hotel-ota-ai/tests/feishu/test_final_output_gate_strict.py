from __future__ import annotations

import unittest

from runtime.feishu_output_renderer import build_feishu_send_payload


class TestFinalOutputGateStrict(unittest.TestCase):
    def _payload_for_summary(self, summary: str) -> dict:
        return build_feishu_send_payload(
            {
                "intent": "runtime_status",
                "status": "ok",
                "summary": summary,
                "data_source_type": "unavailable",
                "freshness_status": "unavailable",
            },
            role="admin",
        )

    def test_blocks_open_id_chat_id_user_target(self) -> None:
        payload = self._payload_for_summary("open_id=ou_example chat_id=oc_example user:ou_example")

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("ou_example", payload["text"])
        self.assertNotIn("oc_example", payload["text"])
        self.assertNotIn("user:ou", payload["text"])

    def test_blocks_git_status_output(self) -> None:
        payload = self._payload_for_summary("git status\nOn branch align-v20-architecture\nmodified: runtime/cli.py")

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("On branch", payload["text"])
        self.assertNotIn("runtime/cli.py", payload["text"])

    def test_allows_model_provider_footer(self) -> None:
        payload = self._payload_for_summary("Agent: hotel-ota-chief\nModel: deepseek-v4-flash\nProvider: deepseek")

        self.assertTrue(payload["send_allowed"])
        self.assertIn("Agent:", payload["text"])
        self.assertIn("Model:", payload["text"])
        self.assertIn("Provider:", payload["text"])

    def test_blocks_private_paths(self) -> None:
        payload = self._payload_for_summary("/etc/hotel-ota-ai/private.json /opt/openclaw/workspaces/app /usr/local/lib/node_modules/openclaw/dist")

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("/etc/", payload["text"])
        self.assertNotIn("/opt/", payload["text"])
        self.assertNotIn("/usr/local/lib", payload["text"])

    def test_blocks_code_fix_success_claim(self) -> None:
        payload = self._payload_for_summary("已修复代码，已执行 systemctl restart openclaw-gateway，源码如下")

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("已修复代码", payload["text"])
        self.assertNotIn("systemctl", payload["text"])

    def test_blocks_var_lib_private_path(self) -> None:
        payload = self._payload_for_summary(
            "护栏存在 /var/lib/hotel-ota-ai/hotel_ops.sqlite 表里"
        )

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("/var/lib", payload["text"])

    def test_blocks_nginx_report_path(self) -> None:
        payload = self._payload_for_summary(
            "报告写到 /usr/share/nginx/html/reports/ota_diagnosis_report.html"
        )

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("/usr/share/nginx", payload["text"])

    def test_blocks_user_id_literal(self) -> None:
        payload = self._payload_for_summary("user_id=12345 union_id=on_abcdef")

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("user_id", payload["text"])
        self.assertNotIn("union_id", payload["text"])

    def test_blocks_cat_private_config_command(self) -> None:
        payload = self._payload_for_summary(
            "你可以在服务器执行 cat /etc/hotel-ota-ai/database-source.json 查看"
        )

        self.assertFalse(payload["send_allowed"])
        self.assertNotIn("cat /etc", payload["text"])


if __name__ == "__main__":
    unittest.main()

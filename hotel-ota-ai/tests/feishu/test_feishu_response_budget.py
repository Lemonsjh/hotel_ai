from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.cli import main
from runtime.feishu_command_router import safe_route_feishu_command


def _capture_cli(argv: list[str]) -> dict:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(argv)
    payload = json.loads(buffer.getvalue())
    payload["_exit_code"] = code
    payload["_raw_chars"] = len(buffer.getvalue())
    return payload


class TestFeishuResponseBudget(unittest.TestCase):
    def test_cli_full_chain_render_returns_compact_payload_by_default(self) -> None:
        payload = _capture_cli(
            [
                "feishu-route",
                "--message",
                "\u5b8c\u6574\u6f14\u793a\u5168\u94fe\u8def",
                "--user-role",
                "operator",
                "--trusted-runtime-role",
                "--render",
            ]
        )

        self.assertEqual(payload["_exit_code"], 0)
        self.assertLess(payload["_raw_chars"], 20_000)
        self.assertEqual(payload["intent"], "demo_chain_all")
        self.assertIn("send_payload", payload)
        self.assertNotIn("chains", payload)
        self.assertNotIn("node_results", payload)
        self.assertNotIn("fixtures", payload)
        self.assertNotIn("runtime_command", payload)
        self.assertNotIn("agent_id", payload)
        self.assertNotIn("model", payload)
        self.assertNotIn("provider", payload)

    def test_cli_developer_detail_does_not_dump_full_demo_graph_by_default(self) -> None:
        payload = _capture_cli(
            [
                "feishu-route",
                "--message",
                "developer detail",
                "--user-role",
                "admin",
                "--trusted-runtime-role",
                "--output-profile",
                "developer_debug",
                "--render",
            ]
        )

        self.assertEqual(payload["_exit_code"], 0)
        self.assertLess(payload["_raw_chars"], 20_000)
        self.assertNotIn("chains", payload)
        self.assertNotIn("node_results", payload)
        self.assertNotIn("fixtures", payload)

    def test_send_payload_text_is_bounded(self) -> None:
        result = safe_route_feishu_command(
            "\u8fdb\u5ea6\u8bca\u65ad",
            role="operator",
            trusted_runtime_role=True,
            render=True,
        )

        self.assertIn("send_payload", result)
        self.assertLessEqual(len(result["send_payload"]["text"]), 1_200)

    def test_cli_business_route_requires_feishu_context_by_default(self) -> None:
        payload = _capture_cli(["feishu-route", "--message", "9", "--user-role", "operator", "--render"])

        self.assertEqual(payload["_exit_code"], 0)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["intent"], "revenue_decision_demo")
        self.assertEqual(payload["blocked_reason"], "missing_required_feishu_auth_context")
        self.assertFalse(payload["business_result_generated"])
        self.assertNotIn("node_result", payload)
        self.assertNotIn("room_type_recommendations", payload)

    def test_cli_trusted_runtime_role_allows_local_demo_preview(self) -> None:
        payload = _capture_cli(
            [
                "feishu-route",
                "--message",
                "9",
                "--user-role",
                "operator",
                "--trusted-runtime-role",
                "--render",
            ]
        )

        self.assertEqual(payload["_exit_code"], 0)
        self.assertEqual(payload["intent"], "revenue_decision_demo")
        self.assertIn(payload["status"], {"ok", "preview_only", "partial"})
        self.assertIn("node_id", payload)

    def test_full_json_requires_trusted_runtime_role(self) -> None:
        payload = _capture_cli(
            [
                "feishu-route",
                "--message",
                "\u5b8c\u6574\u6f14\u793a\u5168\u94fe\u8def",
                "--user-role",
                "operator",
                "--full-json",
                "--render",
            ]
        )

        self.assertEqual(payload["_exit_code"], 0)
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(payload["blocked_reason"], "full_json_requires_trusted_runtime_role")
        self.assertLess(payload["_raw_chars"], 20_000)
        self.assertNotIn("chains", payload)

    def test_full_json_stays_available_for_trusted_local_debug(self) -> None:
        payload = _capture_cli(
            [
                "feishu-route",
                "--message",
                "15",
                "--user-role",
                "operator",
                "--trusted-runtime-role",
                "--full-json",
                "--render",
            ]
        )

        self.assertEqual(payload["_exit_code"], 0)
        self.assertEqual(payload["intent"], "runtime_status")
        self.assertNotIn("compact_result", payload)

    def test_truncated_payload_does_not_expose_local_debug_command(self) -> None:
        previous = os.environ.get("HOTEL_OTA_FEISHU_TEXT_LIMIT")
        os.environ["HOTEL_OTA_FEISHU_TEXT_LIMIT"] = "160"
        try:
            result = safe_route_feishu_command(
                "\u5b8c\u6574\u6f14\u793a\u5168\u94fe\u8def",
                role="operator",
                trusted_runtime_role=True,
                render=True,
            )
        finally:
            if previous is None:
                os.environ.pop("HOTEL_OTA_FEISHU_TEXT_LIMIT", None)
            else:
                os.environ["HOTEL_OTA_FEISHU_TEXT_LIMIT"] = previous

        text = result["send_payload"]["text"]
        self.assertIn("详细诊断仅限本地受信维护通道", text)
        self.assertNotIn("--trusted-runtime-role", text)
        self.assertNotIn("--full-json", text)
        self.assertIn("feishu_text_truncated", result["send_payload"]["warnings"])

    def test_route_log_records_compact_output_size_not_full_demo_graph(self) -> None:
        previous = os.environ.get("HOTEL_OTA_FEISHU_ROUTE_LOG")
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            log_path = Path(tmp) / "feishu-route.jsonl"
            os.environ["HOTEL_OTA_FEISHU_ROUTE_LOG"] = str(log_path)
            try:
                safe_route_feishu_command(
                    "\u5b8c\u6574\u6f14\u793a\u5168\u94fe\u8def",
                    role="operator",
                    trusted_runtime_role=True,
                    render=True,
                )
            finally:
                if previous is None:
                    os.environ.pop("HOTEL_OTA_FEISHU_ROUTE_LOG", None)
                else:
                    os.environ["HOTEL_OTA_FEISHU_ROUTE_LOG"] = previous

            record = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])

        self.assertLess(record["output_chars"], 20_000)
        self.assertEqual(record["intent"], "demo_chain_all")


if __name__ == "__main__":
    unittest.main()

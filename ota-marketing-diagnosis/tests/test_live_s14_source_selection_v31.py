from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "s14_feishu_entry.py"


class LiveS14SourceSelectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="s14_live_flow_")
        self.previous_state_dir = os.environ.get("S14_STATE_DIR")
        self.previous_callback_enabled = os.environ.get(
            "S14_FEISHU_CARD_CALLBACK_ENABLED"
        )
        os.environ["S14_STATE_DIR"] = self.tmp.name
        os.environ.pop("S14_FEISHU_CARD_CALLBACK_ENABLED", None)

        spec = importlib.util.spec_from_file_location(
            f"s14_feishu_entry_test_{id(self)}",
            SCRIPT,
        )
        assert spec and spec.loader
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.module.STATE_DIR = Path(self.tmp.name)
        self.module.STATE_DIR.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.previous_state_dir is None:
            os.environ.pop("S14_STATE_DIR", None)
        else:
            os.environ["S14_STATE_DIR"] = self.previous_state_dir
        if self.previous_callback_enabled is None:
            os.environ.pop("S14_FEISHU_CARD_CALLBACK_ENABLED", None)
        else:
            os.environ["S14_FEISHU_CARD_CALLBACK_ENABLED"] = (
                self.previous_callback_enabled
            )
        self.tmp.cleanup()

    def test_trigger_card_defaults_to_typed_choice_without_callback(self) -> None:
        card = self.module._source_selection_card()
        fallback = card["card"]["elements"][1]

        self.assertEqual(fallback["tag"], "div")
        self.assertIn("直接回复", fallback["text"]["content"])
        self.assertNotIn('"tag": "action"', json.dumps(card, ensure_ascii=False))

    def test_trigger_card_adds_buttons_only_when_callback_is_enabled(self) -> None:
        os.environ["S14_FEISHU_CARD_CALLBACK_ENABLED"] = "1"
        card = self.module._source_selection_card()
        actions = card["card"]["elements"][1]["actions"]
        labels = [action["text"]["content"] for action in actions]
        sources = [action["value"]["source"] for action in actions]

        self.assertEqual(labels, ["数据库", "上传Excel"])
        self.assertEqual(sources, ["database", "excel"])
        rendered = str(card)
        self.assertNotIn("携程 / 美团", rendered)
        self.assertNotIn("选择渠道", rendered)

    def test_all_text_variants_use_unified_multi_platform(self) -> None:
        for text in ("S14诊断", "美团诊断", "携程诊断", "多渠道诊断"):
            with self.subTest(text=text):
                context = self.module._request_context(text)
                self.assertEqual(context["platform"], "multi")
                self.assertEqual(context["period_days"], 30)

    def test_excel_wait_state_is_scoped_to_chat_and_sender(self) -> None:
        self.module._set_flow_state(
            "awaiting_excel",
            chat_id="chat-a",
            sender_id="user-a",
        )

        same = self.module._get_flow_state("chat-a", "user-a")
        other_user = self.module._get_flow_state("chat-a", "user-b")
        other_chat = self.module._get_flow_state("chat-b", "user-a")

        self.assertEqual(same["state"], "awaiting_excel")
        self.assertIsNone(other_user)
        self.assertIsNone(other_chat)

    def test_excel_choice_enters_waiting_state_without_running_report(self) -> None:
        payload = self.module._handle_source_choice(
            "excel",
            chat_id="chat-a",
            sender_id="user-a",
            text="上传Excel",
            output_format="card",
        )

        state = self.module._get_flow_state("chat-a", "user-a")
        self.assertEqual(state["state"], "awaiting_excel")
        self.assertEqual(
            payload["card"]["header"]["title"]["content"],
            "S14诊断｜等待Excel附件",
        )

    def test_database_choice_runs_current_report_and_clears_state(self) -> None:
        self.module._set_flow_state(
            "awaiting_source",
            chat_id="chat-a",
            sender_id="user-a",
        )
        fake_result = {
            "feishu_card": {
                "msg_type": "interactive",
                "card": {
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "lark_md",
                                "content": "报告完成",
                            },
                        }
                    ]
                },
            }
        }

        with patch.object(self.module, "_run_database", return_value=fake_result) as run:
            payload = self.module._handle_source_choice(
                "database",
                chat_id="chat-a",
                sender_id="user-a",
                text="数据库",
                output_format="card",
            )

        run.assert_called_once()
        self.assertIsNone(self.module._get_flow_state("chat-a", "user-a"))
        content = payload["card"]["elements"][0]["text"]["content"]
        self.assertEqual(content, "报告完成")

    def test_card_format_does_not_leak_json_without_explicit_raw_opt_in(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [
            str(SCRIPT),
            "--text",
            "S14诊断",
            "--chat-id",
            "chat-safe",
            "--sender-id",
            "user-safe",
            "--format",
            "card",
        ]
        with (
            patch.object(sys, "argv", argv),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(self.module.main(), 0)

        self.assertIn("请选择数据来源，回复：", stdout.getvalue())
        self.assertIn("数据库** — 系统自动拉取数据诊断", stdout.getvalue())
        self.assertIn("上传Excel** — 发送已填好的Excel附件诊断", stdout.getvalue())
        self.assertNotIn("当前报告不再区分渠道", stdout.getvalue())
        self.assertNotIn('"msg_type"', stdout.getvalue())
        self.assertIn("--raw-card-json", stderr.getvalue())

    def test_raw_card_json_requires_explicit_opt_in(self) -> None:
        stdout = io.StringIO()
        argv = [
            str(SCRIPT),
            "--text",
            "S14诊断",
            "--chat-id",
            "chat-raw",
            "--sender-id",
            "user-raw",
            "--format",
            "card",
            "--raw-card-json",
        ]
        with patch.object(sys, "argv", argv), contextlib.redirect_stdout(stdout):
            self.assertEqual(self.module.main(), 0)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertEqual(
            payload["card"]["header"]["title"]["content"],
            "S14诊断｜请选择数据来源",
        )


if __name__ == "__main__":
    unittest.main()

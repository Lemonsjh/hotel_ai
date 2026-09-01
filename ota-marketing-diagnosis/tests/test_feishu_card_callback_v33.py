from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.s14_feishu_card_callback import (
    GENERIC_FAILURE_MESSAGE,
    CardCallbackController,
    outbound_message_parts,
    parse_card_source_action,
)


def callback_payload(
    *,
    source: str = "database",
    action: str = "s14_source",
) -> dict:
    return {
        "header": {"event_id": "evt-1"},
        "event": {
            "operator": {"open_id": "ou-user"},
            "action": {"value": {"action": action, "source": source}},
            "context": {
                "open_chat_id": "oc-chat",
                "open_message_id": "om-card",
            },
        },
    }


class FeishuCardCallbackTest(unittest.TestCase):
    def test_parses_only_supported_s14_source_actions(self) -> None:
        action = parse_card_source_action(callback_payload())
        self.assertIsNotNone(action)
        self.assertEqual(action.chat_id, "oc-chat")
        self.assertEqual(action.sender_id, "ou-user")
        self.assertEqual(action.source, "database")

        self.assertIsNone(
            parse_card_source_action(callback_payload(action="other"))
        )
        self.assertIsNone(
            parse_card_source_action(callback_payload(source="unknown"))
        )

    def test_accepts_callback_and_sends_structured_card_once(self) -> None:
        sent: list[tuple[str, object]] = []
        calls: list[tuple[str, str, str]] = []

        def run_source(source: str, *, chat_id: str, sender_id: str) -> dict:
            calls.append((source, chat_id, sender_id))
            return {
                "msg_type": "interactive",
                "card": {"elements": [{"tag": "div"}]},
            }

        controller = CardCallbackController(
            lambda chat_id, payload: sent.append((chat_id, payload)),
            run_source_choice=run_source,
            submit_background=lambda job: job(),
        )

        status, message = controller.accept(callback_payload())
        duplicate_status, duplicate_message = controller.accept(callback_payload())

        self.assertEqual(status, "accepted")
        self.assertIn("正在生成", message)
        self.assertEqual(duplicate_status, "duplicate")
        self.assertIn("重复点击", duplicate_message)
        self.assertEqual(calls, [("database", "oc-chat", "ou-user")])
        self.assertEqual(len(sent), 1)
        self.assertIsInstance(sent[0][1], dict)

    def test_failure_reply_is_bounded_and_never_contains_exception_text(self) -> None:
        sent: list[object] = []

        def fail(*args, **kwargs):
            raise RuntimeError("SECRET traceback and Python source")

        controller = CardCallbackController(
            lambda chat_id, payload: sent.append(payload),
            run_source_choice=fail,
            submit_background=lambda job: job(),
        )
        with self.assertLogs("s14.feishu.card_callback", level="ERROR"):
            status, _ = controller.accept(callback_payload())

        self.assertEqual(status, "accepted")
        self.assertEqual(sent, [GENERIC_FAILURE_MESSAGE])
        self.assertNotIn("SECRET", sent[0])
        self.assertNotIn("Python", sent[0])

    def test_outbound_card_uses_interactive_content_not_visible_json_text(self) -> None:
        msg_type, content = outbound_message_parts(
            {
                "msg_type": "interactive",
                "card": {
                    "header": {
                        "title": {"tag": "plain_text", "content": "S14诊断"}
                    }
                },
            }
        )

        self.assertEqual(msg_type, "interactive")
        self.assertEqual(json.loads(content)["header"]["title"]["content"], "S14诊断")
        self.assertNotIn('"text": "{', content)

    def test_unexpected_payload_becomes_fixed_plain_text(self) -> None:
        msg_type, content = outbound_message_parts({"unexpected": "source code"})

        self.assertEqual(msg_type, "text")
        self.assertEqual(json.loads(content), {"text": GENERIC_FAILURE_MESSAGE})
        self.assertNotIn("source code", content)


if __name__ == "__main__":
    unittest.main()

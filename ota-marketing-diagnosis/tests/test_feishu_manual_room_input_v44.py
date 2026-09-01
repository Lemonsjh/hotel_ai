from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "s14_feishu_entry.py"
SPEC = importlib.util.spec_from_file_location("s14_feishu_entry_test", SCRIPT_PATH)
assert SPEC and SPEC.loader
ENTRY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENTRY)


class FeishuManualRoomInputTests(unittest.TestCase):
    def test_request_context_passes_manual_names_to_runtime(self):
        context = ENTRY._request_context(
            "S14诊断，房型名称：五人战队套房、电竞双床房",
            manual_room_type_names=["五人战队套房", "电竞双床房"],
            sender_id="user-1",
        )
        self.assertEqual(
            context["manual_room_type_names"],
            ["五人战队套房", "电竞双床房"],
        )
        self.assertEqual(context["manual_input_operator"], "user-1")
        self.assertIn("房型名称", context["request_text"])

    def test_source_card_confirms_saved_room_names(self):
        card = ENTRY._source_selection_card(["五人战队套房", "电竞双床房"])
        content = card["card"]["elements"][0]["text"]["content"]
        self.assertIn("已记录人工房型名称", content)
        self.assertIn("五人战队套房", content)

    def test_manual_text_can_be_saved_before_source_choice(self):
        names = ENTRY._manual_names(
            "房型名称：五人战队套房、电竞双床房",
            {},
        )
        self.assertEqual(names, ["五人战队套房", "电竞双床房"])


if __name__ == "__main__":
    unittest.main()

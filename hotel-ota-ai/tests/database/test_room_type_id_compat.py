from __future__ import annotations

import unittest

from runtime.feishu_command_router import _chat_price_guard_payload


class TestRoomTypeIdCompat(unittest.TestCase):
    def test_room_type_id_preferred_when_explicit_id_is_available(self) -> None:
        payload = _chat_price_guard_payload("房型: KING 底价158 顶价238 最小涨跌幅1% 最大涨跌幅15%")

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["room_type_id"], "KING")
        self.assertEqual(payload.get("room_type_match_quality"), "exact_id")

    def test_room_type_name_fallback_marks_inferred(self) -> None:
        payload = _chat_price_guard_payload("把至臻·电竞大床房底价设为158，顶价238")

        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["room_type_name"], "至臻·电竞大床房")
        self.assertEqual(payload["room_type_match_quality"], "name_fallback")
        self.assertTrue(payload["requires_room_type_confirmation"])
        self.assertTrue(payload["room_type_id"].startswith("NAME_"))
        self.assertEqual(payload["floor_price"], 158.0)
        self.assertEqual(payload["ceiling_price"], 238.0)


if __name__ == "__main__":
    unittest.main()

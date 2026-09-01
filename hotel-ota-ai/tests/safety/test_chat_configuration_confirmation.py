from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.control_plane import (
    cancel_chat_configuration_request,
    confirm_chat_configuration_request,
    create_chat_configuration_request,
    resolve_price_guard_policy,
    verify_audit_chain,
)


class TestChatConfigurationConfirmation(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self._tmp.name) / "chat-control.sqlite")
        self.owner = {
            "principal_id": "owner-1",
            "role": "owner",
            "hotel_ids": ["hotel-a"],
            "resolved_hotel_id": "hotel-a",
            "chat_id": "oc_hotel_a",
            "global_admin": False,
        }
        self.operator = {
            "principal_id": "operator-1",
            "role": "operator",
            "hotel_ids": ["hotel-a"],
            "resolved_hotel_id": "hotel-a",
            "chat_id": "oc_hotel_a",
            "global_admin": False,
        }

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _price_payload() -> dict[str, object]:
        return {
            "room_type_id": "KING",
            "floor_price": 150,
            "ceiling_price": 250,
            "max_increase_pct": 0.2,
            "max_decrease_pct": 0.2,
            "min_increase_pct": 0.05,
            "min_decrease_pct": 0.05,
        }

    def test_owner_request_requires_second_chat_confirmation_before_policy_is_active(self) -> None:
        request = create_chat_configuration_request(
            self.db_path,
            request_kind="price_guard_policy",
            hotel_id="hotel-a",
            requester=self.owner,
            chat_id="oc_hotel_a",
            payload=self._price_payload(),
            expires_at="2026-06-24T10:10:00",
            now="2026-06-24T10:00:00",
        )

        self.assertEqual(request["status"], "pending_confirmation")
        self.assertTrue(request["request_id"].startswith("CFG-"))
        self.assertEqual(
            resolve_price_guard_policy(
                self.db_path,
                hotel_id="hotel-a",
                room_type_id="KING",
                at_time="2026-06-24T10:01:00",
            )["source"],
            "default_policy",
        )

        confirmed = confirm_chat_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.owner,
            chat_id="oc_hotel_a",
            now="2026-06-24T10:01:00",
        )

        self.assertEqual(confirmed["status"], "confirmed")
        self.assertEqual(confirmed["policy"]["max_increase_pct"], 0.2)
        self.assertEqual(
            resolve_price_guard_policy(
                self.db_path,
                hotel_id="hotel-a",
                room_type_id="KING",
                at_time="2026-06-24T10:02:00",
            )["source"],
            "active_price_guard_policy",
        )
        self.assertTrue(verify_audit_chain(self.db_path, "hotel-a")["valid"])

    def test_operator_cannot_initiate_config_request_and_wrong_chat_confirm_rejected(self) -> None:
        # 2.8 收紧:operator 不再能发起配置请求(_chat_requester_allowed 仅 admin/owner)。
        blocked = create_chat_configuration_request(
            self.db_path,
            request_kind="price_guard_policy",
            hotel_id="hotel-a",
            requester=self.operator,
            chat_id="oc_hotel_a",
            payload=self._price_payload(),
            expires_at="2026-06-24T10:10:00",
            now="2026-06-24T10:00:00",
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason"], "configuration_request_not_authorized")

        # 保留覆盖:owner 发起的请求,从错误 chat 确认应被拒(chat_mismatch)。
        request = create_chat_configuration_request(
            self.db_path,
            request_kind="price_guard_policy",
            hotel_id="hotel-a",
            requester=self.owner,
            chat_id="oc_hotel_a",
            payload=self._price_payload(),
            expires_at="2026-06-24T10:10:00",
            now="2026-06-24T10:00:00",
        )
        self.assertEqual(request["status"], "pending_confirmation")

        wrong_chat = confirm_chat_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.owner,
            chat_id="oc_other",
            now="2026-06-24T10:01:00",
        )
        self.assertEqual(wrong_chat["status"], "blocked")
        self.assertEqual(wrong_chat["reason"], "configuration_request_chat_mismatch")

        confirmed = confirm_chat_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.owner,
            chat_id="oc_hotel_a",
            now="2026-06-24T10:02:00",
        )
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertTrue(verify_audit_chain(self.db_path, "hotel-a")["valid"])

    def test_cancelled_or_replayed_chat_confirmation_never_applies_policy(self) -> None:
        request = create_chat_configuration_request(
            self.db_path,
            request_kind="price_guard_policy",
            hotel_id="hotel-a",
            requester=self.owner,
            chat_id="oc_hotel_a",
            payload=self._price_payload(),
            expires_at="2026-06-24T10:10:00",
            now="2026-06-24T10:00:00",
        )
        cancelled = cancel_chat_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.owner,
            chat_id="oc_hotel_a",
            now="2026-06-24T10:01:00",
        )
        self.assertEqual(cancelled["status"], "cancelled")

        replay = confirm_chat_configuration_request(
            self.db_path,
            request_id=request["request_id"],
            actor=self.owner,
            chat_id="oc_hotel_a",
            now="2026-06-24T10:02:00",
        )
        self.assertEqual(replay["status"], "blocked")
        self.assertEqual(replay["reason"], "configuration_request_not_pending")
        self.assertEqual(
            resolve_price_guard_policy(
                self.db_path,
                hotel_id="hotel-a",
                room_type_id="KING",
                at_time="2026-06-24T10:02:00",
            )["source"],
            "default_policy",
        )


if __name__ == "__main__":
    unittest.main()

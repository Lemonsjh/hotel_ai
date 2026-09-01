from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from runtime.control_plane import confirm_chat_role_change_request, create_chat_role_change_request
from runtime.safety.auth import bootstrap_active_auth, build_auth_context
from runtime.storage import connect


class TestHotelRoleScope(unittest.TestCase):
    def _bootstrap(self, root: Path) -> tuple[str, str]:
        db_path = str(root / "auth.sqlite")
        config_path = root / "auth.json"
        config_path.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": [],
                    "users": [
                        {"principal_id": "owner-1", "open_id": "ou_owner"},
                        {"principal_id": "target-1", "open_id": "ou_target"},
                    ],
                    "hotel_memberships": [
                        {"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"}
                    ],
                    "group_chat_bindings": [
                        {"chat_id": "oc_group_a", "hotel_id": "hotel-a"},
                        {"chat_id": "oc_group_b", "hotel_id": "hotel-a"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(db_path, config_path=str(config_path))
        return db_path, str(config_path)

    def test_role_granted_in_one_group_applies_to_all_groups_bound_to_hotel(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path, config_path = self._bootstrap(Path(tmp))
            actor = {
                "principal_id": "owner-1",
                "role": "owner",
                "hotel_ids": ["hotel-a"],
                "resolved_hotel_id": "hotel-a",
                "global_admin": False,
            }
            request = create_chat_role_change_request(
                db_path,
                hotel_id="hotel-a",
                chat_id="oc_group_a",
                requester=actor,
                target_principal_id="target-1",
                requested_role="operator",
                operation="grant",
                now="2026-08-07T09:00:00",
            )
            self.assertEqual(request["status"], "pending_confirmation")
            confirmed = confirm_chat_role_change_request(
                db_path,
                request_id=request["request_id"],
                actor=actor,
                chat_id="oc_group_a",
                now="2026-08-07T09:01:00",
            )
            self.assertEqual(confirmed["status"], "confirmed")

            group_a = build_auth_context(
                source="feishu",
                chat_id="oc_group_a",
                chat_type="group",
                open_id="ou_target",
                config_path=config_path,
                auth_db_path=db_path,
            )
            group_b = build_auth_context(
                source="feishu",
                chat_id="oc_group_b",
                chat_type="group",
                open_id="ou_target",
                config_path=config_path,
                auth_db_path=db_path,
            )

        self.assertEqual(group_a["auth_status"], "authorized")
        self.assertEqual(group_b["auth_status"], "authorized")
        self.assertEqual(group_a["user_role"], "operator")
        self.assertEqual(group_b["user_role"], "operator")

    def test_role_change_writes_only_hotel_memberships(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path, _ = self._bootstrap(Path(tmp))
            actor = {
                "principal_id": "owner-1",
                "role": "owner",
                "hotel_ids": ["hotel-a"],
                "resolved_hotel_id": "hotel-a",
                "global_admin": False,
            }
            request = create_chat_role_change_request(
                db_path,
                hotel_id="hotel-a",
                chat_id="oc_group_a",
                requester=actor,
                target_principal_id="target-1",
                requested_role="frontdesk",
                operation="grant",
                now="2026-08-07T09:00:00",
            )
            confirmed = confirm_chat_role_change_request(
                db_path,
                request_id=request["request_id"],
                actor=actor,
                chat_id="oc_group_a",
                now="2026-08-07T09:01:00",
            )
            self.assertEqual(confirmed["status"], "confirmed")
            with closing(connect(db_path)) as conn:
                row = conn.execute(
                    "SELECT role, status FROM hotel_memberships WHERE principal_id='target-1' AND hotel_id='hotel-a'"
                ).fetchone()
                legacy = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_role_memberships'"
                ).fetchone()

        self.assertEqual(dict(row), {"role": "frontdesk", "status": "active"})
        self.assertIsNone(legacy)


if __name__ == "__main__":
    unittest.main()

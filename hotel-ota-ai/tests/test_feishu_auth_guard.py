from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.safety.auth import bootstrap_active_auth
from runtime.safety.feishu_auth_guard import evaluate_feishu_auth_guard


class FeishuAuthGuardTest(unittest.TestCase):
    def _seed_auth(self) -> tuple[str, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        db_path = str(root / "hotel_ops.sqlite")
        config_path = root / "role-map.json"
        config_path.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": [],
                    "users": [
                        {
                            "principal_id": "p-operator",
                            "open_id": "ou_authorized",
                            "display_name": "Operator",
                        }
                    ],
                    "hotel_memberships": [
                        {"principal_id": "p-operator", "hotel_id": "puyue-demo", "role": "operator"}
                    ],
                    "group_chat_bindings": [
                        {"chat_id": "oc_authorized_chat", "hotel_id": "puyue-demo", "chat_type": "group"}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(db_path, config_path=str(config_path))
        return db_path, str(config_path)

    def test_authorized_bound_group_can_continue(self) -> None:
        db_path, config_path = self._seed_auth()
        result = evaluate_feishu_auth_guard(
            db_path=db_path,
            auth_config=config_path,
            chat_id="oc_authorized_chat",
            chat_type="group",
            user_id=None,
            open_id="ou_authorized",
            union_id=None,
            hotel_id=None,
            action="view_diagnosis",
        )
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["should_continue"])
        self.assertEqual(result["resolved_hotel_id"], "puyue-demo")
        self.assertEqual(result["user_role"], "operator")

    def test_unknown_sender_is_fail_closed(self) -> None:
        db_path, config_path = self._seed_auth()
        result = evaluate_feishu_auth_guard(
            db_path=db_path,
            auth_config=config_path,
            chat_id="oc_authorized_chat",
            chat_type="group",
            user_id=None,
            open_id="ou_unknown",
            union_id=None,
            hotel_id=None,
            action="view_diagnosis",
        )
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["should_continue"])
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["reason"], "sqlite_principal_not_found")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.control_plane import _chat_hash, build_tenant_management_read_model
from runtime.feishu_command_router import route_feishu_command
from runtime.feishu_output_renderer import build_feishu_send_payload, render_feishu_output
from runtime.storage import connect, init_schema


class ProductionFeishuRegressionsTests(unittest.TestCase):
    def test_identity_copy_stays_separate_from_data_source_status(self) -> None:
        rendered = render_feishu_output(
            {
                "intent": "identity",
                "personal_role": "admin",
                "auth_backend": "sqlite_active_auth",
                "auth_status": "ok",
                "tenant_status": "bound",
                "chat_type": "group",
                "chat_bound": True,
                "resolved_hotel_id": "puyue",
            },
            "owner_business",
        )

        text = rendered["text"]
        self.assertNotIn("demo", text.lower())
        self.assertNotIn("sample", text.lower())
        self.assertNotIn("MySQL", text)

    def test_current_chat_role_view_does_not_include_other_chat_members_or_raw_open_ids(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "auth.sqlite")
            with connect(db_path) as conn:
                with conn:
                    init_schema(conn)
                    conn.execute(
                        "INSERT INTO chat_role_memberships (chat_id_hash, principal_id, hotel_id, role, status, created_at, updated_at) VALUES (?, 'owner-a', 'puyue', 'owner', 'active', '2026-07-03', '2026-07-03')",
                        (_chat_hash("oc_current"),),
                    )
                    conn.execute(
                        "INSERT INTO chat_role_memberships (chat_id_hash, principal_id, hotel_id, role, status, created_at, updated_at) VALUES ('chat-b', 'owner-b', 'puyue', 'owner', 'active', '2026-07-03', '2026-07-03')"
                    )

            result = build_tenant_management_read_model(db_path, hotel_id="puyue", chat_id="oc_current")

        text = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["role_scope"], "current_chat")
        self.assertEqual(result["member_role_counts"]["owner"], 1)
        self.assertNotIn("owner-b", text)
        self.assertNotIn("ou_", text)

    def test_third_party_report_route_returns_migrated_notice(self) -> None:
        result = route_feishu_command("第三方OTA诊断报告", role="owner", render=True)

        self.assertEqual(result["intent"], "third_party_report_preview")
        self.assertEqual(result["blocked_reason"], "s14_ext_migrated_to_independent_service")
        self.assertIn("第三方营销诊断已迁移", result["send_payload"]["text"])

    def test_footer_is_allowed_but_raw_open_id_is_not(self) -> None:
        footer = render_feishu_output(
            {"intent": "runtime_status", "status": "ok", "summary": "Agent: a\nModel: b\nProvider: c"},
            "owner_business",
        )
        self.assertIn("Agent:", footer["text"])

        unsafe = build_feishu_send_payload(
            {"intent": "runtime_status", "status": "ok", "summary": "open_id=ou_sensitive"},
            role="admin",
        )
        self.assertNotIn("ou_sensitive", unsafe["text"])


if __name__ == "__main__":
    unittest.main()

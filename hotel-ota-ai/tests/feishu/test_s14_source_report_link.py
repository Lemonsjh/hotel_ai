from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth
from tests.s14.test_s14_report_url import write_minimal_s14_xlsx


class TestS14SourceReportLink(unittest.TestCase):
    def test_registered_excel_source_renders_clickable_report_url_without_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = str(root / "auth.sqlite")
            excel = root / "monthly.xlsx"
            reports = root / "reports"
            role_map = root / "role-map.json"
            source_config = root / "s14-source.json"
            write_minimal_s14_xlsx(excel)
            role_map.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "direct_message_policy": "role_mapped_users_only",
                        "global_admin_principal_ids": [],
                        "users": [{"principal_id": "owner-1", "open_id": "ou_owner", "display_name": "owner"}],
                        "hotel_memberships": [{"principal_id": "owner-1", "hotel_id": "hotel-a", "role": "owner"}],
                        "group_chat_bindings": [{"chat_id": "oc_hotel_a", "hotel_id": "hotel-a"}],
                    }
                ),
                encoding="utf-8",
            )
            source_config.write_text(
                json.dumps(
                    {
                        "hotels": {
                            "hotel-a": {
                                "s14_sources": {
                                    "monthly_excel": {
                                        "enabled": True,
                                        "source_mode": "excel",
                                        "path": str(excel),
                                    }
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            bootstrap_active_auth(db_path, config_path=str(role_map))
            old_dir = os.environ.get("HOTEL_OTA_S14_REPORT_DIR")
            old_base = os.environ.get("HOTEL_OTA_S14_REPORT_BASE_URL")
            os.environ["HOTEL_OTA_S14_REPORT_DIR"] = str(reports)
            os.environ["HOTEL_OTA_S14_REPORT_BASE_URL"] = "https://reports.example.com/reports"
            try:
                result = safe_route_feishu_command(
                    "s14 source=monthly_excel",
                    db_path=db_path,
                    chat_id="oc_hotel_a",
                    chat_type="group",
                    open_id="ou_owner",
                    auth_config=str(role_map),
                    s14_source_config=str(source_config),
                    production_feishu=True,
                    render=True,
                )
            finally:
                if old_dir is None:
                    os.environ.pop("HOTEL_OTA_S14_REPORT_DIR", None)
                else:
                    os.environ["HOTEL_OTA_S14_REPORT_DIR"] = old_dir
                if old_base is None:
                    os.environ.pop("HOTEL_OTA_S14_REPORT_BASE_URL", None)
                else:
                    os.environ["HOTEL_OTA_S14_REPORT_BASE_URL"] = old_base

        text = result["send_payload"]["text"]
        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["blocked_reason"], "s14_ext_migrated_to_independent_service")
        self.assertIn("第三方营销诊断已迁移到独立服务", text)
        self.assertNotIn("https://reports.example.com/reports/hotel-a/ota_diagnosis_report.html", text)
        self.assertNotIn(str(reports), text)
        self.assertNotIn("report_local_path", text)
        self.assertNotIn("html_report_path", text)
        self.assertNotIn("DSN", text)
        self.assertNotIn("token", text.lower())
        self.assertFalse(result["live_allowed"])
        self.assertFalse(result["business_result_generated"])


if __name__ == "__main__":
    unittest.main()

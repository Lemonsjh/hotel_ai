from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.adapters.database import TEMPLATES, V4_TEMPLATE_TABLE_KEYS
from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth


class TestMeituanReviewDetailIngestion(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        root = Path(self._tmp.name)
        self.db_path = str(root / "auth.sqlite")
        self.auth_config = root / "role-map.json"
        self.auth_config.write_text(
            json.dumps(
                {
                    "version": 3,
                    "direct_message_policy": "role_mapped_users_only",
                    "global_admin_principal_ids": ["owner-1"],
                    "users": [{"principal_id": "owner-1", "open_id": "test-owner-open"}],
                    "hotel_memberships": [{"principal_id": "owner-1", "hotel_id": "xingfeng", "role": "owner"}],
                    "group_chat_bindings": [{"chat_id": "chat-xingfeng", "hotel_id": "xingfeng"}],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        bootstrap_active_auth(self.db_path, config_path=str(self.auth_config))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_review_detail_template_is_registered_without_task_tables(self) -> None:
        self.assertIn("ota_review_detail", TEMPLATES)
        self.assertEqual(V4_TEMPLATE_TABLE_KEYS["ota_review_detail"], ("meituan_review_detail",))

    def test_review_draft_generated_for_negative_unreplied_review(self) -> None:
        db_payload = {
            "status": "ok",
            "payload": {
                "rows": [
                    {
                        "hotel_id": "xingfeng",
                        "channel_source": "meituan",
                        "poi_id": "poi-1",
                        "review_id": "10103927050",
                        "review_score": 2.0,
                        "review_content": "卫生和设施都不太满意，晚上也有点吵。",
                        "review_time": "2026-06-25 10:31:18",
                        "is_replied": 0,
                        "is_negative_review": 1,
                        "room_type_name": "至臻·电竞大床房",
                    }
                ]
            },
        }

        with mock.patch("runtime.feishu_command_router.database_template_result", return_value=db_payload) as query:
            result = safe_route_feishu_command(
                "生成待回复评论草稿",
                db_path=self.db_path,
                chat_id="chat-xingfeng",
                chat_type="group",
                open_id="test-owner-open",
                auth_config=str(self.auth_config),
                production_feishu=True,
                render=True,
            )

        query.assert_called_once_with("ota_review_detail", "xingfeng")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["review_draft_generated"])
        self.assertFalse(result["review_publish_attempted"])
        text = result["send_payload"]["text"]
        self.assertIn("评论回复草稿", text)
        self.assertIn("当前阶段仅生成草稿", text)
        self.assertIn("未执行发布", text)
        self.assertNotIn("已发布", text)
        self.assertNotIn("审批已创建", text)


if __name__ == "__main__":
    unittest.main()

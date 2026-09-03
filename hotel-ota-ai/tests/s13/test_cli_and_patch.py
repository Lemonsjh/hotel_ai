from __future__ import annotations

import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.s13.cli import run_s13_cli
from runtime.s13.feishu import _render, _service
from runtime.s13.source import MemoryReviewSourceRepository
from runtime.s13.source import MySQLReviewSourceRepository
from runtime.s13.task_outbox import SQLiteReviewTaskOutbox
from runtime.s13_runtime_patch import _patch_auth


class CliAndPatchTests(unittest.TestCase):
    def test_s13_data_gap_text_does_not_expose_internal_configuration(self) -> None:
        self.assertEqual(
            _render(
                {
                    "status": "data_gap",
                    "action": "list_pending",
                    "blocked_reason": "s13_source_dsn_not_configured",
                }
            ),
            "评论明细暂不可用，当前不能列出未回复评论或生成回复草稿。",
        )

    def test_s13_source_uses_hotel_scoped_s12_read_source(self) -> None:
        with (
            patch(
                "runtime.adapters.database.resolve_hotel_dsn",
                return_value="mysql://reader:pwd@db/reviews",
            ) as resolve_dsn,
            patch.object(MySQLReviewSourceRepository, "__init__", return_value=None) as init,
        ):
            MySQLReviewSourceRepository.from_env(hotel_id="hotel-a")

        self.assertEqual(
            resolve_dsn.call_args_list,
            [
                unittest.mock.call("hotel-a", "HOTEL_OTA_S12_SOURCE_DSN"),
            ],
        )
        init.assert_called_once_with("mysql://reader:pwd@db/reviews")

    def test_feishu_s13_uses_local_reply_task_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch(
            "runtime.s13.feishu.MySQLReviewSourceRepository.from_env",
            return_value=MemoryReviewSourceRepository([]),
        ):
            service = _service(str(Path(tmp) / "control.sqlite"), hotel_id="hotel-a")

        self.assertIsInstance(service.outbox, SQLiteReviewTaskOutbox)

    def test_cli_list_and_draft_use_opaque_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "reviews.json"
            fixture.write_text(
                json.dumps(
                    {
                        "reviews": [
                            {
                                "hotel_id": "hotel-a",
                                "platform": "meituan",
                                "review_id": "physical-1",
                                "review_content": None,
                                "star_rating": 5,
                                "is_replied": False,
                                "source_snapshot": "2026-08-03T15:00:00+08:00"
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            db = str(root / "control.sqlite")
            task = str(root / "task.sqlite")
            common = [
                "--db", db,
                "review-reply-list",
                "--hotel-id", "hotel-a",
                "--principal-role", "owner",
                "--principal-ref", "owner-1",
                "--as-of", "2026-08-03T16:00:00+08:00",
                "--source-fixture", str(fixture),
                "--task-sqlite", task,
            ]
            listed = run_s13_cli(common)
            ref = listed["items"][0]["review_ref"]
            drafted = run_s13_cli(
                [
                    "--db", db,
                    "review-reply-draft",
                    "--hotel-id", "hotel-a",
                    "--principal-role", "owner",
                    "--principal-ref", "owner-1",
                    "--as-of", "2026-08-03T16:00:00+08:00",
                    "--source-fixture", str(fixture),
                    "--task-sqlite", task,
                    "--review-ref", ref,
                ]
            )
            self.assertEqual(drafted["status"], "ok")
            self.assertEqual(drafted["draft_candidate"]["candidate_origin"], "deterministic_candidate")

    def test_s13_auth_patch_adds_viewer_and_grants_s13_to_admin(self) -> None:
        module = types.SimpleNamespace(
            ROLES=("admin", "owner", "operator", "frontdesk", "guest"),
            TENANT_MEMBER_ROLES=("owner", "operator", "frontdesk"),
            PERMISSIONS_BY_ROLE={
                "admin": {"execute_live_action"},
                "owner": set(),
                "operator": set(),
                "frontdesk": set(),
                "guest": set(),
            },
            ACTION_TO_PERMISSION={},
        )
        _patch_auth(module)
        self.assertIn("viewer", module.ROLES)
        self.assertIn("viewer", module.TENANT_MEMBER_ROLES)
        self.assertIn("review_reply_confirm", module.PERMISSIONS_BY_ROLE["admin"])
        self.assertIn("review_reply_confirm", module.PERMISSIONS_BY_ROLE["owner"])
        self.assertIn("review_reply_confirm", module.PERMISSIONS_BY_ROLE["operator"])
        self.assertEqual(module.PERMISSIONS_BY_ROLE["viewer"], set())


if __name__ == "__main__":
    unittest.main()

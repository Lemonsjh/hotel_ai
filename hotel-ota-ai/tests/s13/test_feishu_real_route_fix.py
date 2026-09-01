from __future__ import annotations

import types
import unittest
from unittest.mock import patch

from runtime.s13_feishu_route_fix_patch import _patch_router


class _FakeS13Service:
    def list_pending(self, context, *, limit=50):  # type: ignore[no-untyped-def]
        assert context.hotel_id == "puyue"
        assert context.principal_role == "owner"
        assert context.principal_ref == "principal-owner"
        return {
            "status": "ok",
            "action": "list_pending",
            "items": [
                {
                    "review_ref": "REV-real-review",
                    "platform": "meituan",
                    "star_rating": 5,
                    "review_content_present": True,
                    "redacted_excerpt": "真实评论",
                }
            ],
            "count": 1,
        }


class FeishuRealRouteFixTests(unittest.TestCase):
    def test_generic_review_reply_overrides_legacy_n017_demo(self) -> None:
        fake_router = types.SimpleNamespace(
            __name__="runtime.feishu_command_router",
            route_feishu_command=lambda message, *args, **kwargs: {
                "status": "preview_only",
                "intent": "review_reply_draft",
                "runtime_command": "--demo demo-node --node N017",
                "demo_dataset_id": "legacy-demo",
                "draft_preview_allowed": True,
                "auth_role": "owner",
                "resolved_hotel_id": "puyue",
            },
        )
        _patch_router(fake_router)

        trusted = {
            "auth_status": "authorized",
            "principal_id": "principal-owner",
            "user_role": "owner",
            "resolved_hotel_id": "puyue",
            "auth_backend": "sqlite_active",
            "tenant_status": "resolved",
        }
        with (
            patch(
                "runtime.s13_feishu_route_fix_patch._trusted_auth_context",
                return_value=trusted,
            ),
            patch("runtime.s13.feishu._service", return_value=_FakeS13Service()),
        ):
            result = fake_router.route_feishu_command(
                "评论回复",
                role="owner",
                db_path="control.sqlite",
                hotel_id="puyue",
                chat_id="oc-trusted",
                open_id="ou-trusted",
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["skill_id"], "S13")
        self.assertEqual(result["intent"], "review_reply")
        self.assertEqual(result["action"], "list_pending")
        self.assertEqual(result["items"][0]["review_ref"], "REV-real-review")
        self.assertNotIn("demo_dataset_id", result)
        self.assertNotIn("draft_preview_allowed", result)
        self.assertNotIn("--demo", str(result.get("runtime_command") or ""))

    def test_auth_block_is_not_bypassed_without_trusted_principal(self) -> None:
        blocked = {
            "status": "blocked",
            "intent": "review_reply_draft",
            "blocked_reason": "missing_feishu_identity",
        }
        fake_router = types.SimpleNamespace(
            __name__="runtime.feishu_command_router",
            route_feishu_command=lambda message, *args, **kwargs: dict(blocked),
        )
        _patch_router(fake_router)

        with patch(
            "runtime.s13_feishu_route_fix_patch._trusted_auth_context",
            return_value={},
        ):
            result = fake_router.route_feishu_command("评论回复")

        self.assertEqual(result, blocked)


if __name__ == "__main__":
    unittest.main()

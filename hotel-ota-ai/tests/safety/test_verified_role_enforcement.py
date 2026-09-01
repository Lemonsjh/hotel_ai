from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.safety.auth import build_auth_context


class TestVerifiedRoleEnforcement(unittest.TestCase):
    @mock.patch.dict(os.environ, {"HOTEL_OTA_REQUIRE_VERIFIED_ROLE": "1"}, clear=False)
    def test_self_declared_role_rejected_in_production(self) -> None:
        # flag=1 下,非 feishu 源的自报 --user-role 不得被信任 → 降级 guest。
        context = build_auth_context(source="manual_test", user_role="owner")

        self.assertEqual(context["user_role"], "guest")
        self.assertEqual(context["auth_status"], "unauthorized")
        self.assertEqual(context["reason"], "verified_identity_required")

    @mock.patch.dict(os.environ, {"HOTEL_OTA_REQUIRE_VERIFIED_ROLE": "1"}, clear=False)
    def test_cli_and_cron_self_declared_role_also_rejected(self) -> None:
        # 堵新口子:agent 改传 --auth-source cron/cli 冒充也一律降级 guest。
        for source in ("cron", "cli"):
            with self.subTest(source=source):
                context = build_auth_context(source=source, user_role="owner")
                self.assertEqual(context["user_role"], "guest")
                self.assertEqual(context["reason"], "verified_identity_required")

    @mock.patch.dict(os.environ, {"HOTEL_OTA_REQUIRE_VERIFIED_ROLE": "1"}, clear=False)
    def test_feishu_identity_resolution_not_affected_by_flag(self) -> None:
        # flag=1 不得误伤 feishu 源:身份匹配的真实角色仍正常解析(非 guest)。
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            auth_path = Path(tmp) / "feishu-role-map.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "allowed_chat_ids": ["oc_allowed"],
                        "users": [{"role": "admin", "open_id": "ou_admin", "feishu_open_id": "ou_admin"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            context = build_auth_context(
                source="feishu",
                open_id="ou_admin",
                chat_id="oc_allowed",
                config_path=str(auth_path),
                user_role="owner",  # 自报角色应被 feishu 路径忽略,以身份解析为准
            )

        self.assertEqual(context["user_role"], "admin")
        self.assertNotEqual(context["reason"], "verified_identity_required")

    def test_flag_off_keeps_existing_self_declared_role_behavior(self) -> None:
        # 默认(flag 未设/为 0):保持现状,自报角色仍生效,不破坏既有测试/dev。
        with mock.patch.dict(os.environ, {"HOTEL_OTA_REQUIRE_VERIFIED_ROLE": "0"}, clear=False):
            context = build_auth_context(source="manual_test", user_role="owner")
        self.assertEqual(context["user_role"], "owner")

    @mock.patch.dict(os.environ, {"HOTEL_OTA_REQUIRE_VERIFIED_ROLE": "1"}, clear=False)
    def test_spoofed_role_denied_end_to_end_through_permission_gate(self) -> None:
        # 端到端:flag=1 下,冒充 owner 的 manual_test 上下文经 permission_gate 被拒。
        from runtime.safety.auth import permission_gate

        auth_context = build_auth_context(source="manual_test", user_role="owner")
        gate = permission_gate(auth_context, "price_update")
        self.assertFalse(gate["allowed"])


class TestEnvCheckVerifiedRole(unittest.TestCase):
    def _run_env_check(self, extra_env: dict[str, str]) -> dict:
        import io

        from runtime.cli import main

        base = {"HOTEL_OTA_ENV": "production"}
        base.update(extra_env)
        buffer = io.StringIO()
        with mock.patch.dict(os.environ, base, clear=True):
            with contextlib.redirect_stdout(buffer):
                main(["env-check"])
        return json.loads(buffer.getvalue())

    def test_production_without_verified_role_flag_is_flagged(self) -> None:
        result = self._run_env_check({})
        self.assertIn("verified_role_not_enforced", result["must_fix_before_commercial"])

    def test_production_with_verified_role_flag_not_flagged(self) -> None:
        result = self._run_env_check({"HOTEL_OTA_REQUIRE_VERIFIED_ROLE": "1"})
        self.assertNotIn("verified_role_not_enforced", result["must_fix_before_commercial"])


if __name__ == "__main__":
    unittest.main()



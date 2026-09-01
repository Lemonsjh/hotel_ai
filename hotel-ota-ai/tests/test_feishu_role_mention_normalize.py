"""Regression tests: Feishu mention markup + whitespace in named role requests.

Ensures messages like "将<at ...>杨毅</at> 的角色设为老板" resolve the target
directly without agent-side normalization, and that other command formats are
untouched.
"""

from __future__ import annotations

import os
import shutil
import tempfile

from runtime.feishu_calendar_scope_patch import install as _install_calendar_patch
from runtime.feishu_role_command_patch import install as _install_role_patch
from runtime.feishu_command_router import safe_route_feishu_command

_install_calendar_patch()
_install_role_patch()

SRC_DB = os.environ.get("HOTEL_OTA_DB", "/var/lib/hotel-ota-ai/hotel_ops.sqlite")
ACCOUNT_ID = "wyn-ota-ai"
CHAT_ID = "oc_8fef10cf5759f058824b7ef69e041706"
OPEN_ID = "ou_17f3227f70b88d12c7c2632128ca9cc8"  # wyn owner


def _route(message: str, member_info: list[dict], db_path: str) -> dict:
    return safe_route_feishu_command(
        message,
        role="guest",
        db_path=db_path,
        render=False,
        hotel_id=None,
        account_id=ACCOUNT_ID,
        chat_id=CHAT_ID,
        chat_type="group",
        open_id=OPEN_ID,
        auth_config=None,
        member_info=member_info,
        production_feishu=True,
        compact=False,
    )


def test_raw_mention_message_creates_request() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "hotel_ops.sqlite")
        shutil.copy(SRC_DB, db_path)
        raw = '将<at user_id="ou_mention_test_001">王测试</at> 的角色设为运营'
        result = _route(
            raw,
            [{"name": "王测试", "open_id": "ou_mention_test_001"}],
            db_path,
        )
        assert result.get("intent") == "chat_role_named_request", result
        assert result.get("status") == "pending_confirmation", result
        assert result.get("requested_role") == "operator", result
        assert result.get("operation") == "grant", result
        assert result.get("request_id", "").startswith("ROLE-"), result


def test_already_member_returns_already_member() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "hotel_ops.sqlite")
        shutil.copy(SRC_DB, db_path)
        # 杨毅 is already an owner in the source DB (if seeded); route must not error
        raw = '将<at user_id="ou_05c722690e45411511d140b328f4c61c">杨毅</at> 的角色设为老板'
        result = _route(
            raw,
            [{"name": "杨毅", "open_id": "ou_05c722690e45411511d140b328f4c61c"}],
            db_path,
        )
        assert result.get("intent") == "chat_role_named_request", result
        assert result.get("status") in {"pending_confirmation", "already_member"}, result


def test_direct_grant_format_untouched() -> None:
    from runtime import feishu_command_router as router

    assert router._chat_role_named_payload("授予 ou_12345 为 老板") is None
    assert router._chat_role_named_payload("撤销 ou_12345 为 运营") is None


def test_revoke_mention_phrasing_still_parses() -> None:
    from runtime.feishu_role_command_patch import parse_named_role_revoke

    payload = parse_named_role_revoke('将<at user_id="ou_x">杨毅</at> 的角色撤销')
    assert payload is not None
    assert payload["operation"] == "revoke"
    assert payload["role"] == "__current_hotel_role__"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {exc!r}")
    print("failures =", failures)
    raise SystemExit(1 if failures else 0)

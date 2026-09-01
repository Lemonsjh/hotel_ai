from __future__ import annotations

from runtime.safety.auth import PERMISSIONS_BY_ROLE


def test_owner_can_manage_hotel_roles() -> None:
    assert "manage_roles" in PERMISSIONS_BY_ROLE["owner"]


def test_owner_does_not_gain_admin_only_safety_permissions() -> None:
    assert "manage_safety_config" not in PERMISSIONS_BY_ROLE["owner"]
    assert "execute_live_action" not in PERMISSIONS_BY_ROLE["owner"]
    assert "manage_safety_config" in PERMISSIONS_BY_ROLE["admin"]

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestGatewayNonrootMigration(unittest.TestCase):
    def test_hardened_dropin_has_nonroot_and_systemd_boundaries(self) -> None:
        dropin = ROOT / "ops" / "systemd" / "openclaw-gateway-nonroot.override.conf.example"
        text = dropin.read_text(encoding="utf-8")

        for expected in [
            "User=openclaw",
            "Group=openclaw",
            "NoNewPrivileges=true",
            "ProtectSystem=strict",
            "CapabilityBoundingSet=",
            "UMask=0077",
        ]:
            self.assertIn(expected, text)
        self.assertNotIn("ReadWritePaths=/etc/hotel-ota-ai", text)

    def test_preflight_is_read_only_and_documents_required_access(self) -> None:
        preflight = ROOT / "ops" / "gateway-nonroot-preflight.sh"
        text = preflight.read_text(encoding="utf-8")

        self.assertIn("--dry-run", text)
        self.assertIn("/etc/hotel-ota-ai/feishu-role-map.json", text)
        self.assertNotIn("systemctl restart", text)
        self.assertNotIn("useradd", text)

    def test_role_map_apply_contract_is_separate_from_gateway(self) -> None:
        document = ROOT / "ops" / "role-map-apply-helper.md"
        text = document.read_text(encoding="utf-8")

        self.assertIn("root-owned", text)
        self.assertIn("atomic rename", text)
        self.assertIn("Gateway MUST NOT write", text)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class TestRuntimeManifestBoundaries(unittest.TestCase):
    def test_runtime_manifest_required_files_exist(self) -> None:
        manifest = load_json(ROOT / "manifests" / "runtime_manifest.yaml")

        for file_name in manifest["runtime_required"]["root_files"]:
            self.assertTrue((ROOT / file_name).exists(), file_name)
        for directory in manifest["runtime_required"]["directories"]:
            self.assertTrue((ROOT / directory).is_dir(), directory)
        for file_name in manifest["runtime_required_architecture_files"]:
            self.assertTrue((ROOT / file_name).exists(), file_name)
        for file_name in manifest["runtime_required_contract_files"]:
            self.assertTrue((ROOT / file_name).exists(), file_name)

    def test_runtime_manifest_uses_v27_contract_sources(self) -> None:
        manifest = load_json(ROOT / "manifests" / "runtime_manifest.yaml")

        required_contracts = set(manifest["runtime_required_contract_files"])
        for expected in {
            "contracts/v27/contract.json",
            "contracts/v27/field_registry.yaml",
            "contracts/v27/node_io_contract.yaml",
            "contracts/v27/skill_io_contract.yaml",
            "contracts/v27/edge_payload_contract.yaml",
            "contracts/v27/scenario_chain_contract.yaml",
            "contracts/v27/source_alias_mapping.yaml",
            "contracts/v27/data_gap_impact_matrix.yaml",
        }:
            self.assertIn(expected, required_contracts)

        self.assertNotIn("contracts/field_registry.yaml", required_contracts)
        self.assertNotIn("contracts/node_io_contract.yaml", required_contracts)

        required_skill_files = set(manifest["runtime_required_skill_files"])
        self.assertIn("skills/hotel-ota/**/references/v27_alignment.json", required_skill_files)
        self.assertNotIn("skills/hotel-ota/**/references/v20_alignment.json", required_skill_files)
        self.assertIn("skills/hotel-ota/**/references/v20_alignment.json", manifest["legacy_skill_reference_files"])

    def test_agents_declares_v27_contract_precedence(self) -> None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        self.assertIn("contracts/v27/contract.json", text)
        self.assertIn("如 `architecture/` registry 与 `contracts/v27/contract.json` 冲突", text)
        self.assertNotIn("以 `architecture/` 下 V26 注册文件为准", text)

    def test_deploy_manifest_excludes_dev_source_and_private_config(self) -> None:
        manifest = load_json(ROOT / "manifests" / "deploy_manifest.yaml")
        excludes = set(manifest["exclude"])

        for pattern in [
            "docs_dev/**",
            "tests/**",
            "references/source/*.xlsx",
            "references/source/*.drawio",
            "references/source/raw/**",
            ".env",
            ".env.*",
        ]:
            self.assertIn(pattern, excludes)

        include_text = "\n".join(manifest["include"])
        self.assertNotIn("docs_dev", include_text)
        self.assertNotIn("references/source", include_text)
        for forbidden in [
            "cron/s2_snapshot_worker.py",
            "cron/run_s2_snapshot.sh",
            "ops/openclaw-plugins/hotel-ota-feishu-auth/**",
            "ops/systemd/hotel-ota-s2-snapshot.service",
            "ops/systemd/hotel-ota-s2-snapshot.timer",
        ]:
            self.assertNotIn(forbidden, manifest["include"])

        notes = "\n".join(manifest["notes"])
        self.assertIn("optional", notes.lower())
        self.assertNotIn("hotel-ota-cron.env", notes)
        for removed_path in [
            "cron/s2_snapshot_worker.py",
            "cron/run_s2_snapshot.sh",
            "ops/systemd/hotel-ota-s2-snapshot.service",
            "ops/systemd/hotel-ota-s2-snapshot.timer",
        ]:
            self.assertFalse((ROOT / removed_path).exists(), removed_path)
        self.assertTrue((ROOT / "docs_dev/archive/optional-s2-timer.md").exists())

    def test_only_source_manifest_contains_local_absolute_paths(self) -> None:
        windows_drive = r"[A-Z]:" + re.escape(chr(92))
        windows_users = "C:" + re.escape(chr(92)) + "Users"
        posix_users = "/" + "Users" + "/"
        local_path_pattern = re.compile(rf"(?:{windows_drive}|{re.escape(posix_users)}|{windows_users})")
        allowed = ROOT / "references" / "source" / "source_manifest.yaml"
        checked_suffixes = {".md", ".json", ".yaml", ".py"}

        offenders: list[str] = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in checked_suffixes:
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            if any(part in {".git", ".claude", ".venv", "venv", "env", "__pycache__", ".pytest_cache", ".mypy_cache"} for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if local_path_pattern.search(text) and path.resolve() != allowed.resolve():
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()

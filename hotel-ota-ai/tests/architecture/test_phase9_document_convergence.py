from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestPhase9DocumentConvergence(unittest.TestCase):
    def test_legacy_requirements_tree_is_removed(self) -> None:
        self.assertFalse((ROOT / "requirements").exists())
        self.assertFalse((ROOT / "architecture" / "phase9_document_convergence_index.json").exists())

    def test_current_authority_and_deployment_entries_exist(self) -> None:
        required_paths = [
            "AGENTS.md",
            "BOOTSTRAP.md",
            "TOOLS.md",
            "README.md",
            "contracts/v27/contract.json",
            "ops/server-update-guide.md",
            "manifests/deploy_manifest.yaml",
        ]
        for relative_path in required_paths:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).exists())

    def test_deleted_requirement_references_do_not_return(self) -> None:
        checked_paths = [
            ROOT / "README.md",
            ROOT / "architecture" / "phase9_document_convergence.md",
            ROOT / "manifests" / "docs_context_manifest.yaml",
        ]
        for path in checked_paths:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("requirements/OpenClaw实施教程.md", text)
                self.assertNotIn("phase9_document_convergence_index.json\"", text)

        phase9 = (ROOT / "architecture" / "phase9_document_convergence.md").read_text(encoding="utf-8")
        self.assertIn("2026-08-07 旧 requirements 清理", phase9)
        self.assertIn("全部 25 个", phase9)


if __name__ == "__main__":
    unittest.main()

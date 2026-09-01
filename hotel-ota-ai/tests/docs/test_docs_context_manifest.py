from __future__ import annotations

import unittest
from pathlib import Path

from tools.generate_docs_context_manifest import (
    AUTHORITATIVE_PATHS,
    EXCLUDED_PATHS,
    OPERATIONAL_PATHS,
    STARTUP_DOCS,
    generate_manifest,
    iter_markdown_files,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "manifests" / "docs_context_manifest.yaml"
OPENCLAW_MANIFEST = ROOT / "manifests" / "openclaw_context_manifest.yaml"


class TestDocsContextManifest(unittest.TestCase):
    def test_tool_metadata_and_retired_requirements_are_excluded(self) -> None:
        paths = {path.relative_to(ROOT).as_posix() for path in iter_markdown_files()}
        self.assertFalse(any(path.startswith(".claude/") for path in paths))
        self.assertFalse(any(path.startswith(".codex/") for path in paths))
        self.assertFalse(any(path.startswith(".trae/") for path in paths))
        self.assertFalse(any(path.startswith("requirements/") for path in paths))

    def test_manifest_is_generated_from_current_rules(self) -> None:
        self.assertTrue(MANIFEST.exists())
        text = MANIFEST.read_text(encoding="utf-8")
        self.assertEqual(text, generate_manifest())
        self.assertIn("schema_version: docs_context_manifest.v2", text)
        self.assertIn("current_fact_source: contracts/v27/contract.json", text)
        self.assertNotIn('doc_path: "requirements/', text)

    def test_manifest_paths_are_current_and_resolvable(self) -> None:
        for relative_path in STARTUP_DOCS:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())

        for relative_path in AUTHORITATIVE_PATHS + OPERATIONAL_PATHS:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).exists())

        self.assertIn("requirements/", EXCLUDED_PATHS)
        self.assertFalse((ROOT / "requirements").exists())

    def test_openclaw_context_manifest_is_small_and_process_file_free(self) -> None:
        self.assertTrue(OPENCLAW_MANIFEST.exists())
        text = OPENCLAW_MANIFEST.read_text(encoding="utf-8")
        for doc in STARTUP_DOCS:
            self.assertIn(f'- "{doc}"', text)
        for process_doc in ["task_plan.md", "progress.md", "findings.md", "docs/superpowers/plans"]:
            self.assertNotIn(process_doc, text)
        self.assertNotIn("docs_context_manifest.yaml", text)


if __name__ == "__main__":
    unittest.main()

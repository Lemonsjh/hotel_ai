from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_FILES = ["USER.md", "IDENTITY.md", "SOUL.md", "HEARTBEAT.md", "MEMORY.md"]
FORBIDDEN_TERMS = ["api_key", "secret", "password", "dsn", "token", "open_id", "chat_id", "access_token"]


class TestWorkspaceMemoryFiles(unittest.TestCase):
    def test_workspace_files_exist_and_are_not_ignored(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for name in WORKSPACE_FILES:
            self.assertTrue((ROOT / name).exists(), name)
            self.assertNotIn(name, gitignore)
        self.assertIn(".openclaw/", gitignore)
        self.assertIn(".venv/", gitignore)

    def test_workspace_files_are_not_sensitive_sources(self) -> None:
        for name in WORKSPACE_FILES:
            text = (ROOT / name).read_text(encoding="utf-8")
            lowered = text.lower()
            for term in FORBIDDEN_TERMS:
                self.assertNotIn(term, lowered, name)
            self.assertIn("不是权限来源", text)
            self.assertIn("业务数据来源", text)
            self.assertIn("审批依据", text)

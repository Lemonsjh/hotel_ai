from __future__ import annotations

import json
import contextlib
import io
import unittest
from pathlib import Path

from runtime.cli import main


ROOT = Path(__file__).resolve().parents[2]


class TestOpenClawContextBudget(unittest.TestCase):
    def test_openclaw_example_uses_bounded_context_injection(self) -> None:
        payload = json.loads((ROOT / "config" / "openclaw.example.json").read_text(encoding="utf-8"))

        defaults = payload["agents"]["defaults"]
        chief = payload["agents"]["list"][0]
        self.assertEqual(defaults["contextInjection"], "continuation-skip")
        self.assertEqual(chief["contextInjection"], "continuation-skip")
        self.assertLessEqual(defaults["bootstrapTotalMaxChars"], 80_000)
        self.assertEqual(chief["bootstrapTotalMaxChars"], 80_000)
        self.assertLessEqual(chief["skillsLimits"]["maxSkillsPromptChars"], 16_000)

    def test_openclaw_read_first_manifest_excludes_large_reference_sources(self) -> None:
        text = (ROOT / "manifests" / "openclaw_context_manifest.yaml").read_text(encoding="utf-8")
        read_first = text.split("root_context_files:", 1)[1]

        forbidden = [
            "docs_dev",
            "docs/architecture_reference/v27",
            "contracts/v27/contract.json",
            "task_plan.md",
            "progress.md",
            "findings.md",
        ]
        for item in forbidden:
            with self.subTest(item=item):
                self.assertNotIn(item, read_first)

    def test_env_check_reports_openclaw_context_policy(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(["env-check"])

        payload = json.loads(buffer.getvalue())
        policy = payload["openclaw_context_policy"]

        self.assertEqual(code, 0)
        self.assertEqual(policy["example_default_context_injection"], "continuation-skip")
        self.assertEqual(policy["example_chief_context_injection"], "continuation-skip")
        self.assertTrue(policy["openclaw_context_manifest_exists"])
        self.assertEqual(policy["read_first_file_count"], 9)
        self.assertLessEqual(policy["example_default_bootstrap_total_max_chars"], 80_000)
        self.assertEqual(policy["example_chief_bootstrap_total_max_chars"], 80_000)

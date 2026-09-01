from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class TestFeishuDeploymentGuidance(unittest.TestCase):
    def test_gateway_context_examples_use_2026_5_28_compatible_strategy(self) -> None:
        docs = [
            ROOT / "ops" / "server-update-guide.md",
        ]
        for path in docs:
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn('contextInjection: "always"', text)
                self.assertNotIn("contextInjection 'always'", text)
                self.assertIn("continuation-skip", text)

    def test_root_runtime_rules_do_not_require_business_coverage_in_feishu_reply(self) -> None:
        text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn("S5 revenue replies must include or summarize `contract_input_coverage`", text)

    def test_plugin_installation_is_staged_and_independent_of_s2_timer(self) -> None:
        text = (ROOT / "ops" / "openclaw-plugins" / "hotel-ota-feishu-auth" / "INSTALL.txt").read_text(encoding="utf-8")
        self.assertIn("isolated OpenClaw home", text)
        self.assertIn("config validate", text)
        self.assertIn("inbound_claim", text)
        self.assertIn("no dependency on an S2 timer", text)


if __name__ == "__main__":
    unittest.main()

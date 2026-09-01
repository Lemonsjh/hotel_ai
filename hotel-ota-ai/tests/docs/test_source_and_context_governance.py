from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_MANIFEST = ROOT / "references" / "source" / "source_manifest.yaml"
P0_DOCS = ["AGENTS.md", "USER.md", "IDENTITY.md", "SOUL.md", "HEARTBEAT.md", "MEMORY.md", "BOOTSTRAP.md", "TOOLS.md", "README.md"]


class TestSourceAndContextGovernance(unittest.TestCase):
    def test_source_manifest_matches_current_v27_archive_state(self) -> None:
        manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))

        self.assertEqual(manifest["current_machine_contract"], "contracts/v27/contract.json")
        self.assertIn("source_archives", manifest)
        self.assertEqual(
            manifest["source_archives"]["v27_contract_source"],
            "docs/architecture_reference/v27/酒店OTA_AI数字员工_协作开发总地图_V27_项目修复可执行契约版.json",
        )
        self.assertEqual(
            manifest["source_archives"]["v27_source_data_list"],
            "docs/architecture_reference/v27/数据列表.txt",
        )
        self.assertNotIn("数据列表.txt", manifest["source_archives"].get("external_not_archived", []))

    def test_openclaw_p0_docs_do_not_repeat_contract_notice_sections(self) -> None:
        combined = "\n".join((ROOT / doc).read_text(encoding="utf-8") for doc in P0_DOCS)
        self.assertIn("contracts/v27/contract.json", combined)
        for doc in P0_DOCS:
            with self.subTest(doc=doc):
                text = (ROOT / doc).read_text(encoding="utf-8")
                self.assertNotIn("## V27 Contract-First Notice", text)

    def test_bootstrap_uses_v27_current_reading_wording(self) -> None:
        text = (ROOT / "BOOTSTRAP.md").read_text(encoding="utf-8")
        self.assertNotIn("## V26 读取补充", text)
        self.assertIn("contracts/v27/contract.json", text)
        self.assertIn("AGENTS.md", text)

    def test_v27_architecture_references_are_p1_not_openclaw_read_first(self) -> None:
        manifest = (ROOT / "manifests" / "docs_context_manifest.yaml").read_text(encoding="utf-8")
        self.assertRegex(
            manifest,
            r'doc_path: "docs/architecture_reference/v27/02-调价建议算法\.md"[\s\S]*?priority: "P1"[\s\S]*?max_context_policy: "read_when_relevant"',
        )


if __name__ == "__main__":
    unittest.main()

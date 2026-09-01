from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
P0_DOCS = ["AGENTS.md", "USER.md", "IDENTITY.md", "SOUL.md", "HEARTBEAT.md", "MEMORY.md", "BOOTSTRAP.md", "TOOLS.md", "README.md"]
FORBIDDEN_RUNTIME_CONTEXT_PHRASES = [
    "2026-06-15",
    "6 月 15",
    "交付优先级",
    "验收重点",
    "Current Effective Runtime Rules - 2026-06-15",
    "legacy migration reference）（legacy migration reference）",
    "角色只在 JSON",
    "SQLite 只有经营数据",
    "手改 feishu-role-map",
    "SQL UPDATE",
    "live 执行全部权限",
]
FORBIDDEN_OPENCLAW_MANIFEST_PHRASES = [
    "task_plan.md",
    "progress.md",
    "findings.md",
    "docs_dev",
    "协作开发",
    "Skill测试协作",
]


class TestOpenClawContextFiles(unittest.TestCase):
    def test_p0_docs_keep_current_contract_and_boundary_without_repeated_summary(self) -> None:
        combined = "\n".join((ROOT / doc).read_text(encoding="utf-8") for doc in P0_DOCS)
        self.assertIn("contracts/v27/contract.json", combined)
        self.assertIn("不是权限来源", combined)
        self.assertIn("业务数据来源", combined)
        self.assertIn("审批依据", combined)
        self.assertNotIn("Current Effective Runtime Rules - 2026-06-15", combined)

    def test_p0_docs_do_not_contain_obvious_secret_values(self) -> None:
        secret_patterns = [
            r"password\s*=",
            r"api[_-]?key\s*=",
            r"secret\s*=",
            r"token\s*=[A-Za-z0-9_\-]{12,}",
            r"mysql://[^\\s]+:[^\\s]+@",
        ]
        for doc in P0_DOCS:
            text = (ROOT / doc).read_text(encoding="utf-8").lower()
            with self.subTest(doc=doc):
                for pattern in secret_patterns:
                    self.assertIsNone(re.search(pattern, text), pattern)

    def test_p0_docs_do_not_contain_stale_delivery_or_process_context(self) -> None:
        for doc in P0_DOCS:
            text = (ROOT / doc).read_text(encoding="utf-8")
            with self.subTest(doc=doc):
                for phrase in FORBIDDEN_RUNTIME_CONTEXT_PHRASES:
                    self.assertNotIn(phrase, text)

    def test_openclaw_manifest_does_not_load_process_or_collaboration_docs(self) -> None:
        text = (ROOT / "manifests" / "openclaw_context_manifest.yaml").read_text(encoding="utf-8")
        for phrase in FORBIDDEN_OPENCLAW_MANIFEST_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, text)

    def test_runtime_docs_do_not_recommend_naked_feishu_user_role_for_production(self) -> None:
        for doc in P0_DOCS:
            text = (ROOT / doc).read_text(encoding="utf-8")
            for lineno, line in enumerate(text.splitlines(), start=1):
                with self.subTest(doc=doc, line=lineno):
                    if "feishu-route" in line and "--user-role" in line:
                        self.assertIn("--trusted-runtime-role", line)

    def test_p0_docs_state_active_auth_and_controlled_change_flow(self) -> None:
        required = [
            "SQLite Active Auth",
            "BIND",
            "ROLE",
            "CFG",
            "chat_bindings",
            "chat:oc_xxx",
            "user:ou_xxx",
            "price task outbox",
            "PENDING/SUCCESS/FAILED",
            "business_date 是售卖日",
            "market-source.json",
            "openclaw_bridge_http_search",
            "source registry",
        ]
        combined = "\n".join((ROOT / doc).read_text(encoding="utf-8") for doc in P0_DOCS)
        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

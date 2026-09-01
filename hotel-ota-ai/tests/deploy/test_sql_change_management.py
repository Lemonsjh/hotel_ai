from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SQL_DIR = ROOT / "ops" / "sql"


class TestSqlChangeManagement(unittest.TestCase):
    def test_sql_readme_blocks_agent_managed_views(self) -> None:
        text = (SQL_DIR / "README.md").read_text(encoding="utf-8")
        self.assertIn("runtime", text)
        self.assertIn("manual_review_required", text)
        self.assertIn("view_migration_version", text)
        self.assertIn("v_openclaw_*", text)
        self.assertIn("不得直接执行 DDL", text)

    def test_placeholder_has_no_executable_ddl_or_secrets(self) -> None:
        text = (SQL_DIR / "20260626_openclaw_zhiting_views.placeholder.sql").read_text(encoding="utf-8")
        self.assertIn("manual_review_required", text)
        self.assertIn("No executable DDL", text)
        executable = re.compile(r"^\s*(CREATE|ALTER|DROP|GRANT|REVOKE)\b", re.IGNORECASE | re.MULTILINE)
        self.assertIsNone(executable.search(text))
        self.assertNotRegex(text, r"mysql://|mysql\+pymysql://|password\s*=|token\s*=|secret\s*=")


if __name__ == "__main__":
    unittest.main()

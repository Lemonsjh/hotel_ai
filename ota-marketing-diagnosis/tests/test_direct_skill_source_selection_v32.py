from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "s14-operation-diagnosis"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from runtime import S14OperationDiagnosis


class DirectSkillSourceSelectionTest(unittest.TestCase):
    def test_default_direct_invocation_returns_serializable_source_choice(self):
        result = S14OperationDiagnosis({}).execute({})

        self.assertEqual(result["status"], "awaiting_source")
        self.assertEqual(result["platform"], "multi")
        self.assertEqual(result["data_source"], "pending")
        rendered = json.dumps(result, ensure_ascii=False)
        self.assertIn("数据库", rendered)
        self.assertIn("上传Excel", rendered)
        self.assertIn("系统自动拉取数据诊断", result["feishu_message"])
        self.assertIn("发送已填好的Excel附件诊断", result["feishu_message"])
        self.assertNotIn('"tag": "action"', rendered)
        self.assertIn("直接回复", rendered)
        self.assertNotIn("选择渠道", rendered)
        self.assertNotIn("report_url", result)

    def test_explicit_source_selection_is_serializable(self):
        result = S14OperationDiagnosis({}).execute(
            {"data_source_mode": "source_selection", "platform": "meituan"}
        )

        self.assertEqual(result["platform"], "multi")
        json.dumps(result, ensure_ascii=False)

    def test_source_buttons_require_explicit_callback_configuration(self):
        result = S14OperationDiagnosis(
            {"feishu_card_callback_enabled": True}
        ).execute({"data_source_mode": "source_selection"})

        rendered = json.dumps(result["feishu_card"], ensure_ascii=False)
        self.assertIn('"tag": "action"', rendered)
        self.assertIn('"source": "database"', rendered)
        self.assertIn('"source": "excel"', rendered)

    def test_excel_pending_does_not_run_report(self):
        result = S14OperationDiagnosis({}).execute(
            {"data_source_mode": "excel_pending"}
        )

        self.assertEqual(result["status"], "awaiting_excel")
        self.assertEqual(result["data_source"], "excel_pending")
        self.assertNotIn("report_url", result)
        json.dumps(result, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()

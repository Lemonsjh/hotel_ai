from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from runtime.s14_ext_third_party_diagnosis import diagnose_s14_ext_excel_file
from tests.s14.test_s14_report_url import write_minimal_s14_xlsx


class TestS14ExtPreservesReportUrl(unittest.TestCase):
    def test_ext_excel_preserves_report_url_and_safety_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            excel = root / "s14-ext.xlsx"
            reports = root / "reports"
            write_minimal_s14_xlsx(excel)
            old_base = os.environ.get("HOTEL_OTA_S14_REPORT_BASE_URL")
            os.environ["HOTEL_OTA_S14_REPORT_BASE_URL"] = "https://reports.example.com/reports"
            try:
                result = diagnose_s14_ext_excel_file(str(excel), hotel_id="hotel-a", report_dir=str(reports))
            finally:
                if old_base is None:
                    os.environ.pop("HOTEL_OTA_S14_REPORT_BASE_URL", None)
                else:
                    os.environ["HOTEL_OTA_S14_REPORT_BASE_URL"] = old_base

        self.assertEqual(result["node_id"], "N022")
        self.assertEqual(result["skill_id"], "S14-EXT")
        self.assertEqual(result["source_mode"], "third_party_excel")
        self.assertEqual(result["publisher_status"], "published")
        self.assertEqual(result["report_url"], "https://reports.example.com/reports/hotel-a/ota_diagnosis_report.html")
        self.assertTrue(result["external_isolated"])
        self.assertFalse(result["live_allowed"])
        self.assertFalse(result["formal_approval_created"])
        self.assertEqual(result["live_execution_count"], 0)


if __name__ == "__main__":
    unittest.main()

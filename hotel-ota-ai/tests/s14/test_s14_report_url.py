from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from runtime.s14_operation_diagnosis import (
    diagnose_s14_excel_file,
    diagnose_s14_mysql_template_result,
)


def write_minimal_s14_xlsx(path: Path) -> None:
    """Legacy fixture helper retained for S14-EXT migration tests only."""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData>
            <row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>hos_score</t></is></c><c r=\"B1\" t=\"inlineStr\"><is><t>payment_conversion_rate</t></is></c></row>
            <row r=\"2\"><c r=\"A2\"><v>82</v></c><c r=\"B2\"><v>0.02</v></c></row>
            </sheetData></worksheet>""",
        )


class TestS14RetiredDirectReportSource(unittest.TestCase):
    def test_excel_source_fails_closed_without_creating_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            excel = root / "s14.xlsx"
            reports = root / "reports"
            write_minimal_s14_xlsx(excel)

            result = diagnose_s14_excel_file(
                str(excel),
                hotel_id="hotel-a",
                report_dir=str(reports),
            )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(
            result["blocked_reason"],
            "s14_direct_source_removed_use_versioned_capability_results",
        )
        self.assertEqual(result["source_policy"], "versioned_capability_results_only")
        self.assertFalse(result["excel_source_allowed"])
        self.assertFalse(result["business_result_generated"])
        self.assertFalse(result["write_performed"])
        self.assertFalse(reports.exists())
        self.assertNotIn("html_report_path", result)
        self.assertNotIn("report_url", result)

    def test_mysql_derived_payload_fails_closed(self) -> None:
        result = diagnose_s14_mysql_template_result(
            {
                "status": "ok",
                "payload": {
                    "occupancy": 0.8,
                    "adr": 180,
                    "revpar": 144,
                    "exposure": 1000,
                },
            },
            hotel_id="hotel-a",
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(
            result["blocked_reason"],
            "s14_direct_source_removed_use_versioned_capability_results",
        )
        self.assertFalse(result["direct_business_table_read_allowed"])
        self.assertFalse(result["business_result_generated"])
        self.assertNotIn("diagnosis_score", result)
        self.assertNotIn("module_scores", result)


if __name__ == "__main__":
    unittest.main()

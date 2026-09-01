from __future__ import annotations

import re
import unittest
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIELD_DOC = Path(
    os.environ.get(
        "HOTEL_OTA_DATABASE_FIELD_DOC",
        str(ROOT.parent / "功能逻辑蓝图" / "数据库数据字段说明_详细版(4).md"),
    )
)


class TestDatabaseFieldSourceContract(unittest.TestCase):
    def _field_doc_text(self) -> str:
        if not FIELD_DOC.exists():
            raise unittest.SkipTest("external database field source document is not available in this environment")
        return FIELD_DOC.read_text(encoding="utf-8")

    def test_field_source_declares_twenty_two_tables(self) -> None:
        text = self._field_doc_text()

        self.assertIn("表数量：22 张", text)
        table_rows = re.findall(r"\|\s*\d+\s*\|\s*`([^`]+)`\s*\|", text)
        self.assertEqual(len(table_rows), 22)
        self.assertIn("byh_plugin_auth_status", table_rows)
        self.assertIn("byh_plugin_run_log", table_rows)
        self.assertIn("ctrip_zhiting_price_task", table_rows)
        self.assertIn("meituan_zhiting_price_task", table_rows)

    def test_field_source_uses_final_zhiting_table_shape(self) -> None:
        text = self._field_doc_text()

        self.assertIn("每张表都必须保留 `hotel_name`、`source_platform`、`snapshot_time`", text)
        self.assertIn("`jy01_hotel_statistics_daily` 是日经营快照横表", text)
        self.assertIn("`jy03_hotel_statistics_month` 是月经营快照横表", text)
        for field in ("occupancy_rate", "adr", "revpar", "sold_rooms", "remaining_rooms", "orders_today"):
            self.assertIn(field, text)

    def test_task_table_contract_keeps_room_type_and_status_semantics(self) -> None:
        text = self._field_doc_text()

        for table in ("ctrip_zhiting_price_task", "meituan_zhiting_price_task"):
            self.assertIn(table, text)
            self.assertIn("room_type_name", text)
            self.assertIn("business_date", text)
            self.assertIn("target_sale_price", text)
            self.assertIn("execute_status", text)
        self.assertIn("PENDING", text)
        self.assertIn("SUCCESS", text)
        self.assertIn("FAILED", text)
        self.assertIn("`business_date`：业务日期", text)
        self.assertIn("业务日期，表示指标、房费、价格或调价任务归属到哪一天", text)


if __name__ == "__main__":
    unittest.main()

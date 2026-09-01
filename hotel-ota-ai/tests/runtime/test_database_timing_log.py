from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.adapters.database import database_template_result


class DatabaseTimingLogTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = os.environ.copy()
        os.environ["HOTEL_OTA_DB_READONLY"] = "1"

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old_env)

    def test_database_template_timing_log_is_off_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "runtime.adapters.database._query_mysql",
            return_value={"status": "ok", "payload": {"source_status": "ok", "rows": [{"x": 1}]}},
        ):
            os.environ["HOTEL_OTA_LOG_DIR"] = tmp
            os.environ.pop("HOTEL_OTA_DB_TIMING_LOG", None)
            result = database_template_result("room_fee_daily", "puyue", db_kind="mysql", dsn="mysql://user:secret@host/db")

            self.assertEqual(result["status"], "ok")
            self.assertFalse((Path(tmp) / "database-template-timing.jsonl").exists())

    def test_database_template_timing_log_writes_redacted_jsonl_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "runtime.adapters.database._query_mysql",
            return_value={
                "status": "ok",
                "payload": {
                    "source_status": "ok",
                    "rows": [{"business_date": "2026-07-02"}, {"business_date": "2026-07-03"}],
                    "risk_flags": ["sample_risk"],
                },
            },
        ):
            os.environ["HOTEL_OTA_DB_TIMING_LOG"] = "1"
            os.environ["HOTEL_OTA_LOG_DIR"] = tmp
            result = database_template_result("room_fee_daily", "puyue", db_kind="mysql", dsn="mysql://user:secret@host/db")

            self.assertEqual(result["status"], "ok")
            log_path = Path(tmp) / "database-template-timing.jsonl"
            self.assertTrue(log_path.exists())
            record = json.loads(log_path.read_text(encoding="utf-8").strip())

        self.assertEqual(record["template"], "room_fee_daily")
        self.assertEqual(record["hotel_id"], "puyue")
        self.assertEqual(record["status"], "ok")
        self.assertEqual(record["source_status"], "ok")
        self.assertEqual(record["row_count"], 2)
        self.assertEqual(record["risk_flags"], ["sample_risk"])
        self.assertGreaterEqual(record["duration_ms"], 0)
        serialized = json.dumps(record, ensure_ascii=False)
        self.assertNotIn("mysql://", serialized)
        self.assertNotIn("secret", serialized.lower())
        self.assertNotIn("SELECT", serialized.upper())


if __name__ == "__main__":
    unittest.main()

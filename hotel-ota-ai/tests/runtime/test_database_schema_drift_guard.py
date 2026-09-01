from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.adapters.schema_drift_guard import (
    _remove_stats_period_type_mappings,
    guard_database_template_result,
)


class FakeOperationalError(Exception):
    pass


class DatabaseSchemaDriftGuardTests(unittest.TestCase):
    def test_removes_stats_period_type_from_all_profile_mappings(self) -> None:
        config = {
            "default_profile": "production",
            "profiles": {
                "base": {
                    "columns": {
                        "daily_metrics": {
                            "period_type": "stats_period_type",
                            "business_date": "business_date",
                        }
                    }
                },
                "production": {
                    "inherits": "base",
                    "columns": {
                        "ctrip_business_metrics": {
                            "stats_period_type": "stats_period_type",
                            "metric_name": "metric_name",
                        },
                        "meituan_business_metrics": {
                            "period_type": "stats_period_type",
                            "metric_value": "metric_value",
                        },
                    },
                },
            },
        }

        sanitized, removed = _remove_stats_period_type_mappings(config)

        self.assertEqual(len(removed), 3)
        self.assertNotIn("period_type", sanitized["profiles"]["base"]["columns"]["daily_metrics"])
        self.assertNotIn(
            "stats_period_type",
            sanitized["profiles"]["production"]["columns"]["ctrip_business_metrics"],
        )
        self.assertNotIn(
            "period_type",
            sanitized["profiles"]["production"]["columns"]["meituan_business_metrics"],
        )
        self.assertEqual(
            sanitized["profiles"]["production"]["columns"]["ctrip_business_metrics"]["metric_name"],
            "metric_name",
        )

    def test_retries_with_temporary_sanitized_mapping(self) -> None:
        config = {
            "default_profile": "production",
            "profiles": {
                "production": {
                    "columns": {
                        "daily_metrics": {
                            "period_type": "stats_period_type",
                            "business_date": "business_date",
                        }
                    }
                }
            },
        }
        calls: list[str | None] = []

        def original(
            template: str,
            hotel_id: str,
            mapping_config: str | None = None,
            date: str | None = None,
        ) -> dict:
            del hotel_id, date
            calls.append(mapping_config)
            if len(calls) == 1:
                raise FakeOperationalError(1054, "Unknown column 'stats_period_type' in 'field list'")
            self.assertIsNotNone(mapping_config)
            self.assertTrue(Path(str(mapping_config)).is_file())
            with open(str(mapping_config), "r", encoding="utf-8") as handle:
                retried_config = json.load(handle)
            self.assertNotIn(
                "period_type",
                retried_config["profiles"]["production"]["columns"]["daily_metrics"],
            )
            return {
                "status": "ok",
                "template": template,
                "payload": {"normalized_metrics": {"room_nights": 18}},
            }

        guarded = guard_database_template_result(original)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            mapping_path = Path(tmp) / "db-mapping.json"
            mapping_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
            with mock.patch.dict(os.environ, {"HOTEL_OTA_DB_MAPPING_CONFIG": str(mapping_path)}):
                result = guarded("daily_metrics", "puyue", date="2026-08-03")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["schema_drift_recovered"])
        self.assertIn(
            "schema_drift_recovered:stats_period_type_mapping_removed",
            result["risk_flags"],
        )
        self.assertIn(
            "schema_drift_recovered:stats_period_type_mapping_removed",
            result["payload"]["risk_flags"],
        )
        self.assertEqual(len(calls), 2)
        self.assertFalse(Path(str(calls[1])).exists())

    def test_unrelated_database_error_is_not_hidden(self) -> None:
        def original(template: str, hotel_id: str, **kwargs) -> dict:
            del template, hotel_id, kwargs
            raise FakeOperationalError(1146, "Table does not exist")

        guarded = guard_database_template_result(original)
        with self.assertRaises(FakeOperationalError):
            guarded("daily_metrics", "puyue")

    def test_missing_mapping_file_returns_explicit_data_gap(self) -> None:
        def original(template: str, hotel_id: str, **kwargs) -> dict:
            del template, hotel_id, kwargs
            raise FakeOperationalError(1054, "Unknown column 'stats_period_type' in 'where clause'")

        guarded = guard_database_template_result(original)
        with mock.patch.dict(os.environ, {}, clear=True):
            result = guarded("daily_metrics", "puyue")

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["reason"], "database_schema_drift_stats_period_type")
        self.assertIn("stats_period_type_mapping_invalid", result["risk_flags"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.cli import main
from runtime.decisions.calendar import sync_holiday_provider_cache
from tests.test_security_and_freshness import _capture_json


class TestMarketContextDegradation(unittest.TestCase):
    def test_events_disabled_does_not_block_basic_environment_context(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            config_path = Path(tmp) / "market-source.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "hotels": {
                            "xingfeng": {
                                "weather": {
                                    "provider": "manual_weather",
                                    "enabled": True,
                                    "condition": "cloudy",
                                    "temperature_c": 26,
                                },
                                "events": {"provider": "openclaw_bridge_http_search", "enabled": False},
                                "regional_heat": {"provider": "composite", "enabled": True},
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            operating_fixture = Path(tmp) / "operating.json"
            operating_fixture.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "freshness_status": "fresh",
                        "business_status": "current",
                        "data_business_date": "2026-06-27",
                    }
                ),
                encoding="utf-8",
            )
            _capture_json(main, ["--db", db_path, "init-db"])
            with mock.patch.dict(os.environ, {"HOTEL_OTA_MARKET_SOURCE_CONFIG": str(config_path)}, clear=True):
                result = _capture_json(
                    main,
                    [
                        "--db",
                        db_path,
                        "market-context",
                        "--hotel-id",
                        "xingfeng",
                        "--date",
                        "2026-06-27",
                        "--operating-fixture",
                        str(operating_fixture),
                    ],
                )

        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["context_generation_allowed"])
        self.assertEqual(result["market_context_level"], "basic_environment")
        self.assertIn("events", result["omitted_modules"])
        self.assertFalse(result["downstream_revenue_allowed"])
        self.assertFalse(result["approval_allowed"])
        self.assertFalse(result["live_allowed"])

    def test_confirmed_external_calendar_is_accepted_for_basic_context(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _capture_json(main, ["--db", db_path, "init-db"])
            sync_holiday_provider_cache(
                db_path,
                2026,
                {
                    "provider": "apisbo",
                    "endpoint_template": "https://api.apisbo.com/holidays/year/{year}",
                    "commercial_use_confirmed": True,
                },
                http_get=lambda endpoint, timeout, headers=None: {
                    "days": [{"date": "2026-06-19", "type": "holiday", "name": "Dragon Boat Festival"}]
                },
            )
            operating_fixture = Path(tmp) / "operating.json"
            operating_fixture.write_text(
                json.dumps({"status": "ok", "freshness_status": "fresh", "business_status": "current"}),
                encoding="utf-8",
            )
            config_path = Path(tmp) / "market-source.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "hotels": {
                            "xingfeng": {
                                "weather": {"provider": "manual_weather", "enabled": True, "condition": "sunny"},
                                "events": {"provider": "manual_json", "enabled": False},
                                "regional_heat": {"provider": "composite", "enabled": True},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"HOTEL_OTA_MARKET_SOURCE_CONFIG": str(config_path)}, clear=True):
                result = _capture_json(
                    main,
                    [
                        "--db",
                        db_path,
                        "market-context",
                        "--hotel-id",
                        "xingfeng",
                        "--date",
                        "2026-06-19",
                        "--operating-fixture",
                        str(operating_fixture),
                    ],
                )

        self.assertEqual(result["calendar_context"]["source_quality"], "confirmed_external")
        self.assertTrue(result["context_generation_allowed"])

    def test_market_context_derives_progress_from_database_when_fixture_missing(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            _capture_json(main, ["--db", db_path, "init-db"])
            operating_fixture = Path(tmp) / "operating.json"
            operating_fixture.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "freshness_status": "fresh",
                        "business_status": "current",
                        "data_business_date": "2026-06-27",
                    }
                ),
                encoding="utf-8",
            )
            config_path = Path(tmp) / "market-source.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "hotels": {
                            "xingfeng": {
                                "weather": {"provider": "manual_weather", "enabled": True, "condition": "sunny"},
                                "events": {"provider": "manual_json", "enabled": False},
                                "regional_heat": {"provider": "composite", "enabled": True},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            db_result = {
                "status": "ok",
                "payload": {
                    "business_date": "2026-06-27",
                    "freshness_status": "fresh",
                    "business_status": "current",
                    "orders_today": 11,
                    "sold_rooms": 16,
                    "room_nights": 16,
                    "occupancy_rate": 0.32,
                },
            }
            with mock.patch.dict(os.environ, {"HOTEL_OTA_MARKET_SOURCE_CONFIG": str(config_path)}, clear=True), mock.patch(
                "runtime.decisions.calendar.database_source_enabled", return_value=True
            ), mock.patch("runtime.decisions.calendar.database_template_result", return_value=db_result):
                result = _capture_json(
                    main,
                    [
                        "--db",
                        db_path,
                        "market-context",
                        "--hotel-id",
                        "xingfeng",
                        "--date",
                        "2026-06-27",
                        "--operating-fixture",
                        str(operating_fixture),
                    ],
                )

        self.assertEqual(result["progress_context"]["status"], "partial")
        self.assertEqual(result["progress_context"]["actual_source"], "mysql_runtime")
        self.assertEqual(result["progress_context"]["current_facts"]["actual_sold_rooms"], 16)
        self.assertIn("progress", result["used_modules"])
        self.assertFalse(result["downstream_revenue_allowed"])


if __name__ == "__main__":
    unittest.main()

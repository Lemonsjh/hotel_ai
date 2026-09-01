from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime.cli import main
from runtime.decisions.calendar import get_calendar_day, sync_holiday_provider_cache
from tests.test_security_and_freshness import _capture_json


class TestHolidayProviderSync(unittest.TestCase):
    def test_remote_sync_requires_commercial_confirmation(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            result = sync_holiday_provider_cache(
                str(Path(tmp) / "calendar.sqlite"),
                2026,
                {
                    "provider": "apisbo",
                    "endpoint_template": "https://api.apisbo.com/holidays/year/{year}",
                    "commercial_use_confirmed": False,
                },
                http_get=lambda endpoint, timeout, headers=None: {"days": []},
            )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["reason"], "holiday_provider_commercial_use_not_confirmed")

    def test_endpoint_template_and_apisbo_day_types_are_cached(self) -> None:
        seen: list[str] = []

        def fake_get(endpoint: str, timeout: float, headers: dict | None = None) -> dict:
            seen.append(endpoint)
            return {
                "days": [
                    {"date": "2026-10-01", "type": "holiday", "name": "National Day"},
                    {"date": "2026-09-27", "type": "workday", "name": "Adjusted Workday"},
                ]
            }

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "calendar.sqlite")
            result = sync_holiday_provider_cache(
                db_path,
                2026,
                {
                    "provider": "apisbo",
                    "endpoint_template": "https://api.apisbo.com/holidays/year/{year}",
                    "commercial_use_confirmed": True,
                },
                http_get=fake_get,
            )
            day = get_calendar_day(db_path, "2026-10-01")

        self.assertEqual(seen, ["https://api.apisbo.com/holidays/year/2026"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(day["source_quality"], "confirmed_external")
        self.assertTrue(day["is_holiday"])

    def test_jiejiariapi_schema_and_api_key_header_are_supported(self) -> None:
        seen_headers: list[dict | None] = []

        def fake_get(endpoint: str, timeout: float, headers: dict | None = None) -> dict:
            seen_headers.append(headers)
            return {
                "holidays": [{"date": "2026-05-01", "name": "Labor Day"}],
                "workdays": [{"date": "2026-04-26", "name": "Adjusted Workday"}],
                "weekends": [{"date": "2026-05-02", "name": "Weekend"}],
            }

        with mock.patch.dict(os.environ, {"JIEJIARI_API_KEY": "secret-key"}, clear=True):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = str(Path(tmp) / "calendar.sqlite")
                result = sync_holiday_provider_cache(
                    db_path,
                    2026,
                    {
                        "provider": "jiejiariapi",
                        "endpoint_template": "https://api.jiejiariapi.com/v1/holidays/{year}",
                        "api_key_env": "JIEJIARI_API_KEY",
                        "api_key_header": "Authorization",
                        "commercial_use_confirmed": True,
                    },
                    http_get=fake_get,
                )
                holiday = get_calendar_day(db_path, "2026-05-01")

        self.assertEqual(result["status"], "ok")
        self.assertTrue(holiday["is_holiday"])
        self.assertEqual(seen_headers[0]["Accept"], "application/json")
        self.assertEqual(seen_headers[0]["User-Agent"], "hotel-ota-ai/1.0")
        self.assertEqual(seen_headers[0]["Authorization"], "secret-key")

    def test_primary_timeout_falls_back_to_jiejiariapi_with_redacted_diagnostics(self) -> None:
        seen: list[tuple[str, dict | None]] = []

        def fake_get(endpoint: str, timeout: float, headers: dict | None = None) -> dict:
            seen.append((endpoint, headers))
            if "apisbo" in endpoint:
                raise TimeoutError("primary timed out with sensitive query should not leak")
            return {"holidays": [{"date": "2026-05-01", "name": "Labor Day"}]}

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "calendar.sqlite")
            result = sync_holiday_provider_cache(
                db_path,
                2026,
                {
                    "provider": "apisbo",
                    "enabled": True,
                    "commercial_use_confirmed": True,
                    "fallback_providers": ["jiejiariapi"],
                    "providers": {
                        "apisbo": {
                            "provider": "apisbo",
                            "endpoint_template": "https://api.apisbo.com/holidays/year/{year}",
                            "commercial_use_confirmed": True,
                        },
                        "jiejiariapi": {
                            "provider": "jiejiariapi",
                            "endpoint_template": "https://api.jiejiariapi.com/v1/holidays/{year}",
                            "commercial_use_confirmed": True,
                        },
                    },
                },
                http_get=fake_get,
            )
            holiday = get_calendar_day(db_path, "2026-05-01")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["provider"], "jiejiariapi")
        self.assertTrue(result["fallback_attempted"])
        self.assertEqual(result["fallback_provider"], "jiejiariapi")
        self.assertEqual(result["provider_diagnostics"][0]["provider"], "apisbo")
        self.assertEqual(result["provider_diagnostics"][0]["error_type"], "TimeoutError")
        self.assertEqual(result["provider_diagnostics"][0]["endpoint_host"], "api.apisbo.com")
        self.assertNotIn("endpoint", result["provider_diagnostics"][0])
        self.assertTrue(holiday["is_holiday"])
        self.assertEqual(seen[0][1]["Accept"], "application/json")
        self.assertEqual(seen[0][1]["User-Agent"], "hotel-ota-ai/1.0")

    def test_primary_timeout_falls_back_to_anonymous_jiejiariapi_as_non_commercial(self) -> None:
        seen: list[tuple[str, dict | None]] = []

        def fake_get(endpoint: str, timeout: float, headers: dict | None = None) -> dict:
            seen.append((endpoint, headers))
            if "apisbo" in endpoint:
                raise TimeoutError("primary unavailable")
            return {"holidays": [{"date": "2026-05-01", "name": "Labor Day"}]}

        with mock.patch.dict(os.environ, {}, clear=True):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = str(Path(tmp) / "calendar.sqlite")
                result = sync_holiday_provider_cache(
                    db_path,
                    2026,
                    {
                        "provider": "apisbo",
                        "enabled": True,
                        "commercial_use_confirmed": True,
                        "fallback_providers": ["jiejiariapi"],
                        "providers": {
                            "apisbo": {
                                "provider": "apisbo",
                                "endpoint_template": "https://api.apisbo.com/holidays/year/{year}",
                                "commercial_use_confirmed": True,
                            },
                            "jiejiariapi": {
                                "provider": "jiejiariapi",
                                "endpoint_template": "https://api.jiejiariapi.com/v1/holidays/{year}",
                                "api_key_env": "JIEJIARI_API_KEY",
                                "api_key_query_param": "key",
                                "allow_anonymous": True,
                                "commercial_use_confirmed": False,
                            },
                        },
                    },
                    http_get=fake_get,
                )
                holiday = get_calendar_day(db_path, "2026-05-01")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["provider"], "jiejiariapi")
        self.assertEqual(result["auth_mode"], "anonymous")
        self.assertEqual(result["source_quality"], "anonymous_free_test")
        self.assertFalse(result["commercial_output_allowed"])
        self.assertTrue(result["fallback_attempted"])
        self.assertNotIn("key=", seen[1][0])
        self.assertEqual(seen[1][1]["Accept"], "application/json")
        self.assertTrue(holiday["is_holiday"])
        self.assertEqual(holiday["source_quality"], "anonymous_free_test")

    def test_jiejiariapi_api_key_query_param_is_confirmed_external(self) -> None:
        seen: list[str] = []

        def fake_get(endpoint: str, timeout: float, headers: dict | None = None) -> dict:
            seen.append(endpoint)
            return {"holidays": [{"date": "2026-10-01", "name": "National Day"}]}

        with mock.patch.dict(os.environ, {"JIEJIARI_API_KEY": "secret-key"}, clear=True):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = str(Path(tmp) / "calendar.sqlite")
                result = sync_holiday_provider_cache(
                    db_path,
                    2026,
                    {
                        "provider": "jiejiariapi",
                        "endpoint_template": "https://api.jiejiariapi.com/v1/holidays/{year}",
                        "api_key_env": "JIEJIARI_API_KEY",
                        "api_key_query_param": "key",
                        "commercial_use_confirmed": True,
                    },
                    http_get=fake_get,
                )
                holiday = get_calendar_day(db_path, "2026-10-01")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["auth_mode"], "api_key")
        self.assertEqual(result["source_quality"], "confirmed_external")
        self.assertTrue(result["commercial_output_allowed"])
        self.assertIn("key=secret-key", seen[0])
        self.assertTrue(holiday["is_holiday"])
        self.assertEqual(holiday["source_quality"], "confirmed_external")

    def test_all_holiday_providers_fail_keeps_builtin_seed_fallback(self) -> None:
        def fake_get(endpoint: str, timeout: float, headers: dict | None = None) -> dict:
            raise TimeoutError("provider unavailable")

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "calendar.sqlite")
            result = sync_holiday_provider_cache(
                db_path,
                2026,
                {
                    "provider": "apisbo",
                    "enabled": True,
                    "commercial_use_confirmed": True,
                    "fallback_providers": ["jiejiariapi"],
                    "providers": {
                        "apisbo": {
                            "provider": "apisbo",
                            "endpoint_template": "https://api.apisbo.com/holidays/year/{year}",
                            "commercial_use_confirmed": True,
                        },
                        "jiejiariapi": {
                            "provider": "jiejiariapi",
                            "endpoint_template": "https://api.jiejiariapi.com/v1/holidays/{year}",
                            "commercial_use_confirmed": True,
                        },
                    },
                },
                http_get=fake_get,
            )
            holiday = get_calendar_day(db_path, "2026-10-01")

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["reason"], "holiday_provider_all_failed")
        self.assertTrue(result["seed_fallback_used"])
        self.assertEqual(result["source_quality"], "project_seed_fallback")
        self.assertEqual(len(result["provider_diagnostics"]), 2)
        self.assertTrue(holiday["is_holiday"])

    def test_calendar_sync_can_select_remote_provider_from_market_source(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "calendar.sqlite")
            config_path = Path(tmp) / "market-source.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "hotels": {
                            "hotel-a": {
                                "holiday": {
                                    "provider": "apisbo",
                                    "commercial_use_confirmed": False,
                                    "providers": {
                                        "apisbo": {
                                            "provider": "apisbo",
                                            "endpoint_template": "https://api.apisbo.com/holidays/year/{year}",
                                        }
                                    },
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            result = _capture_json(
                main,
                [
                    "--db",
                    db_path,
                    "calendar-sync",
                    "--year",
                    "2026",
                    "--market-source-config",
                    str(config_path),
                    "--hotel-id",
                    "hotel-a",
                    "--holiday-provider",
                    "apisbo",
                    "--sync-remote-holidays",
                ],
            )

        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(result["reason"], "holiday_provider_commercial_use_not_confirmed")
        self.assertEqual(result["seed_sync"]["status"], "ok")


if __name__ == "__main__":
    unittest.main()

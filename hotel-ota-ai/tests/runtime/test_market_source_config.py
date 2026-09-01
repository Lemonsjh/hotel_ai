from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.cli import main
from runtime.decisions.calendar import normalize_weather
from tests.test_security_and_freshness import _capture_json


class TestMarketSourceConfig(unittest.TestCase):
    def _write_market_config(self, tmp: str, *, events_path: str | None = None) -> Path:
        config_path = Path(tmp) / "market-source.json"
        config_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "weather": {
                        "provider": "qweather_api",
                        "enabled": True,
                        "location": "101020100",
                        "api_key_env": "QWEATHER_API_KEY",
                    },
                    "events": {
                        "provider": "manual_json",
                        "enabled": True,
                        "path": events_path or str(Path(tmp) / "missing-local-events.json"),
                    },
                    "regional_heat": {
                        "provider": "composite",
                        "enabled": True,
                        "weights": {
                            "event_heat": 0.25,
                            "ota_conversion": 0.25,
                            "historical_same_period": 0.2,
                            "competitor_signal": 0.15,
                            "booking_progress": 0.15,
                        },
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return config_path

    def test_qweather_payload_is_normalized_to_weather_context(self) -> None:
        weather = normalize_weather(
            {"now": {"text": "Light rain", "temp": "8", "precip": "1.2"}},
            "qweather_api",
        )

        self.assertEqual(weather["status"], "ok")
        self.assertEqual(weather["source"], "qweather_api")
        self.assertEqual(weather["source_quality"], "secondary")
        self.assertEqual(weather["weather_risk_level"], "medium")
        self.assertEqual(weather["weather_signal"], "cautious")

    def test_market_context_reports_unconfigured_qweather_without_inventing_weather(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            config_path = self._write_market_config(tmp)
            _capture_json(main, ["--db", db_path, "init-db"])
            with patch.dict(
                os.environ,
                {"HOTEL_OTA_MARKET_SOURCE_CONFIG": str(config_path)},
                clear=True,
            ):
                result = _capture_json(
                    main,
                    [
                        "--db",
                        db_path,
                        "market-context",
                        "--hotel-id",
                        "puyue-demo",
                        "--date",
                        "2026-06-18",
                    ],
                )

        weather = result["weather_context"]
        self.assertEqual(result["status"], "data_gap")
        self.assertEqual(weather["status"], "unavailable")
        self.assertEqual(weather["source"], "qweather_api")
        self.assertEqual(weather["reason"], "weather_provider_not_configured")
        self.assertEqual(result["weather_source"], "qweather_api")
        self.assertNotIn("Sunny", json.dumps(result, ensure_ascii=False))

    def test_event_discover_imports_manual_events_from_market_source_config(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            events_path = Path(tmp) / "local-events.json"
            events_path.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "date": "2026-06-19",
                                "name": "Dragon Boat Market",
                                "event_type": "holiday_market",
                                "location": "nearby mall",
                                "distance_km": 1.2,
                                "confidence": 0.85,
                                "expected_heat": "high",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config_path = self._write_market_config(tmp, events_path=str(events_path))
            _capture_json(main, ["--db", db_path, "init-db"])
            with patch.dict(os.environ, {"HOTEL_OTA_MARKET_SOURCE_CONFIG": str(config_path)}, clear=True):
                result = _capture_json(
                    main,
                    [
                        "--db",
                        db_path,
                        "event-discover",
                        "--hotel-id",
                        "puyue-demo",
                        "--date-range",
                        "2026-06-18..2026-06-21",
                    ],
                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["source"], "manual_json")
        self.assertEqual(result["events_imported"], 1)
        self.assertEqual(result["event_source"], "manual_json")
        self.assertNotIn(str(events_path), json.dumps(result, ensure_ascii=False))

    def test_market_context_composite_heat_is_partial_when_components_are_missing(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            events_path = Path(tmp) / "local-events.json"
            events_path.write_text(
                json.dumps(
                    {"events": [{"date": "2026-06-18", "name": "Local Expo", "expected_heat": "medium", "confidence": 0.8}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config_path = self._write_market_config(tmp, events_path=str(events_path))
            _capture_json(main, ["--db", db_path, "init-db"])
            with patch.dict(os.environ, {"HOTEL_OTA_MARKET_SOURCE_CONFIG": str(config_path)}, clear=True):
                result = _capture_json(
                    main,
                    [
                        "--db",
                        db_path,
                        "market-context",
                        "--hotel-id",
                        "puyue-demo",
                        "--date",
                        "2026-06-18",
                    ],
                )

        heat = result["regional_heat_context"]
        self.assertEqual(result["regional_heat_source"], "composite")
        self.assertEqual(heat["status"], "partial")
        self.assertIn("regional_heat_index", heat)
        self.assertIn("missing_fields", heat)
        self.assertIn("ota_conversion", heat["missing_fields"])
        self.assertEqual(result["calendar_context"]["business_date"], "2026-06-18")

    def test_market_source_config_falls_back_to_default_private_path_when_env_missing(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            config_path = self._write_market_config(tmp)
            _capture_json(main, ["--db", db_path, "init-db"])
            with patch("runtime.market_sources.DEFAULT_MARKET_SOURCE_CONFIG", str(config_path)), patch.dict(os.environ, {}, clear=True):
                result = _capture_json(
                    main,
                    [
                        "--db",
                        db_path,
                        "market-context",
                        "--hotel-id",
                        "puyue-demo",
                        "--date",
                        "2026-06-18",
                    ],
                )

        self.assertEqual(result["weather_source"], "qweather_api")
        self.assertNotEqual(result["weather_context"]["reason"], "market_source_config_not_configured")


if __name__ == "__main__":
    unittest.main()

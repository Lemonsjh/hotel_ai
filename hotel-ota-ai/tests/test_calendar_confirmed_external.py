from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

from runtime.decisions.calendar import market_context
from tests.test_security_and_freshness import _capture_json


class TestCalendarConfirmedExternal(unittest.TestCase):
    def test_confirmed_external_calendar_allows_basic_market_context(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            fixture = Path(tmp) / "calendar.json"
            weather_fixture = Path(tmp) / "weather.json"
            operating_fixture = Path(tmp) / "operating.json"
            fixture.write_text(
                json.dumps(
                    {
                        "business_date": "2026-06-27",
                        "source_quality": "confirmed_external",
                        "demand_level": "normal",
                        "holiday_name": None,
                    }
                ),
                encoding="utf-8",
            )
            weather_fixture.write_text(
                json.dumps({"weather_signal": "normal", "temperature_c": 25, "source_quality": "confirmed"}),
                encoding="utf-8",
            )
            operating_fixture.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "freshness_status": "fresh",
                        "business_status": "current",
                        "occupancy_rate": 0.68,
                    }
                ),
                encoding="utf-8",
            )
            result = _capture_json(
                market_context,
                argparse.Namespace(
                    hotel_id="puyue-demo",
                    db=":memory:",
                    date="2026-06-27",
                    calendar_fixture=str(fixture),
                    weather_provider="weather_fixture",
                    weather_fixture=str(weather_fixture),
                    operating_fixture=str(operating_fixture),
                    progress_fixture=None,
                    market_source_config=None,
                ),
            )

        self.assertTrue(result["context_generation_allowed"])
        self.assertEqual(result["market_context_level"], "basic_environment")
        self.assertIn("calendar", result["used_modules"])


if __name__ == "__main__":
    unittest.main()

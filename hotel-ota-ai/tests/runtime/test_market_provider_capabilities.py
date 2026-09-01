from __future__ import annotations

import unittest
from unittest import mock

from runtime.decisions.calendar import normalize_weather
from runtime.market_sources import build_event_context, call_openclaw_search, call_openclaw_weather, probe_market_provider_capability, resolve_weather_payload


class TestMarketProviderCapabilities(unittest.TestCase):
    def test_openclaw_weather_without_bridge_is_explicitly_unavailable(self) -> None:
        payload, meta = call_openclaw_weather()

        self.assertIsNone(payload)
        self.assertEqual(meta["reason"], "openclaw_weather_capability_not_available")

    def test_openclaw_search_results_are_partial_candidate_context_only(self) -> None:
        candidates, meta = call_openclaw_search(
            capability_call=lambda name, request: {"results": [{"title": "Concert", "url": "https://example.test/event"}]},
            query="hotel activity",
        )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(meta["status"], "partial")
        self.assertFalse(meta["direct_price_trigger_allowed"])

    def test_openclaw_configured_market_sources_degrade_without_inventing_external_facts(self) -> None:
        config = {
            "status": "ok",
            "hotels": {
                "hotel-a": {
                    "weather": {"provider": "openclaw_weather", "enabled": True},
                    "events": {"provider": "openclaw_search", "enabled": True},
                    "regional_heat": {"provider": "composite", "enabled": True},
                }
            },
        }
        payload, provider, reason = resolve_weather_payload(config, hotel_id="hotel-a")
        events = build_event_context(config, hotel_id="hotel-a", business_date="2026-06-24")

        self.assertIsNone(payload)
        self.assertEqual(provider, "openclaw_weather")
        self.assertEqual(reason, "openclaw_weather_capability_not_available")
        self.assertEqual(events["status"], "data_gap")
        self.assertEqual(events["source"], "openclaw_search")
    def test_unconfigured_openclaw_provider_is_explicitly_unavailable(self) -> None:
        result = probe_market_provider_capability("openclaw_weather", capabilities={})

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "openclaw_weather_capability_not_available")

    def test_declared_search_provider_is_candidate_only(self) -> None:
        result = probe_market_provider_capability("openclaw_search", capabilities={"openclaw_search": True})

        self.assertTrue(result["available"])
        self.assertEqual(result["field_quality"], "search_inferred")
        self.assertEqual(result["decision_effect"], "confidence_only")

    def test_wttr_weather_provider_is_no_key_fallback_when_location_is_configured(self) -> None:
        config = {
            "status": "ok",
            "hotels": {
                "hotel-a": {
                    "weather": {"provider": "wttr_http", "enabled": True, "location": "Shanghai"},
                    "events": {"provider": "manual_json", "enabled": False},
                    "regional_heat": {"provider": "composite", "enabled": True},
                }
            },
        }
        with mock.patch(
            "runtime.market_sources._wttr_now",
            return_value={"current_condition": [{"weatherDesc": [{"value": "Light rain"}], "temp_C": "8"}]},
        ):
            payload, provider, reason = resolve_weather_payload(config, hotel_id="hotel-a")

        self.assertEqual(provider, "wttr_http")
        self.assertIsNone(reason)
        self.assertEqual(payload["current_condition"][0]["temp_C"], "8")

    def test_open_meteo_provider_normalizes_wmo_weather_code(self) -> None:
        config = {
            "status": "ok",
            "hotels": {
                "hotel-a": {
                    "weather": {
                        "provider": "open_meteo",
                        "enabled": True,
                        "latitude": 26.57,
                        "longitude": 106.71,
                        "timezone": "Asia/Shanghai",
                        "display_location": "Guiyang",
                    },
                    "events": {"provider": "manual_json", "enabled": False},
                    "regional_heat": {"provider": "composite", "enabled": True},
                }
            },
        }
        payload = {
            "current": {
                "time": "2026-06-26T16:45",
                "weather_code": 3,
                "temperature_2m": 22.4,
                "apparent_temperature": 22.1,
                "precipitation": 0,
                "rain": 0,
                "showers": 0,
                "cloud_cover": 95,
                "wind_speed_10m": 6.5,
            }
        }
        with mock.patch("runtime.market_sources._open_meteo_now", return_value=payload):
            resolved, provider, reason = resolve_weather_payload(config, hotel_id="hotel-a")

        weather = normalize_weather(resolved, provider)
        self.assertEqual(provider, "open_meteo")
        self.assertIsNone(reason)
        self.assertEqual(weather["weather_code"], 3)
        self.assertEqual(weather["weather_text"], "overcast")
        self.assertEqual(weather["weather_signal"], "neutral")
        self.assertEqual(weather["weather_risk_level"], "low")

    def test_open_meteo_requires_coordinates_without_silent_default(self) -> None:
        config = {
            "status": "ok",
            "hotels": {
                "hotel-a": {
                    "weather": {"provider": "open_meteo", "enabled": True, "display_location": "Guiyang"},
                }
            },
        }

        payload, provider, reason = resolve_weather_payload(config, hotel_id="hotel-a")

        self.assertIsNone(payload)
        self.assertEqual(provider, "open_meteo")
        self.assertEqual(reason, "weather_coordinates_not_configured")

    def test_open_meteo_distinguishes_drizzle_from_heavy_rain(self) -> None:
        weather = normalize_weather(
            {
                "current": {
                    "time": "2026-06-26T17:00",
                    "weather_code": 51,
                    "temperature_2m": 21,
                    "apparent_temperature": 21,
                    "precipitation": 0.2,
                    "rain": 0,
                    "showers": 0,
                },
                "display_location": "Guiyang",
            },
            "open_meteo",
        )

        self.assertEqual(weather["weather_text"], "drizzle")
        self.assertEqual(weather["weather_signal"], "cautious")
        self.assertEqual(weather["weather_risk_level"], "medium")

    def test_open_meteo_failure_can_fallback_to_wttr_without_masking_source(self) -> None:
        config = {
            "status": "ok",
            "hotels": {
                "hotel-a": {
                    "weather": {
                        "provider": "open_meteo",
                        "enabled": True,
                        "latitude": 26.57,
                        "longitude": 106.71,
                        "timezone": "Asia/Shanghai",
                        "location": "Guiyang",
                        "fallback_providers": ["wttr_http"],
                    },
                }
            },
        }
        with mock.patch("runtime.market_sources._open_meteo_now", side_effect=TimeoutError):
            with mock.patch(
                "runtime.market_sources._wttr_now",
                return_value={"current_condition": [{"weatherDesc": [{"value": "Cloudy"}], "temp_C": "22"}]},
            ):
                payload, provider, reason = resolve_weather_payload(config, hotel_id="hotel-a")

        self.assertEqual(provider, "open_meteo_failed_fallback_wttr_http")
        self.assertIsNone(reason)
        self.assertEqual(payload["current_condition"][0]["temp_C"], "22")

    def test_open_meteo_uses_tenant_coordinates_per_hotel(self) -> None:
        config = {
            "status": "ok",
            "hotels": {
                "hotel-a": {
                    "weather": {"provider": "open_meteo", "enabled": True, "latitude": 26.1, "longitude": 106.1},
                },
                "hotel-b": {
                    "weather": {"provider": "open_meteo", "enabled": True, "latitude": 31.2, "longitude": 121.5},
                },
            },
        }
        seen: list[tuple[float, float]] = []

        def fake_open_meteo(weather_config: dict) -> dict:
            seen.append((float(weather_config["latitude"]), float(weather_config["longitude"])))
            return {"current": {"weather_code": 0, "temperature_2m": 25}}

        with mock.patch("runtime.market_sources._open_meteo_now", side_effect=fake_open_meteo):
            resolve_weather_payload(config, hotel_id="hotel-a")
            resolve_weather_payload(config, hotel_id="hotel-b")

        self.assertEqual(seen, [(26.1, 106.1), (31.2, 121.5)])


if __name__ == "__main__":
    unittest.main()

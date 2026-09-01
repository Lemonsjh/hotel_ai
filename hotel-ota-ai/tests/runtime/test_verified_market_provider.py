from __future__ import annotations

import os
import unittest

from runtime.market_sources import (
    _EVENT_CACHE,
    build_regional_heat_context,
    load_verified_http_events,
    market_config_for_hotel,
    resolve_weather_payload,
)


class TestVerifiedMarketProvider(unittest.TestCase):
    def setUp(self) -> None:
        _EVENT_CACHE.clear()
        self._old = os.environ.get("HOTEL_OTA_EVENT_TOKEN")
        os.environ["HOTEL_OTA_EVENT_TOKEN"] = "test-token"
        self.config = {
            "status": "ok",
            "hotels": {
                "hotel-a": {
                    "events": {
                        "provider": "verified_http_json",
                        "endpoint": "https://events.example.test/v1/events",
                        "bearer_token_env": "HOTEL_OTA_EVENT_TOKEN",
                        "cache_ttl_seconds": 21600,
                    }
                }
            },
        }

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("HOTEL_OTA_EVENT_TOKEN", None)
        else:
            os.environ["HOTEL_OTA_EVENT_TOKEN"] = self._old

    def test_tenant_market_config_does_not_fall_back_to_another_hotel(self) -> None:
        resolved = market_config_for_hotel(self.config, "hotel-b")

        self.assertEqual(resolved["status"], "data_gap")
        self.assertEqual(resolved["reason"], "tenant_market_config_not_found")

    def test_weather_and_regional_heat_do_not_fall_back_across_tenants(self) -> None:
        config = {
            **self.config,
            "weather": {"provider": "weather_fixture", "path": "root-only.json"},
            "regional_heat": {"provider": "composite"},
        }

        _, _provider, weather_reason = resolve_weather_payload(config, hotel_id="hotel-b")
        heat = build_regional_heat_context(config, hotel_id="hotel-b", event_context={"status": "ok"})

        self.assertEqual(weather_reason, "tenant_market_config_not_found")
        self.assertEqual(heat["status"], "data_gap")
        self.assertEqual(heat["reason"], "tenant_market_config_not_found")

    def test_verified_provider_rejects_invalid_transport_or_schema(self) -> None:
        insecure = {**self.config, "hotels": {"hotel-a": {"events": {**self.config["hotels"]["hotel-a"]["events"], "endpoint": "http://events.example.test"}}}}
        _, transport_meta = load_verified_http_events(insecure, hotel_id="hotel-a", business_date="2026-06-23")
        _, schema_meta = load_verified_http_events(
            self.config,
            hotel_id="hotel-a",
            business_date="2026-06-23",
            http_get=lambda *_: {"source_id": "events-a", "fetched_at": "2026-06-23T10:00:00", "events": [{"event_id": "x"}]},
        )

        self.assertEqual(transport_meta["reason"], "event_provider_https_required")
        self.assertEqual(schema_meta["reason"], "event_provider_invalid_schema")

    def test_verified_provider_uses_valid_schema_without_exposing_credentials(self) -> None:
        events, meta = load_verified_http_events(
            self.config,
            hotel_id="hotel-a",
            business_date="2026-06-23",
            http_get=lambda *_: {
                "source_id": "events-a",
                "fetched_at": "2026-06-23T10:00:00",
                "events": [
                    {
                        "event_id": "evt-1",
                        "date": "2026-06-23",
                        "event_name": "Concert",
                        "confidence": 0.9,
                        "source_url": "https://events.example.test/e/1",
                    }
                ],
            },
        )

        self.assertEqual(meta["status"], "ok")
        self.assertEqual(events[0]["event_name"], "Concert")
        self.assertEqual(events[0]["event_id"], "evt-1")
        self.assertNotIn("test-token", str(meta))

    def test_verified_provider_uses_fresh_cache_and_marks_expired_cache_partial(self) -> None:
        calls = []

        def ok_get(*_args):
            calls.append("ok")
            return {
                "source_id": "events-cache",
                "fetched_at": "2026-06-23T10:00:00",
                "events": [
                    {
                        "event_id": "evt-cache",
                        "date": "2026-06-23",
                        "event_name": "Cached concert",
                        "confidence": 0.9,
                        "source_url": "https://events.example.test/e/cache",
                    }
                ],
            }

        events, first = load_verified_http_events(self.config, hotel_id="hotel-a", business_date="2026-06-23", http_get=ok_get)
        cached_events, cached = load_verified_http_events(
            self.config,
            hotel_id="hotel-a",
            business_date="2026-06-23",
            http_get=lambda *_: self.fail("fresh cache should avoid a second HTTP request"),
        )
        self.assertEqual(first["status"], "ok")
        self.assertEqual(cached["cache_status"], "fresh_cache")
        self.assertEqual(events, cached_events)
        self.assertEqual(calls, ["ok"])

        expired = {
            **self.config,
            "hotels": {
                "hotel-a": {
                    "events": {
                        **self.config["hotels"]["hotel-a"]["events"],
                        "endpoint": "https://events-expired.example.test/v1/events",
                        "cache_ttl_seconds": 0,
                    }
                }
            },
        }
        load_verified_http_events(expired, hotel_id="hotel-a", business_date="2026-06-23", http_get=ok_get)
        stale_events, stale = load_verified_http_events(
            expired,
            hotel_id="hotel-a",
            business_date="2026-06-23",
            http_get=lambda *_: (_ for _ in ()).throw(TimeoutError()),
        )
        self.assertEqual(stale["status"], "partial")
        self.assertEqual(stale["reason"], "event_provider_stale_cache")
        self.assertTrue(stale["stale"])
        self.assertEqual(stale_events[0]["event_id"], "evt-cache")


if __name__ == "__main__":
    unittest.main()

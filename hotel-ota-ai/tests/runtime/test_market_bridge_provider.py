from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from runtime.market_sources import build_event_context


class _BridgeHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        _ = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        payload = {
            "service_id": "hotel-ota-event-search-bridge",
            "source_type": "verified_search",
            "generated_at": "2026-06-25T09:00:00+08:00",
            "results": [
                {
                    "title": "Huaxi Music Weekend",
                    "url": "https://events.example.test/huaxi-music-weekend",
                    "date": "2026-06-25",
                    "location": "Huaxi District",
                    "confidence": 0.72,
                    "expected_heat": "medium",
                }
            ],
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


class TestMarketBridgeProvider(unittest.TestCase):
    def test_unconfigured_events_expose_event_data_gap_semantics(self) -> None:
        context = build_event_context(
            {"status": "missing", "reason": "market_source_config_not_configured"},
            business_date="2026-06-30",
            hotel_id="hotel-a",
        )

        self.assertEqual(context["status"], "data_gap")
        self.assertEqual(context["data_gap_type"], "event_data_gap")
        self.assertTrue(context["event_data_gap"])
        self.assertEqual(context["local_event_count"], 0)
        self.assertFalse(context["direct_price_trigger_allowed"])

    def test_openclaw_bridge_rejects_non_localhost_endpoint(self) -> None:
        context = build_event_context(
            {
                "status": "ok",
                "events": {
                    "provider": "openclaw_bridge_http_search",
                    "endpoint": "https://events.example.com/search",
                },
            },
            business_date="2026-06-25",
            hotel_id="puyue",
        )
        self.assertEqual(context["status"], "data_gap")
        self.assertEqual(context["reason"], "market_bridge_endpoint_not_localhost")

    def test_openclaw_bridge_requires_trusted_handshake(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), _BridgeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            context = build_event_context(
                {
                    "status": "ok",
                    "events": {
                        "provider": "openclaw_bridge_http_search",
                        "endpoint": f"http://127.0.0.1:{server.server_port}/search",
                        "query_template": "{business_date} {hotel_id} nearby events",
                        "timeout_seconds": 2,
                    },
                },
                business_date="2026-06-25",
                hotel_id="puyue",
            )
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(context["status"], "data_gap")
        self.assertEqual(context["reason"], "market_bridge_token_not_configured")

    def test_openclaw_bridge_returns_verified_partial_candidates_without_price_trigger(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), _BridgeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.dict("os.environ", {"HOTEL_OTA_EVENT_BRIDGE_TOKEN": "secret-token"}):
                context = build_event_context(
                    {
                        "status": "ok",
                        "events": {
                            "provider": "openclaw_bridge_http_search",
                            "endpoint": f"http://127.0.0.1:{server.server_port}/search",
                            "query_template": "{business_date} {hotel_id} nearby events",
                            "timeout_seconds": 2,
                            "bearer_token_env": "HOTEL_OTA_EVENT_BRIDGE_TOKEN",
                            "expected_service_id": "hotel-ota-event-search-bridge",
                        },
                    },
                    business_date="2026-06-25",
                    hotel_id="puyue",
                )
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(context["status"], "partial")
        self.assertEqual(context["event_source"], "openclaw_bridge_http_search")
        self.assertEqual(context["field_quality"], "search_inferred")
        self.assertEqual(context["source_quality"], "partial_verified")
        self.assertFalse(context["direct_price_trigger_allowed"])
        self.assertEqual(context["event_candidates"][0]["event_name"], "Huaxi Music Weekend")


if __name__ == "__main__":
    unittest.main()

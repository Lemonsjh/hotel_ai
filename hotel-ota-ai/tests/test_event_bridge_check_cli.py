from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from runtime.cli import main
from tests.test_security_and_freshness import _capture_json


class _BridgeHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        _ = self.rfile.read(int(self.headers.get("Content-Length", "0") or "0"))
        body = json.dumps(
            {
                "service_id": "hotel-ota-event-search-bridge",
                "source_type": "verified_search",
                "source_id": "test-bridge",
                "fetched_at": "2026-06-27T10:00:00+08:00",
                "events": [
                    {
                        "event_id": "evt-bridge-1",
                        "date": "2026-06-27",
                        "event_name": "Local Business Expo",
                        "event_type": "exhibition",
                        "location": "nearby center",
                        "source_url": "https://events.example.test/expo",
                        "confidence": 0.72,
                        "expected_heat": "medium",
                        "status": "candidate",
                    }
                ],
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object) -> None:
        return


class TestEventBridgeCheckCli(unittest.TestCase):
    def test_event_bridge_check_reports_disabled_as_non_blocking_data_gap(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            config_path = Path(tmp) / "market-source.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "hotels": {
                            "xingfeng": {
                                "events": {
                                    "provider": "openclaw_bridge_http_search",
                                    "enabled": False,
                                    "endpoint": "http://127.0.0.1:8787/search",
                                    "bearer_token_env": "HOTEL_OTA_EVENT_BRIDGE_CREDENTIAL",
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
                    "event-bridge-check",
                    "--hotel-id",
                    "xingfeng",
                    "--date",
                    "2026-06-27",
                    "--market-source-config",
                    str(config_path),
                ],
            )

        self.assertEqual(result["status"], "data_gap")
        self.assertTrue(result["bridge_configured"])
        self.assertFalse(result["bridge_enabled"])
        self.assertTrue(result["endpoint_localhost"])
        self.assertEqual(result["token_status"], "missing")
        self.assertFalse(result["commercial_output_allowed"])

    def test_env_check_includes_event_bridge_status_without_token_value(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            config_path = Path(tmp) / "market-source.json"
            config_path.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "hotels": {
                            "xingfeng": {
                                "events": {
                                    "provider": "openclaw_bridge_http_search",
                                    "enabled": True,
                                    "endpoint": "http://127.0.0.1:8787/search",
                                    "bearer_token_env": "HOTEL_OTA_EVENT_BRIDGE_CREDENTIAL",
                                    "expected_service_id": "hotel-ota-event-search-bridge",
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {
                    "HOTEL_OTA_MARKET_SOURCE_CONFIG": str(config_path),
                    "HOTEL_OTA_EVENT_BRIDGE_CREDENTIAL": "secret-token-value",
                },
                clear=True,
            ):
                result = _capture_json(main, ["env-check"])

        text = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["event_bridge_status"]["provider"], "openclaw_bridge_http_search")
        self.assertTrue(result["event_bridge_status"]["enabled"])
        self.assertEqual(result["event_bridge_status"]["token_status"], "set")
        self.assertNotIn("secret-token-value", text)

    def test_event_discover_uses_openclaw_bridge_http_search(self) -> None:
        server = HTTPServer(("127.0.0.1", 0), _BridgeHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                db_path = str(Path(tmp) / "hotel_ops.sqlite")
                config_path = Path(tmp) / "market-source.json"
                config_path.write_text(
                    json.dumps(
                        {
                            "version": 3,
                            "hotels": {
                                "xingfeng": {
                                    "events": {
                                        "provider": "openclaw_bridge_http_search",
                                        "enabled": True,
                                        "endpoint": f"http://127.0.0.1:{server.server_port}/search",
                                        "bearer_token_env": "HOTEL_OTA_EVENT_BRIDGE_CREDENTIAL",
                                        "expected_service_id": "hotel-ota-event-search-bridge",
                                    }
                                }
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                _capture_json(main, ["--db", db_path, "init-db"])
                with mock.patch.dict(os.environ, {"HOTEL_OTA_EVENT_BRIDGE_CREDENTIAL": "secret-token-value"}, clear=True):
                    result = _capture_json(
                        main,
                        [
                            "--db",
                            db_path,
                            "event-discover",
                            "--hotel-id",
                            "xingfeng",
                            "--date-range",
                            "2026-06-27..2026-06-28",
                            "--market-source-config",
                            str(config_path),
                        ],
                    )
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["event_source"], "openclaw_bridge_http_search")
        self.assertEqual(result["events_imported"], 1)


if __name__ == "__main__":
    unittest.main()

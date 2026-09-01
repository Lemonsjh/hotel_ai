from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

SERVICE_ID = "hotel-ota-event-search-bridge"
SOURCE_TYPE = "verified_search"


def _load_fixture(path: str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    events = payload.get("events") if isinstance(payload, dict) else payload
    return events if isinstance(events, list) else []


def build_search_response(*, hotel_id: str, business_date: str, fixture_path: str | None = None) -> dict[str, Any]:
    return {
        "service_id": SERVICE_ID,
        "source_type": SOURCE_TYPE,
        "source_id": "local_development_stub",
        "fetched_at": business_date,
        "hotel_id": hotel_id,
        "business_date": business_date,
        "events": _load_fixture(fixture_path),
        "notice": "local development stub only; not a production trusted event source",
    }


class EventSearchBridgeHandler(BaseHTTPRequestHandler):
    fixture_path: str | None = None

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self.send_error(404)
            return
        self._send_json({"status": "ok", "service_id": SERVICE_ID, "source_type": SOURCE_TYPE})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/search":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            payload = {}
        self._send_json(
            build_search_response(
                hotel_id=str(payload.get("hotel_id") or "unknown"),
                business_date=str(payload.get("business_date") or ""),
                fixture_path=self.fixture_path,
            )
        )

    def log_message(self, *_args: object) -> None:
        return

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local development stub for hotel OTA event search bridge.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--fixture")
    args = parser.parse_args(argv)
    EventSearchBridgeHandler.fixture_path = args.fixture
    server = HTTPServer((args.host, args.port), EventSearchBridgeHandler)
    print(f"event_search_bridge_stub listening on http://{args.host}:{args.port}")  # noqa: T201
    server.serve_forever()


if __name__ == "__main__":
    main()

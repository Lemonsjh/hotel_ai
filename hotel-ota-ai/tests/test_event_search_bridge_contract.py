from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.event_search_bridge_stub import build_search_response


class TestEventSearchBridgeContract(unittest.TestCase):
    def test_stub_returns_contract_shape_and_empty_events_by_default(self) -> None:
        payload = build_search_response(hotel_id="xingfeng", business_date="2026-06-27")

        self.assertEqual(payload["service_id"], "hotel-ota-event-search-bridge")
        self.assertEqual(payload["source_type"], "verified_search")
        self.assertEqual(payload["events"], [])
        self.assertIn("not a production trusted event source", payload["notice"])

    def test_stub_can_load_fixture_without_rewriting_contract(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            fixture = Path(tmp) / "events.json"
            fixture.write_text(
                json.dumps(
                    {
                        "events": [
                            {
                                "event_id": "evt-1",
                                "date": "2026-06-27",
                                "event_name": "Local Concert",
                                "source_url": "https://example.test/event",
                                "confidence": 0.7,
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = build_search_response(hotel_id="xingfeng", business_date="2026-06-27", fixture_path=str(fixture))

        self.assertEqual(payload["events"][0]["event_id"], "evt-1")
        self.assertEqual(payload["service_id"], "hotel-ota-event-search-bridge")


if __name__ == "__main__":
    unittest.main()

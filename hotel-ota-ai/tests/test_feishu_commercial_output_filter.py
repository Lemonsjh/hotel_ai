from __future__ import annotations

import unittest

from runtime.feishu_output_renderer import render_feishu_output


class TestFeishuCommercialOutputFilter(unittest.TestCase):
    def test_business_calendar_hides_optional_event_gap_details(self) -> None:
        rendered = render_feishu_output(
            {
                "intent": "business_calendar",
                "business_date": "2026-06-27",
                "market_context_status": "partial",
                "holiday_source": "builtin_project_seed",
                "event_source": "openclaw_bridge_http_search",
                "weather_source": "manual_weather",
                "regional_heat_source": "composite",
                "event_context": {"status": "data_gap", "local_event_count": 0, "reason": "market_bridge_token_not_configured"},
                "weather_context": {"status": "ok", "weather_signal": "neutral", "weather_risk_level": "low"},
                "regional_heat_context": {"status": "partial", "regional_heat_index": 52, "missing_fields": ["ota_conversion"]},
                "event_discovery_reason": "market_bridge_token_not_configured",
                "regional_heat_missing_fields": ["ota_conversion"],
            },
            "owner_business",
        )

        text = rendered["text"]
        self.assertIn("S4", text)
        self.assertNotIn("market_bridge_token_not_configured", text)
        self.assertNotIn("missing_fields", text)
        self.assertNotIn("regional_heat_missing_fields", text)
        self.assertNotIn("Gaps", text)


if __name__ == "__main__":
    unittest.main()

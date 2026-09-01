from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.cli import main
from runtime.decisions.calendar import get_calendar_day, load_holiday_seed
from runtime.feishu_command_router import safe_route_feishu_command
from runtime.safety.auth import bootstrap_active_auth


BUSINESS_CALENDAR = "\u4e1a\u52a1\u65e5\u5386"
HOLIDAY_CALENDAR = "\u8282\u5047\u65e5\u65e5\u5386"
EVENT_CALENDAR = "\u6d3b\u52a8\u65e5\u5386"
NEARBY_EVENTS = "\u5468\u8fb9\u6d3b\u52a8"
REGIONAL_HEAT = "\u5546\u5708\u70ed\u5ea6"
WEATHER_IMPACT = "\u5929\u6c14\u5f71\u54cd"


def _capture_cli(args: list[str]) -> dict:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(args)
    payload = json.loads(buffer.getvalue())
    payload["_exit_code"] = code
    return payload


class TestFeishuBusinessCalendar(unittest.TestCase):
    def _auth_config(self, tmp: str, *, allowed_chat_ids: list[str] | None = None) -> Path:
        path = Path(tmp) / "feishu-role-map.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "default_policy": "deny_unknown",
                    "allowed_chat_ids": allowed_chat_ids or ["oc_allowed"],
                    "users": [
                        {
                            "name": "admin",
                            "role": "admin",
                            "open_id": "ou_admin",
                            "feishu_open_id": "ou_admin",
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return path

    def test_naked_user_role_admin_is_blocked_for_business_calendar(self) -> None:
        result = _capture_cli(["feishu-route", "--message", BUSINESS_CALENDAR, "--user-role", "admin", "--render"])

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["intent"], "business_calendar")
        self.assertEqual(result["blocked_reason"], "missing_required_feishu_auth_context")
        self.assertTrue(result["trusted_runtime_role_required"])
        self.assertFalse(result["business_result_generated"])
        self.assertEqual(result["rendered"]["template"], "guest_limited")
        self.assertNotIn("holiday_source", result["send_payload"]["text"])

    def test_business_calendar_authorizes_from_open_id_chat_id_and_role_map(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            auth_path = self._auth_config(tmp)
            result = safe_route_feishu_command(
                BUSINESS_CALENDAR,
                open_id="ou_admin",
                chat_id="oc_allowed",
                auth_config=str(auth_path),
                render=True,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["intent"], "business_calendar")
        self.assertEqual(result["auth_role"], "admin")
        self.assertIn("holiday_source", result)
        self.assertIn("event_source", result)
        self.assertIn("weather_source", result)
        self.assertIn("regional_heat_source", result)
        rendered_text = result["send_payload"]["text"]
        self.assertIn("holiday_source", rendered_text)
        self.assertIn("event_source", rendered_text)
        self.assertIn("weather_source", rendered_text)
        self.assertNotIn(str(auth_path), rendered_text)
        self.assertNotIn("ou_admin", rendered_text)
        self.assertNotIn("oc_allowed", rendered_text)

    def test_chat_not_allowed_is_blocked_not_guest_fallback(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            auth_path = self._auth_config(tmp, allowed_chat_ids=["oc_allowed"])
            result = safe_route_feishu_command(
                BUSINESS_CALENDAR,
                open_id="ou_admin",
                chat_id="oc_not_allowed",
                auth_config=str(auth_path),
                render=True,
            )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["intent"], "business_calendar")
        self.assertEqual(result["blocked_reason"], "chat_not_allowed")
        self.assertEqual(result["auth_status"], "unauthorized")
        self.assertFalse(result["business_result_generated"])

    def test_business_calendar_natural_language_phrases_are_runtime_backed(self) -> None:
        phrases = [
            BUSINESS_CALENDAR,
            HOLIDAY_CALENDAR,
            EVENT_CALENDAR,
            NEARBY_EVENTS,
            REGIONAL_HEAT,
            WEATHER_IMPACT,
        ]
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            auth_path = self._auth_config(tmp)
            for phrase in phrases:
                with self.subTest(phrase=phrase):
                    result = safe_route_feishu_command(
                        phrase,
                        open_id="ou_admin",
                        chat_id="oc_allowed",
                        auth_config=str(auth_path),
                    )

                    self.assertEqual(result["intent"], "business_calendar")
                    self.assertIn(result["status"], {"ok", "partial", "data_gap"})
                    self.assertEqual(result["runtime_command"], "market-context")
                    self.assertIn("holiday_source", result)
                    self.assertIn("event_source", result)
                    self.assertIn("weather_source", result)
                    self.assertIn("regional_heat_source", result)

    def test_builtin_holiday_seed_file_is_used_without_remote_sync(self) -> None:
        seed = load_holiday_seed(2026)

        self.assertIn("2026-09-25", seed)
        self.assertEqual(seed["2026-09-25"]["holiday_group"], "\u4e2d\u79cb\u8282")
        self.assertIn("2026-10-01", seed)
        self.assertEqual(seed["2026-10-01"]["holiday_group"], "\u56fd\u5e86\u8282")
        self.assertEqual(seed["2026-09-25"]["source"], "apisbo_holidays_year_2026_manual_seed")

    def test_calendar_query_prefers_seed_file_for_fixed_holidays(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db_path = str(Path(tmp) / "calendar.sqlite")
            mid_autumn = get_calendar_day(db_path, "2026-09-25")
            national_day = get_calendar_day(db_path, "2026-10-01")

        self.assertTrue(mid_autumn["is_holiday"])
        self.assertEqual(mid_autumn["holiday_group"], "\u4e2d\u79cb\u8282")
        self.assertEqual(mid_autumn["source"], "apisbo_holidays_year_2026_manual_seed")
        self.assertTrue(national_day["is_holiday"])
        self.assertEqual(national_day["holiday_group"], "\u56fd\u5e86\u8282")
        self.assertEqual(national_day["source"], "apisbo_holidays_year_2026_manual_seed")

    def test_s4_alias_routes_to_market_context_with_configured_sources(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            auth_path = self._auth_config(tmp)
            db_path = str(Path(tmp) / "hotel_ops.sqlite")
            market_path = Path(tmp) / "market-source.json"
            market_path.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "hotels": {
                            "puyue-demo": {
                                "weather": {"provider": "wttr_http", "enabled": True, "location": "Guiyang"},
                                "events": {
                                    "provider": "openclaw_bridge_http_search",
                                    "enabled": True,
                                    "endpoint": "http://127.0.0.1:8787/search",
                                },
                                "regional_heat": {"provider": "composite", "enabled": True},
                            }
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            weather_payload = {"current_condition": [{"weatherDesc": [{"value": "Cloudy"}], "temp_C": "22", "precipMM": "0"}]}
            event_candidates = [
                {"date": "2026-06-26", "name": "商圈活动", "expected_heat": "medium", "confidence": 0.7}
            ]
            with patch.dict("os.environ", {"HOTEL_OTA_MARKET_SOURCE_CONFIG": str(market_path)}, clear=True), patch(
                "runtime.market_sources._wttr_now", return_value=weather_payload
            ), patch(
                "runtime.market_sources.load_openclaw_bridge_events",
                return_value=(
                    event_candidates,
                    {
                        "status": "partial",
                        "source": "openclaw_bridge_http_search",
                        "event_source": "openclaw_bridge_http_search",
                        "field_quality": "search_inferred",
                        "source_quality": "partial",
                        "direct_price_trigger_allowed": False,
                    },
                ),
            ):
                result = safe_route_feishu_command(
                    "s4",
                    db_path=db_path,
                    open_id="ou_admin",
                    chat_id="oc_allowed",
                    chat_type="group",
                    auth_config=str(auth_path),
                    production_feishu=True,
                    render=True,
                    hotel_id="puyue-demo",
                )

        self.assertEqual(result["intent"], "market_context_demo")
        self.assertEqual(result["runtime_command"], "market-context")
        self.assertEqual(result["weather_source"], "wttr_http")
        self.assertEqual(result["event_source"], "openclaw_bridge_http_search")
        self.assertFalse(result["direct_price_trigger_allowed"])
        self.assertIn("wttr_http", result["send_payload"]["text"])
        self.assertNotIn("QWeather 未配置", result["send_payload"]["text"])

    def test_s4_bound_v3_group_uses_resolved_hotel_and_market_template(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            auth_path = root / "role-map-v3.json"
            db_path = str(root / "hotel_ops.sqlite")
            auth_path.write_text(
                json.dumps(
                    {
                        "version": 3,
                        "direct_message_policy": "role_mapped_users_only",
                        "global_admin_principal_ids": ["admin-1"],
                        "users": [{"principal_id": "admin-1", "open_id": "ou_admin"}],
                        "hotel_memberships": [{"principal_id": "admin-1", "hotel_id": "puyue", "role": "owner"}],
                        "group_chat_bindings": [{"chat_id": "oc_allowed", "hotel_id": "puyue"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            bootstrap_active_auth(db_path, config_path=str(auth_path))
            result = safe_route_feishu_command(
                "s4",
                db_path=db_path,
                open_id="ou_admin",
                chat_id="chat:oc_allowed",
                chat_type="group",
                auth_config=str(auth_path),
                production_feishu=True,
                render=True,
            )

        self.assertEqual(result["intent"], "market_context_demo")
        self.assertEqual(result["hotel_id"], "puyue")
        self.assertEqual(result["resolved_hotel_id"], "puyue")
        self.assertEqual(result["rendered"]["template"], "market_context_demo")
        self.assertIn("weather_source", result["send_payload"]["text"])
        self.assertIn("event_source", result["send_payload"]["text"])
        self.assertIn("direct_price_trigger_allowed=false", result["send_payload"]["text"])
        self.assertNotIn("总房量：None", result["send_payload"]["text"])
        self.assertNotIn("ADR：None", result["send_payload"]["text"])


if __name__ == "__main__":
    unittest.main()

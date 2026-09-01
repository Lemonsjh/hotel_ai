from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from runtime.s2_historical_daily_source_patch import (
    HISTORICAL_CONTRACT,
    HISTORICAL_SOURCE_TABLE,
    _build_historical_snapshot_result,
    _is_historical_business_date,
    render_historical_s2_reply,
)


class S2HistoricalDailySourceTests(unittest.TestCase):
    def test_date_classifier_routes_only_past_business_dates(self) -> None:
        now = datetime(2026, 8, 7, 13, 0, tzinfo=timezone(timedelta(hours=8)))
        self.assertTrue(_is_historical_business_date("2026-08-06", now=now))
        self.assertFalse(_is_historical_business_date("2026-08-07", now=now))
        self.assertFalse(_is_historical_business_date("2026-08-08", now=now))

    def _fake_router(self, *, data_business_date: str = "2026-08-06") -> tuple[SimpleNamespace, list[tuple[str, str, dict[str, object]]]]:
        calls: list[tuple[str, str, dict[str, object]]] = []

        def database_template_result(template: str, hotel_id: str, **kwargs: object) -> dict[str, object]:
            calls.append((template, hotel_id, dict(kwargs)))
            if template == "daily_metrics":
                return {
                    "status": "ok",
                    "data_source_type": "mysql_db",
                    "source_mode": "mysql_runtime",
                    "payload": {
                        "hotel_name": "Example Hotel",
                        "data_business_date": data_business_date,
                        "data_snapshot_time": f"{data_business_date} 23:59:00",
                        "freshness_status": "historical_complete",
                        "normalized_metrics": {
                            "room_count": 31,
                            "sold_rooms": 20,
                            "remaining_rooms": 11,
                            "room_nights": 20,
                            "room_revenue": 4200,
                            "orders_today": 18,
                            "occupancy_rate": 64.52,
                            "adr": 210,
                            "revpar": 135.48,
                        },
                    },
                }
            return {
                "status": "ok",
                "payload": {"source_status": "ok", "rows": []},
            }

        def load_s2_optional_results(query, *, hotel_id: str, business_date: str, as_of_time: str | None):
            self.assertEqual(business_date, "2026-08-06")
            return {
                "flow_conversion": {
                    "status": "ok",
                    "_s2_requested_business_date": "2026-08-06",
                    "_s2_source_table": "meituan_ota_business_metrics",
                    "payload": {
                        "source_status": "ok",
                        "rows": [
                            {
                                "channel_source": "meituan",
                                "business_date": "2026-08-06",
                                "snapshot_time": "2026-08-06 23:30:00",
                                "metric_code": "FLOW_EXPOSURE_UV",
                                "metric_name": "曝光人数",
                                "metric_value": 4502,
                                "metric_unit": "人",
                            }
                        ],
                    },
                }
            }

        def build_s2_operating_views(*, operating_payload, optional_results):
            from runtime.algorithms.s2_operating_views import build_s2_operating_views

            return build_s2_operating_views(
                operating_payload=operating_payload,
                optional_results=optional_results,
            )

        router = SimpleNamespace(
            _base_result=lambda intent, *, role, output_profile=None: {
                "intent": intent,
                "auth_role": role,
                "output_profile": output_profile,
            },
            database_source_enabled=lambda: True,
            database_template_result=database_template_result,
            load_s2_optional_results=load_s2_optional_results,
            build_s2_operating_views=build_s2_operating_views,
            agent_id_for_node=lambda node_id: "A1",
        )
        return router, calls

    def test_historical_snapshot_reads_exact_day_jy01_not_forecast(self) -> None:
        router, calls = self._fake_router()

        result = _build_historical_snapshot_result(
            router,
            hotel_id="puyue",
            role="owner",
            output_profile="owner_business",
            target_business_date="2026-08-06",
            as_of_time="23:59",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["s2_contract"], HISTORICAL_CONTRACT)
        self.assertEqual(result["historical_source_table"], HISTORICAL_SOURCE_TABLE)
        self.assertEqual(result["business_date"], "2026-08-06")
        self.assertEqual(result["core_metrics"]["sold_rooms"], 20)
        self.assertTrue(calls)
        template, hotel_id, kwargs = calls[0]
        self.assertEqual(template, "daily_metrics")
        self.assertEqual(hotel_id, "puyue")
        self.assertEqual(kwargs.get("date"), "2026-08-06")
        self.assertEqual(kwargs.get("source_platform"), "pms")
        self.assertFalse(any(call[0] == "operating_snapshot" for call in calls))

    def test_historical_snapshot_rejects_cross_day_daily_result(self) -> None:
        router, calls = self._fake_router(data_business_date="2026-08-05")

        result = _build_historical_snapshot_result(
            router,
            hotel_id="puyue",
            role="owner",
            output_profile="owner_business",
            target_business_date="2026-08-06",
            as_of_time="23:59",
        )

        self.assertEqual(result["status"], "data_gap")
        self.assertFalse(result["business_result_generated"])
        self.assertEqual(result["blocked_reason"], "historical_daily_data_gap")
        self.assertFalse(any(call[0] == "operating_snapshot" for call in calls))
        self.assertIn("historical_pms_business_date_mismatch", result["risk_flags"])

    def test_historical_reply_labels_sources_and_exact_day_flow(self) -> None:
        router, _ = self._fake_router()
        result = _build_historical_snapshot_result(
            router,
            hotel_id="puyue",
            role="owner",
            output_profile="owner_business",
            target_business_date="2026-08-06",
            as_of_time="23:59",
        )

        text = render_historical_s2_reply(result["operating_views"])

        self.assertIn("PMS 日终来源 jy01_hotel_statistics_daily", text)
        self.assertIn("三、流量转化（8/6 当日数据）", text)
        self.assertIn("业务日 2026-08-06", text)
        self.assertIn("jl01_room_type_performance_daily", text)
        self.assertIn("未使用 pms_room_type_forecast", text)
        self.assertNotIn("今日数据", text)


if __name__ == "__main__":
    unittest.main()

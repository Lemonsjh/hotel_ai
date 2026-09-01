from __future__ import annotations

import unittest
from types import SimpleNamespace

from runtime.adapters import database as database_adapter
from runtime.algorithms.s2_operating_reply import render_s2_operating_reply
from runtime.s2_historical_flow_snapshot_patch import (
    SOURCE_TABLE,
    _query_exact_meituan_metrics,
    _wrap_historical_builder,
    _wrap_optional_loader,
)


class S2HistoricalFlowSnapshotTests(unittest.TestCase):
    @staticmethod
    def _previous_result(router, **kwargs):
        return {
            "status": "ok",
            "historical_daily": True,
            "business_date": "2026-08-06",
            "operating_views": {
                "flow_conversion": {
                    "status": "no_records",
                    "business_date": "2026-08-06",
                    "platforms": {},
                },
                "quality_flags": ["flow_conversion:no_records", "keep_existing_flag"],
            },
        }

    def test_next_day_snapshot_is_kept_for_exact_historical_business_date(self) -> None:
        calls: list[tuple[str, str, dict[str, object]]] = []

        def database_template_result(template: str, hotel_id: str, **kwargs: object):
            calls.append((template, hotel_id, dict(kwargs)))
            return {
                "status": "ok",
                "payload": {
                    "source_status": "ok",
                    "rows": [
                        {
                            "channel_source": "meituan",
                            "business_date": "2026-08-06",
                            "snapshot_time": "2026-08-07 02:00:00",
                            "metric_code": "FLOW_EXPOSURE_UV",
                            "metric_name": "曝光人数",
                            "metric_value": 4502,
                            "metric_unit": "人",
                        }
                    ],
                },
            }

        router = SimpleNamespace(database_template_result=database_template_result)
        wrapped = _wrap_historical_builder(self._previous_result)
        result = wrapped(
            router,
            hotel_id="puyue",
            role="owner",
            output_profile="owner_business",
            target_business_date="2026-08-06",
            as_of_time="2026-08-06 14:16:00",
        )

        self.assertEqual(len(calls), 1)
        template, hotel_id, kwargs = calls[0]
        self.assertEqual(template, "ota_business_metrics")
        self.assertEqual(hotel_id, "puyue")
        self.assertEqual(kwargs.get("date"), "2026-08-06")
        self.assertEqual(kwargs.get("source_platform"), "meituan")
        self.assertNotIn("as_of_time", kwargs)

        flow = result["operating_views"]["flow_conversion"]
        self.assertEqual(flow["status"], "ok")
        self.assertEqual(flow["business_date"], "2026-08-06")
        self.assertEqual(flow["platforms"]["meituan"]["snapshot_time"], "2026-08-07 02:00:00")
        self.assertEqual(flow["platforms"]["meituan"]["metrics"][0]["metric_code"], "FLOW_EXPOSURE_UV")
        self.assertEqual(result["historical_flow_snapshot_policy"], "business_date_only_no_snapshot_filter")
        self.assertIn("keep_existing_flag", result["operating_views"]["quality_flags"])
        self.assertNotIn("flow_conversion:no_records", result["operating_views"]["quality_flags"])

    def test_cross_day_row_is_not_used_as_historical_fallback(self) -> None:
        def database_template_result(template: str, hotel_id: str, **kwargs: object):
            return {
                "status": "ok",
                "payload": {
                    "source_status": "ok",
                    "rows": [
                        {
                            "channel_source": "meituan",
                            "business_date": "2026-08-05",
                            "snapshot_time": "2026-08-07 02:00:00",
                            "metric_code": "FLOW_EXPOSURE_UV",
                            "metric_name": "曝光人数",
                            "metric_value": 9999,
                            "metric_unit": "人",
                        }
                    ],
                },
            }

        router = SimpleNamespace(database_template_result=database_template_result)
        wrapped = _wrap_historical_builder(self._previous_result)
        result = wrapped(
            router,
            hotel_id="puyue",
            role="owner",
            output_profile="owner_business",
            target_business_date="2026-08-06",
            as_of_time="2026-08-06 23:59:00",
        )

        flow = result["operating_views"]["flow_conversion"]
        self.assertEqual(flow["status"], "no_records")
        self.assertEqual(flow["business_date"], "2026-08-06")
        self.assertEqual(flow["platforms"], {})
        self.assertIn("flow_conversion:no_records", result["operating_views"]["quality_flags"])

    def test_s2_meituan_query_uses_business_date_without_snapshot_filter(self) -> None:
        calls: list[tuple[str, str, dict[str, object]]] = []

        outside_clause, _ = database_adapter._latest_snapshot_clause(
            SOURCE_TABLE,
            {"snapshot_time": "snapshot_time"},
            ["hotel_id = %s"],
            ["puyue"],
        )
        self.assertIn("MAX", outside_clause)

        def query(template: str, hotel_id: str, **kwargs: object):
            calls.append((template, hotel_id, dict(kwargs)))
            scoped_clause = database_adapter._latest_snapshot_clause(
                SOURCE_TABLE,
                {"snapshot_time": "snapshot_time"},
                ["hotel_id = %s", "DATE(business_date) = %s"],
                [hotel_id, kwargs.get("date")],
            )
            self.assertEqual(scoped_clause, ("", []))
            return {"status": "ok", "payload": {"source_status": "ok", "rows": []}}

        _query_exact_meituan_metrics(
            query,
            hotel_id="puyue",
            business_date="2026-08-07",
        )

        self.assertEqual(calls[0][0], "ota_business_metrics")
        self.assertEqual(calls[0][1], "puyue")
        self.assertEqual(calls[0][2].get("date"), "2026-08-07")
        self.assertEqual(calls[0][2].get("source_platform"), "meituan")
        self.assertNotIn("as_of_time", calls[0][2])

    def test_full_meituan_business_day_rows_replace_snapshot_truncated_market_rows(self) -> None:
        metric_codes = [
            "DAY_ROOM_LOWEST_PRICE_AVG",
            "EXPOSE_PV_CNT",
            "INTENTION_UV",
            "PAY_ORDER_CNT_UV",
            "PAY_ORDER_CNT",
            "PAY_ROOMNIGHT",
            "PAY_ADR",
            "PAY_AMT",
            "CONSUME_ROOMNIGHT_SPLIT_EX_7DAYS_REFUND",
            "NOT_AVAILABLE_REAL_ROOM_RATE",
        ]
        calls: list[dict[str, object]] = []

        def query(template: str, hotel_id: str, **kwargs: object):
            calls.append(dict(kwargs))
            if kwargs.get("source_platform") == "meituan":
                return {
                    "status": "ok",
                    "payload": {
                        "source_status": "ok",
                        "rows": [
                            {
                                "table_key": "meituan_business_metrics",
                                "business_date": "2026-08-07",
                                "snapshot_time": "2026-08-07 15:10:00",
                                "metric_code": code,
                                "metric_value": index + 1,
                                "peer_average": index + 0.5,
                            }
                            for index, code in enumerate(metric_codes)
                        ],
                    },
                }
            return {"status": "ok", "payload": {"source_status": "ok", "rows": []}}

        def previous(query_fn, *, hotel_id: str, business_date: str, as_of_time: str | None):
            flow = query_fn(
                "ota_business_metrics",
                hotel_id,
                date=business_date,
                as_of_time=as_of_time,
                source_platform="meituan",
            )
            market = {
                "status": "ok",
                "payload": {
                    "source_status": "ok",
                    "rows": [
                        {
                            "table_key": "meituan_business_metrics",
                            "business_date": business_date,
                            "metric_code": "EXPOSE_PV_CNT",
                            "metric_value": 999,
                            "peer_average": 888,
                        },
                        {
                            "table_key": "ctrip_business_metrics",
                            "business_date": business_date,
                            "metric_code": "CTRIP_KEEP",
                            "metric_value": 1,
                            "peer_average": 1,
                        },
                    ],
                    "row_count": 2,
                    "raw_row_count": 2,
                    "filtered_row_count": 2,
                },
            }
            return {"flow_conversion": flow, "market_metrics": market}

        wrapped = _wrap_optional_loader(previous)
        results = wrapped(
            query,
            hotel_id="puyue",
            business_date="2026-08-07",
            as_of_time="2026-08-07 15:15:00",
        )

        self.assertNotIn("as_of_time", calls[0])
        market_rows = results["market_metrics"]["payload"]["rows"]
        meituan_rows = [row for row in market_rows if row.get("table_key") == "meituan_business_metrics"]
        ctrip_rows = [row for row in market_rows if row.get("table_key") == "ctrip_business_metrics"]
        self.assertEqual(len(meituan_rows), 10)
        self.assertEqual({row["metric_code"] for row in meituan_rows}, set(metric_codes))
        self.assertEqual(len(ctrip_rows), 1)
        self.assertEqual(results["market_metrics"]["payload"]["row_count"], 11)
        self.assertEqual(
            results["market_metrics"]["payload"]["s2_meituan_business_date_policy"],
            "hotel_id_business_date_only",
        )

    def test_reply_calls_peer_rows_comparable_metrics(self) -> None:
        text = render_s2_operating_reply(
            {
                "core_operating": {},
                "room_type_status": {"items": []},
                "flow_conversion": {"status": "no_records", "business_date": "2026-08-07", "platforms": {}},
                "market_competition": {
                    "platforms": {
                        "meituan": {
                            "status": "ok",
                            "peer_aggregate": [{"metric_code": "A"}, {"metric_code": "B"}],
                            "loss_context": {},
                            "competition_circles": [],
                        }
                    }
                },
                "price_and_lead": {"platforms": {}},
                "promotion_activity": {"platforms": {}},
                "quality_flags": [],
            }
        )
        self.assertIn("同行可比指标 2 项", text)
        self.assertNotIn("同行聚合 2 条", text)


if __name__ == "__main__":
    unittest.main()

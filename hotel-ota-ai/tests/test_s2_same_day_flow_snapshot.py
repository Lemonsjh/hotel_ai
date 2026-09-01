from __future__ import annotations

import unittest

from runtime.algorithms.s2_operating_reply import render_s2_operating_reply
from runtime.algorithms.s2_operating_views import (
    FLOW_SOURCE_TABLE,
    _flow_view,
    load_s2_optional_results,
)


class S2SameDayFlowSnapshotTests(unittest.TestCase):
    def test_optional_loader_requests_same_day_meituan_flow(self) -> None:
        calls: list[tuple[str, str, dict[str, object]]] = []

        def fake_query(template: str, hotel_id: str, **kwargs: object) -> dict[str, object]:
            calls.append((template, hotel_id, dict(kwargs)))
            return {
                "status": "ok",
                "payload": {"source_status": "ok", "rows": []},
            }

        results = load_s2_optional_results(
            fake_query,
            hotel_id="hotel-1",
            business_date="2026-08-07",
            as_of_time="13:00",
        )

        self.assertIn("flow_conversion", results)
        flow_calls = [
            call
            for call in calls
            if call[0] == "ota_business_metrics"
            and call[2].get("source_platform") == "meituan"
        ]
        self.assertEqual(len(flow_calls), 1)
        _, hotel_id, kwargs = flow_calls[0]
        self.assertEqual(hotel_id, "hotel-1")
        self.assertEqual(kwargs.get("date"), "2026-08-07")
        self.assertEqual(kwargs.get("as_of_time"), "13:00")
        self.assertEqual(kwargs.get("source_platform"), "meituan")
        self.assertEqual(
            results["flow_conversion"].get("_s2_requested_business_date"),
            "2026-08-07",
        )
        self.assertEqual(
            results["flow_conversion"].get("_s2_source_table"),
            FLOW_SOURCE_TABLE,
        )

    def test_flow_view_keeps_only_requested_day_meituan_rows(self) -> None:
        result = {
            "status": "ok",
            "_s2_requested_business_date": "2026-08-07",
            "_s2_source_table": FLOW_SOURCE_TABLE,
            "payload": {
                "source_status": "ok",
                "rows": [
                    {
                        "channel_source": "meituan",
                        "business_date": "2026-08-06",
                        "snapshot_time": "2026-08-06 23:30:00",
                        "metric_code": "FLOW_EXPOSURE_UV",
                        "metric_name": "曝光人数",
                        "metric_value": 111,
                        "metric_unit": "人",
                    },
                    {
                        "channel_source": "meituan",
                        "business_date": "2026-08-07",
                        "snapshot_time": "2026-08-07 12:30:00",
                        "metric_code": "FLOW_EXPOSURE_UV",
                        "metric_name": "曝光人数",
                        "metric_value": 222,
                        "metric_unit": "人",
                    },
                    {
                        "channel_source": "ctrip",
                        "business_date": "2026-08-07",
                        "snapshot_time": "2026-08-07 12:30:00",
                        "metric_code": "FLOW_EXPOSURE_UV",
                        "metric_name": "曝光人数",
                        "metric_value": 333,
                        "metric_unit": "人",
                    },
                ],
            },
        }

        view = _flow_view(result)

        self.assertEqual(view["status"], "ok")
        self.assertEqual(view["business_date"], "2026-08-07")
        self.assertEqual(view["source_table"], FLOW_SOURCE_TABLE)
        self.assertEqual(set(view["platforms"]), {"meituan"})
        meituan = view["platforms"]["meituan"]
        self.assertEqual(meituan["business_date"], "2026-08-07")
        self.assertEqual(meituan["metric_count"], 1)
        self.assertEqual(meituan["metrics"][0]["metric_value"], 222)

    def test_flow_view_does_not_fall_back_to_previous_day(self) -> None:
        result = {
            "status": "ok",
            "_s2_requested_business_date": "2026-08-07",
            "_s2_source_table": FLOW_SOURCE_TABLE,
            "payload": {
                "source_status": "ok",
                "rows": [
                    {
                        "channel_source": "meituan",
                        "business_date": "2026-08-06",
                        "snapshot_time": "2026-08-06 23:30:00",
                        "metric_code": "FLOW_EXPOSURE_UV",
                        "metric_name": "曝光人数",
                        "metric_value": 111,
                        "metric_unit": "人",
                    }
                ],
            },
        }

        view = _flow_view(result)

        self.assertEqual(view["status"], "no_records")
        self.assertEqual(view["business_date"], "2026-08-07")
        self.assertEqual(view["platforms"], {})
        self.assertTrue(
            any("2026-08-07" in flag for flag in view.get("quality_flags") or [])
        )

    def test_reply_labels_flow_panel_as_today(self) -> None:
        views = {
            "core_operating": {
                "status": "ok",
                "business_date": "2026-08-07",
                "snapshot_time": "2026-08-07 12:30:00",
            },
            "room_type_status": {"items": []},
            "flow_conversion": {
                "status": "ok",
                "business_date": "2026-08-07",
                "platforms": {
                    "meituan": {
                        "status": "ok",
                        "business_date": "2026-08-07",
                        "snapshot_time": "2026-08-07 12:30:00",
                        "metric_count": 1,
                        "metrics": [
                            {
                                "metric_code": "FLOW_EXPOSURE_UV",
                                "metric_name": "曝光人数",
                                "metric_value": 222,
                                "metric_unit": "人",
                            }
                        ],
                        "quality_flags": [],
                    }
                },
            },
            "market_competition": {"platforms": {}},
            "price_and_lead": {"platforms": {}},
            "promotion_activity": {"platforms": {}},
            "quality_flags": [],
        }

        text = render_s2_operating_reply(views)

        self.assertIn("三、流量转化（8/7 今日数据）", text)
        self.assertNotIn("上一完整业务日", text)
        self.assertIn("业务日 2026-08-07", text)

    def test_reply_reports_same_day_gap_without_old_day_fallback(self) -> None:
        views = {
            "core_operating": {
                "status": "ok",
                "business_date": "2026-08-07",
                "snapshot_time": "2026-08-07 12:30:00",
            },
            "room_type_status": {"items": []},
            "flow_conversion": {
                "status": "no_records",
                "business_date": "2026-08-07",
                "platforms": {},
            },
            "market_competition": {"platforms": {}},
            "price_and_lead": {"platforms": {}},
            "promotion_activity": {"platforms": {}},
            "quality_flags": [],
        }

        text = render_s2_operating_reply(views)

        self.assertIn("三、流量转化（8/7 今日数据）", text)
        self.assertIn("2026-08-07 当日未查询到流量转化记录", text)
        self.assertIn("未使用其他业务日数据", text)
        self.assertNotIn("2026-08-06", text)


if __name__ == "__main__":
    unittest.main()

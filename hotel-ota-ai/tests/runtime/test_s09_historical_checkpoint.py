from __future__ import annotations

import datetime as dt

from runtime.s01_s17_exact_route_patch import _is_s09_message, _s09_checkpoint_request, _s09_history_days
from runtime.s09_historical_checkpoint import (
    build_s09_checkpoint_report,
    build_s09_daily_history_report,
    render_s09_checkpoint_report,
    render_s09_daily_history_report,
)


def _row(day: str, hour: int, code: str, value: float, unit: str) -> dict[str, object]:
    return {
        "hotel_id": "puyue", "business_date": day, "snapshot_hour": f"{day} {hour:02d}:00:00",
        "snapshot_time": f"{day} {hour:02d}:01:00", "metric_code": code,
        "metric_value": value, "metric_unit": unit,
    }


class Source:
    def hourly_metric_rows(self, *args, **kwargs):
        del args, kwargs
        rows = []
        for day, browse in (("2026-08-20", 100), ("2026-08-21", 120)):
            rows.extend([
                _row(day, 19, "INTENTION_UV", browse, "person"),
                _row(day, 19, "PAY_ORDER_CNT", 5, "order"),
                _row(day, 19, "PAY_ORDER_CNT_UV", 5, "%"),
            ])
        return rows

    def daily_metric_rows(self, *args, **kwargs):
        del args, kwargs
        rows = []
        for day, exposure, browse, pay in (("2026-08-20", 1000, 100, 5), ("2026-08-21", 1200, 120, 6)):
            rows.extend([
                {**_row(day, 19, "FLOW_EXPOSURE_UV", exposure, "person"), "snapshot_time": f"{day} 23:00:00"},
                {**_row(day, 19, "FLOW_INTENTION_UV", browse, "person"), "snapshot_time": f"{day} 23:00:00"},
                {**_row(day, 19, "FLOW_PAY_ORDER_CNT", pay, "order"), "snapshot_time": f"{day} 23:00:00"},
            ])
        return rows


def test_checkpoint_route_matches_natural_language_request() -> None:
    text = "最近7天截至19点的浏览人数和转化率数据帮我分析一下"
    assert _is_s09_message(text)
    assert _s09_checkpoint_request(text) == (7, 19)
    assert _s09_history_days("分析一下最近7天每天的浏览人数和转化数据") == 7


def test_checkpoint_report_uses_exact_checkpoint_hour_only() -> None:
    report = build_s09_checkpoint_report(
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 21, 20, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        source=Source(), days=2, checkpoint_hour=19,
    )
    assert report["status"] == "ok"
    assert [item["business_date"] for item in report["entries"]] == ["2026-08-20", "2026-08-21"]
    assert report["entries"][0]["stages"]["browse_uv"] == 100
    assert report["entries"][0]["stages"]["pay_orders"] == 5
    rendered = render_s09_checkpoint_report(report)
    assert "不与日级数据混用" in rendered
    assert "观测 19:00" in rendered


def test_checkpoint_report_excludes_nonmatching_hourly_batch() -> None:
    class Stale(Source):
        def hourly_metric_rows(self, *args, **kwargs):
            return [
                _row("2026-08-21", 16, "INTENTION_UV", 100, "person"),
                _row("2026-08-21", 16, "PAY_ORDER_CNT", 5, "order"),
            ]

    report = build_s09_checkpoint_report(
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 21, 20, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        source=Stale(), days=2, checkpoint_hour=19,
    )
    assert report["status"] == "data_gap"
    assert "19:00" in report["missing_dates"]["2026-08-21"]


def test_daily_history_keeps_exposure_and_browse_as_separate_fields() -> None:
    report = build_s09_daily_history_report(
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 21, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        source=Source(), days=2,
    )
    assert report["status"] == "ok"
    first = report["entries"][0]["stages"]
    assert first["exposure_uv"] == 1000
    assert first["browse_uv"] == 100
    rendered = render_s09_daily_history_report(report)
    assert "曝光 1000｜浏览/意向 100" in rendered
    assert "同一快照批次" in rendered

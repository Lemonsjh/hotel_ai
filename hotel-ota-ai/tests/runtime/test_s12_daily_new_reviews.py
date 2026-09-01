from __future__ import annotations

import datetime as dt

from runtime import s01_s17_exact_route_patch as s12_route
from runtime.s01_s17_exact_route_patch import (
    _is_s12_daily_new_reviews_message,
    _is_s12_message,
    _s12_new_review_window_days,
)
from runtime.s12_daily_new_reviews import (
    _quality_summary,
    build_s12_daily_new_reviews_report,
    render_s12_daily_new_reviews_report,
)


class _Source:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def _columns(self, table: str) -> set[str]:
        if table == "hotels":
            return {"hotel_id", "config_json"}
        return {
            "id", "hotel_id", "review_id", "review_time", "snapshot_time",
            "review_platform", "channel_source",
            "is_replied", "merchant_reply_time", "merchant_reply_content",
            "review_score", "is_negative_review",
        }

    def _query(self, sql: str, params: tuple[object, ...]):
        self.calls.append((sql, params))
        if "FROM `hotels`" in sql:
            return [{"config_json": '{"channels":["meituan"]}'}]
        if "meituan_ota_review_detail" in sql:
            return [
                {
                    "id": 1, "hotel_id": "puyue", "review_id": "mt-1",
                    "review_time": "2026-08-16 09:00:00",
                    "snapshot_time": "2026-08-16 09:10:00",
                    "review_platform": "meituan", "channel_source": "meituan",
                    "is_replied": 1, "review_score": 5, "is_negative_review": 0,
                },
                {
                    "id": 2, "hotel_id": "puyue", "review_id": "dp-1",
                    "review_time": "2026-08-16 12:00:00",
                    "snapshot_time": "2026-08-16 12:10:00",
                    "review_platform": "dianping", "channel_source": "meituan",
                    "is_replied": 0, "review_score": 2, "is_negative_review": 1,
                },
                {
                    "id": 3, "hotel_id": "puyue", "review_id": "mt-1",
                    "review_time": "2026-08-16 09:00:00",
                    "snapshot_time": "2026-08-16 13:10:00",
                    "review_platform": "meituan", "channel_source": "meituan",
                    "is_replied": 1, "review_score": 5, "is_negative_review": 0,
                },
            ]
        raise AssertionError("disabled Ctrip table must not be queried")


def test_s12_daily_new_reviews_uses_review_time_day_and_enabled_channels() -> None:
    source = _Source()
    report = build_s12_daily_new_reviews_report(
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 17, 9, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        source=source,  # type: ignore[arg-type]
    )

    assert report["status"] == "ok"
    assert report["target_review_date"] == "2026-08-16"
    assert report["total_new_review_count"] == 2
    assert report["platform_counts"] == {"meituan": 1, "dianping": 1}
    assert report["quality_summary"]["current_reply"]["rate"] == 0.5
    assert report["quality_summary"]["rating"]["positive_rate"] == 0.5
    assert report["quality_summary"]["rating"]["low_score_count"] == 1
    assert report["quality_summary"]["source_negative"]["count"] == 1
    detail_call = next(call for call in source.calls if "review_detail" in call[0])
    assert "`merchant_reply_time`" in detail_call[0]
    assert "`merchant_reply_content`" in detail_call[0]
    assert detail_call[1][1:3] == (
        dt.datetime(2026, 8, 16),
        dt.datetime(2026, 8, 17),
    )
    text = render_s12_daily_new_reviews_report(report)
    assert "新增评论：2 条" in text
    assert "美团 1 条｜大众点评 1 条" in text
    assert "总计回复率（统计区间内评论，截至当前）：已回复 1 条，未回复 1 条，回复率 50.0%" in text
    assert "总计评价质量：好评（≥4分） 1 条，好评率 50.0%" in text
    assert "总计来源差评：1 条，占比 50.0%" in text


def test_s12_reply_fact_falls_back_only_when_reply_flag_is_missing() -> None:
    summary = _quality_summary([
        {"is_replied": None, "merchant_reply_time": "2026-08-18 10:00:00"},
        {"is_replied": False, "merchant_reply_content": "已有内容但状态为未回复"},
    ])

    assert summary["current_reply"] == {
        "known_count": 2,
        "replied_count": 1,
        "unreplied_count": 1,
        "rate": 0.5,
    }


def test_s12_daily_new_review_phrases_route_to_real_s12() -> None:
    assert _is_s12_message("昨日新增了几条评论？") is True
    assert _is_s12_message("昨天新增评论") is True
    assert _is_s12_daily_new_reviews_message("查看昨天的新增好评数") is True
    assert _s12_new_review_window_days("查看昨天的新增好评数") == 1
    assert _s12_new_review_window_days("最新两天的新增评论") == 2
    assert _s12_new_review_window_days("近3天新增评论") == 3


def test_s12_daily_new_review_rerun_uses_quoted_context() -> None:
    previous = "S12 昨日新增评论（真实数据只读）\n新增评论：3 条。"
    assert _is_s12_daily_new_reviews_message("你重新执行一下", previous) is True
    assert _is_s12_daily_new_reviews_message("你重新执行一下") is False


def test_s12_recent_review_window_uses_requested_days() -> None:
    source = _Source()
    report = build_s12_daily_new_reviews_report(
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 18, 9, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        source=source,  # type: ignore[arg-type]
        days=2,
    )

    assert report["window_days"] == 2
    assert report["target_review_date"] == "2026-08-16"
    assert report["target_review_end_date"] == "2026-08-17"
    assert report["daily_counts"] == {"2026-08-16": 2, "2026-08-17": 0}
    text = render_s12_daily_new_reviews_report(report)
    assert "S12 近 2 天新增评论" in text
    assert "按日新增：2026-08-16 2 条｜2026-08-17 0 条" in text


def test_daily_s12_replaces_scaffold_demo_metadata(monkeypatch) -> None:
    report = {
        "status": "ok",
        "skill_id": "S12",
        "intent": "reputation_daily_new_reviews",
        "hotel_id": "puyue",
        "target_review_date": "2026-08-17",
        "as_of_datetime": "2026-08-18T13:00:00+08:00",
        "business_result_generated": True,
        "data_source_type": "real_database",
    }
    monkeypatch.setattr(s12_route.S12MySQLSource, "from_env", lambda **_: object())
    monkeypatch.setattr(s12_route, "build_s12_daily_new_reviews_report", lambda **_: report)
    monkeypatch.setattr(s12_route, "render_s12_daily_new_reviews_report", lambda _: "昨日新增评论：1 条。")

    result = s12_route._custom_result(
        {
            "data_business_date": "2026-06-11",
            "business_date": "2026-06-11",
            "freshness_status": "demo_data",
            "demo_dataset_id": "demo",
            "run_context": {"business_date": "2026-06-11"},
        },
        code="S12",
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 18, 13, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        daily_new_reviews=True,
    )

    assert result["data_business_date"] == "2026-08-17"
    assert result["business_date"] == "2026-08-17"
    assert result["freshness_status"] == "date_scoped"
    assert result["data_source_type"] == "real_database"
    assert "demo_dataset_id" not in result
    assert "run_context" not in result


def test_s12_deterministic_summary_is_sent_verbatim() -> None:
    class _Router:
        @staticmethod
        def render_feishu_output(*_args):
            return {"text": "fallback"}

        @staticmethod
        def build_feishu_send_payload(*_args, **_kwargs):
            return {"text": "fallback", "send_allowed": True}

        @staticmethod
        def compact_feishu_route_result(value):
            return value

    summary = "S12 昨日新增评论（真实数据只读）\n新增评论：1 条。"
    result = s12_route._finish(
        _Router(),
        {"skill_id": "S12", "summary": summary},
        render=True,
        compact=False,
        role="operator",
    )

    assert result["send_payload"]["text"] == summary
    assert result["send_payload"]["delivery_mode"] == "verbatim"
    assert result["send_payload"]["model_rewrite_allowed"] is False

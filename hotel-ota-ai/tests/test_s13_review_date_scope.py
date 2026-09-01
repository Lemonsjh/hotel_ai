from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from runtime.s13_pending_performance_patch import (
    _ACTIVE_REVIEW_COUNT_ONLY,
    _ACTIVE_REVIEW_DATE_SCOPE,
    _ACTIVE_REVIEW_PLATFORM_SCOPE,
    _bounded_unreplied_query,
    _count_summary,
    _review_time_bounds,
    _source_specs_for_platform,
    _wrap_route,
    review_count_only,
    review_date_scope,
    review_platform_scope,
)


SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def test_review_date_scope_only_narrows_explicit_today_or_yesterday() -> None:
    assert review_date_scope("今天有未回复评论吗") == "today"
    assert review_date_scope("查看今日未回复评论") == "today"
    assert review_date_scope("昨天有哪些待回复评论") == "yesterday"
    assert review_date_scope("查看昨日未回复评论") == "yesterday"
    assert review_date_scope("还有哪些待回复评论") is None
    assert review_date_scope("现在有未回复评论吗") is None


def test_review_platform_scope_only_narrows_explicit_meituan_family_channel() -> None:
    assert review_platform_scope("当前大众点评有几条未回复评论？") == "dianping"
    assert review_platform_scope("查看大众点评待回复评论") == "dianping"
    assert review_platform_scope("当前美团有几条未回复评论？") == "meituan"
    assert review_platform_scope("查看美团待回复评论") == "meituan"
    assert review_platform_scope("当前有几条未回复评论？") is None


def test_review_count_only_detects_quantity_question() -> None:
    assert review_count_only("当前大众点评有几条未回复评论？") is True
    assert review_count_only("美团有多少条待回复评论") is True
    assert review_count_only("查看大众点评待回复评论") is False


def test_meituan_family_platform_scope_skips_ctrip_source() -> None:
    assert _source_specs_for_platform("dianping") == (("meituan", "meituan"),)
    assert _source_specs_for_platform("meituan") == (("meituan", "meituan"),)
    assert _source_specs_for_platform(None) == (
        ("meituan", "meituan"),
        ("ctrip_family", "ctrip"),
    )


def test_review_time_bounds_are_exact_calendar_day_ranges() -> None:
    as_of = dt.datetime(2026, 8, 7, 15, 27, tzinfo=SHANGHAI)
    today_start, today_end, today_inclusive = _review_time_bounds(
        as_of, SHANGHAI, "today"
    )
    assert today_start == dt.datetime(2026, 8, 7, 0, 0, tzinfo=SHANGHAI)
    assert today_end == as_of
    assert today_inclusive is True

    yesterday_start, yesterday_end, yesterday_inclusive = _review_time_bounds(
        as_of, SHANGHAI, "yesterday"
    )
    assert yesterday_start == dt.datetime(2026, 8, 6, 0, 0, tzinfo=SHANGHAI)
    assert yesterday_end == dt.datetime(2026, 8, 7, 0, 0, tzinfo=SHANGHAI)
    assert yesterday_inclusive is False


class _Cursor:
    def __init__(self) -> None:
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql: str, params: tuple[object, ...]) -> None:
        self.sql = sql
        self.params = params

    def fetchall(self):
        return []


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


class _Repository:
    def __init__(self) -> None:
        self.cursor = _Cursor()

    def _resolve_columns(self, table: str):
        return {
            "hotel_id": "hotel_id",
            "review_id": "review_id",
            "review_content": "review_content",
            "star_rating": "star_rating",
            "is_replied": "is_replied",
            "is_negative_review": "is_negative_review",
            "source_snapshot": "snapshot_time",
            "review_time": "review_time",
            "platform_scope": "channel_source",
        }

    @staticmethod
    def _select_expression(column: str | None, alias: str) -> str:
        return f"`{column}` AS `{alias}`" if column else f"NULL AS `{alias}`"

    def _connect(self):
        return _Connection(self.cursor)


def _fake_source():
    return SimpleNamespace(
        SHANGHAI_TZ=SHANGHAI,
        REVIEW_DETAIL_WINDOW_DAYS=60,
        SourceDataGap=RuntimeError,
        _TABLES={
            "meituan": "meituan_ota_review_detail",
            "ctrip_family": "ctrip_ota_review_detail",
        },
        _safe_identifier=lambda value: value,
        _as_replied=lambda value: False,
        normalize_platform=lambda value, default: (
            "dianping" if value == "大众点评" else "meituan" if value == "美团" else value or default
        ),
        _as_float=lambda value: value,
        _as_source_negative=lambda value: value,
        ReviewRecord=lambda **kwargs: SimpleNamespace(**kwargs),
    )


def test_mysql_today_scope_replaces_rolling_60_day_lower_bound() -> None:
    source = _fake_source()
    repository = _Repository()
    as_of = dt.datetime(2026, 8, 7, 15, 27, tzinfo=SHANGHAI)
    token = _ACTIVE_REVIEW_DATE_SCOPE.set("today")
    try:
        _bounded_unreplied_query(
            source,
            repository,
            table="meituan_ota_review_detail",
            hotel_id="puyue",
            as_of=as_of,
            limit=20,
            default_platform="meituan",
        )
    finally:
        _ACTIVE_REVIEW_DATE_SCOPE.reset(token)

    assert repository.cursor.params[0] == "puyue"
    assert repository.cursor.params[1] == dt.datetime(2026, 8, 7, 15, 27)
    assert repository.cursor.params[2] == dt.datetime(2026, 8, 7, 0, 0)
    assert repository.cursor.params[3] == dt.datetime(2026, 8, 7, 15, 27)
    assert "`review_time`>=%s" in repository.cursor.sql
    assert "`review_time`<=%s" in repository.cursor.sql


def test_mysql_yesterday_scope_is_closed_open_day_range() -> None:
    source = _fake_source()
    repository = _Repository()
    as_of = dt.datetime(2026, 8, 7, 15, 27, tzinfo=SHANGHAI)
    token = _ACTIVE_REVIEW_DATE_SCOPE.set("yesterday")
    try:
        _bounded_unreplied_query(
            source,
            repository,
            table="meituan_ota_review_detail",
            hotel_id="puyue",
            as_of=as_of,
            limit=20,
            default_platform="meituan",
        )
    finally:
        _ACTIVE_REVIEW_DATE_SCOPE.reset(token)

    assert repository.cursor.params[2] == dt.datetime(2026, 8, 6, 0, 0)
    assert repository.cursor.params[3] == dt.datetime(2026, 8, 7, 0, 0)
    assert "`review_time`<%s" in repository.cursor.sql


def test_mysql_dianping_scope_pushes_exact_channel_source_filter() -> None:
    source = _fake_source()
    repository = _Repository()
    as_of = dt.datetime(2026, 8, 7, 15, 57, tzinfo=SHANGHAI)
    token = _ACTIVE_REVIEW_PLATFORM_SCOPE.set("dianping")
    try:
        _bounded_unreplied_query(
            source,
            repository,
            table="meituan_ota_review_detail",
            hotel_id="puyue",
            as_of=as_of,
            limit=20,
            default_platform="meituan",
        )
    finally:
        _ACTIVE_REVIEW_PLATFORM_SCOPE.reset(token)

    assert "`channel_source`=%s" in repository.cursor.sql
    assert repository.cursor.params[0] == "puyue"
    assert repository.cursor.params[1] == "大众点评"


def test_meituan_family_scope_does_not_query_ctrip_table() -> None:
    source = _fake_source()
    repository = _Repository()
    as_of = dt.datetime(2026, 8, 7, 15, 57, tzinfo=SHANGHAI)
    token = _ACTIVE_REVIEW_PLATFORM_SCOPE.set("dianping")
    try:
        rows = _bounded_unreplied_query(
            source,
            repository,
            table="ctrip_ota_review_detail",
            hotel_id="puyue",
            as_of=as_of,
            limit=20,
            default_platform="ctrip",
        )
    finally:
        _ACTIVE_REVIEW_PLATFORM_SCOPE.reset(token)

    assert rows == []
    assert repository.cursor.sql == ""


def test_count_summary_is_exact_below_cap_and_bounded_at_cap() -> None:
    exact = _count_summary(
        {"items": [{}, {}, {}], "more_may_exist": False, "pending_list_limit": 20},
        date_label="",
        platform_label="大众点评",
    )
    assert exact == "大众点评当前有3条未回复评论。"

    bounded = _count_summary(
        {"items": [{}] * 20, "more_may_exist": True, "pending_list_limit": 20},
        date_label="",
        platform_label="大众点评",
    )
    assert bounded == "大众点评当前至少有20条未回复评论（单次查询展示上限20条）。"


def test_route_scope_is_active_only_during_scoped_s13_request() -> None:
    observed: list[tuple[str | None, str | None, bool]] = []

    def previous(message: str, *args, **kwargs):
        observed.append(
            (
                _ACTIVE_REVIEW_DATE_SCOPE.get(),
                _ACTIVE_REVIEW_PLATFORM_SCOPE.get(),
                _ACTIVE_REVIEW_COUNT_ONLY.get(),
            )
        )
        return {"skill_id": "S13", "intent": "review_reply", "status": "ok"}

    wrapped = _wrap_route(previous)
    result = wrapped("今天大众点评有几条未回复评论")

    assert observed == [("today", "dianping", True)]
    assert _ACTIVE_REVIEW_DATE_SCOPE.get() is None
    assert _ACTIVE_REVIEW_PLATFORM_SCOPE.get() is None
    assert _ACTIVE_REVIEW_COUNT_ONLY.get() is False
    assert result["review_date_scope"] == "today"
    assert result["review_date_filter_applied"] is True
    assert result["review_platform_scope"] == "dianping"
    assert result["review_channel_source_filter"] == "大众点评"
    assert result["review_platform_filter_applied"] is True
    assert result["review_count_only"] is True

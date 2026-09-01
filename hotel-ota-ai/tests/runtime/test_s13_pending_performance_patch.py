from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from runtime import s13_pending_performance_patch as patch


def test_limits_are_bounded() -> None:
    assert patch._effective_limit(50) == 20
    assert patch._effective_limit(0) == 1
    assert patch._scan_limit(20) == 100
    assert patch._scan_limit(999) <= patch.MAX_SCAN_PER_TABLE


def test_bounded_query_filters_unreplied_in_sql() -> None:
    class Cursor:
        sql = ""
        params = ()

        def execute(self, sql, params):  # type: ignore[no-untyped-def]
            self.sql = sql
            self.params = params

        def fetchall(self):  # type: ignore[no-untyped-def]
            return [
                {
                    "hotel_id": "puyue",
                    "review_id": "r-1",
                    "review_content": None,
                    "star_rating": 5,
                    "is_replied": 0,
                    "source_snapshot": "2026-08-03 10:00:00",
                    "review_time": "2026-08-01 10:00:00",
                    "platform_scope": "meituan",
                }
            ]

    cursor = Cursor()

    class CursorContext:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return cursor

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            return None

    class Connection:
        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *args):  # type: ignore[no-untyped-def]
            return None

        def cursor(self):  # type: ignore[no-untyped-def]
            return CursorContext()

    class Repository:
        def _resolve_columns(self, table):  # type: ignore[no-untyped-def]
            return {
                "hotel_id": "hotel_id",
                "review_id": "review_id",
                "review_content": "review_content",
                "star_rating": "review_score",
                "is_replied": "is_replied",
                "source_snapshot": "snapshot_time",
                "review_time": "review_time",
                "platform_scope": "review_platform",
            }

        def _select_expression(self, column, alias):  # type: ignore[no-untyped-def]
            return f"`{column}` AS `{alias}`" if column else f"NULL AS `{alias}`"

        def _connect(self):  # type: ignore[no-untyped-def]
            return Connection()

    class ReviewRecord:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            self.__dict__.update(kwargs)

    source = SimpleNamespace(
        SHANGHAI_TZ=dt.timezone(dt.timedelta(hours=8)),
        REVIEW_DETAIL_WINDOW_DAYS=60,
        SourceDataGap=RuntimeError,
        ReviewRecord=ReviewRecord,
        _safe_identifier=lambda value: value,
        _as_replied=lambda value: False if str(value) == "0" else None,
        normalize_platform=lambda value, default: value or default,
        _as_float=lambda value: float(value) if value is not None else None,
    )
    rows = patch._bounded_unreplied_query(
        source,
        Repository(),
        table="meituan_ota_review_detail",
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 4, tzinfo=source.SHANGHAI_TZ),
        limit=20,
        default_platform="meituan",
    )
    assert len(rows) == 1
    assert rows[0].review_content is None
    assert "MAX_EXECUTION_TIME(3000)" in cursor.sql
    assert "`_s13_rn`=1" in cursor.sql
    assert "CAST(`is_replied` AS CHAR)" in cursor.sql
    assert cursor.params[-1] == 100
    latest = patch._bounded_unreplied_query(
        source,
        Repository(),
        table="meituan_ota_review_detail",
        hotel_id="puyue",
        as_of=dt.datetime(2026, 8, 4, tzinfo=source.SHANGHAI_TZ),
        limit=1,
        default_platform="meituan",
        latest_only=True,
    )
    assert len(latest) == 1
    assert "ORDER BY `review_time` DESC" in cursor.sql
    assert cursor.params[-1] == 1


def test_service_caps_pending_items_before_ref_issuance() -> None:
    captured = {}

    class Service:
        def list_pending(self, context, *, limit=50):  # type: ignore[no-untyped-def]
            captured["limit"] = limit
            return {
                "status": "ok",
                "action": "list_pending",
                "items": [{"review_ref": str(index)} for index in range(limit)],
            }

    service_module = SimpleNamespace(S13Service=Service)
    patch._patch_service(service_module)
    result = Service().list_pending(object(), limit=50)
    assert captured["limit"] == 20
    assert result["returned_count"] == 20
    assert result["more_may_exist"] is True


def test_pending_renderer_is_compact() -> None:
    feishu = SimpleNamespace(
        _render=lambda result: "original",
        PLATFORM_LABELS={"meituan": "美团"},
        PLATFORM_DISPLAY_ORDER=("meituan",),
    )
    patch._patch_feishu(feishu)
    text = feishu._render(
        {
            "action": "list_pending",
            "pending_list_limit": 20,
            "more_may_exist": True,
            "items": [
                {
                    "platform": "meituan",
                    "star_rating": 1,
                    "review_ref": "REV-test",
                    "redacted_excerpt": "差" * 300,
                }
            ],
        }
    )
    assert "按风险与低分优先展示" in text
    assert "仅展示优先级最高前 20 条" in text
    assert len(text) < 400

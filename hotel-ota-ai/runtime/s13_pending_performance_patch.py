from __future__ import annotations

import datetime as dt
from collections import Counter
from contextvars import ContextVar
from typing import Any, Callable, Mapping

_INSTALLED = False
VERSION = "s13-pending-performance.v1"
DATE_SCOPE_VERSION = "s13-review-date-scope.v1"
PLATFORM_SCOPE_VERSION = "s13-review-platform-scope.v1"
MAX_PENDING_ITEMS = 20
MAX_SCAN_PER_TABLE = 200
MYSQL_QUERY_TIMEOUT_MS = 3000
EXCERPT_LIMIT = 96

_ACTIVE_REVIEW_DATE_SCOPE: ContextVar[str | None] = ContextVar(
    "s13_review_date_scope",
    default=None,
)
_ACTIVE_REVIEW_PLATFORM_SCOPE: ContextVar[str | None] = ContextVar(
    "s13_review_platform_scope",
    default=None,
)
_ACTIVE_REVIEW_COUNT_ONLY: ContextVar[bool] = ContextVar(
    "s13_review_count_only",
    default=False,
)


def _effective_limit(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = MAX_PENDING_ITEMS
    return max(1, min(parsed, MAX_PENDING_ITEMS))


def _scan_limit(value: Any) -> int:
    return min(MAX_SCAN_PER_TABLE, max(100, _effective_limit(value) * 5))


def _is_pending_review_question(message: Any) -> bool:
    text = str(message or "").strip()
    return "评论" in text and ("未回复" in text or "待回复" in text)


def review_date_scope(message: Any) -> str | None:
    """Return a narrow date scope for S13 pending-review questions."""

    text = str(message or "").strip()
    if not _is_pending_review_question(text):
        return None
    matches: list[tuple[int, str]] = []
    for token in ("今天", "今日"):
        position = text.find(token)
        if position >= 0:
            matches.append((position, "today"))
    for token in ("昨天", "昨日"):
        position = text.find(token)
        if position >= 0:
            matches.append((position, "yesterday"))
    if not matches:
        return None
    return min(matches, key=lambda item: item[0])[1]


def review_platform_scope(message: Any) -> str | None:
    """Return explicit Meituan-family channel scope for pending-review questions."""

    text = str(message or "").strip()
    if not _is_pending_review_question(text):
        return None
    matches: list[tuple[int, str]] = []
    for token, scope in (("大众点评", "dianping"), ("美团", "meituan")):
        position = text.find(token)
        if position >= 0:
            matches.append((position, scope))
    if not matches:
        return None
    return min(matches, key=lambda item: item[0])[1]


def review_count_only(message: Any) -> bool:
    text = str(message or "").strip()
    return bool(
        _is_pending_review_question(text)
        and any(token in text for token in ("几条", "多少条", "多少个", "有多少"))
    )


def _platform_label(scope: str | None) -> str:
    if scope == "dianping":
        return "大众点评"
    if scope == "meituan":
        return "美团"
    return ""


def _channel_source_value(scope: str) -> str:
    if scope == "dianping":
        return "大众点评"
    if scope == "meituan":
        return "美团"
    raise ValueError(f"unsupported_review_platform_scope:{scope}")


def _source_specs_for_platform(scope: str | None) -> tuple[tuple[str, str], ...]:
    if scope in {"meituan", "dianping"}:
        return (("meituan", "meituan"),)
    return (("meituan", "meituan"), ("ctrip_family", "ctrip"))


def _review_time_bounds(
    as_of: dt.datetime,
    timezone: dt.tzinfo,
    scope: str,
) -> tuple[dt.datetime, dt.datetime, bool]:
    local_as_of = as_of.astimezone(timezone)
    today_start = local_as_of.replace(hour=0, minute=0, second=0, microsecond=0)
    if scope == "today":
        return today_start, local_as_of, True
    if scope == "yesterday":
        return today_start - dt.timedelta(days=1), today_start, False
    raise ValueError(f"unsupported_review_date_scope:{scope}")


def _record_in_scope(source: Any, record: Any, *, as_of: dt.datetime, scope: str) -> bool:
    value = getattr(record, "review_time", None) or getattr(record, "source_snapshot", None)
    parsed = source._parse_source_datetime(value)
    if parsed is None:
        return False
    start, end, end_inclusive = _review_time_bounds(as_of, source.SHANGHAI_TZ, scope)
    if parsed < start:
        return False
    return parsed <= end if end_inclusive else parsed < end


def _record_platform_matches(record: Any, scope: str) -> bool:
    return str(getattr(record, "platform", "") or "").strip().lower() == scope


def _bounded_unreplied_query(
    source: Any,
    repository: Any,
    *,
    table: str,
    hotel_id: str,
    as_of: dt.datetime,
    limit: int,
    default_platform: str,
    latest_only: bool = False,
) -> list[Any]:
    platform_scope = _ACTIVE_REVIEW_PLATFORM_SCOPE.get()
    if platform_scope in {"meituan", "dianping"} and table != source._TABLES["meituan"]:
        return []

    columns = repository._resolve_columns(table)
    canonical_fields = (
        "hotel_id",
        "review_id",
        "review_content",
        "star_rating",
        "is_replied",
        "is_negative_review",
        "source_snapshot",
        "review_time",
        "platform_scope",
    )
    select_fields = [
        repository._select_expression(columns.get(name), name)
        for name in canonical_fields
    ]
    where = [f"`{columns['hotel_id']}`=%s"]
    params: list[Any] = [hotel_id]
    if platform_scope in {"meituan", "dianping"}:
        where.append("`channel_source`=%s")
        params.append(_channel_source_value(platform_scope))

    as_of_local = as_of.astimezone(source.SHANGHAI_TZ).replace(tzinfo=None)
    scope = _ACTIVE_REVIEW_DATE_SCOPE.get()
    if scope:
        range_start, range_end, end_inclusive = _review_time_bounds(
            as_of,
            source.SHANGHAI_TZ,
            scope,
        )
        window_start_local = range_start.replace(tzinfo=None)
        window_end_local = range_end.replace(tzinfo=None)
        review_end_operator = "<=" if end_inclusive else "<"
    else:
        window_start_local = (
            as_of.astimezone(source.SHANGHAI_TZ)
            - dt.timedelta(days=source.REVIEW_DETAIL_WINDOW_DAYS)
        ).replace(tzinfo=None)
        window_end_local = as_of_local
        review_end_operator = "<="
    snapshot_col = str(columns["source_snapshot"])
    review_time_col = str(columns["review_time"])
    where.extend(
        [
            f"`{snapshot_col}`<=%s",
            f"`{review_time_col}`>=%s",
            f"`{review_time_col}`{review_end_operator}%s",
        ]
    )
    params.extend([as_of_local, window_start_local, window_end_local])
    partition_columns = [f"`{columns['review_id']}`"]
    if columns.get("platform_scope"):
        partition_columns.insert(0, f"`{columns['platform_scope']}`")
    row_number = (
        "ROW_NUMBER() OVER ("
        f"PARTITION BY {', '.join(partition_columns)} "
        f"ORDER BY `{snapshot_col}` DESC"
        ") AS `_s13_rn`"
    )
    outer_fields = ", ".join(f"`{name}`" for name in canonical_fields)
    unreplied_values = "'0','false','no','n','unreplied','未回复','pending'"
    sql = (
        f"SELECT /*+ MAX_EXECUTION_TIME({MYSQL_QUERY_TIMEOUT_MS}) */ {outer_fields} FROM ("
        f"SELECT {', '.join(select_fields)}, {row_number} "
        f"FROM `{source._safe_identifier(table)}` WHERE {' AND '.join(where)}"
        ") AS `_s13_latest` "
        "WHERE `_s13_rn`=1 "
        f"AND LOWER(TRIM(CAST(`is_replied` AS CHAR))) IN ({unreplied_values}) "
        f"ORDER BY `review_time` {'DESC' if latest_only else 'ASC'}, `source_snapshot` DESC LIMIT %s"
    )
    params.append(1 if latest_only else _scan_limit(limit))
    try:
        with repository._connect() as conn, conn.cursor() as cursor:
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
    except Exception as exc:  # pragma: no cover - production connectivity
        raise source.SourceDataGap(
            f"review_source_pending_query_failed:{type(exc).__name__}"
        ) from exc

    records: list[Any] = []
    for row in rows:
        replied = source._as_replied(row.get("is_replied"))
        if replied is not False:
            continue
        platform = source.normalize_platform(
            row.get("platform_scope"),
            default=default_platform,
        )
        if platform_scope and platform != platform_scope:
            continue
        content_value = row.get("review_content")
        records.append(
            source.ReviewRecord(
                hotel_id=str(row.get("hotel_id") or hotel_id),
                platform=platform,
                review_id=str(row.get("review_id") or ""),
                review_content=None if content_value is None else str(content_value),
                star_rating=source._as_float(row.get("star_rating")),
                is_replied=False,
                source_snapshot=str(row.get("source_snapshot") or ""),
                review_time=(
                    str(row.get("review_time"))
                    if row.get("review_time") not in (None, "")
                    else None
                ),
                is_negative_review=source._as_source_negative(row.get("is_negative_review")),
            )
        )
    return records


def _patch_memory_source(source: Any, data_rules: Any) -> None:
    cls = source.MemoryReviewSourceRepository
    original_list = cls.list_unreplied
    if getattr(original_list, "_s13_review_date_scope", False):
        return

    def list_unreplied(self, *, hotel_id, as_of, limit=MAX_PENDING_ITEMS):  # type: ignore[no-untyped-def]
        date_scope = _ACTIVE_REVIEW_DATE_SCOPE.get()
        platform_scope = _ACTIVE_REVIEW_PLATFORM_SCOPE.get()
        if not date_scope and not platform_scope:
            return original_list(self, hotel_id=hotel_id, as_of=as_of, limit=limit)
        effective = _effective_limit(limit)
        rows = [
            row
            for row in self._latest_for_hotel(hotel_id, as_of=as_of)
            if not row.is_replied
            and (not date_scope or _record_in_scope(source, row, as_of=as_of, scope=date_scope))
            and (not platform_scope or _record_platform_matches(row, platform_scope))
        ]
        return sorted(rows, key=data_rules.queue_priority)[:effective]

    def latest_unreplied(self, *, hotel_id, as_of):  # type: ignore[no-untyped-def]
        date_scope = _ACTIVE_REVIEW_DATE_SCOPE.get()
        platform_scope = _ACTIVE_REVIEW_PLATFORM_SCOPE.get()
        if not date_scope and not platform_scope:
            rows = original_list(self, hotel_id=hotel_id, as_of=as_of, limit=1)
            return rows[0] if rows else None
        rows = [
            row
            for row in self._latest_for_hotel(hotel_id, as_of=as_of)
            if not row.is_replied
            and (not date_scope or _record_in_scope(source, row, as_of=as_of, scope=date_scope))
            and (not platform_scope or _record_platform_matches(row, platform_scope))
        ]
        rows.sort(
            key=lambda item: (item.review_time or item.source_snapshot, item.review_id),
            reverse=True,
        )
        return rows[0] if rows else None

    list_unreplied._s13_review_date_scope = True  # type: ignore[attr-defined]
    latest_unreplied._s13_review_date_scope = True  # type: ignore[attr-defined]
    cls.list_unreplied = list_unreplied
    cls.latest_unreplied = latest_unreplied


def _patch_source(source: Any, data_rules: Any) -> None:
    cls = source.MySQLReviewSourceRepository
    original = cls.list_unreplied
    if not getattr(original, "_s13_pending_bounded", False):

        def list_unreplied(self, *, hotel_id, as_of, limit=MAX_PENDING_ITEMS):  # type: ignore[no-untyped-def]
            effective = _effective_limit(limit)
            rows: list[Any] = []
            gaps: list[str] = []
            source_specs = _source_specs_for_platform(_ACTIVE_REVIEW_PLATFORM_SCOPE.get())
            for table_key, default_platform in source_specs:
                try:
                    rows.extend(
                        _bounded_unreplied_query(
                            source,
                            self,
                            table=source._TABLES[table_key],
                            hotel_id=hotel_id,
                            as_of=as_of,
                            limit=effective,
                            default_platform=default_platform,
                        )
                    )
                except source.SourceDataGap as exc:
                    gaps.append(f"{table_key}:{exc}")
            if not rows and len(gaps) == len(source_specs):
                raise source.SourceDataGap(
                    "review_detail_sources_unavailable:" + "|".join(gaps)
                )
            return sorted(rows, key=data_rules.queue_priority)[:effective]

        def latest_unreplied(self, *, hotel_id, as_of):  # type: ignore[no-untyped-def]
            rows: list[Any] = []
            gaps: list[str] = []
            source_specs = _source_specs_for_platform(_ACTIVE_REVIEW_PLATFORM_SCOPE.get())
            for table_key, default_platform in source_specs:
                try:
                    rows.extend(
                        _bounded_unreplied_query(
                            source,
                            self,
                            table=source._TABLES[table_key],
                            hotel_id=hotel_id,
                            as_of=as_of,
                            limit=1,
                            default_platform=default_platform,
                            latest_only=True,
                        )
                    )
                except source.SourceDataGap as exc:
                    gaps.append(f"{table_key}:{exc}")
            if not rows and len(gaps) == len(source_specs):
                raise source.SourceDataGap(
                    "review_detail_sources_unavailable:" + "|".join(gaps)
                )
            rows.sort(
                key=lambda item: (item.review_time or item.source_snapshot, item.review_id),
                reverse=True,
            )
            return rows[0] if rows else None

        list_unreplied._s13_pending_bounded = True  # type: ignore[attr-defined]
        latest_unreplied._s13_pending_bounded = True  # type: ignore[attr-defined]
        cls.list_unreplied = list_unreplied
        cls.latest_unreplied = latest_unreplied

    _patch_memory_source(source, data_rules)


def _patch_service(service: Any) -> None:
    cls = service.S13Service
    original = cls.list_pending
    if getattr(original, "_s13_pending_limit", False):
        return

    def list_pending(self, context, *, limit=MAX_PENDING_ITEMS):  # type: ignore[no-untyped-def]
        effective = _effective_limit(limit)
        result = original(self, context, limit=effective)
        result["pending_list_contract_version"] = VERSION
        result["pending_list_limit"] = effective
        result["returned_count"] = len(result.get("items") or [])
        result["more_may_exist"] = result["returned_count"] >= effective
        return result

    list_pending._s13_pending_limit = True  # type: ignore[attr-defined]
    cls.list_pending = list_pending


def _short_excerpt(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return "仅评分"
    if len(text) <= EXCERPT_LIMIT:
        return text
    return text[:EXCERPT_LIMIT].rstrip() + "…"


def _scope_label(scope: str | None) -> str:
    if scope == "today":
        return "今日"
    if scope == "yesterday":
        return "昨日"
    return ""


def _count_summary(result: Mapping[str, Any], *, date_label: str, platform_label: str) -> str:
    count = len(list(result.get("items") or []))
    subject = f"{platform_label}{date_label or '当前'}" if platform_label else (date_label or "当前")
    if count == 0:
        return f"{subject}没有未回复评论。"
    if result.get("more_may_exist"):
        limit = result.get("pending_list_limit") or MAX_PENDING_ITEMS
        return f"{subject}至少有{limit}条未回复评论（单次查询展示上限{limit}条）。"
    return f"{subject}有{count}条未回复评论。"


def _patch_feishu(feishu: Any) -> None:
    original = feishu._render
    if getattr(original, "_s13_pending_compact", False):
        return

    def render(result: Mapping[str, Any]) -> str:
        scope = _ACTIVE_REVIEW_DATE_SCOPE.get()
        label = _scope_label(scope)
        platform_scope = _ACTIVE_REVIEW_PLATFORM_SCOPE.get()
        platform_label = _platform_label(platform_scope)
        count_only = _ACTIVE_REVIEW_COUNT_ONLY.get()
        if result.get("action") == "latest_pending" and (label or platform_label):
            text = original(result)
            prefix = f"{platform_label}{label}" or platform_label or label
            if "最新未回复评论" in text:
                return text.replace("最新未回复评论", f"{prefix}最新未回复评论", 1)
            if text.startswith("当前没有可用的未回复评论"):
                return text.replace("当前没有可用的未回复评论", f"{prefix}没有可用的未回复评论", 1)
            return text
        if result.get("action") != "list_pending":
            return original(result)
        if count_only:
            return _count_summary(result, date_label=label, platform_label=platform_label)
        items = list(result.get("items") or [])
        if not items:
            if platform_label or label:
                title = f"{platform_label}{label}" or platform_label or label
                return f"{title}没有可用的未回复评论，或评论明细数据尚未就绪。"
            return "当前没有可用的待回复评论，或评论明细数据尚未就绪。"
        counts = Counter(str(item.get("platform") or "unknown") for item in items)
        breakdown = [
            f"{feishu.PLATFORM_LABELS.get(platform, platform)}{counts[platform]}条"
            for platform in feishu.PLATFORM_DISPLAY_ORDER
            if counts.get(platform, 0) > 0
        ]
        for platform in sorted(set(counts) - set(feishu.PLATFORM_DISPLAY_ORDER)):
            breakdown.append(
                f"{feishu.PLATFORM_LABELS.get(platform, platform)}{counts[platform]}条"
            )
        if platform_label:
            title = f"{platform_label}{label or '当前'}未回复评论"
        else:
            title = f"{label}未回复评论" if label else "待回复评论"
        headline = f"{title}｜按风险与低分优先展示 {len(items)} 条"
        if breakdown:
            headline += f"（{'，'.join(breakdown)}）"
        lines = [headline]
        for index, item in enumerate(items, 1):
            platform = str(item.get("platform") or "-")
            platform_label_item = feishu.PLATFORM_LABELS.get(platform, platform)
            score = item.get("star_rating")
            score_text = "-" if score in (None, "") else str(score)
            lines.append(
                f"{index}. {platform_label_item}｜{score_text}分｜"
                f"{item.get('review_ref')}｜"
                f"{_short_excerpt(item.get('redacted_excerpt'))}"
            )
        if result.get("more_may_exist"):
            lines.append(
                f"仅展示优先级最高前 "
                f"{result.get('pending_list_limit') or MAX_PENDING_ITEMS} 条；"
                "处理后可再次发送“待回复评论”刷新队列。"
            )
        return "\n".join(lines)

    render._s13_pending_compact = True  # type: ignore[attr-defined]
    feishu._render = render


def _wrap_route(previous: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def route(message: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        date_scope = review_date_scope(message)
        platform_scope = review_platform_scope(message)
        count_only = review_count_only(message)
        if date_scope is None and platform_scope is None and not count_only:
            return previous(message, *args, **kwargs)
        date_token = _ACTIVE_REVIEW_DATE_SCOPE.set(date_scope)
        platform_token = _ACTIVE_REVIEW_PLATFORM_SCOPE.set(platform_scope)
        count_token = _ACTIVE_REVIEW_COUNT_ONLY.set(count_only)
        try:
            result = previous(message, *args, **kwargs)
        finally:
            _ACTIVE_REVIEW_COUNT_ONLY.reset(count_token)
            _ACTIVE_REVIEW_PLATFORM_SCOPE.reset(platform_token)
            _ACTIVE_REVIEW_DATE_SCOPE.reset(date_token)
        if isinstance(result, dict) and result.get("skill_id") == "S13":
            if date_scope:
                result["review_date_scope"] = date_scope
                result["review_date_filter_applied"] = True
                result["review_date_scope_contract_version"] = DATE_SCOPE_VERSION
            if platform_scope:
                result["review_platform_scope"] = platform_scope
                result["review_channel_source_filter"] = _channel_source_value(platform_scope)
                result["review_platform_filter_applied"] = True
                result["review_platform_scope_contract_version"] = PLATFORM_SCOPE_VERSION
            if count_only:
                result["review_count_only"] = True
        return result

    route._s13_review_date_scope = True  # type: ignore[attr-defined]
    route._s13_review_platform_scope = True  # type: ignore[attr-defined]
    return route


def _patch_router(router: Any) -> None:
    for name in ("route_feishu_command", "safe_route_feishu_command"):
        previous = getattr(router, name)
        if getattr(previous, "_s13_review_platform_scope", False):
            continue
        setattr(router, name, _wrap_route(previous))


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    from runtime import feishu_command_router as router
    from runtime import s13_data_rules_patch as data_rules
    from runtime.s13 import feishu, service, source

    _patch_source(source, data_rules)
    _patch_service(service)
    _patch_feishu(feishu)
    _patch_router(router)

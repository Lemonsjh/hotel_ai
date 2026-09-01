from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol
from urllib.parse import parse_qs, unquote, urlparse

from runtime.s13.contracts import ReviewRecord, SUPPORTED_PLATFORMS


REVIEW_DETAIL_WINDOW_DAYS = 60
SHANGHAI_TZ = timezone(timedelta(hours=8))


class SourceDataGap(RuntimeError):
    pass


class ReviewSourceRepository(Protocol):
    def list_unreplied(self, *, hotel_id: str, as_of: datetime, limit: int = 50) -> list[ReviewRecord]: ...

    def latest_unreplied(self, *, hotel_id: str, as_of: datetime) -> ReviewRecord | None: ...

    def get_exact(
        self,
        *,
        hotel_id: str,
        platform: str,
        review_id: str,
        as_of: datetime,
    ) -> ReviewRecord | None: ...


def _parse_source_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI_TZ)
    return parsed


def _within_review_window(record: ReviewRecord, *, as_of: datetime) -> bool:
    snapshot_time = _parse_source_datetime(record.source_snapshot)
    if snapshot_time is None or snapshot_time > as_of:
        return False
    review_time = _parse_source_datetime(record.review_time) or snapshot_time
    window_start = as_of - timedelta(days=REVIEW_DETAIL_WINDOW_DAYS)
    return window_start <= review_time <= as_of


class MemoryReviewSourceRepository:
    def __init__(self, records: Iterable[ReviewRecord | dict[str, Any]]) -> None:
        self.records: list[ReviewRecord] = [
            item if isinstance(item, ReviewRecord) else ReviewRecord(**item)
            for item in records
        ]

    @classmethod
    def from_json_file(cls, path: str) -> "MemoryReviewSourceRepository":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = raw.get("reviews") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            raise SourceDataGap("source_fixture_reviews_must_be_list")
        return cls(rows)

    def _latest_for_hotel(self, hotel_id: str, *, as_of: datetime) -> list[ReviewRecord]:
        latest: dict[tuple[str, str], ReviewRecord] = {}
        latest_snapshot: dict[tuple[str, str], datetime] = {}
        for row in self.records:
            if row.hotel_id != hotel_id or not _within_review_window(row, as_of=as_of):
                continue
            snapshot_time = _parse_source_datetime(row.source_snapshot)
            if snapshot_time is None:
                continue
            key = (row.platform, row.review_id)
            current_snapshot = latest_snapshot.get(key)
            if current_snapshot is None or snapshot_time > current_snapshot:
                latest[key] = row
                latest_snapshot[key] = snapshot_time
        return list(latest.values())

    def list_unreplied(self, *, hotel_id: str, as_of: datetime, limit: int = 50) -> list[ReviewRecord]:
        rows = [row for row in self._latest_for_hotel(hotel_id, as_of=as_of) if not row.is_replied]
        rows.sort(key=lambda item: (item.review_time or item.source_snapshot, item.review_id), reverse=True)
        return rows[:limit]

    def latest_unreplied(self, *, hotel_id: str, as_of: datetime) -> ReviewRecord | None:
        rows = self.list_unreplied(hotel_id=hotel_id, as_of=as_of, limit=1)
        return rows[0] if rows else None

    def get_exact(
        self,
        *,
        hotel_id: str,
        platform: str,
        review_id: str,
        as_of: datetime,
    ) -> ReviewRecord | None:
        matches = [
            row
            for row in self.records
            if row.hotel_id == hotel_id
            and row.platform == platform
            and row.review_id == review_id
            and _within_review_window(row, as_of=as_of)
        ]
        matches.sort(
            key=lambda item: _parse_source_datetime(item.source_snapshot) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return matches[0] if matches else None

    def to_json(self) -> dict[str, Any]:
        return {"reviews": [asdict(row) for row in self.records]}


_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
_TABLES = {
    "meituan": "meituan_ota_review_detail",
    "ctrip_family": "ctrip_ota_review_detail",
}
_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "hotel_id": ("hotel_id",),
    "review_id": ("review_id", "comment_id", "id"),
    "review_content": ("review_content", "comment_content", "review_text", "comment"),
    "star_rating": ("review_score", "score_value", "star_rating", "score", "rating"),
    "is_replied": ("is_replied", "replied", "reply_status"),
    "is_negative_review": ("is_negative_review", "negative_review", "is_negative", "bad_review_flag"),
    "source_snapshot": ("snapshot_time", "updated_at", "created_at"),
    "review_time": ("review_time", "comment_time", "created_at"),
    "platform_scope": (
        "review_platform",
        "platform_scope",
        "source_platform",
        "channel_source",
        "platform",
    ),
}


def _safe_identifier(value: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise SourceDataGap("unsafe_database_identifier")
    return value


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise SourceDataGap("s13_source_dsn_must_be_mysql")
    database = parsed.path.lstrip("/")
    if not database:
        raise SourceDataGap("s13_source_database_required")
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "charset": query.get("charset", ["utf8mb4"])[0],
        "connect_timeout": int(query.get("connect_timeout", ["5"])[0]),
        "read_timeout": int(query.get("read_timeout", ["10"])[0]),
        "write_timeout": int(query.get("write_timeout", ["10"])[0]),
        "autocommit": True,
    }


def normalize_platform(value: Any, *, default: str) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "美团": "meituan",
        "美团评价": "meituan",
        "meituan": "meituan",
        "大众点评": "dianping",
        "大众点评评价": "dianping",
        "点评": "dianping",
        "dianping": "dianping",
        "携程": "ctrip",
        "ctrip": "ctrip",
        "去哪儿": "qunar",
        "去哪儿网": "qunar",
        "qunar": "qunar",
        "同程": "tongcheng",
        "同程旅行": "tongcheng",
        "tongcheng": "tongcheng",
        "智行": "zhixing",
        "智行火车票": "zhixing",
        "zhixing": "zhixing",
    }
    normalized = aliases.get(text, default)
    return normalized if normalized in SUPPORTED_PLATFORMS else default


def _as_replied(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "replied", "已回复", "success"}:
        return True
    if text in {"0", "false", "no", "n", "unreplied", "未回复", "pending"}:
        return False
    return None


def _as_source_negative(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "negative", "差评"}:
        return True
    if text in {"0", "false", "no", "n", "normal", "非差评"}:
        return False
    return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class MySQLReviewSourceRepository:
    """Read-only exact review source used by S12 to issue opaque refs.

    Table names are fixed and column selection is limited to an explicit alias
    allowlist. No caller-provided SQL, table, or column is accepted.
    """

    def __init__(self, dsn: str) -> None:
        try:
            import pymysql  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional production dependency
            raise SourceDataGap("pymysql_not_installed") from exc
        self._pymysql = pymysql
        self._connection_kwargs = _parse_mysql_dsn(dsn)
        self._columns_cache: dict[str, dict[str, str | None]] = {}

    @classmethod
    def from_env(cls, explicit_dsn: str | None = None, hotel_id: str | None = None) -> "MySQLReviewSourceRepository":
        from runtime.adapters.database import resolve_hotel_dsn

        try:
            dsn = explicit_dsn or resolve_hotel_dsn(hotel_id, "HOTEL_OTA_S13_SOURCE_DSN")
        except RuntimeError as exc:
            raise SourceDataGap("s13_source_dsn_not_configured") from exc
        if not dsn:
            raise SourceDataGap("s13_source_dsn_not_configured")
        return cls(dsn)

    def _connect(self):  # type: ignore[no-untyped-def]
        return self._pymysql.connect(
            cursorclass=self._pymysql.cursors.DictCursor,
            **self._connection_kwargs,
        )

    def _resolve_columns(self, table: str) -> dict[str, str | None]:
        table = _safe_identifier(table)
        cached = self._columns_cache.get(table)
        if cached:
            return cached
        with self._connect() as conn, conn.cursor() as cursor:
            cursor.execute(f"SHOW COLUMNS FROM `{table}`")
            available = {str(row["Field"]) for row in cursor.fetchall()}
        resolved: dict[str, str | None] = {}
        for canonical, aliases in _COLUMN_ALIASES.items():
            resolved[canonical] = next((name for name in aliases if name in available), None)
        missing = [
            name
            for name in ("hotel_id", "review_id", "is_replied", "source_snapshot", "review_time")
            if not resolved.get(name)
        ]
        if missing:
            raise SourceDataGap(f"review_detail_missing_columns:{','.join(missing)}")
        self._columns_cache[table] = resolved
        return resolved

    @staticmethod
    def _select_expression(column: str | None, alias: str) -> str:
        if column:
            return f"`{_safe_identifier(column)}` AS `{alias}`"
        return f"NULL AS `{alias}`"

    def _query_table(
        self,
        *,
        table: str,
        hotel_id: str,
        as_of: datetime,
        review_id: str | None,
        limit: int | None,
        default_platform: str,
    ) -> list[ReviewRecord]:
        columns = self._resolve_columns(table)
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
            self._select_expression(columns.get(name), name)
            for name in canonical_fields
        ]
        where = [f"`{columns['hotel_id']}`=%s"]
        params: list[Any] = [hotel_id]
        if review_id is not None:
            where.append(f"`{columns['review_id']}`=%s")
            params.append(review_id)

        as_of_local = as_of.astimezone(SHANGHAI_TZ).replace(tzinfo=None)
        window_start_local = (as_of.astimezone(SHANGHAI_TZ) - timedelta(days=REVIEW_DETAIL_WINDOW_DAYS)).replace(tzinfo=None)
        snapshot_col = str(columns["source_snapshot"])
        review_time_col = str(columns["review_time"])
        where.extend(
            [
                f"`{snapshot_col}`<=%s",
                f"`{review_time_col}`>=%s",
                f"`{review_time_col}`<=%s",
            ]
        )
        params.extend([as_of_local, window_start_local, as_of_local])

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
        sql = (
            f"SELECT {outer_fields} FROM ("
            f"SELECT {', '.join(select_fields)}, {row_number} "
            f"FROM `{_safe_identifier(table)}` WHERE {' AND '.join(where)}"
            ") AS `_s13_latest` "
            "WHERE `_s13_rn`=1 ORDER BY `review_time` DESC, `source_snapshot` DESC"
        )
        if limit is not None:
            sql += " LIMIT %s"
            params.append(max(1, min(int(limit), 500)))
        try:
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                rows = cursor.fetchall()
        except Exception as exc:  # pragma: no cover - production connectivity
            raise SourceDataGap(f"review_source_query_failed:{type(exc).__name__}") from exc

        results: list[ReviewRecord] = []
        for row in rows:
            replied = _as_replied(row.get("is_replied"))
            if replied is None:
                continue
            platform = normalize_platform(row.get("platform_scope"), default=default_platform)
            content_value = row.get("review_content")
            content = None if content_value is None else str(content_value)
            results.append(
                ReviewRecord(
                    hotel_id=str(row.get("hotel_id") or hotel_id),
                    platform=platform,
                    review_id=str(row.get("review_id") or ""),
                    review_content=content,
                    star_rating=_as_float(row.get("star_rating")),
                    is_replied=replied,
                    source_snapshot=str(row.get("source_snapshot") or ""),
                    review_time=str(row.get("review_time")) if row.get("review_time") not in (None, "") else None,
                    is_negative_review=_as_source_negative(row.get("is_negative_review")),
                )
            )
        return results

    def list_unreplied(self, *, hotel_id: str, as_of: datetime, limit: int = 50) -> list[ReviewRecord]:
        rows: list[ReviewRecord] = []
        gaps: list[str] = []
        for table_key, default_platform in (("meituan", "meituan"), ("ctrip_family", "ctrip")):
            try:
                rows.extend(
                    self._query_table(
                        table=_TABLES[table_key],
                        hotel_id=hotel_id,
                        as_of=as_of,
                        review_id=None,
                        limit=None,
                        default_platform=default_platform,
                    )
                )
            except SourceDataGap as exc:
                gaps.append(f"{table_key}:{exc}")
        if not rows and len(gaps) == 2:
            raise SourceDataGap("review_detail_sources_unavailable:" + "|".join(gaps))
        candidates = [row for row in rows if not row.is_replied]
        candidates.sort(key=lambda item: (item.review_time or item.source_snapshot, item.review_id), reverse=True)
        return candidates[:limit]

    def latest_unreplied(self, *, hotel_id: str, as_of: datetime) -> ReviewRecord | None:
        rows = self.list_unreplied(hotel_id=hotel_id, as_of=as_of, limit=1)
        return rows[0] if rows else None

    def get_exact(
        self,
        *,
        hotel_id: str,
        platform: str,
        review_id: str,
        as_of: datetime,
    ) -> ReviewRecord | None:
        if platform in {"meituan", "dianping"}:
            table_key, default_platform = "meituan", "meituan"
        else:
            table_key, default_platform = "ctrip_family", "ctrip"
        rows = self._query_table(
            table=_TABLES[table_key],
            hotel_id=hotel_id,
            as_of=as_of,
            review_id=review_id,
            limit=20,
            default_platform=default_platform,
        )
        exact = [row for row in rows if row.platform == platform]
        return exact[0] if exact else None

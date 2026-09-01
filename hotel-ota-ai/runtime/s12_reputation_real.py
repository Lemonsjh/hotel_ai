from __future__ import annotations

import datetime as dt
import os
import threading
import time
from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlparse

from runtime.s13.policy import detect_topics, redact_review_text


SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8))
VERSION = "s12-real-field-rules.v1"
DETAIL_WINDOW_DAYS = 60
NEGATIVE_POLICY_VERSION = "s12-negative-policy.v1"
LOW_SCORE_THRESHOLD = 3.0
_COLUMN_CACHE_TTL_SECONDS = 300
_SHARED_COLUMNS_CACHE: dict[tuple[str, int, str, str], tuple[float, set[str]]] = {}
_SHARED_COLUMNS_LOCK = threading.Lock()

OVERVIEW_TABLES = (
    ("meituan_family", "meituan_ota_review_overview", "meituan"),
    ("ctrip_family", "ctrip_ota_review_overview", "ctrip"),
)
DETAIL_TABLES = (
    ("meituan_family", "meituan_ota_review_detail", "meituan"),
    ("ctrip_family", "ctrip_ota_review_detail", "ctrip"),
)
RANKING_TABLES = (
    ("meituan_family", "meituan_ota_review_ranking", "meituan"),
    ("ctrip_family", "ctrip_ota_review_ranking", "ctrip"),
)

PLATFORM_LABELS = {
    "meituan": "美团",
    "dianping": "大众点评",
    "ctrip": "携程",
    "qunar": "去哪儿",
    "tongcheng": "同程",
    "zhixing": "智行",
}


class S12DataGap(RuntimeError):
    pass


def _safe_identifier(value: str) -> str:
    text = str(value or "")
    if not text or not text.replace("_", "").isalnum():
        raise S12DataGap("unsafe_database_identifier")
    return text


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise S12DataGap("s12_source_dsn_must_be_mysql")
    database = parsed.path.lstrip("/")
    if not database:
        raise S12DataGap("s12_source_database_required")
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": database,
        "charset": query.get("charset", ["utf8mb4"])[0],
        "connect_timeout": int(query.get("connect_timeout", ["5"])[0]),
        "read_timeout": int(query.get("read_timeout", ["15"])[0]),
        "write_timeout": int(query.get("write_timeout", ["15"])[0]),
        "autocommit": True,
    }


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "replied", "已回复", "negative", "差评"}:
        return True
    if text in {"0", "false", "no", "n", "unreplied", "未回复", "normal", "非差评"}:
        return False
    return None


def _platform(value: Any, default: str) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "美团": "meituan", "美团评价": "meituan", "meituan": "meituan",
        "大众点评": "dianping", "点评": "dianping", "dianping": "dianping",
        "携程": "ctrip", "ctrip": "ctrip",
        "去哪儿": "qunar", "qunar": "qunar",
        "同程": "tongcheng", "tongcheng": "tongcheng",
        "智行": "zhixing", "zhixing": "zhixing",
    }
    return aliases.get(text, default)


def _row_platform(row: Mapping[str, Any], default: str) -> str:
    """Prefer the source's review platform over its collection channel."""
    for field in ("review_platform", "platform_scope", "source_platform", "channel_source"):
        value = row.get(field)
        if value not in (None, ""):
            return _platform(value, default)
    return default


def _ratio(numerator: Any, denominator: Any) -> tuple[float | None, str | None]:
    num = _as_float(numerator)
    den = _as_float(denominator)
    if num is None or den is None:
        return None, "missing_metric"
    if den == 0:
        return None, "not_computable_zero_denominator"
    return num / den, None


def _latest(rows: Sequence[Mapping[str, Any]], *, grain: Sequence[str]) -> tuple[list[dict[str, Any]], int]:
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    same_version: defaultdict[tuple[Any, ...], int] = defaultdict(int)
    for source in rows:
        row = dict(source)
        key = tuple(row.get(field) for field in grain)
        version = (str(row.get("snapshot_time") or ""), int(_as_float(row.get("id")) or 0))
        same_version[key + (version[0],)] += 1
        previous = selected.get(key)
        previous_version = (
            str((previous or {}).get("snapshot_time") or ""),
            int(_as_float((previous or {}).get("id")) or 0),
        )
        if previous is None or version > previous_version:
            selected[key] = row
    duplicates = sum(max(count - 1, 0) for count in same_version.values())
    return list(selected.values()), duplicates


def build_overview_row(platform: str, row: Mapping[str, Any]) -> dict[str, Any]:
    total = _as_float(row.get("total_review_count"))
    unreplied = _as_float(
        row.get("unreplied_review_count")
        if row.get("unreplied_review_count") not in (None, "")
        else row.get("pending_reply_count")
    )
    negative = _as_float(
        row.get("negative_review_count")
        if row.get("negative_review_count") not in (None, "")
        else row.get("bad_review_count")
    )
    unreplied_rate, unreplied_gap = _ratio(unreplied, total)
    negative_rate, negative_gap = _ratio(negative, total)
    gaps = []
    if unreplied_gap:
        gaps.append(f"{unreplied_gap}:overview_unreplied_rate")
    if negative_gap:
        gaps.append(f"{negative_gap}:overview_negative_rate")
    return {
        "platform": platform,
        "review_score": _as_float(row.get("review_score")),
        "review_score_max": _as_float(row.get("review_score_max")),
        "environment_score": _as_float(row.get("environment_score")),
        "facility_score": _as_float(row.get("facility_score")),
        "style_score": _as_float(row.get("style_score")),
        "safety_score": _as_float(row.get("safety_score")),
        "service_score": _as_float(row.get("service_score")),
        "hygiene_score": _as_float(row.get("hygiene_score")),
        "total_review_count": total,
        "unreplied_review_count": unreplied,
        "source_negative_review_count": negative,
        "unreplied_rate": unreplied_rate,
        "source_negative_rate": negative_rate,
        "snapshot_time": row.get("snapshot_time"),
        "data_gaps": gaps,
    }


def detail_priority(row: Mapping[str, Any]) -> tuple[int, str, str]:
    content = str(row.get("review_content") or "").strip()
    risk = bool(detect_topics(content)) and any(
        word in content for word in ("安全", "受伤", "消防", "隐私", "报警", "赔偿", "退款", "起诉")
    )
    score = _as_float(row.get("review_score"))
    source_negative = _as_bool(row.get("is_negative_review"))
    if risk:
        band = 0
    elif source_negative is True:
        band = 1
    elif score is not None and score <= 2:
        band = 2
    elif score is not None and score <= LOW_SCORE_THRESHOLD:
        band = 3
    elif not content:
        band = 4
    else:
        band = 5
    return band, str(row.get("review_time") or row.get("snapshot_time") or ""), str(row.get("review_id") or "")


def build_detail_platform(platform: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    unreplied_rows = [row for row in rows if _as_bool(row.get("is_replied")) is False]
    source_negative_rows = [row for row in rows if _as_bool(row.get("is_negative_review")) is True]
    low_score_rows = [
        row for row in rows
        if _as_float(row.get("review_score")) is not None and float(row["review_score"]) <= LOW_SCORE_THRESHOLD
    ]
    pure_rating_rows = [row for row in unreplied_rows if not str(row.get("review_content") or "").strip()]
    topic_counts: Counter[str] = Counter()
    for row in rows:
        text = redact_review_text(str(row.get("review_content") or ""))
        topic_counts.update(detect_topics(text))
    unreplied_rate, unreplied_gap = _ratio(len(unreplied_rows), total)
    source_negative_rate, source_negative_gap = _ratio(len(source_negative_rows), total)
    low_score_rate, low_score_gap = _ratio(len(low_score_rows), total)
    gaps = []
    if unreplied_gap:
        gaps.append(f"{unreplied_gap}:detail_unreplied_rate")
    if source_negative_gap:
        gaps.append(f"{source_negative_gap}:detail_source_negative_rate")
    if low_score_gap:
        gaps.append(f"{low_score_gap}:detail_low_score_rate")
    queue = sorted(unreplied_rows, key=detail_priority)
    return {
        "platform": platform,
        "window_days": DETAIL_WINDOW_DAYS,
        "total_review_count": total,
        "unreplied_review_count": len(unreplied_rows),
        "source_negative_review_count": len(source_negative_rows),
        "low_score_review_count": len(low_score_rows),
        "pure_rating_unreplied_count": len(pure_rating_rows),
        "unreplied_rate": unreplied_rate,
        "source_negative_rate": source_negative_rate,
        "low_score_rate": low_score_rate,
        "negative_policy_version": NEGATIVE_POLICY_VERSION,
        "low_score_threshold": LOW_SCORE_THRESHOLD,
        "topic_counts": dict(topic_counts.most_common()),
        "queue_preview": [
            {
                "review_id": row.get("review_id"),
                "review_score": _as_float(row.get("review_score")),
                "review_time": row.get("review_time"),
                "review_content_present": bool(str(row.get("review_content") or "").strip()),
                "source_negative": _as_bool(row.get("is_negative_review")),
            }
            for row in queue[:10]
        ],
        "data_gaps": gaps,
    }


class S12MySQLSource:
    def __init__(self, dsn: str) -> None:
        try:
            import pymysql  # type: ignore
        except ImportError as exc:
            raise S12DataGap("pymysql_not_installed") from exc
        self._pymysql = pymysql
        self._kwargs = _parse_mysql_dsn(dsn)
        self._columns_cache: dict[str, set[str]] = {}

    @classmethod
    def from_env(cls, explicit_dsn: str | None = None, hotel_id: str | None = None) -> "S12MySQLSource":
        from runtime.adapters.database import resolve_hotel_dsn

        try:
            dsn = explicit_dsn or resolve_hotel_dsn(hotel_id, "HOTEL_OTA_S12_SOURCE_DSN")
        except RuntimeError as exc:
            raise S12DataGap("s12_source_dsn_not_configured") from exc
        if not dsn and not hotel_id:
            # 向后兼容旧回退链：无 hotel_id 场景允许 S13 库作为兜底
            dsn = os.environ.get("HOTEL_OTA_S13_SOURCE_DSN")
        if not dsn:
            raise S12DataGap("s12_source_dsn_not_configured")
        return cls(dsn)

    def _connect(self):  # type: ignore[no-untyped-def]
        return self._pymysql.connect(cursorclass=self._pymysql.cursors.DictCursor, **self._kwargs)

    def _columns(self, table: str) -> set[str]:
        table = _safe_identifier(table)
        if table in self._columns_cache:
            return self._columns_cache[table]
        key = (
            str(self._kwargs.get("host") or ""),
            int(self._kwargs.get("port") or 3306),
            str(self._kwargs.get("database") or ""),
            table,
        )
        now = time.monotonic()
        with _SHARED_COLUMNS_LOCK:
            cached = _SHARED_COLUMNS_CACHE.get(key)
        if cached and now - cached[0] < _COLUMN_CACHE_TTL_SECONDS:
            self._columns_cache[table] = cached[1]
            return cached[1]
        try:
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                columns = {str(row["Field"]) for row in cursor.fetchall()}
        except Exception as exc:
            raise S12DataGap(f"table_unavailable:{table}:{type(exc).__name__}") from exc
        self._columns_cache[table] = columns
        with _SHARED_COLUMNS_LOCK:
            _SHARED_COLUMNS_CACHE[key] = (now, columns)
        return columns

    def _query(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise S12DataGap(f"source_query_failed:{type(exc).__name__}") from exc

    def overview_rows(self, table: str, *, hotel_id: str, as_of: dt.datetime, default_platform: str) -> tuple[list[dict[str, Any]], int]:
        columns = self._columns(table)
        missing = sorted({"hotel_id", "snapshot_time"} - columns)
        if missing:
            raise S12DataGap(f"{table}:missing_columns:{','.join(missing)}")
        wanted = {
            "id", "snapshot_time", "channel_source", "review_platform", "platform_scope", "source_platform", "hotel_id", "review_score", "review_score_max",
            "environment_score", "facility_score", "style_score", "safety_score", "service_score", "hygiene_score",
            "total_review_count", "unreplied_review_count", "pending_reply_count", "negative_review_count", "bad_review_count",
        }
        select = sorted(columns & wanted)
        rows = self._query(
            f"SELECT {', '.join(f'`{_safe_identifier(name)}`' for name in select)} FROM `{_safe_identifier(table)}` "
            "WHERE `hotel_id`=%s AND `snapshot_time`<=%s",
            (hotel_id, as_of.astimezone(SHANGHAI_TZ).replace(tzinfo=None)),
        )
        for row in rows:
            row["platform"] = _row_platform(row, default_platform)
        return _latest(rows, grain=("hotel_id", "platform"))

    def detail_rows(self, table: str, *, hotel_id: str, as_of: dt.datetime, default_platform: str) -> tuple[list[dict[str, Any]], int]:
        columns = self._columns(table)
        missing = sorted({"hotel_id", "review_id", "snapshot_time", "review_time", "is_replied"} - columns)
        if missing:
            raise S12DataGap(f"{table}:missing_columns:{','.join(missing)}")
        wanted = {
            "id", "snapshot_time", "channel_source", "review_platform", "platform_scope", "source_platform", "hotel_id", "review_id", "review_content",
            "review_score", "is_replied", "is_negative_review", "review_time", "stay_date", "hygiene_score",
            "facility_score", "location_score", "service_score", "read_status", "has_image", "image_count",
        }
        select = sorted(columns & wanted)
        as_of_local = as_of.astimezone(SHANGHAI_TZ).replace(tzinfo=None)
        start = (as_of.astimezone(SHANGHAI_TZ) - dt.timedelta(days=DETAIL_WINDOW_DAYS)).replace(tzinfo=None)
        rows = self._query(
            f"SELECT {', '.join(f'`{_safe_identifier(name)}`' for name in select)} FROM `{_safe_identifier(table)}` "
            "WHERE `hotel_id`=%s AND `review_time` BETWEEN %s AND %s AND `snapshot_time`<=%s",
            (hotel_id, start, as_of_local, as_of_local),
        )
        for row in rows:
            row["platform"] = _row_platform(row, default_platform)
        return _latest(rows, grain=("hotel_id", "platform", "review_id"))

    def ranking_rows(self, table: str, *, hotel_id: str, as_of: dt.datetime, default_platform: str) -> tuple[list[dict[str, Any]], int]:
        columns = self._columns(table)
        missing = sorted({"hotel_id", "snapshot_time"} - columns)
        if missing:
            raise S12DataGap(f"{table}:missing_columns:{','.join(missing)}")
        wanted = {
            "id", "snapshot_time", "channel_source", "review_platform", "platform_scope", "source_platform", "hotel_id", "rank_item_name", "rank_item_value",
            "competitor_rank", "rank_position", "competition_circle_hotel_count", "peer_average", "metric_unit",
        }
        select = sorted(columns & wanted)
        rows = self._query(
            f"SELECT {', '.join(f'`{_safe_identifier(name)}`' for name in select)} FROM `{_safe_identifier(table)}` "
            "WHERE `hotel_id`=%s AND `snapshot_time`<=%s",
            (hotel_id, as_of.astimezone(SHANGHAI_TZ).replace(tzinfo=None)),
        )
        for row in rows:
            row["platform"] = _row_platform(row, default_platform)
        return _latest(rows, grain=("hotel_id", "platform", "rank_item_name"))


def build_s12_report(*, hotel_id: str, as_of: dt.datetime, source: S12MySQLSource) -> dict[str, Any]:
    platforms: dict[str, dict[str, Any]] = {}
    data_gaps: list[str] = []
    duplicate_count = 0
    for family, table, default_platform in OVERVIEW_TABLES:
        try:
            rows, duplicates = source.overview_rows(table, hotel_id=hotel_id, as_of=as_of, default_platform=default_platform)
        except S12DataGap as exc:
            data_gaps.append(f"{family}:overview:{exc}")
            continue
        duplicate_count += duplicates
        for row in rows:
            platform = str(row.get("platform") or default_platform)
            platforms.setdefault(platform, {"platform": platform})["overview"] = build_overview_row(platform, row)

    detail_seen_by_family: dict[str, bool] = {}
    for family, table, default_platform in DETAIL_TABLES:
        try:
            rows, duplicates = source.detail_rows(table, hotel_id=hotel_id, as_of=as_of, default_platform=default_platform)
        except S12DataGap as exc:
            detail_seen_by_family[family] = False
            data_gaps.append(f"{family}:detail:{exc}")
            continue
        duplicate_count += duplicates
        detail_seen_by_family[family] = bool(rows)
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("platform") or default_platform)].append(row)
        for platform, platform_rows in grouped.items():
            platforms.setdefault(platform, {"platform": platform})["detail"] = build_detail_platform(platform, platform_rows)
        if not rows:
            data_gaps.append(f"{family}:hotel_scoped_detail_data_gap")

    for family, table, default_platform in RANKING_TABLES:
        try:
            rows, duplicates = source.ranking_rows(table, hotel_id=hotel_id, as_of=as_of, default_platform=default_platform)
        except S12DataGap as exc:
            data_gaps.append(f"{family}:ranking:{exc}")
            continue
        duplicate_count += duplicates
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("platform") or default_platform)].append(row)
        for platform, platform_rows in grouped.items():
            platforms.setdefault(platform, {"platform": platform})["ranking"] = [
                {
                    "rank_item_name": row.get("rank_item_name"),
                    "rank_item_value": _as_float(row.get("rank_item_value")),
                    "competitor_rank": _as_float(row.get("competitor_rank") if row.get("competitor_rank") not in (None, "") else row.get("rank_position")),
                    "competition_circle_hotel_count": _as_float(row.get("competition_circle_hotel_count")),
                    "peer_average": _as_float(row.get("peer_average")),
                    "metric_unit": row.get("metric_unit"),
                    "snapshot_time": row.get("snapshot_time"),
                }
                for row in platform_rows
            ]

    for platform, item in platforms.items():
        family = "meituan_family" if platform in {"meituan", "dianping"} else "ctrip_family"
        if item.get("overview") and not item.get("detail") and not detail_seen_by_family.get(family):
            item["detail_status"] = "hotel_scoped_data_gap"
        elif item.get("detail"):
            item["detail_status"] = "available"
        else:
            item["detail_status"] = "unavailable"
        overview = item.get("overview") or {}
        detail = item.get("detail") or {}
        if overview.get("unreplied_review_count") is not None:
            item["authoritative_unreplied_review_count"] = overview["unreplied_review_count"]
            item["authoritative_unreplied_source"] = "platform_overview"
        if (
            overview.get("unreplied_review_count") is not None
            and detail.get("unreplied_review_count") is not None
            and overview["unreplied_review_count"] != detail["unreplied_review_count"]
        ):
            item["unreplied_count_quality"] = "overview_detail_mismatch"
            data_gaps.append(f"{platform}:overview_detail_unreplied_count_mismatch")

    status = "ok" if platforms and all(item.get("overview") or item.get("detail") for item in platforms.values()) else "partial" if platforms else "data_gap"
    return {
        "status": status,
        "skill_id": "S12",
        "intent": "reputation_management",
        "hotel_id": hotel_id,
        "as_of_datetime": as_of.isoformat(timespec="seconds"),
        "platforms": platforms,
        "data_gaps": sorted(set(data_gaps)),
        "source_duplicate_count": duplicate_count,
        "negative_policy_version": NEGATIVE_POLICY_VERSION,
        "algorithm_version": VERSION,
        "data_source_type": "real_database" if platforms else "unavailable",
        "business_result_generated": bool(platforms),
        "approval_data_allowed": False,
        "live_allowed": False,
    }


def _num(value: Any, digits: int = 1) -> str:
    number = _as_float(value)
    if number is None:
        return "—"
    if abs(number - round(number)) < 1e-9:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _pct(value: Any) -> str:
    number = _as_float(value)
    return "—" if number is None else f"{number * 100:.1f}%"


def render_s12_report(report: Mapping[str, Any]) -> str:
    if report.get("status") == "data_gap":
        return "⭐ S12 口碑管理\n当前酒店没有可用的真实口碑总览或评论明细。"
    lines = [
        f"⭐ S12 口碑管理｜截至 {str(report.get('as_of_datetime') or '')[11:16]}",
        "口径：平台、总览和评论明细分别计算；空值不转零，不跨酒店或跨平台借数据。",
    ]
    order = ("meituan", "dianping", "ctrip", "qunar", "tongcheng", "zhixing")
    for platform in order:
        item = (report.get("platforms") or {}).get(platform)
        if not item:
            continue
        lines.extend(["", f"【{PLATFORM_LABELS.get(platform, platform)}】"])
        overview = item.get("overview")
        if overview:
            lines.append(
                f"平台总览  评分 {_num(overview.get('review_score'))}/{_num(overview.get('review_score_max'))}"
                f"  ｜  累计评价 {_num(overview.get('total_review_count'))}"
            )
            lines.append(
                f"  待回复（平台汇总） {_num(overview.get('unreplied_review_count'))}（{_pct(overview.get('unreplied_rate'))}）"
                f"  ｜  来源差评 {_num(overview.get('source_negative_review_count'))}（{_pct(overview.get('source_negative_rate'))}）"
            )
        detail = item.get("detail")
        if detail:
            lines.append(f"近{detail.get('window_days')}日明细  {detail.get('total_review_count')}条")
            if item.get("unreplied_count_quality") == "overview_detail_mismatch":
                lines.append("  明细未回复状态与平台汇总不一致；待回复总数以平台汇总为准。")
            else:
                lines.append(
                    f"  待回复 {detail.get('unreplied_review_count')}（{_pct(detail.get('unreplied_rate'))}）"
                )
            lines.append(
                f"  来源差评 {detail.get('source_negative_review_count')}（{_pct(detail.get('source_negative_rate'))}）"
                f"  ｜  低分≤{_num(detail.get('low_score_threshold'))} {detail.get('low_score_review_count')}"
                f"（{_pct(detail.get('low_score_rate'))}）"
            )
            lines.append(f"  纯评分待回复 {detail.get('pure_rating_unreplied_count')}条；纯评分保留在队列，不因无正文删除。")
            topics = detail.get("topic_counts") or {}
            if topics:
                labels = {
                    "cleanliness": "卫生", "service_response": "服务响应", "noise": "噪音隔音",
                    "facilities": "设施设备", "room_condition": "房间体验", "checkin": "入住办理",
                }
                lines.append("  高频主题  " + "  ｜  ".join(f"{labels.get(key, key)} {value}" for key, value in list(topics.items())[:5]))
        elif item.get("detail_status") == "hotel_scoped_data_gap":
            lines.append("评论明细  当前酒店无 exact 明细；不借用其他酒店数据，主题与待回复队列不生成。")
        ranking = item.get("ranking") or []
        if ranking:
            rank_text = []
            for row in ranking[:5]:
                name = row.get("rank_item_name") or "排名项"
                rank = _num(row.get("competitor_rank"), 0)
                total = _num(row.get("competition_circle_hotel_count"), 0)
                rank_text.append(f"{name} {rank}{f'/{total}' if total != '—' else ''}")
            lines.append("排名  " + "  ｜  ".join(rank_text))
    lines.extend([
        "",
        f"负面口径  来源差评标识与低分≤{_num(LOW_SCORE_THRESHOLD)}分别展示；版本 {NEGATIVE_POLICY_VERSION}。",
        "建议  优先处理风险、来源差评和低分评论；具体公开回复进入 S13 草稿与确认流程。",
    ])
    if report.get("data_gaps"):
        lines.extend(["", "【数据边界】", "；".join(str(item) for item in report.get("data_gaps") or [])])
    return "\n".join(lines)

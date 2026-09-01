from __future__ import annotations

import datetime as dt
import os
from collections import defaultdict
from statistics import median
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlparse


SHANGHAI_TZ = dt.timezone(dt.timedelta(hours=8))
VERSION = "s09-real-field-rules.v1"
HISTORY_DAYS = 90
SOURCE_RATE_TOLERANCE = 0.01

MEITUAN_TABLE = "meituan_ota_business_metrics"
CTRIP_TABLE = "ctrip_ota_business_metrics"
MEITUAN_30D_TABLE = "meituan_ota_flow_conversion_30d"
CTRIP_30D_TABLE = "ctrip_ota_flow_conversion_30d"

COUNT_UNITS = {
    "count",
    "order",
    "orders",
    "person",
    "people",
    "uv",
    "次",
    "单",
    "人",
    "间夜",
    "room_night",
}
RATE_UNITS = {"%", "pct", "percent", "percentage", "ratio", "rate"}

MEITUAN_CODES = {
    "exposure_uv": ("FLOW_EXPOSURE_UV", COUNT_UNITS),
    "browse_uv": ("FLOW_INTENTION_UV", COUNT_UNITS),
    "pay_orders": ("FLOW_PAY_ORDER_CNT", COUNT_UNITS),
    "source_first_rate": ("FLOW_INTENTION_PER_EXPOSURE", RATE_UNITS),
    "source_second_rate": ("FLOW_PAY_ORDER_PER_INTENTION", RATE_UNITS),
    "check_browse_uv": ("INTENTION_UV", COUNT_UNITS),
    "check_pay_orders": ("PAY_ORDER_CNT", COUNT_UNITS),
    "check_second_rate": ("PAY_ORDER_CNT_UV", RATE_UNITS),
}
CTRIP_CODES = {
    "list_exposure_count": ("list_page_exposure_count", COUNT_UNITS),
    "detail_visitor_count": ("detail_page_visitor_count", COUNT_UNITS),
    "submit_orders": ("order_submit_count", COUNT_UNITS),
    "source_first_rate": ("exposure_conversion_rate", RATE_UNITS),
    "source_second_rate": ("order_conversion_rate", RATE_UNITS),
}

PLATFORM_LABELS = {
    "meituan": "美团",
    "dianping": "大众点评",
    "ctrip": "携程",
    "qunar": "去哪儿",
    "tongcheng": "同程",
    "zhixing": "智行",
}


class S09DataGap(RuntimeError):
    pass


def _safe_identifier(value: str) -> str:
    text = str(value or "")
    if not text or not text.replace("_", "").isalnum():
        raise S09DataGap("unsafe_database_identifier")
    return text


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise S09DataGap("s09_source_dsn_must_be_mysql")
    database = parsed.path.lstrip("/")
    if not database:
        raise S09DataGap("s09_source_database_required")
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


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else None


def _timestamp_key(value: Any) -> str:
    return str(value or "")


def _normalize_unit(value: Any) -> str:
    return str(value or "").strip().lower()


def _rate(value: Any, unit: Any = None) -> float | None:
    number = _as_float(value)
    if number is None:
        return None
    normalized = _normalize_unit(unit)
    if normalized in RATE_UNITS and abs(number) > 1:
        return number / 100.0
    if abs(number) > 1 and abs(number) <= 100:
        return number / 100.0
    return number


def _ratio(numerator: Any, denominator: Any) -> tuple[float | None, str | None]:
    num = _as_float(numerator)
    den = _as_float(denominator)
    if num is None or den is None:
        return None, "missing_metric"
    if den == 0:
        return None, "not_computable_zero_denominator"
    return num / den, None


def _median(values: Iterable[float | None]) -> float | None:
    clean = [float(value) for value in values if value is not None]
    return median(clean) if clean else None


def _status_by_peer(value: float | None, peer: float | None, threshold: float) -> str:
    if value is None:
        return "unavailable"
    if peer is None or peer <= 0:
        return "unknown"
    return "weak" if value < peer * threshold else "healthy"


def _sample_quality(*, denominator: float | None, numerator: float | None, stage: str) -> str:
    if denominator is None or numerator is None:
        return "unavailable"
    if stage == "first":
        if denominator >= 300 and numerator >= 30:
            return "stable"
        if denominator >= 30:
            return "weak"
        return "trend_only"
    if denominator >= 50 and numerator >= 3:
        return "stable"
    if denominator >= 30 and numerator >= 2:
        return "weak"
    return "trend_only"


def _latest_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    grain_fields: Sequence[str],
) -> tuple[list[dict[str, Any]], int]:
    selected: dict[tuple[Any, ...], dict[str, Any]] = {}
    seen_at_version: defaultdict[tuple[Any, ...], int] = defaultdict(int)
    for source in rows:
        row = dict(source)
        grain = tuple(row.get(field) for field in grain_fields)
        version = (_timestamp_key(row.get("snapshot_time")), int(_as_float(row.get("id")) or 0))
        same_version = grain + (version[0],)
        seen_at_version[same_version] += 1
        current = selected.get(grain)
        if current is None:
            selected[grain] = row
            continue
        current_version = (
            _timestamp_key(current.get("snapshot_time")),
            int(_as_float(current.get("id")) or 0),
        )
        if version > current_version:
            selected[grain] = row
    duplicate_count = sum(max(count - 1, 0) for count in seen_at_version.values())
    return list(selected.values()), duplicate_count


def _metric_map(
    rows: Sequence[Mapping[str, Any]],
    definitions: Mapping[str, tuple[str, set[str]]],
) -> tuple[dict[str, float | None], list[str], list[str]]:
    by_code = {str(row.get("metric_code") or ""): row for row in rows}
    values: dict[str, float | None] = {}
    gaps: list[str] = []
    conflicts: list[str] = []
    for name, (code, expected_units) in definitions.items():
        row = by_code.get(code)
        if not row:
            values[name] = None
            gaps.append(f"missing_metric:{code}")
            continue
        unit = _normalize_unit(row.get("metric_unit"))
        if unit and unit not in expected_units:
            values[name] = None
            gaps.append(f"unit_mismatch:{code}:{unit}")
            continue
        values[name] = (
            _rate(row.get("metric_value"), row.get("metric_unit"))
            if expected_units is RATE_UNITS
            else _as_float(row.get("metric_value"))
        )
        if row.get("peer_average") not in (None, ""):
            values[f"{name}_peer"] = (
                _rate(row.get("peer_average"), row.get("metric_unit"))
                if expected_units is RATE_UNITS
                else _as_float(row.get("peer_average"))
            )
        if row.get("competitor_rank") not in (None, ""):
            values[f"{name}_rank"] = _as_float(row.get("competitor_rank"))
    return values, gaps, conflicts


def _compare_source_rate(
    derived: float | None,
    source: float | None,
    *,
    name: str,
) -> list[str]:
    if derived is None or source is None:
        return []
    return [f"source_conflict:{name}"] if abs(derived - source) > SOURCE_RATE_TOLERANCE else []


def build_daily_platform(
    platform: str,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    definitions = MEITUAN_CODES if platform == "meituan" else CTRIP_CODES
    values, gaps, conflicts = _metric_map(rows, definitions)
    if platform == "meituan":
        first, first_gap = _ratio(values.get("browse_uv"), values.get("exposure_uv"))
        second, second_gap = _ratio(values.get("pay_orders"), values.get("browse_uv"))
        conflicts.extend(_compare_source_rate(first, values.get("source_first_rate"), name="exposure_to_browse"))
        conflicts.extend(_compare_source_rate(second, values.get("source_second_rate"), name="browse_to_pay"))
        if values.get("check_browse_uv") is not None and values.get("browse_uv") is not None:
            if abs(float(values["check_browse_uv"]) - float(values["browse_uv"])) > 0:
                conflicts.append("source_conflict:FLOW_INTENTION_UV_vs_INTENTION_UV")
        if values.get("check_pay_orders") is not None and values.get("pay_orders") is not None:
            if abs(float(values["check_pay_orders"]) - float(values["pay_orders"])) > 0:
                conflicts.append("source_conflict:FLOW_PAY_ORDER_CNT_vs_PAY_ORDER_CNT")
        first_quality = _sample_quality(
            denominator=values.get("exposure_uv"),
            numerator=values.get("browse_uv"),
            stage="first",
        )
        second_quality = _sample_quality(
            denominator=values.get("browse_uv"),
            numerator=values.get("pay_orders"),
            stage="second",
        )
        stages = {
            "exposure_uv": values.get("exposure_uv"),
            "browse_uv": values.get("browse_uv"),
            "pay_orders": values.get("pay_orders"),
            "exposure_to_browse_ratio": first,
            "browse_to_pay_ratio": second,
            "source_exposure_to_browse_ratio": values.get("source_first_rate"),
            "source_browse_to_pay_ratio": values.get("source_second_rate"),
        }
    else:
        first, first_gap = _ratio(values.get("detail_visitor_count"), values.get("list_exposure_count"))
        second, second_gap = _ratio(values.get("submit_orders"), values.get("detail_visitor_count"))
        conflicts.extend(_compare_source_rate(first, values.get("source_first_rate"), name="list_to_detail"))
        conflicts.extend(_compare_source_rate(second, values.get("source_second_rate"), name="detail_to_submit"))
        first_quality = _sample_quality(
            denominator=values.get("list_exposure_count"),
            numerator=values.get("detail_visitor_count"),
            stage="first",
        )
        second_quality = _sample_quality(
            denominator=values.get("detail_visitor_count"),
            numerator=values.get("submit_orders"),
            stage="second",
        )
        stages = {
            "list_exposure_count": values.get("list_exposure_count"),
            "detail_visitor_count": values.get("detail_visitor_count"),
            "submit_orders": values.get("submit_orders"),
            "list_to_detail_ratio": first,
            "detail_to_submit_ratio": second,
            "source_list_to_detail_ratio": values.get("source_first_rate"),
            "source_detail_to_submit_ratio": values.get("source_second_rate"),
            "first_denominator_kind": "impression_count",
        }
    if first_gap:
        gaps.append(f"{first_gap}:first_stage")
    if second_gap:
        gaps.append(f"{second_gap}:second_stage")
    sample_date = next((_date(row.get("business_date")) for row in rows if row.get("business_date")), None)
    snapshot_time = max((_timestamp_key(row.get("snapshot_time")) for row in rows), default=None)
    return {
        "platform": platform,
        "business_date": sample_date,
        "snapshot_time": snapshot_time,
        "stages": stages,
        "first_stage_quality": first_quality,
        "second_stage_quality": second_quality,
        "data_gaps": sorted(set(gaps)),
        "source_conflicts": sorted(set(conflicts)),
        "source_duplicate_count": 0,
    }


def build_30d_platform(platform: str, row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    source = dict(row)
    if platform == "meituan":
        exposure = _as_float(source.get("exposure_uv"))
        browse = _as_float(source.get("browse_uv"))
        pay = _as_float(source.get("pay_order_count"))
        first, first_gap = _ratio(browse, exposure)
        second, second_gap = _ratio(pay, browse)
        source_first = _rate(source.get("exposure_to_browse_rate_pct"), "%")
        source_second = _rate(source.get("browse_to_pay_rate_pct"), "%")
        peer_first = _rate(source.get("peer_exposure_to_browse_rate_pct"), "%")
        peer_second = _rate(source.get("peer_browse_to_pay_rate_pct"), "%")
        stages = {
            "exposure_uv": exposure,
            "browse_uv": browse,
            "pay_orders": pay,
            "exposure_to_browse_ratio": first,
            "browse_to_pay_ratio": second,
            "source_exposure_to_browse_ratio": source_first,
            "source_browse_to_pay_ratio": source_second,
            "peer_exposure_to_browse_ratio": peer_first,
            "peer_browse_to_pay_ratio": peer_second,
        }
        conflicts = (
            _compare_source_rate(first, source_first, name="30d_exposure_to_browse")
            + _compare_source_rate(second, source_second, name="30d_browse_to_pay")
        )
    else:
        app_visitors = _as_float(source.get("app_visitors"))
        list_exposure = _as_float(source.get("list_exposure"))
        detail_visitors = _as_float(source.get("detail_exposure"))
        filling = _as_float(source.get("order_filling_count"))
        submitted = _as_float(source.get("order_submit_count"))
        first, first_gap = _ratio(detail_visitors, list_exposure)
        middle, middle_gap = _ratio(filling, detail_visitors)
        third, third_gap = _ratio(submitted, filling)
        total, total_gap = _ratio(submitted, detail_visitors)
        source_first = _rate(source.get("exposure_to_detail_rate_pct"), "%")
        source_middle = _rate(source.get("detail_to_order_rate_pct"), "%")
        source_third = _rate(source.get("order_to_submit_rate_pct"), "%")
        stages = {
            "app_visitors": app_visitors,
            "list_exposure_count": list_exposure,
            "detail_visitor_count": detail_visitors,
            "order_filling_count": filling,
            "submit_orders": submitted,
            "list_to_detail_ratio": first,
            "detail_to_order_filling_ratio": middle,
            "order_filling_to_submit_ratio": third,
            "detail_to_submit_ratio": total,
            "source_list_to_detail_ratio": source_first,
            "source_detail_to_order_filling_ratio": source_middle,
            "source_order_filling_to_submit_ratio": source_third,
            "peer_list_to_detail_ratio": _rate(source.get("peer_exposure_to_detail_rate_pct"), "%"),
            "peer_detail_to_order_filling_ratio": _rate(source.get("peer_detail_to_order_rate_pct"), "%"),
            "peer_order_filling_to_submit_ratio": _rate(source.get("peer_order_to_submit_rate_pct"), "%"),
            "first_denominator_kind": "impression_count",
            "detail_exposure_semantic": "detail_visitor_count",
        }
        conflicts = (
            _compare_source_rate(first, source_first, name="30d_list_to_detail")
            + _compare_source_rate(middle, source_middle, name="30d_detail_to_order_filling")
            + _compare_source_rate(third, source_third, name="30d_order_filling_to_submit")
        )
        first_gap = first_gap
        second_gap = middle_gap or third_gap or total_gap
    gaps = []
    if first_gap:
        gaps.append(f"{first_gap}:30d_first_stage")
    if second_gap:
        gaps.append(f"{second_gap}:30d_later_stage")
    ranks = {
        key: source.get(key)
        for key in source
        if str(key).endswith("_rank") and source.get(key) not in (None, "")
    }
    return {
        "platform": platform,
        "period_start_date": _date(source.get("period_start_date")),
        "period_end_date": _date(source.get("period_end_date")),
        "business_date": _date(source.get("business_date")),
        "snapshot_time": source.get("snapshot_time"),
        "data_updated_at": source.get("data_updated_at"),
        "stages": stages,
        "ranks": ranks,
        "data_gaps": gaps,
        "source_conflicts": sorted(set(conflicts)),
        "single_window_only": True,
    }


def diagnose_platform(platform_result: Mapping[str, Any]) -> dict[str, Any]:
    daily = platform_result.get("daily") or {}
    window = platform_result.get("rolling_30d") or {}
    stages = daily.get("stages") or {}
    peer_stages = (window.get("stages") or {}) if isinstance(window, Mapping) else {}
    if platform_result.get("algorithm_platform", platform_result.get("platform")) == "meituan":
        first = stages.get("exposure_to_browse_ratio")
        second = stages.get("browse_to_pay_ratio")
        peer_first = peer_stages.get("peer_exposure_to_browse_ratio")
        peer_second = peer_stages.get("peer_browse_to_pay_ratio")
        first_label = "曝光→浏览"
        second_label = "浏览→支付"
    else:
        first = stages.get("list_to_detail_ratio")
        second = stages.get("detail_to_submit_ratio")
        peer_first = peer_stages.get("peer_list_to_detail_ratio")
        peer_second = None
        first_label = "列表曝光→详情访客"
        second_label = "详情访客→提交"
    first_status = _status_by_peer(_as_float(first), _as_float(peer_first), 0.80)
    second_status = _status_by_peer(_as_float(second), _as_float(peer_second), 0.85)
    weak = []
    if first_status == "weak":
        weak.append(first_label)
    if second_status == "weak":
        weak.append(second_label)
    if not weak:
        if daily.get("first_stage_quality") in {"trend_only", "unavailable"}:
            conclusion = "样本不足，仅作趋势参考"
        else:
            conclusion = "未发现有证据支持的明显漏斗短板"
    else:
        conclusion = "主要短板：" + "、".join(weak)
    suggestions = []
    if first_label in weak:
        suggestions.append("建议先检查列表主图、标题、引流价与曝光人群匹配，不直接归因于房价。")
    if second_label in weak:
        suggestions.append("建议检查房型可售、价格权益、取消政策和下单阻力，再评估推广或价格动作。")
    if not suggestions:
        suggestions.append("建议继续观察同口径历史与同行变化，避免因单日波动直接调整预算或价格。")
    return {
        "first_stage_status": first_status,
        "second_stage_status": second_status,
        "weak_stages": weak,
        "conclusion": conclusion,
        "suggestions": suggestions,
    }


class S09MySQLSource:
    def __init__(self, dsn: str) -> None:
        try:
            import pymysql  # type: ignore
        except ImportError as exc:
            raise S09DataGap("pymysql_not_installed") from exc
        self._pymysql = pymysql
        self._kwargs = _parse_mysql_dsn(dsn)
        self._columns_cache: dict[str, set[str]] = {}

    @classmethod
    def from_env(cls, explicit_dsn: str | None = None, hotel_id: str | None = None) -> "S09MySQLSource":
        from runtime.adapters.database import resolve_hotel_dsn

        try:
            dsn = explicit_dsn or resolve_hotel_dsn(hotel_id, "HOTEL_OTA_S09_SOURCE_DSN")
        except RuntimeError as exc:
            raise S09DataGap("s09_source_dsn_not_configured") from exc
        if not dsn and not hotel_id:
            # 向后兼容旧回退链：无 hotel_id 场景允许 S13 库作为兜底
            dsn = os.environ.get("HOTEL_OTA_S13_SOURCE_DSN")
        if not dsn:
            raise S09DataGap("s09_source_dsn_not_configured")
        return cls(dsn)

    def _connect(self):  # type: ignore[no-untyped-def]
        return self._pymysql.connect(
            cursorclass=self._pymysql.cursors.DictCursor,
            **self._kwargs,
        )

    def _columns(self, table: str) -> set[str]:
        table = _safe_identifier(table)
        if table in self._columns_cache:
            return self._columns_cache[table]
        try:
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                columns = {str(row["Field"]) for row in cursor.fetchall()}
        except Exception as exc:
            raise S09DataGap(f"table_unavailable:{table}:{type(exc).__name__}") from exc
        self._columns_cache[table] = columns
        return columns

    def _query(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise S09DataGap(f"source_query_failed:{type(exc).__name__}") from exc

    def metric_rows(
        self,
        table: str,
        *,
        hotel_id: str,
        as_of: dt.datetime,
    ) -> tuple[list[dict[str, Any]], int]:
        columns = self._columns(table)
        required = {"hotel_id", "business_date", "metric_code", "metric_value", "metric_unit", "snapshot_time"}
        missing = sorted(required - columns)
        if missing:
            raise S09DataGap(f"{table}:missing_columns:{','.join(missing)}")
        optional = [
            name
            for name in ("id", "platform_scope", "metric_name", "peer_average", "competitor_rank")
            if name in columns
        ]
        select = ["hotel_id", "business_date", "metric_code", "metric_value", "metric_unit", "snapshot_time", *optional]
        end_date = as_of.astimezone(SHANGHAI_TZ).date()
        start_date = end_date - dt.timedelta(days=HISTORY_DAYS)
        rows = self._query(
            f"SELECT {', '.join(f'`{_safe_identifier(name)}`' for name in select)} "
            f"FROM `{_safe_identifier(table)}` "
            "WHERE `hotel_id`=%s AND `business_date` BETWEEN %s AND %s "
            "AND `snapshot_time`<=%s",
            (
                hotel_id,
                start_date.isoformat(),
                end_date.isoformat(),
                as_of.astimezone(SHANGHAI_TZ).replace(tzinfo=None),
            ),
        )
        latest, duplicates = _latest_rows(
            rows,
            grain_fields=("hotel_id", "platform_scope", "business_date", "metric_code"),
        )
        return latest, duplicates

    def hourly_metric_rows(
        self,
        table: str,
        *,
        hotel_id: str,
        start_date: dt.date,
        end_date: dt.date,
        as_of: dt.datetime,
    ) -> list[dict[str, Any]]:
        """Read raw hourly rows; checkpoint batch selection belongs to S9's time-aware view."""
        columns = self._columns(table)
        required = {
            "hotel_id", "business_date", "snapshot_hour", "metric_code",
            "metric_value", "metric_unit", "snapshot_time",
        }
        missing = sorted(required - columns)
        if missing:
            raise S09DataGap(f"{table}:missing_columns:{','.join(missing)}")
        optional = [
            name for name in ("id", "platform_scope", "metric_name", "peer_average", "competitor_rank")
            if name in columns
        ]
        select = [
            "hotel_id", "business_date", "snapshot_hour", "metric_code",
            "metric_value", "metric_unit", "snapshot_time", *optional,
        ]
        return self._query(
            f"SELECT {', '.join(f'`{_safe_identifier(name)}`' for name in select)} "
            f"FROM `{_safe_identifier(table)}` "
            "WHERE `hotel_id`=%s AND `business_date` BETWEEN %s AND %s "
            "AND `snapshot_time`<=%s",
            (
                hotel_id,
                start_date.isoformat(),
                end_date.isoformat(),
                as_of.astimezone(SHANGHAI_TZ).replace(tzinfo=None),
            ),
        )

    def daily_metric_rows(
        self,
        table: str,
        *,
        hotel_id: str,
        start_date: dt.date,
        end_date: dt.date,
        as_of: dt.datetime,
    ) -> list[dict[str, Any]]:
        """Read raw daily rows so a historical view can keep every metric in one snapshot batch."""
        columns = self._columns(table)
        required = {"hotel_id", "business_date", "metric_code", "metric_value", "metric_unit", "snapshot_time"}
        missing = sorted(required - columns)
        if missing:
            raise S09DataGap(f"{table}:missing_columns:{','.join(missing)}")
        optional = [
            name for name in ("id", "platform_scope", "metric_name", "peer_average", "competitor_rank")
            if name in columns
        ]
        select = ["hotel_id", "business_date", "metric_code", "metric_value", "metric_unit", "snapshot_time", *optional]
        return self._query(
            f"SELECT {', '.join(f'`{_safe_identifier(name)}`' for name in select)} "
            f"FROM `{_safe_identifier(table)}` "
            "WHERE `hotel_id`=%s AND `business_date` BETWEEN %s AND %s "
            "AND `snapshot_time`<=%s",
            (
                hotel_id,
                start_date.isoformat(),
                end_date.isoformat(),
                as_of.astimezone(SHANGHAI_TZ).replace(tzinfo=None),
            ),
        )

    def latest_30d(
        self,
        table: str,
        *,
        hotel_id: str,
        as_of: dt.datetime,
        platform_scope: str | None = None,
    ) -> dict[str, Any] | None:
        try:
            columns = self._columns(table)
        except S09DataGap:
            return None
        required = {"hotel_id", "period_start_date", "period_end_date", "snapshot_time"}
        if required - columns:
            return None
        selectable = sorted(
            columns
            & {
                "id", "hotel_id", "platform_scope", "business_date", "period_start_date", "period_end_date",
                "snapshot_time", "data_updated_at", "exposure_uv", "browse_uv", "pay_order_count",
                "exposure_to_browse_rate_pct", "browse_to_pay_rate_pct",
                "peer_exposure_to_browse_rate_pct", "peer_browse_to_pay_rate_pct",
                "exposure_peer_rank", "browse_peer_rank", "pay_order_peer_rank",
                "exposure_to_browse_peer_rank", "browse_to_pay_peer_rank",
                "app_visitors", "list_exposure", "detail_exposure", "order_filling_count",
                "order_submit_count", "exposure_to_detail_rate_pct", "detail_to_order_rate_pct",
                "order_to_submit_rate_pct", "peer_exposure_to_detail_rate_pct",
                "peer_detail_to_order_rate_pct", "peer_order_to_submit_rate_pct",
                "list_exposure_peer_rank", "detail_exposure_peer_rank", "order_filling_peer_rank",
                "exposure_to_detail_rate_peer_rank", "detail_to_order_rate_peer_rank",
            }
        )
        where = [
            "`hotel_id`=%s",
            "`period_end_date`<=%s",
            "`snapshot_time`<=%s",
        ]
        params: list[Any] = [
            hotel_id,
            as_of.astimezone(SHANGHAI_TZ).date().isoformat(),
            as_of.astimezone(SHANGHAI_TZ).replace(tzinfo=None),
        ]
        if platform_scope and "platform_scope" in columns:
            where.append("LOWER(`platform_scope`)=%s")
            params.append(platform_scope.lower())
        rows = self._query(
            f"SELECT {', '.join(f'`{_safe_identifier(name)}`' for name in selectable)} "
            f"FROM `{_safe_identifier(table)}` "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY `period_end_date` DESC, `snapshot_time` DESC"
            + (", `id` DESC" if "id" in columns else "")
            + " LIMIT 1",
            params,
        )
        return rows[0] if rows else None


def build_s09_report(
    *,
    hotel_id: str,
    as_of: dt.datetime,
    source: S09MySQLSource,
) -> dict[str, Any]:
    platforms: dict[str, Any] = {}
    global_gaps: list[str] = []
    for algorithm_platform, table, rolling_table in (
        ("meituan", MEITUAN_TABLE, MEITUAN_30D_TABLE),
        ("ctrip", CTRIP_TABLE, CTRIP_30D_TABLE),
    ):
        try:
            rows, duplicates = source.metric_rows(table, hotel_id=hotel_id, as_of=as_of)
        except S09DataGap as exc:
            global_gaps.append(f"{algorithm_platform}:{exc}")
            continue
        grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            scope = str(row.get("platform_scope") or algorithm_platform).strip().lower()
            grouped[(scope, str(row.get("business_date") or "")[:10])].append(row)
        scopes = sorted({scope for scope, _ in grouped})
        if not scopes:
            global_gaps.append(f"{algorithm_platform}:hotel_scoped_data_gap")
            continue
        for scope in scopes:
            dates = sorted({day for item_scope, day in grouped if item_scope == scope})
            if not dates:
                continue
            current_date = dates[-1]
            current_rows = list(grouped[(scope, current_date)])
            # The ctrip-family table can carry several platform_scope values.
            # They use the same field contract but remain separate platform results.
            metric_algorithm = "meituan" if algorithm_platform == "meituan" else "ctrip"
            daily = build_daily_platform(metric_algorithm, current_rows)
            daily["platform"] = scope
            daily["source_duplicate_count"] = duplicates
            history = []
            for day in dates:
                day_rows = list(grouped[(scope, day)])
                if day_rows:
                    point = build_daily_platform(metric_algorithm, day_rows)
                    point["platform"] = scope
                    history.append(point)
            rolling = build_30d_platform(
                metric_algorithm,
                source.latest_30d(
                    rolling_table,
                    hotel_id=hotel_id,
                    as_of=as_of,
                    platform_scope=scope,
                ),
            )
            if rolling:
                rolling["platform"] = scope
            item = {
                "platform": scope,
                "algorithm_platform": metric_algorithm,
                "daily": daily,
                "daily_history": history,
                "rolling_30d": rolling,
            }
            item["diagnosis"] = diagnose_platform(item)
            platforms[scope] = item
    status = "ok" if platforms else "data_gap"
    if platforms and global_gaps:
        status = "partial"
    return {
        "status": status,
        "skill_id": "S9",
        "intent": "traffic_conversion",
        "hotel_id": hotel_id,
        "as_of_datetime": as_of.isoformat(timespec="seconds"),
        "platforms": platforms,
        "data_gaps": global_gaps,
        "algorithm_version": VERSION,
        "data_source_type": "real_database" if platforms else "unavailable",
        "approval_data_allowed": False,
        "live_allowed": False,
        "business_result_generated": bool(platforms),
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


def render_s09_report(report: Mapping[str, Any]) -> str:
    if report.get("status") == "data_gap":
        return "📊 S9 流量与转化诊断\n当前酒店没有可用的真实平台漏斗数据。"
    lines = [
        f"📊 S9 流量与转化诊断｜截至 {str(report.get('as_of_datetime') or '')[11:16]}",
        "口径：各平台、各业务日期和各指标独立取有效版本；不同平台与不同统计窗口不合并平均。",
    ]
    preferred = ("meituan", "dianping", "ctrip", "qunar", "tongcheng", "zhixing")
    available = report.get("platforms") or {}
    ordered = [key for key in preferred if key in available] + sorted(set(available) - set(preferred))
    for platform in ordered:
        item = available.get(platform)
        if not item:
            continue
        daily = item.get("daily") or {}
        stages = daily.get("stages") or {}
        algorithm_platform = item.get("algorithm_platform") or platform
        lines.extend(["", f"【{PLATFORM_LABELS.get(platform, platform)}｜{daily.get('business_date') or '-'}】"])
        if algorithm_platform == "meituan":
            lines.append(
                f"漏斗  曝光UV {_num(stages.get('exposure_uv'))} → 浏览UV {_num(stages.get('browse_uv'))} "
                f"→ 支付订单 {_num(stages.get('pay_orders'))}"
            )
            lines.append(
                f"转化  曝光→浏览 {_pct(stages.get('exposure_to_browse_ratio'))}"
                f"（来源 {_pct(stages.get('source_exposure_to_browse_ratio'))}）"
                f"  ｜  浏览→支付 {_pct(stages.get('browse_to_pay_ratio'))}"
                f"（来源 {_pct(stages.get('source_browse_to_pay_ratio'))}）"
            )
        else:
            lines.append(
                f"漏斗  列表曝光次数 {_num(stages.get('list_exposure_count'))} → 详情访客 {_num(stages.get('detail_visitor_count'))} "
                f"→ 提交订单 {_num(stages.get('submit_orders'))}"
            )
            lines.append(
                f"转化  列表曝光→详情访客 {_pct(stages.get('list_to_detail_ratio'))}"
                f"（来源 {_pct(stages.get('source_list_to_detail_ratio'))}）"
                f"  ｜  详情访客→提交 {_pct(stages.get('detail_to_submit_ratio'))}"
                f"（来源 {_pct(stages.get('source_detail_to_submit_ratio'))}）"
            )
            lines.append("单位  列表分母是曝光次数，详情分子是访客人数；不称为UV一转。")
        lines.append(
            f"样本质量  第一段 {daily.get('first_stage_quality')}  ｜  第二段 {daily.get('second_stage_quality')}"
        )
        rolling = item.get("rolling_30d")
        if rolling:
            rs = rolling.get("stages") or {}
            lines.append(
                f"30日窗口  {rolling.get('period_start_date') or '-'} 至 {rolling.get('period_end_date') or '-'}"
                "（单一滚动窗口，不拆成日样本）"
            )
            if algorithm_platform == "meituan":
                lines.append(
                    f"  本店 曝光→浏览 {_pct(rs.get('exposure_to_browse_ratio'))} / 浏览→支付 {_pct(rs.get('browse_to_pay_ratio'))}"
                    f"  ｜  同行 {_pct(rs.get('peer_exposure_to_browse_ratio'))} / {_pct(rs.get('peer_browse_to_pay_ratio'))}"
                )
            else:
                lines.append(
                    f"  本店 列表→详情 {_pct(rs.get('list_to_detail_ratio'))} / 详情→填写 {_pct(rs.get('detail_to_order_filling_ratio'))}"
                    f" / 填写→提交 {_pct(rs.get('order_filling_to_submit_ratio'))}"
                )
        diagnosis = item.get("diagnosis") or {}
        lines.append("诊断  " + str(diagnosis.get("conclusion") or "—"))
        for suggestion in diagnosis.get("suggestions") or []:
            lines.append("建议  " + str(suggestion))
        conflicts = sorted(set((daily.get("source_conflicts") or []) + ((rolling or {}).get("source_conflicts") or [])))
        if conflicts:
            lines.append("数据校验  来源率与派生率存在差异：" + "、".join(conflicts))
        gaps = sorted(set((daily.get("data_gaps") or []) + ((rolling or {}).get("data_gaps") or [])))
        if gaps:
            lines.append("数据缺口  " + "、".join(gaps))
    if report.get("data_gaps"):
        lines.extend(["", "【未形成的平台】", "；".join(str(item) for item in report.get("data_gaps") or [])])
    lines.extend([
        "",
        "边界  诊断与建议不自动创建调价或推广任务；需要执行时进入对应候选、dry-run、护栏与审批流程。",
    ])
    return "\n".join(lines)

from __future__ import annotations

import os
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qs, unquote, urlparse


TABLES = {
    "meituan": {
        "name": "meituan_ota_promotion_performance_30d",
        "required": {"hotel_id", "period_start_date", "period_end_date", "snapshot_time", "spend_amount", "booking_order_amount"},
        "fields": {
            "hotel_id", "period_start_date", "period_end_date", "snapshot_time", "plan_id", "plan_name", "launch_id", "launch_name",
            "promotion_name", "promotion_status", "exposure_count", "click_count", "booking_order_count", "room_night_count",
            "booking_order_amount", "spend_amount", "cash_spend_amount", "cost_per_click", "click_rate_pct",
        },
    },
    "ctrip": {
        "name": "ctrip_ota_promotion_performance_30d",
        "required": {"hotel_id", "period_start_date", "period_end_date", "snapshot_time", "spend_amount", "booking_order_amount"},
        "fields": {
            "hotel_id", "period_start_date", "period_end_date", "snapshot_time", "platform_scope", "exposure_count", "click_count",
            "click_rate_pct", "spend_amount", "bonus_spend_amount", "cash_spend_amount", "cost_per_click", "booking_order_count",
            "booking_order_amount", "room_night_count", "conversion_rate_pct", "return_on_ad_spend", "data_delayed",
        },
    },
}


class S10DataGap(RuntimeError):
    pass


def _safe_identifier(value: str) -> str:
    value = str(value or "")
    if not value or not value.replace("_", "").isalnum():
        raise S10DataGap("unsafe_database_identifier")
    return value


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise S10DataGap("s10_source_dsn_must_be_mysql")
    database = parsed.path.lstrip("/")
    if not database:
        raise S10DataGap("s10_source_database_required")
    query = parse_qs(parsed.query)
    return {
        "host": parsed.hostname or "127.0.0.1", "port": parsed.port or 3306,
        "user": unquote(parsed.username or ""), "password": unquote(parsed.password or ""), "database": database,
        "charset": query.get("charset", ["utf8mb4"])[0], "connect_timeout": int(query.get("connect_timeout", ["5"])[0]),
        "read_timeout": int(query.get("read_timeout", ["15"])[0]), "write_timeout": int(query.get("write_timeout", ["15"])[0]),
        "autocommit": True,
    }


class S10MySQLSource:
    """Fixed-schema, read-only S10 source; deliberately independent of database mappings."""

    def __init__(self, dsn: str) -> None:
        try:
            import pymysql  # type: ignore
        except ImportError as exc:
            raise S10DataGap("pymysql_not_installed") from exc
        self._pymysql = pymysql
        self._kwargs = _parse_mysql_dsn(dsn)
        self._columns_cache: dict[str, set[str]] = {}

    @classmethod
    def from_env(cls, explicit_dsn: str | None = None, hotel_id: str | None = None) -> "S10MySQLSource":
        from runtime.adapters.database import resolve_hotel_dsn

        try:
            dsn = explicit_dsn or resolve_hotel_dsn(hotel_id, "HOTEL_OTA_S10_SOURCE_DSN")
        except RuntimeError as exc:
            raise S10DataGap("s10_source_dsn_not_configured") from exc
        if not dsn:
            raise S10DataGap("s10_source_dsn_not_configured")
        return cls(dsn)

    def _connect(self):  # type: ignore[no-untyped-def]
        return self._pymysql.connect(cursorclass=self._pymysql.cursors.DictCursor, **self._kwargs)

    def _columns(self, table: str) -> set[str]:
        table = _safe_identifier(table)
        if table not in self._columns_cache:
            try:
                with self._connect() as conn, conn.cursor() as cursor:
                    cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                    self._columns_cache[table] = {str(row["Field"]) for row in cursor.fetchall()}
            except Exception as exc:
                raise S10DataGap("source_table_unavailable") from exc
        return self._columns_cache[table]

    def _query(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise S10DataGap("source_query_failed") from exc

    def latest_rows(
        self,
        platform: str,
        *,
        hotel_id: str,
        as_of_time: str | None,
        per_launch: bool = False,
    ) -> list[dict[str, Any]]:
        spec = TABLES[platform]
        table = str(spec["name"])
        columns = self._columns(table)
        if spec["required"] - columns:
            raise S10DataGap("source_schema_drift")
        selected = sorted(columns & set(spec["fields"]))

        if per_launch and platform == "meituan":
            if "launch_id" not in columns:
                raise S10DataGap("source_schema_drift")
            select = ", ".join(f"p.`{_safe_identifier(field)}`" for field in selected)
            outer_where = "p.`hotel_id`=%s AND p.`launch_id` IS NOT NULL AND p.`launch_id`<>''"
            inner_cutoff = ""
            params: list[Any] = [hotel_id]
            if as_of_time:
                outer_where += " AND p.`snapshot_time`<=%s"
                inner_cutoff = " AND p2.`snapshot_time`<=%s"
                params.extend([as_of_time, as_of_time])
            order_fields = [field for field in ("plan_id", "launch_id", "promotion_name") if field in columns]
            order_clause = (
                " ORDER BY " + ", ".join(f"p.`{_safe_identifier(field)}`" for field in order_fields)
                if order_fields else ""
            )
            rows = self._query(
                f"SELECT {select} FROM `{_safe_identifier(table)}` p WHERE {outer_where} "
                f"AND p.`snapshot_time`=(SELECT MAX(p2.`snapshot_time`) FROM `{_safe_identifier(table)}` p2 "
                f"WHERE p2.`hotel_id`=p.`hotel_id` AND p2.`launch_id`=p.`launch_id`{inner_cutoff})"
                f"{order_clause}",
                params,
            )
        else:
            select = ", ".join(f"`{_safe_identifier(field)}`" for field in selected)
            where = "`hotel_id`=%s"
            params = [hotel_id]
            if as_of_time:
                where += " AND `snapshot_time`<=%s"
                params.append(as_of_time)
            rows = self._query(
                f"SELECT {select} FROM `{_safe_identifier(table)}` WHERE {where} "
                f"AND `snapshot_time`=(SELECT MAX(`snapshot_time`) FROM `{_safe_identifier(table)}` WHERE {where})",
                [*params, *params],
            )

        for row in rows:
            row.update({"channel_source": platform, "table_key": f"{platform}_promotion_performance_30d"})
        return rows


def query_s10_promotion_performance(
    hotel_id: str,
    *,
    as_of_time: str | None = None,
    source: S10MySQLSource | None = None,
    meituan_per_launch: bool = False,
) -> dict[str, Any]:
    """Return normalized S10 rows without loading database-source mappings."""
    try:
        source = source or S10MySQLSource.from_env(hotel_id=hotel_id)
    except S10DataGap as exc:
        return {"status": "data_gap", "reason": str(exc), "payload": {"source_status": "unavailable", "rows": []}}

    rows: list[dict[str, Any]] = []
    source_gaps: list[str] = []
    for platform in TABLES:
        try:
            if platform == "meituan" and meituan_per_launch:
                rows.extend(source.latest_rows(platform, hotel_id=hotel_id, as_of_time=as_of_time, per_launch=True))
            else:
                rows.extend(source.latest_rows(platform, hotel_id=hotel_id, as_of_time=as_of_time))
        except S10DataGap as exc:
            reason = "schema_drift" if str(exc) == "source_schema_drift" else "source_unavailable"
            source_gaps.append(f"{platform}:{reason}")
    snapshots = [str(row["snapshot_time"]) for row in rows if row.get("snapshot_time") not in (None, "")]
    dates = [str(row["period_end_date"]) for row in rows if row.get("period_end_date") not in (None, "")]
    return {
        "status": "ok" if rows or not source_gaps else "data_gap",
        "reason": "source_unavailable" if not rows and source_gaps else None,
        "payload": {
            "source_status": "ok" if rows else "no_rows", "rows": rows, "source_gaps": source_gaps,
            "data_snapshot_time": max(snapshots) if snapshots else None,
            "data_business_date": max(dates) if dates else None,
            "meituan_snapshot_policy": "latest_per_launch" if meituan_per_launch else "latest_global_snapshot",
        },
    }

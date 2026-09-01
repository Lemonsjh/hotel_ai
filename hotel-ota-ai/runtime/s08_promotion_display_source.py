from __future__ import annotations

import os
from typing import Any, Sequence
from urllib.parse import parse_qs, unquote, urlparse


TABLE_NAME = "meituan_ota_promotion_performance_30d"
REQUIRED_COLUMNS = {
    "hotel_id",
    "period_start_date",
    "period_end_date",
    "snapshot_time",
}
DISPLAY_FIELDS = {
    "hotel_id",
    "period_start_date",
    "period_end_date",
    "snapshot_time",
    "plan_id",
    "plan_name",
    "launch_id",
    "launch_name",
    "promotion_name",
    "exposure_count",
    "click_count",
    "booking_order_count",
    "room_night_count",
    "booking_order_amount",
    "spend_amount",
    "cash_spend_amount",
    "cost_per_click",
    "click_rate_pct",
}


class S8PromotionDisplayDataGap(RuntimeError):
    """Raised when the fixed S8 display source cannot be read safely."""


def _safe_identifier(value: str) -> str:
    text = str(value or "")
    if not text or not text.replace("_", "").isalnum():
        raise S8PromotionDisplayDataGap("unsafe_database_identifier")
    return text


def _parse_mysql_dsn(dsn: str) -> dict[str, Any]:
    parsed = urlparse(dsn)
    if parsed.scheme not in {"mysql", "mysql+pymysql"}:
        raise S8PromotionDisplayDataGap("s8_display_source_dsn_must_be_mysql")
    database = parsed.path.lstrip("/")
    if not database:
        raise S8PromotionDisplayDataGap("s8_display_source_database_required")
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


class S8PromotionDisplayMySQLSource:
    """Read-only source for the latest Meituan promotion-performance snapshot."""

    def __init__(self, dsn: str) -> None:
        try:
            import pymysql  # type: ignore
        except ImportError as exc:
            raise S8PromotionDisplayDataGap("pymysql_not_installed") from exc
        self._pymysql = pymysql
        self._kwargs = _parse_mysql_dsn(dsn)
        self._columns_cache: set[str] | None = None

    @classmethod
    def from_env(
        cls, explicit_dsn: str | None = None, hotel_id: str | None = None
    ) -> "S8PromotionDisplayMySQLSource":
        from runtime.adapters.database import resolve_hotel_dsn

        try:
            dsn = explicit_dsn or resolve_hotel_dsn(
                hotel_id, "HOTEL_OTA_S8_DISPLAY_SOURCE_DSN"
            )
        except RuntimeError as exc:
            raise S8PromotionDisplayDataGap("s8_display_source_dsn_not_configured") from exc
        if not dsn:
            raise S8PromotionDisplayDataGap("s8_display_source_dsn_not_configured")
        return cls(dsn)

    def _connect(self):  # type: ignore[no-untyped-def]
        return self._pymysql.connect(
            cursorclass=self._pymysql.cursors.DictCursor,
            **self._kwargs,
        )

    def _columns(self) -> set[str]:
        if self._columns_cache is None:
            table = _safe_identifier(TABLE_NAME)
            try:
                with self._connect() as conn, conn.cursor() as cursor:
                    cursor.execute(f"SHOW COLUMNS FROM `{table}`")
                    self._columns_cache = {
                        str(row["Field"]) for row in cursor.fetchall()
                    }
            except Exception as exc:
                raise S8PromotionDisplayDataGap("source_table_unavailable") from exc
        return set(self._columns_cache)

    def _query(self, sql: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        try:
            with self._connect() as conn, conn.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                return [dict(row) for row in cursor.fetchall()]
        except Exception as exc:
            raise S8PromotionDisplayDataGap("source_query_failed") from exc

    def latest_rows(
        self,
        *,
        hotel_id: str,
        as_of_time: str | None = None,
    ) -> list[dict[str, Any]]:
        columns = self._columns()
        if REQUIRED_COLUMNS - columns:
            raise S8PromotionDisplayDataGap("source_schema_drift")

        selected = sorted(columns & DISPLAY_FIELDS)
        select_clause = ", ".join(
            f"`{_safe_identifier(field)}`" for field in selected
        )
        table = _safe_identifier(TABLE_NAME)
        where_clause = "`hotel_id`=%s"
        params: list[Any] = [hotel_id]
        if as_of_time:
            where_clause += " AND `snapshot_time`<=%s"
            params.append(as_of_time)

        order_fields = [
            field
            for field in ("plan_id", "launch_id", "promotion_name")
            if field in columns
        ]
        order_clause = (
            " ORDER BY "
            + ", ".join(f"`{_safe_identifier(field)}`" for field in order_fields)
            if order_fields
            else ""
        )
        rows = self._query(
            f"SELECT {select_clause} FROM `{table}` WHERE {where_clause} "
            f"AND `snapshot_time`=("
            f"SELECT MAX(`snapshot_time`) FROM `{table}` WHERE {where_clause}"
            f"){order_clause}",
            [*params, *params],
        )
        return rows


def query_s8_promotion_display(
    hotel_id: str,
    *,
    as_of_time: str | None = None,
    source: S8PromotionDisplayMySQLSource | None = None,
) -> dict[str, Any]:
    """Return the latest fixed-table S8 snapshot without recommendations or writes."""

    try:
        source = source or S8PromotionDisplayMySQLSource.from_env(hotel_id=hotel_id)
        rows = source.latest_rows(hotel_id=hotel_id, as_of_time=as_of_time)
    except S8PromotionDisplayDataGap as exc:
        reason = str(exc)
        return {
            "status": "data_gap",
            "reason": reason,
            "payload": {
                "source_status": (
                    "schema_drift" if reason == "source_schema_drift" else "unavailable"
                ),
                "source_table": TABLE_NAME,
                "rows": [],
                "data_snapshot_time": None,
                "data_business_date": None,
            },
        }

    snapshots = [
        str(row["snapshot_time"])
        for row in rows
        if row.get("snapshot_time") not in (None, "")
    ]
    dates = [
        str(row["period_end_date"])
        for row in rows
        if row.get("period_end_date") not in (None, "")
    ]
    return {
        "status": "ok",
        "reason": None,
        "payload": {
            "source_status": "ok" if rows else "no_rows",
            "source_table": TABLE_NAME,
            "rows": rows,
            "data_snapshot_time": max(snapshots) if snapshots else None,
            "data_business_date": max(dates) if dates else None,
        },
    }
